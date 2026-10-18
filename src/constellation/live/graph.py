import hashlib
from collections.abc import Sequence
from typing import Any

from falkordb import FalkorDB
from redis.exceptions import ResponseError

from constellation.graph.write import WritePort
from constellation.live.model import Change, Claim, Item, Plan

_INDEXES = (
    ("Item", "id"),
    ("Item", "repo"),
    ("Claim", "id"),
    ("Person", "alias"),
    ("Repo", "name"),
    ("Change", "id"),
    ("Cursor", "repo"),
)


def _change_id(change: Change) -> str:
    seed = f"{change.item}|{change.predicate}|{change.new}|{change.at}"
    return hashlib.sha1(seed.encode(), usedforsecurity=False).hexdigest()[:16]


class LiveGraph:
    # every write is a MERGE that only sets fields on creation or closes a claim, so replaying a sync, or half of one
    # after a crash, converges on the same graph and can never reopen a claim that was closed
    def __init__(self, db: FalkorDB, write: WritePort, graph: str) -> None:
        self._db, self._write, self._graph = db, write, graph
        for label, prop in _INDEXES:
            write.ensure_index(graph, label, prop)

    def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        return list(self._db.select_graph(self._graph).ro_query(cypher, params=params or {}).result_set)

    def open_claims(self, repo: str) -> dict[tuple[str, str], Claim]:
        rows = self.query(
            "MATCH (i:Item {repo: $repo})-[:HAS_CLAIM]->(c:Claim) WHERE c.valid_to IS NULL "
            "RETURN i.id, c.id, c.predicate, c.value, c.valid_from, c.origin",
            {"repo": repo},
        )
        return {
            (str(r[0]), str(r[2])): Claim(str(r[1]), str(r[0]), str(r[2]), str(r[3]), int(r[4]), None, str(r[5]), None)
            for r in rows
        }

    def cursor(self, repo: str) -> str | None:
        rows = self.query("MATCH (c:Cursor {repo: $repo}) RETURN c.since", {"repo": repo})
        return str(rows[0][0]) if rows else None

    def set_cursor(self, repo: str, since: str) -> None:
        self._write.merge(
            self._graph,
            "UNWIND $rows AS r MERGE (c:Cursor {repo: r.repo}) SET c.since = r.since",
            [{"repo": repo, "since": since}],
        )

    def apply(self, items: Sequence[Item], plan: Plan) -> None:
        merge = self._write.merge
        g = self._graph
        merge(
            g,
            "UNWIND $rows AS r MERGE (i:Item {id: r.id}) "
            "SET i.repo = r.repo, i.number = r.number, i.kind = r.kind, i.title = r.title, "
            "i.created = r.created, i.updated = r.updated "
            "MERGE (p:Person {alias: r.author}) MERGE (i)-[:AUTHORED_BY]->(p) "
            "MERGE (o:Repo {name: r.repo}) MERGE (i)-[:IN_REPO]->(o) MERGE (p)-[:ACTIVE_IN]->(o)",
            [
                {
                    "id": i.doc_id,
                    "repo": i.repo,
                    "number": i.number,
                    "kind": i.kind,
                    "title": i.title,
                    "created": i.created_at,
                    "updated": i.updated_at,
                    "author": i.author,
                }
                for i in items
            ],
        )
        claims = [
            {
                "kid": c.kid,
                "item": c.item,
                "predicate": c.predicate,
                "value": c.value,
                "valid_from": c.valid_from,
                "valid_to": c.valid_to,
                "origin": c.origin,
                "supersedes": c.supersedes,
            }
            for c in plan.new_claims
        ]
        # ON CREATE only: a claim that exists, and may since have been closed, is never rewritten
        merge(
            g,
            "UNWIND $rows AS r MATCH (i:Item {id: r.item}) MERGE (c:Claim {id: r.kid}) "
            "ON CREATE SET c.predicate = r.predicate, c.value = r.value, c.valid_from = r.valid_from, "
            "c.valid_to = r.valid_to, c.origin = r.origin "
            "MERGE (i)-[:HAS_CLAIM]->(c)",
            claims,
        )
        merge(
            g,
            "UNWIND $rows AS r MATCH (c:Claim {id: r.kid}) SET c.valid_to = r.at",
            [{"kid": kid, "at": at} for kid, at in plan.closures],
        )
        merge(
            g,
            "UNWIND $rows AS r MATCH (n:Claim {id: r.kid}), (o:Claim {id: r.supersedes}) MERGE (n)-[:SUPERSEDES]->(o)",
            [c for c in claims if c["supersedes"]],
        )
        merge(
            g,
            "UNWIND $rows AS r MATCH (i:Item {id: r.item}) MERGE (h:Change {id: r.id}) "
            "ON CREATE SET h.item = r.item, h.predicate = r.predicate, h.old = r.old, h.new = r.new, h.at = r.at "
            "MERGE (i)-[:CHANGED]->(h)",
            [
                {"id": _change_id(c), "item": c.item, "predicate": c.predicate, "old": c.old, "new": c.new, "at": c.at}
                for c in plan.changes
            ],
        )

    def backfill_repos(self) -> None:
        # items loaded before repositories were nodes get the same edges a fresh sync gives them
        self._db.select_graph(self._graph).query(
            "MATCH (i:Item)-[:AUTHORED_BY]->(p:Person) MERGE (o:Repo {name: i.repo}) "
            "MERGE (i)-[:IN_REPO]->(o) MERGE (p)-[:ACTIVE_IN]->(o)"
        )

    def build_collaboration(self) -> None:
        # people who open items in the same repository are linked both ways, weighted by how many they share; the
        # algorithms below (PageRank, betweenness, components, paths) run over this projection
        g = self._db.select_graph(self._graph)
        for low, high in (("a", "b"), ("b", "a")):
            g.query(
                "MATCH (a:Person)-[:ACTIVE_IN]->(r:Repo)<-[:ACTIVE_IN]-(b:Person) WHERE a.alias < b.alias "
                f"WITH {low} AS x, {high} AS y, count(r) AS shared MERGE (x)-[c:COLLABORATES]->(y) SET c.repos = shared"
            )

    def ensure_search_indexes(self, dim: int) -> None:
        # HNSW over title embeddings and a full-text index over titles, both inside the engine; idempotent
        g = self._db.select_graph(self._graph)
        statements = (
            "CREATE VECTOR INDEX FOR (n:Item) ON (n.embedding) "
            f"OPTIONS {{dimension: {int(dim)}, similarityFunction: 'cosine', M: 16, "
            "efConstruction: 200, efRuntime: 100}",
            "CALL db.idx.fulltext.createNodeIndex('Item', 'title')",
        )
        for statement in statements:
            try:
                g.query(statement)
            except ResponseError as err:
                if "already" not in str(err).lower() and "exist" not in str(err).lower():
                    raise

    def pending_embeddings(self, limit: int) -> list[tuple[str, str]]:
        # an item needs a vector when it has none, or when its title is no longer the one the vector was made from
        rows = self.query(
            "MATCH (i:Item) WHERE i.embedding IS NULL OR i.embedded_for <> i.title RETURN i.id, i.title "
            "ORDER BY i.id LIMIT $limit",
            {"limit": limit},
        )
        return [(str(r[0]), str(r[1])) for r in rows]

    def set_embeddings(self, rows: Sequence[tuple[str, str, Sequence[float]]]) -> None:
        self._write.merge(
            self._graph,
            "UNWIND $rows AS r MATCH (i:Item {id: r.id}) SET i.embedding = vecf32(r.vector), i.embedded_for = r.title",
            [{"id": i, "title": t, "vector": list(v)} for i, t, v in rows],
        )
