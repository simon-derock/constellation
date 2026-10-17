from pathlib import Path

import pytest
from falkordb import FalkorDB

from constellation.brain.absence import Expectation, expectations
from constellation.graph.catalogue import cypher
from constellation.graph.read import ReadPort
from constellation.graph.write import WritePort
from constellation.ingest.apex import load_apex, raw_events
from constellation.ingest.apex_graph import load_expectations, load_into

pytestmark = pytest.mark.integration
RAW = Path("data/raw/apex")
GRAPH = "brain:apex-absence"


@pytest.fixture(scope="module")
def found() -> list[Expectation]:
    if not RAW.exists():
        pytest.skip("pinned Apex data not fetched")
    return expectations(raw_events(RAW / "corpus/corpus-00000.parquet"))


@pytest.fixture(scope="module")
def port(falkordb: FalkorDB, found: list[Expectation]) -> ReadPort:
    falkordb.select_graph(GRAPH).query("MATCH (n) DETACH DELETE n")
    apex = load_apex(RAW / "corpus/corpus-00000.parquet", Path("third_party/orgforge/config.yaml"))
    load_into(WritePort(falkordb), GRAPH, apex)
    load_expectations(WritePort(falkordb), GRAPH, found)
    return ReadPort(falkordb)


def test_the_graph_answers_every_expectation_exactly(port: ReadPort, found: list[Expectation]) -> None:
    assert len(found) > 1_000
    for x in found:
        rows = port.run(GRAPH, cypher("absence"), {"trigger": x.trigger, "response_type": x.response_type}).rows
        assert rows == ((x.responded, x.response_event, list(x.search_space)),), x


def test_both_outcomes_are_represented(found: list[Expectation]) -> None:
    assert any(x.responded for x in found)
    assert any(not x.responded for x in found)


def test_an_unknown_trigger_returns_nothing_rather_than_a_guess(port: ReadPort) -> None:
    assert port.run(GRAPH, cypher("absence"), {"trigger": "EVT-none", "response_type": "postmortem_created"}).rows == ()
