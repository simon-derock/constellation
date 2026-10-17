import json
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from constellation.agents.epistemic import LLM, Question
from constellation.agents.llm import LLMError
from constellation.agents.planner import solve
from constellation.agents.toolbox import Perspective, Toolbox
from constellation.api.mcp import build_server
from constellation.graph.read import ReadPort
from constellation.proof import ProofQuery, replay


@dataclass(frozen=True, slots=True)
class Tenant:
    key: str
    graph: str
    title: str
    # actor name -> role, resolved server-side so a caller cannot claim a role
    roles: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class Settings:
    tenants: Mapping[str, Tenant]
    allowed_origins: tuple[str, ...]
    published: Path
    asks_per_minute: int = 6
    asks_per_day: int = 200


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


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant: str = Field(min_length=1, max_length=40)
    queries: list[ProofQueryIn] = Field(min_length=1, max_length=50)


def _caller(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def create_app(port: ReadPort, settings: Settings, llm_factory: Callable[[], LLM]) -> FastAPI:
    default = next(iter(settings.tenants.values()))
    mcp_app = build_server(port, default.graph).http_app(path="/")
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

    @app.post("/api/v1/ask")
    def ask(body: AskRequest, request: Request) -> dict[str, Any]:
        tenant = tenant_of(body.tenant)
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

    app.mount("/mcp", mcp_app)
    return app
