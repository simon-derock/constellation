import asyncio
import hashlib
import json
import threading
import uuid
from typing import Any

import pytest
from falkordb import FalkorDB
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from constellation.api import mcp as mcp_module
from constellation.api.mcp import build_server
from constellation.graph.read import ReadPort
from constellation.memory.store import MemoryStore

pytestmark = pytest.mark.integration


def serve(falkordb: FalkorDB, tenant: str) -> FastMCP:
    return build_server(ReadPort(falkordb), "brain:none", memory=MemoryStore(falkordb, tenant=tenant))


@pytest.fixture
def tenant() -> str:
    # a fresh tenant per test: graphs are the isolation unit, so tests never share one
    return f"t{uuid.uuid4().hex[:8]}"


@pytest.fixture
def server(falkordb: FalkorDB, tenant: str) -> FastMCP:
    return serve(falkordb, tenant)


def call(server: FastMCP, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        async with Client(server) as client:
            result = await client.call_tool(tool, args)
            assert isinstance(result.structured_content, dict)
            return result.structured_content

    return asyncio.run(run())


def run_threads(count: int, work: Any) -> None:
    threads = [threading.Thread(target=work, args=(n,)) for n in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


@pytest.mark.ac("AC-T2-04")
def test_a_stale_remember_is_a_conflict_that_reports_the_current_version_and_loses_nothing(server: FastMCP) -> None:
    first = call(server, "remember", {"principal": "alice", "key": "owner", "value": "Sam", "expected_version": 0})
    assert first == {"ok": True, "key": "owner", "version": 1}
    stale = call(server, "remember", {"principal": "alice", "key": "owner", "value": "Priya", "expected_version": 0})
    assert stale["ok"] is False
    assert stale["conflict"] is True
    assert (stale["current_version"], stale["current_value"]) == (1, "Sam")
    assert call(server, "recall", {"principal": "alice", "key": "owner"})["value"] == "Sam"
    second = call(server, "remember", {"principal": "alice", "key": "owner", "value": "Priya", "expected_version": 1})
    assert second["version"] == 2
    assert call(server, "recall", {"principal": "alice", "key": "owner"}) == {
        "key": "owner",
        "found": True,
        "value": "Priya",
        "version": 2,
    }


@pytest.mark.ac("AC-T2-04")
def test_a_version_for_a_fact_that_does_not_exist_is_a_conflict_not_a_create(server: FastMCP) -> None:
    result = call(server, "remember", {"principal": "alice", "key": "k", "value": "v", "expected_version": 3})
    assert (result["ok"], result["current_version"], result["current_value"]) == (False, 0, None)
    assert call(server, "recall", {"principal": "alice", "key": "k"})["found"] is False


@pytest.mark.ac("AC-T2-04")
def test_many_agents_creating_the_same_fact_get_exactly_one_winner(server: FastMCP) -> None:
    wins: list[str] = []
    seen: list[dict[str, Any]] = []

    def create(n: int) -> None:
        result = call(
            server, "remember", {"principal": "shared", "key": "lead", "value": f"agent-{n}", "expected_version": 0}
        )
        seen.append(result)
        if result["ok"]:
            wins.append(f"agent-{n}")

    run_threads(16, create)
    assert len(seen) == 16
    assert len(wins) == 1
    assert call(server, "recall", {"principal": "shared", "key": "lead"})["value"] == wins[0]


@pytest.mark.ac("AC-T2-04")
def test_agents_that_retry_on_conflict_lose_no_update(server: FastMCP) -> None:
    call(server, "remember", {"principal": "shared", "key": "counter", "value": "0", "expected_version": 0})
    agents, increments = 8, 5
    conflicts: list[int] = []

    def worker(_: int) -> None:
        lost = 0
        for _ in range(increments):
            while True:
                current = call(server, "recall", {"principal": "shared", "key": "counter"})
                args = {
                    "principal": "shared",
                    "key": "counter",
                    "value": str(int(current["value"]) + 1),
                    "expected_version": current["version"],
                }
                if call(server, "remember", args)["ok"]:
                    break
                lost += 1
        conflicts.append(lost)

    run_threads(agents, worker)
    final = call(server, "recall", {"principal": "shared", "key": "counter"})
    assert final["value"] == str(agents * increments)
    assert final["version"] == agents * increments + 1
    assert sum(conflicts) > 0


@pytest.mark.ac("AC-T2-05")
def test_principals_do_not_see_each_other_and_the_same_name_in_two_tenants_is_two_graphs(
    falkordb: FalkorDB, tenant: str
) -> None:
    here, there = serve(falkordb, tenant), serve(falkordb, f"{tenant}x")
    call(here, "remember", {"principal": "alice", "key": "colour", "value": "teal", "expected_version": 0})
    assert call(here, "recall", {"principal": "bob", "key": "colour"})["found"] is False
    assert call(there, "recall", {"principal": "alice", "key": "colour"})["found"] is False
    call(there, "remember", {"principal": "alice", "key": "colour", "value": "red", "expected_version": 0})
    assert call(here, "recall", {"principal": "alice", "key": "colour"})["value"] == "teal"


@pytest.mark.ac("AC-T2-05")
@pytest.mark.parametrize(
    "principal", ["", "../x", "a:b", "A", "x" * 64, "a b", "a`b", "a'b", "mem:other:alice", "-a", "a\n", "alice;bob"]
)
def test_a_principal_that_could_reach_another_graph_is_refused_and_makes_nothing(
    falkordb: FalkorDB, tenant: str, principal: str
) -> None:
    server = serve(falkordb, tenant)
    calls: list[tuple[str, dict[str, Any]]] = [
        ("remember", {"key": "k", "value": "v", "expected_version": 0}),
        ("recall", {"key": "k"}),
    ]
    for tool, args in calls:
        with pytest.raises(ToolError):
            call(server, tool, {"principal": principal, **args})
    assert MemoryStore(falkordb, tenant).principals() == []


@pytest.mark.ac("AC-T2-05")
def test_cypher_in_a_key_or_value_is_stored_as_text_and_runs_nothing(falkordb: FalkorDB, server: FastMCP) -> None:
    call(server, "remember", {"principal": "bob", "key": "safe", "value": "kept", "expected_version": 0})
    attack = "'}) MATCH (n) DETACH DELETE n //"
    call(server, "remember", {"principal": "alice", "key": attack, "value": attack, "expected_version": 0})
    assert call(server, "recall", {"principal": "alice", "key": attack})["value"] == attack
    assert call(server, "recall", {"principal": "bob", "key": "safe"})["value"] == "kept"


def test_a_read_never_makes_a_graph_and_the_number_of_graphs_is_bounded(
    falkordb: FalkorDB, tenant: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mcp_module, "MAX_PRINCIPALS", 2)
    server, store = serve(falkordb, tenant), MemoryStore(falkordb, tenant)
    assert call(server, "recall", {"principal": "ghost", "key": "k"})["found"] is False
    assert store.principals() == []
    for name in ("one", "two"):
        call(server, "remember", {"principal": name, "key": "k", "value": "v", "expected_version": 0})
    with pytest.raises(ToolError, match="at most 2"):
        call(server, "remember", {"principal": "three", "key": "k", "value": "v", "expected_version": 0})
    assert store.principals() == ["one", "two"]
    assert call(server, "remember", {"principal": "one", "key": "k", "value": "w", "expected_version": 1})["ok"]


@pytest.mark.parametrize(
    "args",
    [
        {"key": "k", "value": "v" * 4_001, "expected_version": 0},
        {"key": "k" * 129, "value": "v", "expected_version": 0},
        {"key": "", "value": "v", "expected_version": 0},
        {"key": "k", "value": "v", "expected_version": -1},
        {"key": "k", "value": "v", "expected_version": 10**10},
        {"key": "k", "value": "v"},
        {"key": "sem:billing owner", "value": "Sam", "expected_version": 0},
    ],
)
def test_remember_refuses_what_exceeds_a_cap_before_the_graph(
    falkordb: FalkorDB, tenant: str, args: dict[str, Any]
) -> None:
    with pytest.raises(ToolError):
        call(serve(falkordb, tenant), "remember", {"principal": "alice", "key": "k", **args})
    assert MemoryStore(falkordb, tenant).principals() == []


def test_a_value_at_the_cap_is_stored_whole(server: FastMCP) -> None:
    value = "é" * 4_000
    call(server, "remember", {"principal": "alice", "key": "big", "value": value, "expected_version": 0})
    assert call(server, "recall", {"principal": "alice", "key": "big"})["value"] == value


def episode(server: FastMCP, principal: str, subject: str, value: str, *evidence: str) -> dict[str, Any]:
    args = {"principal": principal, "task": "t", "subject": subject, "value": value, "evidence": list(evidence)}
    return call(server, "record_episode", args)


@pytest.mark.ac("AC-T2-01")
def test_consolidation_through_the_tool_needs_agreeing_episodes_and_returns_their_evidence(server: FastMCP) -> None:
    assert episode(server, "alice", "billing owner", "Sam", "ENG-1") == {"recorded": True, "subject": "billing owner"}
    assert call(server, "learned", {"principal": "alice"}) == {"new": [], "truncated": False, "facts": []}
    episode(server, "alice", "billing owner", "Sam", "slack-9", "ENG-1")
    episode(server, "alice", "search owner", "Priya", "ENG-3")
    episode(server, "alice", "search owner", "Yusuf", "ENG-4")
    first = call(server, "learned", {"principal": "alice"})
    assert first["new"] == ["billing owner"]
    assert first["facts"] == [
        {
            "key": "sem:billing owner",
            "subject": "billing owner",
            "value": "Sam",
            "support": 2,
            "evidence_count": 2,
            "evidence": ["ENG-1", "slack-9"],
        }
    ]
    # consolidation is idempotent: asking again learns nothing new and returns the same facts
    again = call(server, "learned", {"principal": "alice"})
    assert (again["new"], again["facts"]) == ([], first["facts"])
    assert call(server, "recall", {"principal": "alice", "key": "sem:billing owner"}) == {
        "key": "sem:billing owner",
        "found": True,
        "value": "Sam",
        "version": 1,
    }


@pytest.mark.ac("AC-T2-01")
def test_a_later_disagreeing_episode_does_not_change_what_was_learned_or_its_evidence(server: FastMCP) -> None:
    episode(server, "alice", "owner", "Sam", "e1")
    episode(server, "alice", "owner", "Sam", "e2")
    call(server, "learned", {"principal": "alice"})
    episode(server, "alice", "owner", "Priya", "e3")
    (fact,) = call(server, "learned", {"principal": "alice"})["facts"]
    assert (fact["value"], fact["evidence"]) == ("Sam", ["e1", "e2"])


@pytest.mark.ac("AC-T2-01")
def test_the_learned_list_is_bounded_and_says_when_it_was_cut(server: FastMCP) -> None:
    for subject in ("a", "b", "c"):
        episode(server, "alice", subject, "v", "e1")
        episode(server, "alice", subject, "v", "e2")
    result = call(server, "learned", {"principal": "alice", "limit": 2})
    assert [f["subject"] for f in result["facts"]] == ["a", "b"]
    assert result["truncated"] is True
    with pytest.raises(ToolError):
        call(server, "learned", {"principal": "alice", "limit": 51})


@pytest.mark.ac("AC-T2-05")
def test_episodes_in_one_principal_teach_another_nothing_and_learning_makes_no_graph(
    falkordb: FalkorDB, tenant: str
) -> None:
    server = serve(falkordb, tenant)
    episode(server, "alice", "owner", "Sam", "e1")
    episode(server, "alice", "owner", "Sam", "e2")
    episode(server, "bob", "owner", "Sam", "e3")
    assert call(server, "learned", {"principal": "bob"})["facts"] == []
    assert call(server, "learned", {"principal": "ghost"}) == {"new": [], "truncated": False, "facts": []}
    assert MemoryStore(falkordb, tenant).principals() == ["alice", "bob"]


@pytest.mark.parametrize(
    "args",
    [
        {"evidence": []},
        {"evidence": ["e"] * 21},
        {"evidence": ["x" * 201]},
        {"evidence": [""]},
        {"value": "v" * 4_001},
        {"subject": ""},
        {"subject": "s" * 129},
        {"task": "t" * 129},
        {"evidence": "ENG-1"},
    ],
)
def test_record_episode_refuses_what_exceeds_a_cap_or_cites_nothing(
    falkordb: FalkorDB, tenant: str, args: dict[str, Any]
) -> None:
    base = {"principal": "alice", "task": "t", "subject": "s", "value": "v", "evidence": ["e"]}
    with pytest.raises(ToolError):
        call(serve(falkordb, tenant), "record_episode", {**base, **args})
    assert MemoryStore(falkordb, tenant).principals() == []


def test_episodes_at_the_caps_are_stored(falkordb: FalkorDB, tenant: str) -> None:
    server = serve(falkordb, tenant)
    for _ in range(2):
        episode(server, "alice", "s" * 128, "é" * 4_000, *[f"{n:03d}" + "x" * 197 for n in range(20)])
    (fact,) = call(server, "learned", {"principal": "alice"})["facts"]
    assert (fact["value"], fact["evidence_count"]) == ("é" * 4_000, 20)


def hand_over(server: FastMCP, state: dict[str, Any], principal: str = "team") -> dict[str, Any]:
    args = {"principal": principal, "source": "planner", "target": "executor", "state": state}
    return call(server, "handoff", args)


def claim(server: FastMCP, hid: str, agent: str = "executor", principal: str = "team") -> dict[str, Any]:
    return call(server, "claim", {"principal": principal, "handoff_id": hid, "agent": agent})


@pytest.mark.ac("AC-T2-03")
def test_a_handoff_arrives_exactly_as_given_and_is_claimed_once(server: FastMCP) -> None:
    state = {"task": "triage", "evidence": ["ENG-1", "slack-9"], "step": 3, "nested": {"é": [1, 2.5, None, True]}}
    made = hand_over(server, state)
    canonical = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert made["state_sha256"] == hashlib.sha256(canonical.encode()).hexdigest()
    assert (made["source"], made["target"]) == ("planner", "executor")
    won = claim(server, made["handoff_id"])
    assert won == {"claimed": True, "handoff_id": made["handoff_id"], "winner": "executor", "state": state}
    lost = claim(server, made["handoff_id"])
    assert lost == {"claimed": False, "handoff_id": made["handoff_id"], "winner": "executor"}


@pytest.mark.ac("AC-T2-03")
def test_exactly_one_of_many_concurrent_claimants_wins_and_the_rest_are_told_who_did(server: FastMCP) -> None:
    state = {"step": 1}
    hid = hand_over(server, state)["handoff_id"]
    results: list[dict[str, Any]] = []

    def contend(_: int) -> None:
        results.append(claim(server, hid))

    run_threads(16, contend)
    assert len(results) == 16
    winners = [r for r in results if r["claimed"]]
    assert len(winners) == 1
    assert winners[0]["state"] == state
    assert all(r["winner"] == "executor" and "state" not in r for r in results if not r["claimed"])


@pytest.mark.ac("AC-T2-03")
def test_a_handoff_is_not_claimed_by_the_wrong_agent_and_stays_claimable(server: FastMCP) -> None:
    hid = hand_over(server, {"step": 1})["handoff_id"]
    with pytest.raises(ToolError, match="addressed to 'executor'"):
        claim(server, hid, agent="intruder")
    assert claim(server, hid)["claimed"] is True


@pytest.mark.ac("AC-T2-03")
def test_a_tampered_state_is_refused_and_does_not_count_as_a_claim(falkordb: FalkorDB, tenant: str) -> None:
    server, store = serve(falkordb, tenant), MemoryStore(falkordb, tenant)
    hid = hand_over(server, {"step": 1})["handoff_id"]
    falkordb.select_graph(store.graph_name("team")).query("MATCH (h:Handoff) SET h.state = '{\"step\":99}'")
    with pytest.raises(ToolError, match="hash"):
        claim(server, hid)
    assert store.claimed_by("team", hid) is None


@pytest.mark.ac("AC-T2-05")
def test_a_handoff_cannot_be_claimed_from_another_principal_or_another_tenant(falkordb: FalkorDB, tenant: str) -> None:
    here, there = serve(falkordb, tenant), serve(falkordb, f"{tenant}x")
    hid = hand_over(here, {"step": 1})["handoff_id"]
    call(here, "remember", {"principal": "other", "key": "k", "value": "v", "expected_version": 0})
    hand_over(there, {"step": 1})
    for server, principal in [(here, "other"), (there, "team"), (here, "ghost")]:
        with pytest.raises(ToolError, match="unknown handoff"):
            claim(server, hid, principal=principal)
    assert MemoryStore(falkordb, tenant).principals() == ["other", "team"]
    assert claim(here, hid)["claimed"] is True


@pytest.mark.parametrize(
    "args",
    [
        {"state": {"blob": "x" * 8_192}},
        {"state": []},
        {"state": "step 1"},
        {"source": "Planner"},
        {"source": ""},
        {"target": "a b"},
        {"target": "x" * 64},
    ],
)
def test_handoff_refuses_oversize_non_json_or_badly_named_input_before_the_graph(
    falkordb: FalkorDB, tenant: str, args: dict[str, Any]
) -> None:
    base = {"principal": "team", "source": "planner", "target": "executor", "state": {"step": 1}}
    with pytest.raises(ToolError):
        call(serve(falkordb, tenant), "handoff", {**base, **args})
    assert MemoryStore(falkordb, tenant).principals() == []


def test_a_state_that_is_not_strict_json_is_refused_even_when_a_caller_skips_the_wire(
    falkordb: FalkorDB, tenant: str
) -> None:
    # over the wire a NaN becomes null; called in process it would reach the tool, which must not store it
    args = {"principal": "team", "source": "planner", "target": "executor", "state": {"n": float("nan")}}
    with pytest.raises(ToolError, match="plain JSON"):
        asyncio.run(serve(falkordb, tenant).call_tool("handoff", args))
    assert MemoryStore(falkordb, tenant).principals() == []


def test_a_state_at_the_cap_is_carried_whole_and_one_character_more_is_refused(server: FastMCP) -> None:
    # {"k":""} is 8 bytes of JSON around the string, and each é is two
    state = {"k": "é" * ((8_192 - 8) // 2)}
    assert len(json.dumps(state, separators=(",", ":"), ensure_ascii=False).encode()) == 8_192
    hid = hand_over(server, state)["handoff_id"]
    assert claim(server, hid)["state"] == state
    with pytest.raises(ToolError, match="the most a handoff carries"):
        hand_over(server, {"k": "é" * ((8_192 - 8) // 2 + 1)})


@pytest.mark.parametrize("hid", ["", "x", "A" * 32, "0" * 31, "0" * 33, "g" * 32, "0" * 32 + "\n"])
def test_claim_refuses_a_handoff_id_that_is_not_one(server: FastMCP, hid: str) -> None:
    with pytest.raises(ToolError):
        claim(server, hid)


@pytest.mark.ac("AC-INV-06")
def test_memory_tools_are_absent_without_a_store_and_no_tool_chooses_a_graph_or_a_tenant(falkordb: FalkorDB) -> None:
    async def names(server: FastMCP) -> dict[str, Any]:
        async with Client(server) as client:
            return {t.name: t for t in await client.list_tools()}

    bare = asyncio.run(names(build_server(ReadPort(falkordb), "brain:none")))
    full = asyncio.run(names(serve(falkordb, "t0")))
    memory_tools = {"remember", "recall", "record_episode", "learned", "handoff", "claim"}
    assert not memory_tools & set(bare)
    assert memory_tools <= set(full)
    for tool in full.values():
        assert not {"graph", "cypher", "query", "tenant"} & set(tool.input_schema["properties"]), tool.name
    assert full["recall"].annotations.read_only_hint is True
    assert all(full[name].annotations.read_only_hint is False for name in memory_tools - {"recall"})
    assert full["remember"].annotations.destructive_hint is True
    assert full["record_episode"].annotations.destructive_hint is False
