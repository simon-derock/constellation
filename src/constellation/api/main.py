import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path

import uvicorn
from falkordb import FalkorDB
from fastapi import FastAPI

from constellation.agents.epistemic import LLM
from constellation.agents.llm import LLMError, ModelLock, WorkersAI
from constellation.api.app import Settings, Tenant, create_app
from constellation.brain.roles import roles_from_config
from constellation.graph.read import ReadPort

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
        tenants={"apex": Tenant("apex", env.get("APEX_GRAPH", "brain:apex"), "Apex Athletics (OrgForge)", roles)},
        allowed_origins=_origins(env.get("ALLOWED_ORIGINS", "")),
        published=Path(env.get("PUBLISHED_DIR", "results/published")),
        asks_per_minute=int(env.get("ASKS_PER_MINUTE", "6")),
        asks_per_day=int(env.get("ASKS_PER_DAY", "150")),
    )


def _llm_factory(env: Mapping[str, str]) -> Callable[[], LLM]:
    account, token = env.get("CLOUDFLARE_ACCOUNT_ID"), env.get("CLOUDFLARE_API_TOKEN")
    lock = ModelLock(env.get("MODEL", "@cf/openai/gpt-oss-20b"), temperature=0.0, max_tokens=1_024)

    def make() -> LLM:
        if not account or not token:
            raise LLMError("no model credentials configured")
        return WorkersAI(account, token, lock)

    return make


def create() -> FastAPI:
    env = os.environ
    port = ReadPort(FalkorDB(host=env.get("FALKORDB_HOST", "localhost"), port=int(env.get("FALKORDB_PORT", "6379"))))
    return create_app(port, settings_from_env(env), llm_factory=_llm_factory(env))


if __name__ == "__main__":
    uvicorn.run(
        "constellation.api.main:create",
        factory=True,
        # loopback unless the deployment says otherwise: the container image sets HOST=0.0.0.0 explicitly
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=True,
    )
