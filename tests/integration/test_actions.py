import threading
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from falkordb import FalkorDB

from constellation.actions.sinks import DryRunSink, SinkError
from constellation.actions.store import ActionStore, CapError
from constellation.memory.store import ConflictError, MemoryStore

pytestmark = pytest.mark.integration
PAYLOAD = {"kind": "file_issue", "title": "Ownership gap: kubernetes-deploy", "body": "Evidence: abc"}
EVIDENCE = [{"name": "ownership_all", "params": {}, "sha256": "a" * 64}]


class CountingSink:
    def __init__(self, fail: bool = False) -> None:
        self.calls, self.fail = 0, fail

    def execute(self, action: Mapping[str, Any]) -> dict[str, object]:
        self.calls += 1
        if self.fail:
            raise SinkError("provider refused")
        return {"dry_run": False, "url": "https://github.com/o/r/issues/1", "number": 1}


@pytest.fixture
def store(falkordb: FalkorDB) -> ActionStore:
    tenant = f"t{uuid.uuid4().hex[:8]}"
    return ActionStore(MemoryStore(falkordb, tenant), clock=lambda: datetime(2026, 10, 18, 12, tzinfo=UTC))


def propose(store: ActionStore, title: str = PAYLOAD["title"]) -> str:
    return store.propose(PAYLOAD["kind"], title, PAYLOAD["body"], EVIDENCE).id


@pytest.mark.ac("AC-INV-05")
def test_proposing_the_same_payload_twice_is_one_action(store: ActionStore) -> None:
    first, second = propose(store), propose(store)
    assert first == second
    assert len(store.recent()) == 1
    assert store.get(first).status == "proposed"
    assert store.get(first).evidence == EVIDENCE


@pytest.mark.ac("AC-INV-05")
def test_an_action_cannot_execute_before_it_is_approved(store: ActionStore) -> None:
    action_id = propose(store)
    sink = CountingSink()
    with pytest.raises(ConflictError):
        store.execute(action_id, sink, mode="real", daily_cap=5)
    assert sink.calls == 0
    assert store.get(action_id).status == "proposed"


@pytest.mark.ac("AC-INV-05")
def test_the_lifecycle_records_who_approved_and_what_happened(store: ActionStore) -> None:
    action_id = propose(store)
    store.approve(action_id, "operator")
    done = store.execute(action_id, DryRunSink("o/r"), mode="dry-run", daily_cap=5)
    assert (done.status, done.approver, done.mode) == ("executed", "operator", "dry-run")
    assert done.result is not None
    assert done.result["dry_run"] is True


def test_a_rejected_action_can_be_neither_approved_nor_executed(store: ActionStore) -> None:
    action_id = propose(store)
    store.reject(action_id, "operator")
    with pytest.raises(ConflictError):
        store.approve(action_id, "operator")
    with pytest.raises(ConflictError):
        store.execute(action_id, CountingSink(), mode="real", daily_cap=5)


@pytest.mark.ac("AC-INV-05")
def test_exactly_one_of_many_concurrent_executions_reaches_the_sink(store: ActionStore) -> None:
    action_id = propose(store)
    store.approve(action_id, "operator")
    sink = CountingSink()
    won: list[int] = []

    def run() -> None:
        try:
            store.execute(action_id, sink, mode="real", daily_cap=5)
            won.append(1)
        except ConflictError:
            pass

    threads = [threading.Thread(target=run) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert (sum(won), sink.calls) == (1, 1)


def test_a_failed_execution_is_recorded_and_never_retried_without_a_new_approval(store: ActionStore) -> None:
    action_id = propose(store)
    store.approve(action_id, "operator")
    failed = store.execute(action_id, CountingSink(fail=True), mode="real", daily_cap=5)
    assert failed.status == "failed"
    assert failed.result == {"error": "provider refused"}
    with pytest.raises(ConflictError):
        store.execute(action_id, CountingSink(), mode="real", daily_cap=5)


def test_real_executions_are_capped_per_day_and_dry_runs_are_not(store: ActionStore) -> None:
    ids = [propose(store, title=f"Gap {i}") for i in range(4)]
    for action_id in ids[:2]:
        store.approve(action_id, "operator")
        store.execute(action_id, CountingSink(), mode="real", daily_cap=2)
    store.approve(ids[2], "operator")
    with pytest.raises(CapError):
        store.execute(ids[2], CountingSink(), mode="real", daily_cap=2)
    assert store.get(ids[2]).status == "approved"
    store.approve(ids[3], "public demo")
    assert store.execute(ids[3], DryRunSink("o/r"), mode="dry-run", daily_cap=2).status == "executed"


@pytest.mark.ac("AC-INV-05")
def test_no_execution_without_an_approval_exists_and_tampering_is_detected(
    falkordb: FalkorDB, store: ActionStore
) -> None:
    action_id = propose(store)
    store.approve(action_id, "operator")
    store.execute(action_id, DryRunSink("o/r"), mode="dry-run", daily_cap=5)
    assert store.unapproved_executions() == []
    rogue = propose(store, title="Rogue")
    falkordb.select_graph(store.graph).query("MATCH (a:Action {id: $id}) SET a.status = 'executed'", {"id": rogue})
    assert store.unapproved_executions() == [rogue]


@pytest.mark.ac("AC-INV-05")
def test_provenance_is_recorded_and_defaults_to_a_rule_suggestion(falkordb: FalkorDB, store: ActionStore) -> None:
    by_rule = store.propose(PAYLOAD["kind"], "From a rule", PAYLOAD["body"], EVIDENCE)
    by_agent = store.propose(PAYLOAD["kind"], "From the agent", PAYLOAD["body"], EVIDENCE, provenance="agent")
    assert (by_rule.provenance, by_agent.provenance) == ("rule", "agent")
    assert store.get(by_agent.id).provenance == "agent"
    falkordb.select_graph(store.graph).query("MATCH (a:Action {id: $id}) REMOVE a.provenance", {"id": by_rule.id})
    assert store.get(by_rule.id).provenance == "rule"


@pytest.mark.ac("AC-INV-05")
def test_an_agent_proposal_walks_the_same_approval_flow_as_a_rule_suggestion(store: ActionStore) -> None:
    action_id = store.propose(PAYLOAD["kind"], "Agent", PAYLOAD["body"], EVIDENCE, provenance="agent").id
    sink = CountingSink()
    with pytest.raises(ConflictError):
        store.execute(action_id, sink, mode="real", daily_cap=5)
    store.approve(action_id, "operator")
    done = store.execute(action_id, DryRunSink("o/r"), mode="dry-run", daily_cap=5)
    assert (done.status, done.approver, done.provenance) == ("executed", "operator", "agent")
    assert sink.calls == 0
    assert store.unapproved_executions() == []
