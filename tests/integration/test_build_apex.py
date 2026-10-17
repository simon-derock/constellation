import json
from pathlib import Path

import pytest
from falkordb import FalkorDB

from constellation.graph.catalogue import cypher
from constellation.graph.read import ReadPort
from constellation.ingest.build_apex import build
from constellation.ingest.pins import IntegrityError

pytestmark = pytest.mark.integration
RAW = Path("data/raw/apex")
GRAPH = "brain:apex-full"


@pytest.fixture(scope="module")
def built(falkordb: FalkorDB) -> dict[str, int]:
    if not RAW.exists():
        pytest.skip("pinned Apex data not fetched")
    falkordb.select_graph(GRAPH).query("MATCH (n) DETACH DELETE n")
    return build(falkordb, GRAPH, RAW, Path("pins/datasets.json"))


def test_one_build_composes_every_capability(falkordb: FalkorDB, built: dict[str, int]) -> None:
    port = ReadPort(falkordb)
    assert port.run(GRAPH, cypher("owner_as_of"), {"domain": "Project Titan", "day": 30}).rows[0][0] == "Sam"
    assert port.run(GRAPH, cypher("apex_cone"), {"actor": "Jax", "day": 30}).rows[0][0]
    assert port.run(GRAPH, cypher("escalation_path"), {"person": "Yusuf", "day": 60}).rows[0][0] == ["Yusuf", "Priya"]
    assert built["causal_edges"] > 1_000
    assert built["expectations"] > 1_000


def test_rebuilding_changes_nothing(falkordb: FalkorDB, built: dict[str, int]) -> None:
    port = ReadPort(falkordb)
    shape = "MATCH (n) WITH count(n) AS nodes MATCH ()-[r]->() RETURN nodes, count(r)"
    before = port.run(GRAPH, shape).rows
    assert build(falkordb, GRAPH, RAW, Path("pins/datasets.json")) == built
    assert port.run(GRAPH, shape).rows == before


def test_a_tampered_pin_stops_the_build(falkordb: FalkorDB, tmp_path: Path, built: dict[str, int]) -> None:
    pins = json.loads(Path("pins/datasets.json").read_text())
    pins["apex"]["files"][3]["sha256"] = "0" * 64
    (tmp_path / "pins.json").write_text(json.dumps(pins))
    with pytest.raises(IntegrityError):
        build(falkordb, "brain:apex-tampered", RAW, tmp_path / "pins.json")
