import re
from collections.abc import Mapping, Sequence

from falkordb import FalkorDB
from redis.exceptions import ResponseError

# Cypher cannot parameterise labels or property names; anything spliced into query text must match this
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


def safe_identifier(name: str) -> str:
    if not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"unsafe Cypher identifier {name!r}")
    return name


# C0 controls other than tab, newline and carriage return carry no meaning and break the client's parameter header
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean(value: object) -> object:
    if isinstance(value, str):
        return _CONTROL.sub("", value)
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    return value


class WritePort:
    # writes belong to ingestion and memory only; the agent read path never holds one of these
    def __init__(self, db: FalkorDB) -> None:
        self._db = db

    def ensure_index(self, graph: str, label: str, prop: str) -> None:
        try:
            index = f"CREATE INDEX FOR (n:{safe_identifier(label)}) ON (n.{safe_identifier(prop)})"
            self._db.select_graph(graph).query(index)
        except ResponseError as err:
            # idempotent schema: an existing index is the desired state, anything else is a failure
            if "already indexed" not in str(err):
                raise

    def merge(self, graph: str, cypher: str, rows: Sequence[Mapping[str, object]], batch: int = 500) -> None:
        # one UNWIND per batch: bounded query size, MERGE keeps reloads idempotent
        target = self._db.select_graph(graph)
        for start in range(0, len(rows), batch):
            target.query(cypher, params={"rows": clean(list(rows[start : start + batch]))})
