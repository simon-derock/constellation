from collections.abc import Mapping, Sequence

from falkordb import FalkorDB
from redis.exceptions import ResponseError


class WritePort:
    # writes belong to ingestion and memory only; the agent read path never holds one of these
    def __init__(self, db: FalkorDB) -> None:
        self._db = db

    def ensure_index(self, graph: str, label: str, prop: str) -> None:
        try:
            self._db.select_graph(graph).query(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
        except ResponseError as err:
            # idempotent schema: an existing index is the desired state, anything else is a failure
            if "already indexed" not in str(err):
                raise

    def merge(self, graph: str, cypher: str, rows: Sequence[Mapping[str, object]], batch: int = 500) -> None:
        # one UNWIND per batch: bounded query size, MERGE keeps reloads idempotent
        target = self._db.select_graph(graph)
        for start in range(0, len(rows), batch):
            target.query(cypher, params={"rows": list(rows[start : start + batch])})
