import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from falkordb import FalkorDB
from fastapi.testclient import TestClient
from test_api import ORIGIN, PLAN, Scripted

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
RAISE_FLAG = "MATCH (:Event {eid: 'EVT-8-incident_opened-1219'})-[:EXPECTS]->(x:Expectation) SET x.responded = true"
ASK = {"tenant": "apex", "kind": "SILENCE", "question": QUESTION, "session": SESSION}


@pytest.fixture(scope="module")
def port(falkordb: FalkorDB) -> ReadPort:
    if not Path("data/raw/apex").exists():
        pytest.skip("pinned Apex data not fetched")
    falkordb.select_graph(GRAPH).query("MATCH (n) DETACH DELETE n")
    build(falkordb, GRAPH, Path("data/raw/apex"), Path("pins/datasets.json"))
    return ReadPort(falkordb)


class Rig:
    def __init__(self, port: ReadPort, falkordb: FalkorDB, tmp_path: Path, llm: Scripted, graph: str = GRAPH) -> None:
        self.llm, self.falkordb = llm, falkordb
        self.memory = MemoryStore(falkordb, f"ask{uuid.uuid4().hex[:6]}")
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

    def graph(self, cypher: str) -> list[list[Any]]:
        result = self.falkordb.select_graph(self.memory.graph_name(PRINCIPAL)).query(cypher)
        return [list(row) for row in result.result_set]


@pytest.fixture
def private_graph(port: ReadPort, falkordb: FalkorDB) -> Iterator[str]:
    # a copy the test may change, so no other test sees the Apex graph differ
    name = f"{GRAPH}-{uuid.uuid4().hex[:6]}"
    falkordb.select_graph(GRAPH).copy(name)
    yield name
    falkordb.select_graph(name).delete()


@pytest.fixture
def rig(port: ReadPort, falkordb: FalkorDB, tmp_path: Path) -> Rig:
    return Rig(port, falkordb, tmp_path, Scripted([PLAN, PLAN, PLAN, PLAN]))


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
    assert rig.llm.calls == 1
    again = rig.ask(session=OTHER, question=QUESTION.upper() + "  ").json()
    assert rig.llm.calls == 1
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
    port: ReadPort, falkordb: FalkorDB, tmp_path: Path, private_graph: str
) -> None:
    rig = Rig(port, falkordb, tmp_path, Scripted([PLAN, PLAN, PLAN]), private_graph)
    assert rig.ask().json()["answer"]["exists"] is False
    assert rig.ask(session=OTHER).json()["recalled"] is True
    # a risk flag now exists in the graph the answer was drawn from
    falkordb.select_graph(private_graph).query(RAISE_FLAG)
    changed = rig.ask(session=OTHER).json()
    assert changed["recalled"] is False
    assert changed["answer"]["exists"] is True
    assert rig.llm.calls == 2
    # the new answer replaced the old procedure, so the next repeat is recalled again
    assert rig.ask(session=OTHER).json()["recalled"] is True
    assert rig.llm.calls == 2


@pytest.mark.ac("AC-T2-01")
def test_an_answer_the_graph_has_contradicted_is_never_learned(
    port: ReadPort, falkordb: FalkorDB, tmp_path: Path, private_graph: str
) -> None:
    rig = Rig(port, falkordb, tmp_path, Scripted([PLAN, PLAN]), private_graph)
    rig.ask()
    falkordb.select_graph(private_graph).query(RAISE_FLAG)
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
    rig = Rig(port, falkordb, tmp_path, Scripted(["no json", "no json", '{"exists": true}']))
    got = rig.ask()
    assert got.status_code == 200
    assert got.json()["answer"] == {"exists": True}
    assert rig.graph("MATCH (n) RETURN count(n)") == [[0]]


def test_a_live_tenant_still_refuses_questions(rig: Rig) -> None:
    assert rig.ask(tenant="live").status_code == 422
