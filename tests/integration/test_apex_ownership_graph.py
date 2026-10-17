from pathlib import Path

import pytest
from falkordb import FalkorDB

from constellation.brain.ownership import OwnershipFact, owner_as_of, ownership_timeline
from constellation.graph.catalogue import cypher
from constellation.graph.read import ReadPort
from constellation.graph.write import WritePort
from constellation.ingest.apex import ownership_sources
from constellation.ingest.apex_graph import load_ownership

pytestmark = pytest.mark.integration
RAW = Path("data/raw/apex")
GRAPH = "brain:apex-ownership"


@pytest.fixture(scope="module")
def facts() -> list[OwnershipFact]:
    if not RAW.exists():
        pytest.skip("pinned Apex data not fetched")
    sources = ownership_sources(RAW / "corpus/corpus-00000.parquet", RAW / "supplemental/domain_registry.json")
    return ownership_timeline(*sources)


@pytest.fixture(scope="module")
def port(falkordb: FalkorDB, facts: list[OwnershipFact]) -> ReadPort:
    falkordb.select_graph(GRAPH).query("MATCH (n) DETACH DELETE n")
    load_ownership(WritePort(falkordb), GRAPH, facts)
    return ReadPort(falkordb)


def _probe_days(facts: list[OwnershipFact]) -> list[int]:
    # every boundary and its neighbours, plus a coarse sweep: off-by-one errors live at boundaries
    edges = {b for f in facts for b in (f.interval.start, f.interval.end) if b is not None}
    return sorted({d + k for d in edges for k in (-1, 0, 1)} | set(range(-700, 61, 25)))


@pytest.mark.ac("AC-T3-02")
def test_graph_owner_equals_the_timeline_on_every_boundary(facts: list[OwnershipFact], port: ReadPort) -> None:
    for domain in sorted({f.domain for f in facts}):
        for day in _probe_days(facts):
            rows = port.run(GRAPH, cypher("owner_as_of"), {"domain": domain, "day": day}).rows
            expected = owner_as_of(facts, domain, day)
            assert (rows[0][0] if rows else None) == expected.owner, (domain, day)
            if rows:
                assert rows[0][2:] == (expected.origin, expected.evidence, expected.start_known)


@pytest.mark.ac("AC-INV-03")
def test_an_ownership_proof_replays_to_the_same_hash(port: ReadPort) -> None:
    params = {"domain": "Project Titan", "day": 30}
    first = port.run(GRAPH, cypher("owner_as_of"), params)
    assert first.rows[0][0] == "Sam"
    assert port.run(GRAPH, cypher("owner_as_of"), params).sha256 == first.sha256


def test_reloading_ownership_is_idempotent(falkordb: FalkorDB, facts: list[OwnershipFact], port: ReadPort) -> None:
    count = "MATCH ()-[o:OWNS]->() RETURN count(o)"
    before = port.run(GRAPH, count).rows
    load_ownership(WritePort(falkordb), GRAPH, facts)
    assert port.run(GRAPH, count).rows == before == ((len(facts),),)
