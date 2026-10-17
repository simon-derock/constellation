from pathlib import Path

import pytest
from falkordb import FalkorDB

from constellation.brain.escalation import Chain, path_as_of
from constellation.graph.catalogue import cypher
from constellation.graph.read import ReadPort
from constellation.graph.write import WritePort
from constellation.ingest.apex import escalation_chains
from constellation.ingest.apex_graph import load_escalations

pytestmark = pytest.mark.integration
GRAPH = "brain:apex-escalation"
CORPUS = Path("data/raw/apex/corpus/corpus-00000.parquet")


@pytest.fixture(scope="module")
def chains() -> list[Chain]:
    if not CORPUS.exists():
        pytest.skip("pinned Apex data not fetched")
    return escalation_chains(CORPUS)


@pytest.fixture(scope="module")
def port(falkordb: FalkorDB, chains: list[Chain]) -> ReadPort:
    falkordb.select_graph(GRAPH).query("MATCH (n) DETACH DELETE n")
    load_escalations(WritePort(falkordb), GRAPH, chains)
    return ReadPort(falkordb)


def test_all_fourteen_observed_chains_load(chains: list[Chain]) -> None:
    assert len(chains) == 14


@pytest.mark.ac("AC-T1-04")
def test_graph_path_equals_the_latest_observation_for_everyone_on_every_day(
    port: ReadPort, chains: list[Chain]
) -> None:
    for person in sorted({c.path[0] for c in chains}):
        for day in range(61):
            rows = port.run(GRAPH, cypher("escalation_path"), {"person": person, "day": day}).rows
            expected = path_as_of(chains, person, day)
            if expected is None:
                assert rows == (), (person, day)
                continue
            assert rows == ((list(expected.path), expected.day, expected.evidence),), (person, day)
