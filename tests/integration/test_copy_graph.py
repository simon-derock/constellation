from collections.abc import Iterator

import pytest
from falkordb import FalkorDB
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from constellation.deploy.copy_graph import copy_graph
from constellation.graph.read import ReadPort

pytestmark = pytest.mark.integration
QUERY = "MATCH (n:Thing) RETURN n.id AS id, n.label AS label ORDER BY id"
IMAGE = "falkordb/falkordb:v4.22.1@sha256:b0bdcac2cbaff989e77cb0610439b7a9289e86de033ccbbd4368b66fb680ae7a"


@pytest.fixture(scope="module")
def other() -> Iterator[FalkorDB]:
    box = (
        DockerContainer(IMAGE)
        .with_exposed_ports(6379)
        .waiting_for(LogMessageWaitStrategy("Ready to accept connections"))
    )
    with box:
        yield FalkorDB(host=box.get_container_host_ip(), port=int(box.get_exposed_port(6379)))


def test_a_copied_graph_answers_identically_and_is_independent(falkordb: FalkorDB, other: FalkorDB) -> None:
    name = "brain:copy-a"
    falkordb.select_graph(name).query("UNWIND range(1, 50) AS i CREATE (:Thing {id: i, label: 'n' + toString(i)})")
    copy_graph(falkordb, other, name)
    assert ReadPort(other).run(name, QUERY).sha256 == ReadPort(falkordb).run(name, QUERY).sha256
    other.select_graph(name).query("MATCH (n:Thing {id: 1}) SET n.label = 'changed'")
    assert ReadPort(other).run(name, QUERY).sha256 != ReadPort(falkordb).run(name, QUERY).sha256


def test_a_missing_graph_is_an_error_not_an_empty_copy(falkordb: FalkorDB, other: FalkorDB) -> None:
    with pytest.raises(LookupError, match="no-such"):
        copy_graph(falkordb, other, "brain:no-such")
    assert other.connection.exists("brain:no-such") == 0


def test_an_existing_destination_is_never_overwritten(falkordb: FalkorDB, other: FalkorDB) -> None:
    name = "brain:copy-b"
    falkordb.select_graph(name).query("CREATE (:Thing {id: 1})")
    other.select_graph(name).query("CREATE (:Thing {id: 2})")
    with pytest.raises(FileExistsError):
        copy_graph(falkordb, other, name)
