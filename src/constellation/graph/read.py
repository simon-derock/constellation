import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from falkordb import FalkorDB

type Value = str | int | float | bool | list[Value] | dict[str, Value] | None


@dataclass(frozen=True, slots=True)
class ReadResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[Value, ...], ...]
    sha256: str


def _plain(value: object) -> Value:
    # proofs hash plain values; graph objects carry engine ids that differ between snapshots
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return {k: _plain(v) for k, v in value.items()}
    raise TypeError(f"project properties instead of returning {type(value).__name__}")


def canonical_sha256(columns: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    # sorted keys and fixed separators: same values → same bytes; row order stays significant
    payload = {"columns": list(columns), "rows": [[_plain(v) for v in row] for row in rows]}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(blob.encode()).hexdigest()


class ReadPort:
    # the read path's only door: GRAPH.RO_QUERY, so the engine refuses writes even if a template regresses
    def __init__(self, db: FalkorDB) -> None:
        self._db = db

    def run(
        self, graph: str, cypher: str, params: Mapping[str, object] | None = None, timeout_ms: int = 2_000
    ) -> ReadResult:
        result = self._db.select_graph(graph).ro_query(cypher, params=dict(params or {}), timeout=timeout_ms)
        # header cells are [column_type, name]
        columns = tuple(str(cell[1]) for cell in result.header)
        rows = tuple(tuple(_plain(v) for v in row) for row in result.result_set)
        return ReadResult(columns=columns, rows=rows, sha256=canonical_sha256(columns, rows))
