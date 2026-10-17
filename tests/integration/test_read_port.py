import pytest
from falkordb import FalkorDB
from redis.exceptions import ResponseError

from constellation.graph.read import ReadPort

pytestmark = pytest.mark.integration
GRAPH = "brain:readport"


@pytest.fixture
def seeded(falkordb: FalkorDB) -> FalkorDB:
    graph = falkordb.select_graph(GRAPH)
    graph.query("MATCH (n) DETACH DELETE n")
    graph.query(
        "CREATE (:Person {alias: 'amber-otter'})-[:OWNS {from: 10, to: 20}]->(:Component {id: 'billing'}),"
        " (:Person {alias: 'slate-heron'})-[:OWNS {from: 20}]->(:Component {id: 'search'})"
    )
    return falkordb


@pytest.mark.ac("AC-INV-06")
def test_the_read_port_cannot_write_even_when_asked(seeded: FalkorDB) -> None:
    port = ReadPort(seeded)
    # the refusal comes from the engine, not from our code
    with pytest.raises(ResponseError, match=r"RO_QUERY is to be executed only on read-only queries"):
        port.run(GRAPH, "CREATE (:Person {alias: 'intruder'})")
    assert port.run(GRAPH, "MATCH (p:Person) RETURN count(p) AS n").rows == ((2,),)


@pytest.mark.ac("AC-INV-03")
def test_a_replayed_query_reproduces_its_hash(seeded: FalkorDB) -> None:
    port = ReadPort(seeded)
    cypher = (
        "MATCH (p:Person)-[o:OWNS]->(c:Component {id: $component}) "
        "WHERE o.from <= $day AND (o.to IS NULL OR $day < o.to) RETURN p.alias AS owner, o.from AS since"
    )
    first = port.run(GRAPH, cypher, {"component": "billing", "day": 15})
    assert first.columns == ("owner", "since")
    assert first.rows == (("amber-otter", 10),)
    assert port.run(GRAPH, cypher, {"component": "billing", "day": 15}).sha256 == first.sha256
    assert port.run(GRAPH, cypher, {"component": "billing", "day": 20}).sha256 != first.sha256


def test_returning_a_node_is_refused_so_proofs_hash_plain_values(seeded: FalkorDB) -> None:
    with pytest.raises(TypeError, match="project"):
        ReadPort(seeded).run(GRAPH, "MATCH (p:Person) RETURN p")
