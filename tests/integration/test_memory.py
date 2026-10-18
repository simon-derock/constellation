import threading
import uuid

import pytest
from falkordb import FalkorDB

from constellation.memory.store import ConflictError, MemoryStore, SemanticFact

pytestmark = pytest.mark.integration


@pytest.fixture
def store(falkordb: FalkorDB) -> MemoryStore:
    # a fresh tenant per test: graphs are the isolation unit, so tests never share one
    return MemoryStore(falkordb, tenant=f"t{uuid.uuid4().hex[:8]}")


@pytest.mark.ac("AC-T2-05")
def test_principals_get_separate_graphs_cloned_from_the_template(store: MemoryStore) -> None:
    a, b = store.provision("alice"), store.provision("bob")
    assert a != b
    assert store.provision("alice") == a
    store.write_fact("alice", "colour", "teal", expected_ver=0)
    assert store.read_fact("bob", "colour") is None


@pytest.mark.ac("AC-T2-05")
@pytest.mark.parametrize("principal", ["", "../x", "a:b", "A", "x" * 80, "a b", "a`b", "a'b"])
def test_a_principal_that_could_change_the_graph_name_is_refused(store: MemoryStore, principal: str) -> None:
    with pytest.raises(ValueError, match="principal"):
        store.provision(principal)


@pytest.mark.ac("AC-T2-04")
def test_a_stale_version_is_a_conflict_and_a_fresh_one_wins(store: MemoryStore) -> None:
    store.provision("alice")
    assert store.write_fact("alice", "k", "v1", expected_ver=0) == 1
    with pytest.raises(ConflictError):
        store.write_fact("alice", "k", "stale", expected_ver=0)
    assert store.write_fact("alice", "k", "v2", expected_ver=1) == 2
    fact = store.read_fact("alice", "k")
    assert fact is not None
    assert (fact.value, fact.ver) == ("v2", 2)


@pytest.mark.ac("AC-T2-04")
def test_thirty_two_agents_lose_no_update(store: MemoryStore) -> None:
    store.provision("shared")
    store.write_fact("shared", "counter", "0", expected_ver=0)
    agents, increments = 32, 40
    retries: list[int] = []

    def worker() -> None:
        own = 0
        for _ in range(increments):
            own += store.update_fact("shared", "counter", lambda v: str(int(v) + 1)).retries
        retries.append(own)

    threads = [threading.Thread(target=worker) for _ in range(agents)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    fact = store.read_fact("shared", "counter")
    assert fact is not None
    # serial replay of the same increments ends at the same value; every conflict was retried, none dropped
    assert fact.value == str(agents * increments)
    assert fact.ver == agents * increments + 1
    assert sum(retries) > 0


@pytest.mark.ac("AC-T2-02")
def test_sessions_survive_a_restart_in_order_and_windows_are_bounded(falkordb: FalkorDB, store: MemoryStore) -> None:
    store.provision("alice")
    for n in range(7):
        store.append_turn("alice", "s1", "user" if n % 2 == 0 else "assistant", f"m{n}", proof_id=f"p{n}")
    reopened = MemoryStore(falkordb, tenant=store.tenant)
    assert [t.content for t in reopened.history("alice", "s1")] == [f"m{n}" for n in range(7)]
    assert [t.content for t in reopened.recent("alice", "s1", 3)] == ["m4", "m5", "m6"]
    assert reopened.history("alice", "other") == []


@pytest.mark.ac("AC-T2-03")
def test_a_handoff_preserves_the_task_state_exactly_and_is_claimed_once(store: MemoryStore) -> None:
    store.provision("team")
    state = {"task": "triage", "evidence": ["ENG-1", "slack-9"], "step": 3}
    handoff = store.handoff("team", "planner", "executor", state)
    assert store.claimed_by("team", handoff.hid) is None
    assert store.claim("team", handoff.hid, "executor") == state
    with pytest.raises(ConflictError):
        store.claim("team", handoff.hid, "executor")
    assert store.claimed_by("team", handoff.hid) == "executor"
    assert store.claimed_by("team", "no-such-handoff") is None


@pytest.mark.ac("AC-T2-03")
def test_a_handoff_is_refused_to_the_wrong_agent_and_to_a_tampered_state(
    falkordb: FalkorDB, store: MemoryStore
) -> None:
    store.provision("team")
    handoff = store.handoff("team", "planner", "executor", {"step": 1})
    with pytest.raises(PermissionError):
        store.claim("team", handoff.hid, "intruder")
    falkordb.select_graph(store.graph_name("team")).query("MATCH (h:Handoff) SET h.state = '{\"step\":99}'")
    with pytest.raises(ValueError, match="hash"):
        store.claim("team", handoff.hid, "executor")


@pytest.mark.ac("AC-T2-03")
def test_exactly_one_of_many_concurrent_claimants_wins(store: MemoryStore) -> None:
    store.provision("team")
    handoff = store.handoff("team", "planner", "executor", {"step": 1})
    wins: list[int] = []

    def claim() -> None:
        try:
            store.claim("team", handoff.hid, "executor")
            wins.append(1)
        except ConflictError:
            pass

    threads = [threading.Thread(target=claim) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(wins) == 1


@pytest.mark.ac("AC-T2-01")
def test_semantic_facts_need_two_agreeing_episodes_and_ignore_contradictions(store: MemoryStore) -> None:
    store.provision("alice")
    store.record_episode("alice", "t1", subject="billing owner", value="Sam", evidence=["e1"])
    assert store.consolidate("alice") == []
    store.record_episode("alice", "t2", subject="billing owner", value="Sam", evidence=["e2"])
    store.record_episode("alice", "t3", subject="search owner", value="Priya", evidence=["e3"])
    store.record_episode("alice", "t4", subject="search owner", value="Yusuf", evidence=["e4"])
    made = store.consolidate("alice")
    assert [(f.subject, f.value) for f in made] == [("billing owner", "Sam")]
    assert store.consolidate("alice") == []


@pytest.mark.ac("AC-T2-01")
def test_a_semantic_fact_lists_the_evidence_of_the_episodes_that_agree_with_it(store: MemoryStore) -> None:
    store.provision("alice")
    store.record_episode("alice", "t1", subject="owner", value="Sam", evidence=["e2", "e1"])
    store.record_episode("alice", "t2", subject="owner", value="Sam", evidence=["e2", "e3"])
    assert store.semantic_facts("alice") == []
    store.consolidate("alice")
    store.record_episode("alice", "t3", subject="owner", value="Priya", evidence=["e9"])
    assert store.semantic_facts("alice") == [SemanticFact("owner", "Sam", 2, ("e1", "e2", "e3"))]


@pytest.mark.ac("AC-T2-01")
def test_a_procedure_is_reused_only_after_it_verifies_on_the_current_graph(store: MemoryStore) -> None:
    store.provision("alice")
    store.save_procedure("alice", "owner_question", ["find_events", "could_have_known"])
    assert store.reuse_procedure("alice", "owner_question", verify=lambda plan: "could_have_known" in plan) == [
        "find_events",
        "could_have_known",
    ]
    assert store.reuse_procedure("alice", "owner_question", verify=lambda plan: False) is None
    assert store.reuse_procedure("alice", "unknown_task", verify=lambda plan: True) is None


@pytest.mark.ac("AC-T2-05")
def test_a_fleet_of_clones_never_reads_across_tenants(falkordb: FalkorDB) -> None:
    tenant = f"fleet{uuid.uuid4().hex[:6]}"
    store = MemoryStore(falkordb, tenant=tenant)
    principals = [f"user{i:03d}" for i in range(60)]
    for p in principals:
        store.provision(p)
        store.write_fact(p, "marker", f"owned-by-{p}", expected_ver=0)
    for p in principals:
        fact = store.read_fact(p, "marker")
        assert fact is not None
        assert fact.value == f"owned-by-{p}"
