from collections import Counter
from pathlib import Path

import pytest
from falkordb import FalkorDB

from constellation.brain.causality import CausalEdge, counterfactual, index_causal_links
from constellation.graph.catalogue import cypher
from constellation.graph.read import ReadPort
from constellation.graph.write import WritePort
from constellation.ingest.apex import load_apex, raw_events
from constellation.ingest.apex_graph import load_causes, load_into

pytestmark = pytest.mark.integration
RAW = Path("data/raw/apex")
GRAPH = "brain:apex-causality"


@pytest.fixture(scope="module")
def edges() -> list[CausalEdge]:
    if not RAW.exists():
        pytest.skip("pinned Apex data not fetched")
    return index_causal_links(raw_events(RAW / "corpus/corpus-00000.parquet"))


@pytest.fixture(scope="module")
def port(falkordb: FalkorDB, edges: list[CausalEdge]) -> ReadPort:
    falkordb.select_graph(GRAPH).query("MATCH (n) DETACH DELETE n")
    apex = load_apex(RAW / "corpus/corpus-00000.parquet", Path("third_party/orgforge/config.yaml"))
    load_into(WritePort(falkordb), GRAPH, apex)
    load_causes(WritePort(falkordb), GRAPH, edges)
    return ReadPort(falkordb)


def test_the_full_index_is_much_larger_than_the_benchmark_sample(edges: list[CausalEdge]) -> None:
    per_type = Counter(e.link_type for e in edges)
    assert len(edges) > 1_000
    assert max(per_type.values()) > 15


def test_every_edge_lands_in_the_graph(port: ReadPort, edges: list[CausalEdge]) -> None:
    assert port.run(GRAPH, "MATCH ()-[x:CAUSES]->() RETURN count(x)").rows == ((len(edges),),)


def test_graph_counterfactual_equals_the_python_rule(port: ReadPort, edges: list[CausalEdge]) -> None:
    fan_in = Counter((e.effect, e.link_type) for e in edges)
    single = [e for e in edges if fan_in[(e.effect, e.link_type)] == 1][:40]
    shared = [e for e in edges if fan_in[(e.effect, e.link_type)] > 1][:40]
    assert single
    assert shared
    for edge in single + shared:
        params = {"cause": edge.cause, "effect": edge.effect, "link_type": edge.link_type}
        linked, alternatives = port.run(GRAPH, cypher("counterfactual"), params).rows[0]
        expected = counterfactual(edges, edge.link_type, edge.cause, edge.effect)
        assert isinstance(alternatives, list)
        assert (linked, tuple(alternatives)) == (expected.linked, expected.alternatives)


def test_an_unrelated_pair_is_not_linked(port: ReadPort, edges: list[CausalEdge]) -> None:
    params = {"cause": "EVT-none", "effect": edges[0].effect, "link_type": edges[0].link_type}
    assert port.run(GRAPH, cypher("counterfactual"), params).rows[0][0] is False
