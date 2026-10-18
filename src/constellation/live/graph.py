import hashlib
from collections.abc import Sequence
from typing import Any

from falkordb import FalkorDB

from constellation.graph.write import WritePort
from constellation.live.model import Change, Claim, Item, Plan

_INDEXES = (
    ("Item", "id"),
    ("Item", "repo"),
    ("Claim", "id"),
    ("Person", "alias"),
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
            "MERGE (p:Person {alias: r.author}) MERGE (i)-[:AUTHORED_BY]->(p)",
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
