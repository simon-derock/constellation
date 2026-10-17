from collections.abc import Iterator

import pytest
from falkordb import FalkorDB
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

# pinned by digest: the engine the proofs were recorded against (ADR-0001)
FALKORDB_IMAGE = (
    "falkordb/falkordb:v4.22.1@sha256:b0bdcac2cbaff989e77cb0610439b7a9289e86de033ccbbd4368b66fb680ae7a"
)


@pytest.fixture(scope="session")
def falkordb() -> Iterator[FalkorDB]:
    container = (
        DockerContainer(FALKORDB_IMAGE)
        .with_exposed_ports(6379)
        .waiting_for(LogMessageWaitStrategy("Ready to accept connections"))
    )
    with container:
        yield FalkorDB(host=container.get_container_host_ip(), port=int(container.get_exposed_port(6379)))
