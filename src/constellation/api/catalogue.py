from typing import Annotated

from pydantic import Field

from constellation.graph.catalogue import cypher
from constellation.graph.read import ReadPort, Value

# bounds are part of the contract: input outside them never reaches the graph
Day = Annotated[int, Field(ge=-1_000, le=1_000, description="simulation day (Apex runs -579..60)")]
Name = Annotated[str, Field(min_length=1, max_length=128)]
EventId = Annotated[str, Field(min_length=1, max_length=128, description="event id, e.g. EVT-8-incident_opened-1219")]

type Proof = dict[str, str | dict[str, str | int] | list[str] | list[list[Value]]]


def prove(port: ReadPort, graph: str, name: str, params: dict[str, str | int]) -> Proof:
    # one catalogue query and the proof of what it returned: name, parameters, columns, rows, result hash
    result = port.run(graph, cypher(name), params)
    return {
        "query": name,
        "params": params,
        "columns": list(result.columns),
        "rows": [list(row) for row in result.rows],
        "sha256": result.sha256,
    }
