import asyncio
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


@pytest.mark.ac("AC-INV-06")
def test_memory_tools_are_absent_without_a_store_and_no_tool_chooses_a_graph_or_a_tenant(falkordb: FalkorDB) -> None:
    async def names(server: FastMCP) -> dict[str, Any]:
        async with Client(server) as client:
            return {t.name: t for t in await client.list_tools()}

    bare = asyncio.run(names(build_server(ReadPort(falkordb), "brain:none")))
    full = asyncio.run(names(serve(falkordb, "t0")))
    assert not {"remember", "recall"} & set(bare)
    assert {"remember", "recall"} <= set(full)
    for tool in full.values():
        assert not {"graph", "cypher", "query", "tenant"} & set(tool.input_schema["properties"]), tool.name
    assert full["recall"].annotations.read_only_hint is True
    assert full["remember"].annotations.read_only_hint is False
