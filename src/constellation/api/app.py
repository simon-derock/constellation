import hmac
import json
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from constellation.actions.sinks import DryRunSink, Sink
from constellation.actions.store import ActionRecord, ActionStore, CapError
from constellation.actions.suggest import suggestions_from_rows
from constellation.agents.epistemic import LLM, Question
from constellation.agents.llm import LLMError
from constellation.agents.planner import solve
from constellation.agents.toolbox import Perspective, Toolbox
from constellation.api.catalogue import prove
from constellation.api.mcp import build_server
from constellation.api.projection import VIEWS, build_graph, view_by_id
from constellation.graph.catalogue import cypher
from constellation.graph.read import ReadPort
from constellation.live.embed import Embedder
from constellation.live.search import hybrid_search
from constellation.memory.store import ConflictError, MemoryStore
from constellation.proof import ProofQuery, replay


@dataclass(frozen=True, slots=True)
class Tenant:
    key: str
    graph: str
    title: str
    # actor name -> role, resolved server-side so a caller cannot claim a role
    roles: Mapping[str, str]
    # a tenant fed by the live GitHub sync rather than a simulated company; it answers through /live, not /ask
    live: bool = False


@dataclass(frozen=True, slots=True)
class Settings:
    tenants: Mapping[str, Tenant]
    allowed_origins: tuple[str, ...]
    published: Path
    asks_per_minute: int = 6
    asks_per_day: int = 200
    # empty disables real execution entirely: only the public dry-run exists
    approver_key: str = ""
    real_actions_per_day: int = 3


class Limiter:
    # per-caller minute window plus one global daily cap: the free model quota is shared, so it is protected globally
    def __init__(self, per_minute: int, per_day: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._per_minute, self._per_day, self._clock = per_minute, per_day, clock
        self._recent: dict[str, deque[float]] = defaultdict(deque)
        self._day: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self, caller: str) -> bool:
        now = self._clock()
        with self._lock:
            window, day = self._recent[caller], self._day
            while window and now - window[0] > 60:
                window.popleft()
            while day and now - day[0] > 86_400:
                day.popleft()
            if len(window) >= self._per_minute or len(day) >= self._per_day:
                return False
            window.append(now)
            day.append(now)
            return True


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant: str = Field(min_length=1, max_length=40)
    kind: Literal["PERSPECTIVE", "COUNTERFACTUAL", "SILENCE"]
    question: str = Field(min_length=1, max_length=600)
    actor: str | None = Field(default=None, min_length=1, max_length=64)
    day: int | None = Field(default=None, ge=-1_000, le=1_000)


class ProofQueryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=64)]
    params: dict[str, Any] = Field(default_factory=dict, max_length=12)
    sha256: Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]


class ProposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant: str = Field(min_length=1, max_length=40)
    payload_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["dry-run", "real"] = "dry-run"


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant: str = Field(min_length=1, max_length=40)
    queries: list[ProofQueryIn] = Field(min_length=1, max_length=50)


def _caller(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def _action_json(record: ActionRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "kind": record.kind,
        "title": record.title,
        "body": record.body,
        "status": record.status,
        "approver": record.approver,
        "mode": record.mode,
        "result": record.result,
        "evidence": record.evidence,
        "created": record.created,
    }


def create_app(
    port: ReadPort,
    settings: Settings,
    llm_factory: Callable[[], LLM],
    memory: MemoryStore | None = None,
    real_sink: Sink | None = None,
    repo: str = "",
    embedder: Embedder | None = None,
) -> FastAPI:
    default = next(iter(settings.tenants.values()))
    live_graph = next((t.graph for t in settings.tenants.values() if t.live), None)
    mcp_app = build_server(port, default.graph, live_graph, embedder).http_app(path="/")
    app = FastAPI(title="Constellation", version="0.1.0", lifespan=mcp_app.lifespan)
    limiter = Limiter(settings.asks_per_minute, settings.asks_per_day)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["content-type"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[[Request], Any]) -> Response:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def tenant_of(key: str) -> Tenant:
        tenant = settings.tenants.get(key)
        if tenant is None:
            raise HTTPException(422, "unknown tenant")
        return tenant

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> dict[str, Any]:
        counts: dict[str, int] = {}
        for key, tenant in settings.tenants.items():
            try:
                rows = port.run(tenant.graph, "MATCH (n) RETURN count(n)").rows
                counts[key] = int(str(rows[0][0])) if rows else 0
            except Exception:
                counts[key] = 0
        if not all(counts.values()):
            raise HTTPException(503, "graph not ready")
        return {"status": "ready", "tenants": counts}

    @app.get("/api/v1/tenants")
    def tenants() -> dict[str, Any]:
        return {"tenants": [{"key": t.key, "title": t.title} for t in settings.tenants.values()]}

    @app.get("/api/v1/actors")
    def actors(tenant: str) -> dict[str, Any]:
        roles = tenant_of(tenant).roles
        return {"actors": [{"name": name, "role": roles[name]} for name in sorted(roles)]}

    @app.get("/api/v1/ownership")
    def ownership(tenant: str) -> dict[str, Any]:
        proof = prove(port, tenant_of(tenant).graph, "ownership_all", {})
        columns = [str(c) for c in proof["columns"]]
        by_domain: dict[str, list[dict[str, Any]]] = {}
        for row in proof["rows"]:
            record = dict(zip(columns, row, strict=True))
            by_domain.setdefault(str(record.pop("domain")), []).append(record)
        return {
            "domains": [{"domain": name, "intervals": spans} for name, spans in by_domain.items()],
            "proof": {"queries": [{"name": "ownership_all", "params": {}, "sha256": proof["sha256"]}]},
        }

    def live_tenant(key: str) -> Tenant:
        tenant = tenant_of(key)
        if not tenant.live:
            raise HTTPException(422, "this tenant has no live graph")
        return tenant

    def block(name: str, graph: str, params: dict[str, str | int]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        proof = prove(port, graph, name, params)
        columns = [str(c) for c in proof["columns"]]
        rows = [dict(zip(columns, row, strict=True)) for row in proof["rows"]]
        return rows, {"name": name, "params": params, "sha256": proof["sha256"]}

    @app.get("/api/v1/live")
    def live_view(tenant: str, at: Annotated[int | None, Query(ge=0, le=4_102_444_800)] = None) -> dict[str, Any]:
        graph = live_tenant(tenant).graph
        summary, p1 = block("live_summary", graph, {})
        changes, p2 = block("live_recent_changes", graph, {"limit": 25})
        repos, p3 = block("live_repos", graph, {"limit": 12})
        fresh, p4 = block("live_freshness", graph, {})
        proof = [p1, p2, p3, p4]
        as_of: list[dict[str, Any]] | None = None
        if at is not None:
            as_of, p5 = block("live_state_as_of", graph, {"at": at})
            proof.append(p5)
        return {
            "summary": summary,
            "changes": changes,
            "repos": repos,
            "freshness": fresh[0],
            "as_of": as_of,
            "proof": {"queries": proof},
        }

    @app.get("/api/v1/live/item")
    def live_item(tenant: str, item: Annotated[str, Query(min_length=3, max_length=120)]) -> dict[str, Any]:
        history, proof = block("live_item_history", live_tenant(tenant).graph, {"item": item})
        return {"history": history, "proof": {"queries": [proof]}}

    def tenant_for(kind: str) -> Tenant | None:
        return next((t for t in settings.tenants.values() if t.live == (kind == "live")), None)

    @app.get("/api/v1/graph/views")
    def graph_views() -> dict[str, Any]:
        return {
            "views": [
                {"id": v.id, "title": v.title, "hint": v.hint, "tenant": t.key}
                for v in VIEWS
                if (t := tenant_for(v.tenant)) is not None
            ]
        }

    @app.get("/api/v1/graph")
    def graph_view(view: Annotated[str, Query(min_length=1, max_length=40)]) -> dict[str, Any]:
        # a picture of the graph is a set of catalogue queries: its nodes and edges are exactly their rows, and the
        # proof lists them, so what is drawn can be replayed
        try:
            chosen = view_by_id(view)
        except KeyError as err:
            raise HTTPException(422, "unknown view") from err
        tenant = tenant_for(chosen.tenant)
        if tenant is None:
            raise HTTPException(422, "this deployment has no graph for that view")
        rows: list[Any] = []
        proof: list[dict[str, Any]] = []
        for name, params in chosen.steps:
            result = port.run(tenant.graph, cypher(name), params)
            rows.extend(result.rows)
            proof.append({"name": name, "params": params, "sha256": result.sha256})
        try:
            nodes, edges = build_graph(rows)
        except ValueError as err:
            raise HTTPException(503, str(err)) from err
        meta = {"id": chosen.id, "title": chosen.title, "hint": chosen.hint, "tenant": tenant.key}
        return {"view": meta, "nodes": nodes, "edges": edges, "proof": {"queries": proof}}

    search_limiter = Limiter(30, 2_000)

    @app.get("/api/v1/live/search")
    def live_search(
        request: Request, tenant: str, q: Annotated[str, Query(min_length=1, max_length=200)]
    ) -> dict[str, Any]:
        graph = live_tenant(tenant).graph
        if not search_limiter.allow(_caller(request)):
            raise HTTPException(429, "rate limit reached; try again shortly")
        found = hybrid_search(port, graph, q, embedder, k=10)
        return {
            "hits": [{"item": h.item, "title": h.title, "repo": h.repo, "via": list(h.via)} for h in found.hits],
            "vector_used": found.vector_used,
            "proof": {"queries": found.proof},
        }

    @app.get("/api/v1/live/people")
    def live_people(tenant: str) -> dict[str, Any]:
        graph = live_tenant(tenant).graph
        central, p1 = block("live_central_people", graph, {"limit": 10})
        bridges, p2 = block("live_bridge_people", graph, {"limit": 10})
        components, p3 = block("live_components", graph, {})
        return {"central": central, "bridges": bridges, "components": components, "proof": {"queries": [p1, p2, p3]}}

    @app.get("/api/v1/live/path")
    def live_path(
        tenant: str,
        a: Annotated[str, Query(min_length=3, max_length=64, pattern=r"^[a-z0-9-]+$")],
        b: Annotated[str, Query(min_length=3, max_length=64, pattern=r"^[a-z0-9-]+$")],
    ) -> dict[str, Any]:
        rows, proof = block("live_path", live_tenant(tenant).graph, {"from": a, "to": b})
        found = rows[0] if rows else {"path": [], "hops": None}
        return {"path": found["path"], "hops": found["hops"], "proof": {"queries": [proof]}}

    @app.post("/api/v1/ask")
    def ask(body: AskRequest, request: Request) -> dict[str, Any]:
        tenant = tenant_of(body.tenant)
        if tenant.live:
            raise HTTPException(422, "this tenant answers through the live view, not questions")
        perspective: Perspective | None = None
        actor, day = body.actor or "", body.day or 0
        if body.kind == "PERSPECTIVE":
            if not body.actor or body.day is None or body.actor not in tenant.roles:
                raise HTTPException(422, "a perspective question needs a known actor and a day")
            perspective = Perspective(body.actor, tenant.roles[body.actor], body.day)
        if not limiter.allow(_caller(request)):
            raise HTTPException(429, "rate limit reached; try again shortly")
        question = Question("live", body.kind, body.question, actor=actor, day=day)
        tools = Toolbox(port, tenant.graph, perspective)
        try:
            llm = llm_factory()
            run = solve(llm, tools, question)
        except LLMError as err:
            # quota exhaustion, outages and missing credentials all read the same to a visitor; detail stays in logs
            raise HTTPException(503, "the model is unavailable right now; recorded runs are still browsable") from err
        usage = list(getattr(llm, "usage", []))
        return {
            "tenant": tenant.key,
            "kind": body.kind,
            "answer": run.answer,
            "proof": {"queries": [{"name": q.name, "params": q.params, "sha256": q.sha256} for q in tools.queries]},
            "trace": {
                "stop_reason": run.stop_reason,
                "strategy_changes": run.strategy_changes,
                "llm_calls": len(usage),
                "prompt_tokens": sum(u.prompt_tokens for u in usage),
                "completion_tokens": sum(u.completion_tokens for u in usage),
                "tools": [
                    {
                        "tool": c.tool,
                        "args": dict(c.args),
                        "artifacts": len(c.result_ids),
                        "latency_ms": round(c.latency_ms, 1),
                    }
                    for c in tools.calls
                ],
            },
        }

    @app.post("/api/v1/replay")
    def replay_proof(body: ReplayRequest) -> dict[str, Any]:
        tenant = tenant_of(body.tenant)
        queries = [ProofQuery(q.name, q.params, q.sha256) for q in body.queries]
        try:
            report = replay(port, tenant.graph, queries)
        except ValueError as err:
            raise HTTPException(422, str(err)) from err
        return {
            "all_match": report.all_match,
            "results": [{"name": r.name, "match": r.match, "sha256": r.sha256} for r in report.results],
        }

    @app.get("/api/v1/scoreboard")
    def scoreboard() -> dict[str, Any]:
        runs = [json.loads(p.read_text()) for p in sorted(settings.published.glob("*.summary.json"))]
        return {"runs": runs}

    actions_store = ActionStore(memory) if memory is not None else None
    action_limiter = Limiter(10, 300)

    def suggestions_for(tenant: Tenant) -> list[dict[str, Any]]:
        proof = prove(port, tenant.graph, "ownership_all", {})
        columns = [str(c) for c in proof["columns"]]
        domains: dict[str, list[dict[str, Any]]] = {}
        for row in proof["rows"]:
            record = dict(zip(columns, row, strict=True))
            domains.setdefault(str(record.pop("domain")), []).append(record)
        evidence = [{"name": "ownership_all", "params": {}, "sha256": str(proof["sha256"])}]
        return [
            {"kind": s.kind, "title": s.title, "body": s.body, "payload_hash": s.payload_hash, "evidence": evidence}
            for s in suggestions_from_rows(domains, str(proof["sha256"]))
        ]

    def store() -> ActionStore:
        if actions_store is None:
            raise HTTPException(503, "actions are not enabled on this server")
        return actions_store

    @app.get("/api/v1/actions/suggestions")
    def action_suggestions(tenant: str) -> dict[str, Any]:
        return {"suggestions": suggestions_for(tenant_of(tenant))}

    @app.get("/api/v1/actions")
    def action_list() -> dict[str, Any]:
        return {"actions": [_action_json(a) for a in store().recent()]}

    @app.post("/api/v1/actions")
    def action_propose(body: ProposeRequest, request: Request) -> dict[str, Any]:
        # a caller may only propose what the server itself derived from the graph, never a payload of their choosing
        derived = suggestions_for(tenant_of(body.tenant))
        chosen = next((s for s in derived if s["payload_hash"] == body.payload_hash), None)
        if chosen is None:
            raise HTTPException(422, "that is not a suggestion this server derived")
        if not action_limiter.allow(_caller(request)):
            raise HTTPException(429, "rate limit reached; try again shortly")
        return _action_json(store().propose(chosen["kind"], chosen["title"], chosen["body"], chosen["evidence"]))

    def operator(request: Request) -> bool:
        supplied = request.headers.get("x-approver-key", "")
        return bool(settings.approver_key) and hmac.compare_digest(supplied.encode(), settings.approver_key.encode())

    @app.post("/api/v1/actions/{action_id}/approve")
    def action_approve(action_id: str, body: ApproveRequest, request: Request) -> dict[str, Any]:
        actions = store()
        sink: Sink
        if body.mode == "real":
            if not operator(request):
                raise HTTPException(403, "real actions need the operator key")
            if real_sink is None:
                raise HTTPException(503, "real actions are not configured on this server")
            approver, sink = "operator", real_sink
        else:
            approver, sink = "public demo (dry run)", DryRunSink(repo or "owner/repo")
        try:
            actions.approve(action_id, approver)
            record = actions.execute(action_id, sink, mode=body.mode, daily_cap=settings.real_actions_per_day)
        except KeyError as err:
            raise HTTPException(404, "unknown action") from err
        except CapError as err:
            raise HTTPException(429, str(err)) from err
        except ConflictError as err:
            raise HTTPException(409, "this action was already decided") from err
        return _action_json(record)

    app.mount("/mcp", mcp_app)
    return app
