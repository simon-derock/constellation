import random
from pathlib import Path

import pytest
from falkordb import FalkorDB

from constellation.agents.toolbox import Perspective, Toolbox
from constellation.brain.access import born_days, could_have_known, visible_artifacts
from constellation.graph.catalogue import cypher
from constellation.graph.read import ReadPort
from constellation.ingest.apex import ApexCorpus, load_apex
from constellation.ingest.build_apex import build

pytestmark = pytest.mark.integration
RAW = Path("data/raw/apex")
GRAPH = "brain:apex-tools"
SIGNIFICANT = {
    "incident_opened",
    "incident_resolved",
    "design_discussion",
    "retrospective",
    "watercooler_chat",
    "postmortem_created",
    "inbound_external_email",
    "pr_review",
    "knowledge_gap_detected",
}


@pytest.fixture(scope="module")
def apex() -> ApexCorpus:
    if not RAW.exists():
        pytest.skip("pinned Apex data not fetched")
    return load_apex(RAW / "corpus/corpus-00000.parquet", Path("third_party/orgforge/config.yaml"))


@pytest.fixture(scope="module")
def port(falkordb: FalkorDB, apex: ApexCorpus) -> ReadPort:
    falkordb.select_graph(GRAPH).query("MATCH (n) DETACH DELETE n")
    build(falkordb, GRAPH, RAW, Path("pins/datasets.json"))
    return ReadPort(falkordb)


def _sample(apex: ApexCorpus, n: int, seed: int) -> list[tuple[str, str, int]]:
    rng = random.Random(seed)
    events = [e for e in apex.events if e.type in SIGNIFICANT and e.day >= 1]
    actors = sorted(apex.roles)
    return [(rng.choice(actors), e.event_id, e.day) for e in rng.sample(events, n)]


@pytest.mark.ac("AC-T3-03")
def test_graph_could_have_known_equals_the_oracle(apex: ApexCorpus, port: ReadPort) -> None:
    by_id = {e.event_id: e for e in apex.events}
    born = born_days(apex.events)
    corpus = frozenset(a.doc_id for a in apex.artifacts)
    for actor, event, day in _sample(apex, 300, seed=7):
        role = apex.roles[actor]
        tools = Toolbox(port, GRAPH, Perspective(actor, role, day))
        got = tools.could_have_known(event)["could_actor_have_known"]
        assert got == could_have_known(apex.events, born, actor, role, by_id[event], day, corpus), (actor, event)


@pytest.mark.ac("AC-INV-01")
def test_a_perspective_never_returns_an_artifact_outside_the_cone(apex: ApexCorpus, port: ReadPort) -> None:
    for actor, event, day in _sample(apex, 300, seed=11):
        role = apex.roles[actor]
        tools = Toolbox(port, GRAPH, Perspective(actor, role, day))
        tools.event_artifacts(event)
        tools.could_have_known(event)
        cone = visible_artifacts(apex.events, actor, role, day)
        leaked = {i for call in tools.calls for i in call.result_ids} - cone
        assert leaked == set(), (actor, event, leaked)


def test_perspective_tools_refuse_to_run_without_a_perspective(port: ReadPort) -> None:
    with pytest.raises(PermissionError):
        Toolbox(port, GRAPH).could_have_known("EVT-8-incident_opened-1219")


def test_event_linking_ranks_named_people_first_and_reveals_no_artifacts(port: ReadPort) -> None:
    tools = Toolbox(port, GRAPH)
    found = tools.find_events(8, "incident_opened", ["Jax"])
    assert found
    assert all(event["type"] == "incident_opened" for event in found)
    top = found[0]["actors"]
    assert isinstance(top, list)
    assert "Jax" in top
    assert tools.calls[-1].result_ids == ()


def test_every_call_is_recorded_with_its_proofs(port: ReadPort) -> None:
    tools = Toolbox(port, GRAPH)
    tools.event_artifacts("EVT-8-incident_opened-1219")
    tools.causal_links("EVT-8-incident_opened-1219")
    assert [c.tool for c in tools.calls] == ["event_artifacts", "causal_links"]
    assert all(len(p) == 64 for c in tools.calls for p in c.proofs)


def test_dead_ends_are_marked_so_recovery_can_be_scored(port: ReadPort) -> None:
    tools = Toolbox(port, GRAPH)
    tools.find_events(8, "no_such_event_type")
    tools.find_events(8, "incident_opened")
    assert [c.empty for c in tools.calls] == [True, False]


def test_event_lookups_carry_summaries_for_disambiguation(port: ReadPort) -> None:
    found = Toolbox(port, GRAPH).find_events(8, "incident_opened")
    assert found
    assert all(isinstance(e["summary"], str) and e["summary"] for e in found)


def test_a_days_event_types_are_listed_for_correcting_a_failed_lookup(port: ReadPort) -> None:
    rows = port.run(GRAPH, cypher("event_types_on_day"), {"day": 4}).rows
    assert ("knowledge_gap_detected",) in {(r[0],) for r in rows}


def test_a_failed_lookup_returns_the_days_event_types(port: ReadPort) -> None:
    tools = Toolbox(port, GRAPH)
    rows = tools.find_events(4, "design_doc_gap")
    assert rows[0]["no_match"] is True
    kinds = rows[0]["event_types_on_day"]
    assert isinstance(kinds, list)
    assert "knowledge_gap_detected" in kinds
    assert tools.calls[-1].empty is True


def test_counterfactual_names_the_people_on_both_events(port: ReadPort) -> None:
    links = Toolbox(port, GRAPH).causal_links("EVT-8-incident_opened-1219")
    assert links
    first = links[0]
    result = Toolbox(port, GRAPH).counterfactual(str(first["cause"]), str(first["effect"]), str(first["mechanism"]))
    assert result["linked"] is True
    assert isinstance(result["actors"], list)
    assert result["actors"]


def test_people_linked_through_a_shared_artifact_rank_an_event_without_excluding_it(port: ReadPort) -> None:
    rows = Toolbox(port, GRAPH).find_events(4, "knowledge_gap_detected", ["Jax"])
    assert len(rows) > 1
    linked = [r for r in rows if r["via_artifacts"] == ["Jax"]]
    assert linked
    # ranked: events that reach Jax directly or through an artifact come before events that do not reach him
    reach = [bool(r["via_artifacts"]) or "Jax" in str(r["actors"]) for r in rows]
    assert reach == sorted(reach, reverse=True)
