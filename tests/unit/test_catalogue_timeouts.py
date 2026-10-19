from collections.abc import Mapping

import pytest

from constellation.api.catalogue import prove
from constellation.graph.read import ReadResult


class Recorder:
    def __init__(self) -> None:
        self.timeouts: list[int | None] = []

    def run(
        self, graph: str, cypher: str, params: Mapping[str, object] | None = None, timeout_ms: int | None = None
    ) -> ReadResult:
        del graph, cypher, params
        self.timeouts.append(timeout_ms)
        return ReadResult(columns=("x",), rows=((1,),), sha256="0" * 64)


@pytest.mark.parametrize("name", ["live_central_people", "live_bridge_people", "live_components"])
def test_the_graph_algorithms_get_a_long_timeout_for_a_small_host(name: str) -> None:
    port = Recorder()
    prove(port, "brain:falkordb", name, {"limit": 10})  # type: ignore[arg-type]
    assert port.timeouts == [30_000]


def test_every_other_query_keeps_the_default_timeout() -> None:
    port = Recorder()
    prove(port, "brain:falkordb", "live_summary", {})  # type: ignore[arg-type]
    assert port.timeouts == [None]
