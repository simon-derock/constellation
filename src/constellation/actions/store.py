import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from constellation.actions.sinks import Sink
from constellation.memory.store import ConflictError, MemoryStore

type Mode = Literal["dry-run", "real"]
_PRINCIPAL = "ops"


class CapError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ActionRecord:
    id: str
    kind: str
    title: str
    body: str
    payload_hash: str
    status: str
    approver: str | None
    mode: str | None
    result: dict[str, Any] | None
    evidence: list[dict[str, Any]]
    created: str


def _now() -> datetime:
    return datetime.now(UTC)


_FIELDS = "a.id, a.kind, a.title, a.body, a.payload_hash, a.status, a.approver, a.mode, a.result, a.evidence, a.created"


def _record(row: list[object]) -> ActionRecord:
    result = json.loads(str(row[8])) if row[8] else None
    return ActionRecord(
        id=str(row[0]),
        kind=str(row[1]),
        title=str(row[2]),
        body=str(row[3]),
        payload_hash=str(row[4]),
        status=str(row[5]),
        approver=None if row[6] is None else str(row[6]),
        mode=None if row[7] is None else str(row[7]),
        result=result,
        evidence=json.loads(str(row[9])) if row[9] else [],
        created=str(row[10]),
    )


class ActionStore:
    # actions are graph events in the tenant's ops graph: proposed, approved, executed, each a compare-and-set,
    # so who approved what, and what then happened, is queryable and can never be rewritten silently
    def __init__(self, memory: MemoryStore, clock: Callable[[], datetime] = _now) -> None:
        self._memory, self._clock = memory, clock
        self.graph = memory.provision(_PRINCIPAL)

    def _q(self, cypher: str, params: Mapping[str, object] | None = None) -> list[list[object]]:
        return self._memory.query(_PRINCIPAL, cypher, dict(params or {}))

    def propose(self, kind: str, title: str, body: str, evidence: list[dict[str, Any]]) -> ActionRecord:
        payload = json.dumps({"kind": kind, "title": title, "body": body}, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        # the id comes from the payload, so proposing the same thing twice is one action, not two
        self._q(
            "MERGE (a:Action {id: $id}) ON CREATE SET a.kind = $kind, a.title = $title, a.body = $body, "
            "a.payload_hash = $hash, a.status = 'proposed', a.evidence = $evidence, a.created = $now",
            {
                "id": digest[:16],
                "kind": kind,
                "title": title,
                "body": body,
                "hash": digest,
                "evidence": json.dumps(evidence, sort_keys=True),
                "now": self._clock().isoformat(),
            },
        )
        return self.get(digest[:16])

    def get(self, action_id: str) -> ActionRecord:
        rows = self._q(f"MATCH (a:Action {{id: $id}}) RETURN {_FIELDS}", {"id": action_id})
        if not rows:
            raise KeyError(action_id)
        return _record(rows[0])

    def recent(self, limit: int = 50) -> list[ActionRecord]:
        rows = self._q(
            f"MATCH (a:Action) RETURN {_FIELDS} ORDER BY a.created DESC, a.id LIMIT $limit", {"limit": limit}
        )
        return [_record(r) for r in rows]

    def _transition(self, action_id: str, source: str, target: str, approver: str) -> None:
        won = self._q(
            "MATCH (a:Action {id: $id}) WHERE a.status = $source SET a.status = $target, a.approver = $who RETURN a.id",
            {"id": action_id, "source": source, "target": target, "who": approver},
        )
        if not won:
            raise ConflictError(f"action {action_id} is not {source}")

    def approve(self, action_id: str, approver: str) -> None:
        self._transition(action_id, "proposed", "approved", approver)

    def reject(self, action_id: str, approver: str) -> None:
        self._transition(action_id, "proposed", "rejected", approver)

    def execute(self, action_id: str, sink: Sink, mode: Mode, daily_cap: int) -> ActionRecord:
        day = self._clock().date().isoformat()
        # claim and cap check are one statement: of any number of concurrent executions, at most one claims the
        # action, and real executions today can never exceed the cap
        claimed = self._q(
            "MATCH (a:Action {id: $id}) WHERE a.status = 'approved' "
            "OPTIONAL MATCH (b:Action {status: 'executed', mode: 'real', executed_day: $day}) "
            "WITH a, count(b) AS used WHERE $mode <> 'real' OR used < $cap "
            "SET a.status = 'executing', a.mode = $mode RETURN a.id",
            {"id": action_id, "day": day, "mode": mode, "cap": daily_cap},
        )
        if not claimed:
            if self.get(action_id).status == "approved":
                raise CapError(f"the daily limit of {daily_cap} real actions has been reached")
            raise ConflictError(f"action {action_id} is not approved")
        current = self.get(action_id)
        outcome = "executed"
        try:
            result: dict[str, Any] = dict(
                sink.execute({"id": current.id, "kind": current.kind, "title": current.title, "body": current.body})
            )
        except Exception as err:
            outcome, result = "failed", {"error": str(err)[:200]}
        self._q(
            "MATCH (a:Action {id: $id}) WHERE a.status = 'executing' "
            "SET a.status = $status, a.result = $result, a.executed_day = $day",
            {"id": action_id, "status": outcome, "result": json.dumps(result, sort_keys=True), "day": day},
        )
        return self.get(action_id)

    def unapproved_executions(self) -> list[str]:
        # the invariant behind "actions need approval": nothing is executing, executed or failed without an approver
        rows = self._q(
            "MATCH (a:Action) WHERE a.status IN ['executing', 'executed', 'failed'] AND a.approver IS NULL "
            "RETURN a.id ORDER BY a.id"
        )
        return [str(r[0]) for r in rows]
