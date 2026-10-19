from typing import Annotated

from pydantic import Field

from constellation.graph.catalogue import cypher
from constellation.graph.read import ReadPort, Value

# bounds are part of the contract: input outside them never reaches the graph
Day = Annotated[int, Field(ge=-1_000, le=1_000, description="simulation day (Apex runs -579..60)")]
Name = Annotated[str, Field(min_length=1, max_length=128)]
EventId = Annotated[str, Field(min_length=1, max_length=128, description="event id, e.g. EVT-8-incident_opened-1219")]

type Proof = dict[str, str | dict[str, str | int] | list[str] | list[list[Value]]]


# the three graph algorithms take about 130 ms on a normal core and about 3 s on a free host's 0.1 CPU, so they are
# allowed far longer than the 2 s every other query gets
_ALGORITHM_TIMEOUT_MS = 30_000
_ALGORITHMS = frozenset({"live_central_people", "live_bridge_people", "live_components"})


def prove(port: ReadPort, graph: str, name: str, params: dict[str, str | int]) -> Proof:
    # one catalogue query and the proof of what it returned: name, parameters, columns, rows, result hash
    if name in _ALGORITHMS:
        result = port.run(graph, cypher(name), params, timeout_ms=_ALGORITHM_TIMEOUT_MS)
    else:
        result = port.run(graph, cypher(name), params)
    return {
        "query": name,
        "params": params,
        "columns": list(result.columns),
        "rows": [list(row) for row in result.rows],
        "sha256": result.sha256,
    }
