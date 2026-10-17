from pathlib import Path

import pytest
from falkordb import FalkorDB

from constellation.agents.toolbox import Toolbox
from constellation.graph.read import ReadPort
from constellation.ingest.build_apex import build
from constellation.proof import ProofQuery, replay

pytestmark = pytest.mark.integration
GRAPH = "brain:apex-proof"


@pytest.fixture(scope="module")
def port(falkordb: FalkorDB) -> ReadPort:
    if not Path("data/raw/apex").exists():
        pytest.skip("pinned Apex data not fetched")
    falkordb.select_graph(GRAPH).query("MATCH (n) DETACH DELETE n")
    build(falkordb, GRAPH, Path("data/raw/apex"), Path("pins/datasets.json"))
    return ReadPort(falkordb)


@pytest.mark.ac("AC-INV-03")
def test_every_query_a_tool_ran_is_recorded_and_replays_to_the_same_hash(port: ReadPort) -> None:
    tools = Toolbox(port, GRAPH)
    tools.absence("EVT-8-incident_opened-1219", "sf_deals_risk_flagged")
    assert tools.queries
    report = replay(port, GRAPH, tools.queries)
    assert report.all_match is True
    assert len(report.results) == len(tools.queries)


@pytest.mark.ac("AC-INV-03")
def test_a_tampered_hash_is_reported_as_a_mismatch(port: ReadPort) -> None:
    tools = Toolbox(port, GRAPH)
    tools.absence("EVT-8-incident_opened-1219", "sf_deals_risk_flagged")
    bad = [ProofQuery(q.name, q.params, "0" * 64) for q in tools.queries]
    report = replay(port, GRAPH, bad)
    assert report.all_match is False
    assert all(not r.match for r in report.results)


@pytest.mark.parametrize(
    "query",
    [
        ProofQuery("../etc/passwd", {}, "0" * 64),
        ProofQuery("not_in_the_catalogue", {}, "0" * 64),
        ProofQuery("owner_as_of", {"domain": {"nested": "dict"}, "day": 1}, "0" * 64),
        ProofQuery("owner_as_of", {"domain": "x" * 5_000, "day": 1}, "0" * 64),
    ],
)
def test_replay_runs_only_catalogue_queries_with_bounded_plain_parameters(port: ReadPort, query: ProofQuery) -> None:
    with pytest.raises(ValueError, match=r"unknown catalogue query|replay parameter"):
        replay(port, GRAPH, [query])


def test_replay_refuses_an_oversized_proof(port: ReadPort) -> None:
    with pytest.raises(ValueError, match="too many"):
        replay(port, GRAPH, [ProofQuery("event_types", {}, "0" * 64)] * 51)
