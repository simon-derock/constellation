from pathlib import Path

import pytest
from falkordb import FalkorDB

from constellation.brain.access import visible_artifacts
from constellation.graph.read import ReadPort
from constellation.graph.write import WritePort
from constellation.ingest.apex import ApexCorpus, load_apex
from constellation.ingest.apex_graph import cone_query, load_into

pytestmark = pytest.mark.integration
RAW = Path("data/raw/apex")
GRAPH = "brain:apex"


@pytest.fixture(scope="module")
def apex() -> ApexCorpus:
    if not (RAW / "corpus/corpus-00000.parquet").exists():
        pytest.skip("pinned Apex data not fetched: python -m constellation.ingest.fetch apex")
    return load_apex(RAW / "corpus/corpus-00000.parquet", Path("third_party/orgforge/config.yaml"))


@pytest.fixture(scope="module")
def loaded(falkordb: FalkorDB, apex: ApexCorpus) -> ReadPort:
    falkordb.select_graph(GRAPH).query("MATCH (n) DETACH DELETE n")
    load_into(WritePort(falkordb), GRAPH, apex)
    return ReadPort(falkordb)


def _counts(port: ReadPort) -> tuple[int, int]:
    nodes = port.run(GRAPH, "MATCH (n) RETURN count(n)").rows[0][0]
    edges = port.run(GRAPH, "MATCH ()-[r]->() RETURN count(r)").rows[0][0]
    assert isinstance(nodes, int)
    assert isinstance(edges, int)
    return nodes, edges


@pytest.mark.ac("AC-T3-01")
def test_loading_twice_changes_nothing(falkordb: FalkorDB, apex: ApexCorpus, loaded: ReadPort) -> None:
    before = _counts(loaded)
    load_into(WritePort(falkordb), GRAPH, apex)
    assert _counts(loaded) == before
    assert before[0] > 15_000


@pytest.mark.ac("AC-T3-03")
@pytest.mark.parametrize("day", [1, 9, 20, 39, 60])
def test_graph_cone_equals_the_ported_oracle_for_every_actor(apex: ApexCorpus, loaded: ReadPort, day: int) -> None:
    actors = sorted(apex.roles)
    for actor in actors:
        rows = loaded.run(GRAPH, cone_query(), {"actor": actor, "day": day}).rows
        visible = rows[0][0] if rows else []
        assert isinstance(visible, list)
        got = frozenset(str(v) for v in visible)
        assert got == visible_artifacts(apex.events, actor, apex.roles[actor], day), actor


def test_external_actors_have_an_empty_cone(loaded: ReadPort) -> None:
    assert loaded.run(GRAPH, cone_query(), {"actor": "Nora", "day": 60}).rows in ((), (([],),))


@pytest.mark.ac("AC-INV-03")
def test_cone_results_are_canonical_so_proofs_survive_a_reload(loaded: ReadPort) -> None:
    rows = loaded.run(GRAPH, cone_query(), {"actor": "Jax", "day": 30}).rows
    visible = rows[0][0]
    assert isinstance(visible, list)
    ids = [str(v) for v in visible]
    assert ids == sorted(ids)
    assert len(ids) > 0
