import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path

import uvicorn
from falkordb import FalkorDB
from fastapi import FastAPI

from constellation.actions.sinks import GitHubIssueSink, Sink
from constellation.agents.epistemic import LLM
from constellation.agents.llm import CohereChat, LLMError, ModelLock, WorkersAI
from constellation.api.app import Settings, Tenant, create_app
from constellation.brain.roles import roles_from_config
from constellation.graph.read import ReadPort
from constellation.live.loop import start as start_live_sync
from constellation.live.run import embedder_from_env, sync_job
from constellation.memory.store import MemoryStore

# https only, plus localhost for development; a wildcard would let any page call the API with the visitor's network
_ORIGIN = re.compile(r"https://[a-z0-9.-]+(:\d+)?|http://localhost(:\d+)?")


def _origins(raw: str) -> tuple[str, ...]:
    origins = tuple(o.strip() for o in raw.split(",") if o.strip())
    for origin in origins:
        if not _ORIGIN.fullmatch(origin):
            raise ValueError(f"refusing origin {origin!r}: only https origins (or localhost) are allowed")
    return origins


def settings_from_env(env: Mapping[str, str]) -> Settings:
    roles = roles_from_config(Path("third_party/orgforge/config.yaml"))
    return Settings(
        tenants={
            "apex": Tenant("apex", env.get("APEX_GRAPH", "brain:apex"), "Apex Athletics (OrgForge)", roles),
            "falkordb": Tenant(
                "falkordb", env.get("LIVE_GRAPH", "brain:falkordb"), "FalkorDB on GitHub (live)", {}, live=True
            ),
        },
        allowed_origins=_origins(env.get("ALLOWED_ORIGINS", "")),
        published=Path(env.get("PUBLISHED_DIR", "results/published")),
        asks_per_minute=int(env.get("ASKS_PER_MINUTE", "6")),
        asks_per_day=int(env.get("ASKS_PER_DAY", "150")),
        approver_key=env.get("APPROVER_KEY", ""),
        real_actions_per_day=int(env.get("REAL_ACTIONS_PER_DAY", "3")),
    )


def real_sink_from_env(env: Mapping[str, str]) -> Sink | None:
    # real execution needs both halves: someone who may approve it, and a token that may file the issue
    token, key = env.get("GITHUB_ACTIONS_TOKEN"), env.get("APPROVER_KEY")
    if not token or not key:
        return None
    return GitHubIssueSink(env.get("ACTIONS_REPO", "simon-derock/constellation"), token)


def _llm_factory(env: Mapping[str, str]) -> Callable[[], LLM]:
    # a Cohere chat key wins when set; Workers AI is the fallback, each with its own pinned model
    cohere = env.get("COHERE_CHAT_KEY") or env.get("CH")
    account, token = env.get("CLOUDFLARE_ACCOUNT_ID"), env.get("CLOUDFLARE_API_TOKEN")
    default = "command-a-03-2025" if cohere else "@cf/openai/gpt-oss-20b"
    lock = ModelLock(env.get("MODEL", default), temperature=0.0, max_tokens=1_024)

    def make() -> LLM:
        if cohere:
            return CohereChat("", cohere, lock)
        if not account or not token:
            raise LLMError("no model credentials configured")
        return WorkersAI(account, token, lock)

    return make


def create() -> FastAPI:
    env = os.environ
    db = FalkorDB(host=env.get("FALKORDB_HOST", "localhost"), port=int(env.get("FALKORDB_PORT", "6379")))
    # keeps the live tenant current when credentials are present; otherwise it serves the shipped snapshot
    start_live_sync(
        env, lambda e: sync_job(db, e, e.get("LIVE_ORG", "FalkorDB"), e.get("LIVE_GRAPH", "brain:falkordb"))
    )
    return create_app(
        ReadPort(db),
        settings_from_env(env),
        llm_factory=_llm_factory(env),
        memory=MemoryStore(db, tenant="apex"),
        real_sink=real_sink_from_env(env),
        embedder=embedder_from_env(env),
        repo=env.get("ACTIONS_REPO", "simon-derock/constellation"),
    )


if __name__ == "__main__":
    uvicorn.run(
        "constellation.api.main:create",
        factory=True,
        # loopback unless the deployment says otherwise: the container image sets HOST=0.0.0.0 explicitly
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=True,
    )
