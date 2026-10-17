from typing import Any

import pytest
from redis.exceptions import ResponseError

from constellation.memory.store import MemoryStore


class FakeGraph:
    def __init__(self, db: "FakeDB", name: str) -> None:
        self.db, self.name = db, name

    def copy(self, target: str) -> None:
        if self.db.fork_error:
            raise ResponseError(self.db.fork_error)
        self.db.graphs.add(target)

    def query(self, cypher: str, params: dict[str, Any] | None = None) -> None:
        self.db.graphs.add(self.name)
        self.db.queries.append((self.name, cypher))


class FakeDB:
    def __init__(self, fork_error: str = "") -> None:
        self.graphs: set[str] = {"mem:template"}
        self.queries: list[tuple[str, str]] = []
        self.fork_error = fork_error

    def list_graphs(self) -> list[str]:
        return sorted(self.graphs)

    def select_graph(self, name: str) -> FakeGraph:
        return FakeGraph(self, name)


def test_provisioning_builds_the_same_schema_directly_when_the_server_cannot_fork() -> None:
    db = FakeDB("GRAPH.COPY failed, could not fork")
    store = MemoryStore(db, tenant="t1")
    name = store.provision("alice")
    assert name in db.graphs
    indexed = " ".join(q for g, q in db.queries if g == name)
    for label in ("Fact", "Session", "Handoff", "Episode", "Procedure"):
        assert f":{label})" in indexed


def test_other_copy_errors_are_not_swallowed() -> None:
    db = FakeDB("ERR something else entirely")
    with pytest.raises(ResponseError, match="something else"):
        MemoryStore(db, tenant="t1").provision("alice")


def test_a_healthy_copy_is_used_when_it_works() -> None:
    db = FakeDB()
    MemoryStore(db, tenant="t1").provision("alice")
    assert "mem:t1:alice" in db.graphs
    assert [q for g, q in db.queries if g == "mem:t1:alice"] == []
