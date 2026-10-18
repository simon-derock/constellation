import json
import uuid
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from falkordb import FalkorDB
from fastapi.testclient import TestClient
from test_api import ORIGIN, PLAN, Scripted

from constellation.agents.llm import Reply
from constellation.api.app import Settings, Tenant, create_app
from constellation.graph.read import ReadPort
from constellation.ingest.build_apex import build
from constellation.memory.ask import PRINCIPAL, seal
from constellation.memory.store import MemoryStore

pytestmark = pytest.mark.integration
GRAPH = "brain:apex-ask-memory"
SESSION = "11111111-aaaa-4bbb-8ccc-222222222222"
OTHER = "99999999-eeee-4fff-8aaa-000000000000"
QUESTION = "Was a risk flag raised after the Day 8 incident with Jax?"
EXPECTED = "MATCH (:Event {eid: 'EVT-8-incident_opened-1219'})-[:EXPECTS]->(x:Expectation)"
ASK = {"tenant": "apex", "kind": "SILENCE", "question": QUESTION, "session": SESSION}


@pytest.fixture(scope="module")
def port(falkordb: FalkorDB) -> Iterator[ReadPort]:
    if not Path("data/raw/apex").exists():
        pytest.skip("pinned Apex data not fetched")
    falkordb.select_graph(GRAPH).query("MATCH (n) DETACH DELETE n")
    build(falkordb, GRAPH, Path("data/raw/apex"), Path("pins/datasets.json"))
    yield ReadPort(falkordb)
    # the shared engine keeps every graph in memory, so this one is dropped when its tests are done
    falkordb.select_graph(GRAPH).delete()


class Model(Scripted):
    # a memory-backed Ask may end with a follow-up turn that offers propose_action; here it declines and is counted
    # apart, so `calls` counts only the calls that answer the question
    def __init__(self, replies: list[str]) -> None:
        super().__init__(replies)
        self.follow_ups = 0

    def chat(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> Reply:
        if any(t["function"]["name"] == "propose_action" for t in tools):
            self.follow_ups += 1
            return Reply("nothing to propose", (), {"role": "assistant", "content": "nothing to propose"})
        return super().chat(messages, tools)


class Rig:
    def __init__(
        self,
        port: ReadPort,
        falkordb: FalkorDB,
        tmp_path: Path,
        llm: Model,
        graph: str = GRAPH,
        memory_tenant: str = "",
    ) -> None:
        self.llm, self.falkordb = llm, falkordb
        self.memory = MemoryStore(falkordb, memory_tenant or f"ask{uuid.uuid4().hex[:6]}")
        settings = Settings(
            tenants={
                "apex": Tenant("apex", graph, "Apex Athletics", {"Alex": "engineering_mobile", "Tom": "hr_ops"}),
                "live": Tenant("live", graph, "Live", {}, live=True),
            },
            allowed_origins=(ORIGIN,),
            published=tmp_path,
            asks_per_minute=60,
            asks_per_day=1_000,
        )
        self.client = TestClient(create_app(port, settings, llm_factory=lambda: llm, memory=self.memory))

    def ask(self, **overrides: Any) -> Any:
        return self.client.post("/api/v1/ask", json={**ASK, **overrides})

    def view(self, session: str = SESSION, tenant: str = "apex") -> Any:
        return self.client.get("/api/v1/memory", params={"tenant": tenant, "session": session})

    def graph(self, cypher: str) -> list[list[Any]]:
        result = self.falkordb.select_graph(self.memory.graph_name(PRINCIPAL)).query(cypher)
        return [list(row) for row in result.result_set]


@pytest.fixture
def raise_flag(port: ReadPort, falkordb: FalkorDB) -> Iterator[Callable[[], None]]:
    # changes what the answer was drawn from, and puts every value back so the tests stay independent
    graph = falkordb.select_graph(GRAPH)
    before = graph.query(f"{EXPECTED} RETURN x.response_type, x.responded").result_set
    yield lambda: graph.query(f"{EXPECTED} SET x.responded = true")
    for kind, was in before:
        graph.query(f"{EXPECTED} WHERE x.response_type = $kind SET x.responded = $was", {"kind": kind, "was": was})


@pytest.fixture
def rig(port: ReadPort, falkordb: FalkorDB, tmp_path: Path) -> Rig:
    return Rig(port, falkordb, tmp_path, Model([PLAN, PLAN, PLAN, PLAN]))


@pytest.mark.ac("AC-T2-02")
def test_an_answered_question_is_remembered_as_two_turns_and_an_episode(rig: Rig) -> None:
    got = rig.ask().json()
    hashes = [q["sha256"] for q in got["proof"]["queries"]]
    user, assistant = rig.memory.history(PRINCIPAL, SESSION)
    assert (user.role, user.content) == ("user", QUESTION)
    assert (assistant.role, assistant.content) == ("assistant", "No, it did not happen.")
    assert assistant.proof_id == seal(hashes)
    [[task, subject, value, evidence]] = rig.graph("MATCH (e:Episode) RETURN e.task, e.subject, e.value, e.evidence")
    assert (task, value) == ("SILENCE", '{"exists":false}')
    assert subject == "apex|silence|was a risk flag raised after the day 8 incident with jax"
    assert json.loads(evidence) == hashes


@pytest.mark.ac("AC-T2-01")
def test_two_agreeing_answers_become_a_learned_fact_and_one_does_not(rig: Rig) -> None:
    rig.ask()
    assert rig.graph("MATCH (f:Fact) RETURN f.id") == []
    rig.ask(session=OTHER)
    [[fact_id, value, support]] = rig.graph("MATCH (f:Fact) RETURN f.id, f.value, f.support")
    assert fact_id.startswith("sem:apex|silence|")
    assert (value, support) == ('{"exists":false}', 2)


@pytest.mark.ac("AC-T2-01")
@pytest.mark.ac("AC-INV-03")
def test_a_repeated_question_is_recalled_with_no_model_call_and_a_proof_that_replays(rig: Rig) -> None:
    first = rig.ask().json()
    assert first["recalled"] is False
    assert (rig.llm.calls, rig.llm.follow_ups) == (1, 1)
    again = rig.ask(session=OTHER, question=QUESTION.upper() + "  ").json()
    # a recall makes no model call of any kind: no answering call and no follow-up turn proposing an action
    assert (rig.llm.calls, rig.llm.follow_ups) == (1, 1)
    assert again["recalled"] is True
    assert again["answer"] == first["answer"]
    assert again["proof"] == first["proof"]
    assert again["trace"]["llm_calls"] == 0
    assert (again["trace"]["prompt_tokens"], again["trace"]["completion_tokens"]) == (0, 0)
    replayed = rig.client.post("/api/v1/replay", json={"tenant": "apex", "queries": again["proof"]["queries"]})
    assert replayed.json()["all_match"] is True
    # the recall is a turn pair and an episode in the asking session, like any answer
    assert [t.role for t in rig.memory.history(PRINCIPAL, OTHER)] == ["user", "assistant"]
    assert rig.graph("MATCH (p:Procedure) RETURN p.verified_runs, p.failed_runs") == [[1, 0]]


@pytest.mark.ac("AC-T2-01")
def test_a_recall_is_refused_once_the_graph_no_longer_returns_the_stored_hashes(
    port: ReadPort, falkordb: FalkorDB, tmp_path: Path, raise_flag: Callable[[], None]
) -> None:
    rig = Rig(port, falkordb, tmp_path, Model([PLAN, PLAN, PLAN]))
    assert rig.ask().json()["answer"]["exists"] is False
    assert rig.ask(session=OTHER).json()["recalled"] is True
    # a risk flag now exists in the graph the answer was drawn from
    raise_flag()
    changed = rig.ask(session=OTHER).json()
    assert changed["recalled"] is False
    assert changed["answer"]["exists"] is True
    assert rig.llm.calls == 2
    # the new answer replaced the old procedure, so the next repeat is recalled again
    assert rig.ask(session=OTHER).json()["recalled"] is True
    assert rig.llm.calls == 2


@pytest.mark.ac("AC-T2-01")
def test_an_answer_the_graph_has_contradicted_is_never_learned(
    port: ReadPort, falkordb: FalkorDB, tmp_path: Path, raise_flag: Callable[[], None]
) -> None:
    rig = Rig(port, falkordb, tmp_path, Model([PLAN, PLAN]))
    rig.ask()
    raise_flag()
    rig.ask()
    rig.ask(session=OTHER)
    assert rig.graph("MATCH (f:Fact) RETURN f.id") == []
    assert rig.graph("MATCH (e:Episode) RETURN count(e)") == [[3]]


@pytest.mark.ac("AC-T2-01")
def test_a_stored_plan_that_cannot_be_read_is_not_reused_and_does_not_break_the_ask(rig: Rig) -> None:
    rig.ask()
    rig.graph("MATCH (p:Procedure) SET p.plan = '[\"not json'")
    again = rig.ask(session=OTHER)
    assert again.status_code == 200
    assert again.json()["recalled"] is False
    assert rig.llm.calls == 2


@pytest.mark.ac("AC-INV-01")
def test_a_perspective_is_recalled_only_for_the_person_and_day_it_was_asked_from(rig: Rig) -> None:
    plan = json.dumps({"day": 8, "event_type": "incident_opened", "people": ["Jax"], "target_type": ""})
    rig.llm.replies = [plan, plan, plan]
    ask = {"kind": "PERSPECTIVE", "question": "Would Alex have learned of the incident?", "actor": "Alex", "day": 28}
    assert rig.ask(**ask).json()["recalled"] is False
    assert rig.ask(**ask, session=OTHER).json()["recalled"] is True
    assert rig.ask(**{**ask, "actor": "Tom"}).json()["recalled"] is False
    assert rig.ask(**{**ask, "day": 29}).json()["recalled"] is False
    assert rig.llm.calls == 3


@pytest.mark.ac("AC-T2-05")
def test_the_same_words_asked_in_other_sessions_stay_in_their_own_session(rig: Rig) -> None:
    rig.ask()
    rig.ask(session=OTHER)
    assert [t.role for t in rig.memory.history(PRINCIPAL, SESSION)] == ["user", "assistant"]
    assert [t.role for t in rig.memory.history(PRINCIPAL, OTHER)] == ["user", "assistant"]
    assert rig.memory.history(PRINCIPAL, "33333333-cccc-4ddd-8eee-444444444444") == []


@pytest.mark.parametrize(
    "session",
    [
        "",
        "short",
        "UPPERCASE-SESSION-ID",
        "has space in it",
        "x" * 65,
        "a;b-1234567",
        "session_with_underscore",
        "ünïcode-session",
    ],
)
def test_a_malformed_session_is_refused_before_any_model_call(rig: Rig, session: str) -> None:
    assert rig.ask(session=session).status_code == 422
    assert rig.llm.calls == 0


def test_without_a_session_nothing_is_remembered(rig: Rig) -> None:
    body = {k: v for k, v in ASK.items() if k != "session"}
    assert rig.client.post("/api/v1/ask", json=body).status_code == 200
    assert rig.graph("MATCH (n) RETURN count(n)") == [[0]]


def test_an_answer_the_graph_did_not_decide_is_returned_but_not_remembered(
    port: ReadPort, falkordb: FalkorDB, tmp_path: Path
) -> None:
    # no usable plan, so the ReAct loop's final JSON stands on the model's word alone
    rig = Rig(port, falkordb, tmp_path, Model(["no json", "no json", '{"exists": true}']))
    got = rig.ask()
    assert got.status_code == 200
    assert got.json()["answer"] == {"exists": True}
    assert rig.graph("MATCH (n) RETURN count(n)") == [[0]]


def test_a_live_tenant_still_refuses_questions(rig: Rig) -> None:
    assert rig.ask(tenant="live").status_code == 422


@pytest.mark.ac("AC-T2-01")
def test_the_memory_view_shows_turns_what_was_learned_with_its_evidence_and_the_procedure_count(rig: Rig) -> None:
    first = rig.ask().json()
    seen = rig.view().json()
    assert [(t["role"], t["content"]) for t in seen["turns"]] == [
        ("user", QUESTION),
        ("assistant", "No, it did not happen."),
    ]
    assert seen["turns"][1]["seal"] == seal([q["sha256"] for q in first["proof"]["queries"]])
    assert seen["turns"][0]["seal"] == ""
    assert (seen["facts"], seen["procedures"]) == ([], 1)
    rig.ask()
    [fact] = rig.view().json()["facts"]
    assert fact["question"] == QUESTION
    assert (fact["kind"], fact["verdict"], fact["support"]) == ("SILENCE", "No, it did not happen.", 2)
    assert fact["evidence"] == sorted({q["sha256"] for q in first["proof"]["queries"]})


@pytest.mark.ac("AC-T2-05")
def test_a_session_never_sees_another_sessions_turns_or_the_questions_it_asked(rig: Rig) -> None:
    other = "What happened on Day 8 after the incident with Jax?"
    rig.ask()
    rig.ask()
    rig.ask(session=OTHER, question=other)
    mine, theirs = rig.view().json(), rig.view(OTHER).json()
    assert {t["content"] for t in mine["turns"]} == {QUESTION, "No, it did not happen."}
    assert {t["content"] for t in theirs["turns"]} == {other, "No, it did not happen."}
    # the fact learned from my two asks is the principal's, but it is shown only to a session that asked it
    assert [f["question"] for f in mine["facts"]] == [QUESTION]
    assert theirs["facts"] == []
    nobody = rig.view("33333333-cccc-4ddd-8eee-444444444444").json()
    assert (nobody["turns"], nobody["facts"]) == ([], [])
    assert nobody["procedures"] == mine["procedures"] == 2


@pytest.mark.ac("AC-T2-02")
def test_a_session_is_restored_by_its_id_after_a_restart(
    port: ReadPort, falkordb: FalkorDB, tmp_path: Path, rig: Rig
) -> None:
    rig.ask()
    restarted = Rig(port, falkordb, tmp_path, Model([]), memory_tenant=rig.memory.tenant)
    assert [t["role"] for t in restarted.view().json()["turns"]] == ["user", "assistant"]
    assert restarted.ask(session=OTHER).json()["recalled"] is True
    assert restarted.llm.calls == 0


def test_viewing_memory_changes_nothing(rig: Rig) -> None:
    rig.ask()
    before = rig.graph("MATCH (n) RETURN count(n)"), rig.graph("MATCH (p:Procedure) RETURN p.verified_runs")
    for _ in range(3):
        assert rig.view().status_code == 200
    assert (rig.graph("MATCH (n) RETURN count(n)"), rig.graph("MATCH (p:Procedure) RETURN p.verified_runs")) == before


@pytest.mark.parametrize("session", ["", "short", "UPPERCASE-SESSION-ID", "x" * 65, "a b-12345678", "a;b-12345678"])
def test_the_memory_view_refuses_a_malformed_session(rig: Rig, session: str) -> None:
    assert rig.view(session).status_code == 422


def test_the_memory_view_needs_a_session_and_a_known_askable_tenant(rig: Rig) -> None:
    assert rig.client.get("/api/v1/memory", params={"tenant": "apex"}).status_code == 422
    assert rig.view(tenant="nope").status_code == 422
    assert rig.view(tenant="live").status_code == 422


def test_the_memory_view_is_rate_limited_like_the_other_reads(rig: Rig) -> None:
    codes = [rig.view().status_code for _ in range(31)]
    assert codes == [200] * 30 + [429]


def test_without_a_memory_store_ask_is_stateless_and_the_view_is_unavailable(port: ReadPort, tmp_path: Path) -> None:
    settings = Settings(tenants={"apex": Tenant("apex", GRAPH, "Apex", {})}, allowed_origins=(), published=tmp_path)
    llm = Model([PLAN, PLAN])
    client = TestClient(create_app(port, settings, llm_factory=lambda: llm))
    assert [client.post("/api/v1/ask", json=ASK).json()["recalled"] for _ in range(2)] == [False, False]
    assert llm.calls == 2
    assert client.get("/api/v1/memory", params={"tenant": "apex", "session": SESSION}).status_code == 503
