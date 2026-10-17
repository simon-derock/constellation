import hashlib
import json
import random
import re
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from falkordb import FalkorDB
from redis.exceptions import ResponseError

from constellation.graph.write import WritePort, clean

# graph names are built only from these, so no principal or tenant can reach another graph or add Cypher syntax
_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")
_TEMPLATE = "mem:template"
_TEMPLATE_INDEXES = (
    ("Fact", "id"),
    ("Session", "sid"),
    ("Handoff", "hid"),
    ("Episode", "eid"),
    ("Procedure", "task"),
)
_template_lock = threading.Lock()
_JITTER = random.SystemRandom()


class ConflictError(Exception):
    # a compare-and-set lost: the caller re-reads and decides, nothing is overwritten
    pass


@dataclass(frozen=True, slots=True)
class FactRecord:
    value: str
    ver: int


@dataclass(frozen=True, slots=True)
class Updated:
    value: str
    ver: int
    # conflicts this update lost and retried: evidence of contention, never of loss
    retries: int


@dataclass(frozen=True, slots=True)
class Turn:
    n: int
    role: str
    content: str
    proof_id: str


@dataclass(frozen=True, slots=True)
class Handoff:
    hid: str
    state_sha256: str


@dataclass(frozen=True, slots=True)
class SemanticFact:
    subject: str
    value: str
    support: int


def _canonical(state: object) -> str:
    return json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _check(kind: str, name: str) -> str:
    if not _NAME.fullmatch(name):
        raise ValueError(f"invalid {kind} {name!r}")
    return name


class MemoryStore:
    # one graph per tenant and principal, cloned from a template with GRAPH.COPY; every write is a compare-and-set
    def __init__(self, db: FalkorDB, tenant: str) -> None:
        self._db = db
        self.tenant = _check("tenant", tenant)

    def graph_name(self, principal: str) -> str:
        return f"mem:{self.tenant}:{_check('principal', principal)}"

    def _q(self, principal: str, cypher: str, params: dict[str, object] | None = None) -> list[list[object]]:
        graph = self._db.select_graph(self.graph_name(principal))
        return list(graph.query(cypher, params=clean(params or {})).result_set)

    def query(self, principal: str, cypher: str, params: dict[str, object] | None = None) -> list[list[object]]:
        # the one place other stores write to a principal's graph: same validated name, same parameter hygiene
        return self._q(principal, cypher, params)

    def provision(self, principal: str) -> str:
        name = self.graph_name(principal)
        if name in self._db.list_graphs():
            return name
        with _template_lock:
            if _TEMPLATE not in self._db.list_graphs():
                port = WritePort(self._db)
                for label, prop in _TEMPLATE_INDEXES:
                    port.ensure_index(_TEMPLATE, label, prop)
        try:
            self._db.select_graph(_TEMPLATE).copy(name)
        except ResponseError as err:
            # a concurrent provision of the same principal won the copy; the graph existing is the desired state
            if name in self._db.list_graphs():
                return name
            if "could not fork" not in str(err):
                raise
            # GRAPH.COPY forks the server; with no memory headroom to fork (a small free host) the empty template's
            # schema is built directly, which yields the identical graph
            port = WritePort(self._db)
            for label, prop in _TEMPLATE_INDEXES:
                port.ensure_index(name, label, prop)
        return name

    def read_fact(self, principal: str, fact_id: str) -> FactRecord | None:
        rows = self._q(principal, "MATCH (f:Fact {id: $id}) RETURN f.value, f.ver", {"id": fact_id})
        return FactRecord(str(rows[0][0]), int(str(rows[0][1]))) if rows else None

    def write_fact(self, principal: str, fact_id: str, value: str, expected_ver: int) -> int:
        params: dict[str, object] = {"id": fact_id, "value": value, "expected": expected_ver}
        if expected_ver == 0:
            # create-if-absent in one statement: `fresh` survives only on the creating call
            rows = self._q(
                principal,
                "MERGE (f:Fact {id: $id}) ON CREATE SET f.value = $value, f.ver = 1, f.fresh = true "
                "WITH f, f.fresh AS fresh REMOVE f.fresh RETURN fresh",
                params,
            )
            if not rows or rows[0][0] is not True:
                raise ConflictError(f"fact {fact_id!r} already exists")
            return 1
        rows = self._q(
            principal,
            "MATCH (f:Fact {id: $id}) WHERE f.ver = $expected SET f.value = $value, f.ver = f.ver + 1 RETURN f.ver",
            params,
        )
        if not rows:
            raise ConflictError(f"fact {fact_id!r} is no longer at version {expected_ver}")
        return int(str(rows[0][0]))

    def update_fact(
        self, principal: str, fact_id: str, change: Callable[[str], str], default: str = "", timeout_s: float = 20.0
    ) -> Updated:
        deadline = time.monotonic() + timeout_s
        retries = 0
        while True:
            current = self.read_fact(principal, fact_id)
            value, ver = (current.value, current.ver) if current else (default, 0)
            updated = change(value)
            try:
                return Updated(updated, self.write_fact(principal, fact_id, updated, ver), retries)
            except ConflictError:
                retries += 1
                if time.monotonic() > deadline:
                    raise
                # jittered exponential backoff: writers that keep colliding in lockstep are de-synchronised, so none
                # starves; the deadline, not a retry count, bounds the wait
                time.sleep(_JITTER.uniform(0, min(0.02, 0.0002 * 2 ** min(retries, 8))))

    def append_turn(self, principal: str, session: str, role: str, content: str, proof_id: str = "") -> int:
        rows = self._q(
            principal,
            "MERGE (s:Session {sid: $sid}) ON CREATE SET s.n = 0 SET s.n = s.n + 1 "
            "CREATE (s)-[:HAS_TURN]->(:Turn {n: s.n, role: $role, content: $content, proof_id: $proof}) RETURN s.n",
            {"sid": session, "role": role, "content": content, "proof": proof_id},
        )
        return int(str(rows[0][0]))

    def recent(self, principal: str, session: str, limit: int) -> list[Turn]:
        rows = self._q(
            principal,
            "MATCH (:Session {sid: $sid})-[:HAS_TURN]->(t:Turn) RETURN t.n, t.role, t.content, t.proof_id "
            "ORDER BY t.n DESC LIMIT $limit",
            {"sid": session, "limit": limit},
        )
        return [Turn(int(str(r[0])), str(r[1]), str(r[2]), str(r[3])) for r in reversed(rows)]

    def history(self, principal: str, session: str) -> list[Turn]:
        return self.recent(principal, session, 10**6)

    def handoff(self, principal: str, source: str, target: str, state: dict[str, object]) -> Handoff:
        hid, body = uuid.uuid4().hex, _canonical(state)
        digest = hashlib.sha256(body.encode()).hexdigest()
        self._q(
            principal,
            "CREATE (:Handoff {hid: $hid, src: $src, dst: $dst, state: $state, sha: $sha})",
            {"hid": hid, "src": source, "dst": target, "state": body, "sha": digest},
        )
        return Handoff(hid, digest)

    def claim(self, principal: str, hid: str, agent: str) -> dict[str, object]:
        rows = self._q(principal, "MATCH (h:Handoff {hid: $hid}) RETURN h.dst, h.state, h.sha", {"hid": hid})
        if not rows:
            raise KeyError(hid)
        target, body, digest = str(rows[0][0]), str(rows[0][1]), str(rows[0][2])
        if agent != target:
            raise PermissionError(f"handoff {hid} is addressed to {target!r}")
        if hashlib.sha256(body.encode()).hexdigest() != digest:
            raise ValueError("handoff state hash does not match its recorded hash")
        # the claim is one compare-and-set on `claimed_by`, so exactly one concurrent claimant wins
        won = self._q(
            principal,
            "MATCH (h:Handoff {hid: $hid}) WHERE h.claimed_by IS NULL SET h.claimed_by = $agent RETURN h.hid",
            {"hid": hid, "agent": agent},
        )
        if not won:
            raise ConflictError(f"handoff {hid} was already claimed")
        state = json.loads(body)
        if not isinstance(state, dict):
            raise ValueError("handoff state is not an object")
        return state

    def record_episode(self, principal: str, task: str, subject: str, value: str, evidence: Sequence[str]) -> None:
        self._q(
            principal,
            "CREATE (:Episode {eid: $eid, task: $task, subject: $subject, value: $value, evidence: $evidence})",
            {
                "eid": uuid.uuid4().hex,
                "task": task,
                "subject": subject,
                "value": value,
                "evidence": _canonical(list(evidence)),
            },
        )

    def consolidate(self, principal: str) -> list[SemanticFact]:
        # a fact is learned only from two or more episodes that agree and none that disagree
        rows = self._q(principal, "MATCH (e:Episode) RETURN e.subject, e.value")
        values: dict[str, list[str]] = defaultdict(list)
        for subject, value in rows:
            values[str(subject)].append(str(value))
        made: list[SemanticFact] = []
        for subject, seen in sorted(values.items()):
            if len(seen) < 2 or len(set(seen)) != 1:
                continue
            created = self._q(
                principal,
                "MERGE (f:Fact {id: $id}) ON CREATE SET f.value = $value, f.ver = 1, f.subject = $subject, "
                "f.origin = 'consolidated', f.support = $support, f.fresh = true "
                "WITH f, f.fresh AS fresh REMOVE f.fresh RETURN fresh",
                {"id": f"sem:{subject}", "value": seen[0], "subject": subject, "support": len(seen)},
            )
            if created and created[0][0] is True:
                made.append(SemanticFact(subject, seen[0], len(seen)))
        return made

    def save_procedure(self, principal: str, task: str, plan: Sequence[str]) -> None:
        self._q(
            principal,
            "MERGE (p:Procedure {task: $task}) SET p.plan = $plan, p.verified_runs = 0, p.failed_runs = 0",
            {"task": task, "plan": _canonical(list(plan))},
        )

    def reuse_procedure(self, principal: str, task: str, verify: Callable[[list[str]], bool]) -> list[str] | None:
        rows = self._q(principal, "MATCH (p:Procedure {task: $task}) RETURN p.plan", {"task": task})
        if not rows:
            return None
        plan = [str(step) for step in json.loads(str(rows[0][0]))]
        # procedural memory is a hypothesis: it is used only if it still verifies on the current graph
        counter = "verified_runs" if verify(plan) else "failed_runs"
        self._q(principal, f"MATCH (p:Procedure {{task: $task}}) SET p.{counter} = p.{counter} + 1", {"task": task})
        return plan if counter == "verified_runs" else None
