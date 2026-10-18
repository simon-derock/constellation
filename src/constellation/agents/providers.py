import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from constellation.agents.epistemic import LLM
from constellation.agents.llm import ChatClient, LLMError, ModelLock, Reply, Transport, Usage, https_transport

_TEMPERATURE, _MAX_TOKENS = 0.0, 1_024


@dataclass(frozen=True, slots=True)
class Provider:
    name: str
    url: str
    model: str
    # environment names for the token; the first one that is set wins
    keys: tuple[str, ...]
    # environment name of the account id, for the one endpoint that carries it in its path
    account: str = ""
    # models whose id starts with this take reasoning_effort=low (fewer hidden tokens against a per-minute budget);
    # other models on the same host reject the field
    reasoning_prefix: str = ""
    # (per minute, per day) asks that keep one Ask, about 4 calls and 3,800 tokens, inside this provider's free
    # allowance; unset leaves the API's own defaults
    asks: tuple[int, int] | None = None

    def lock(self, model: str = "") -> ModelLock:
        model = model or self.model
        effort = "low" if self.reasoning_prefix and model.startswith(self.reasoning_prefix) else ""
        return ModelLock(model, _TEMPERATURE, _MAX_TOKENS, effort)

    def token(self, env: Mapping[str, str]) -> str:
        return next((value for key in self.keys if (value := env.get(key, "").strip())), "")

    def configured(self, env: Mapping[str, str]) -> bool:
        return bool(self.token(env)) and (not self.account or bool(env.get(self.account, "").strip()))

    def client(
        self,
        env: Mapping[str, str],
        lock: ModelLock,
        transport: Transport = https_transport,
        sleep: Callable[[float], None] = time.sleep,
    ) -> ChatClient:
        if not self.configured(env):
            raise LLMError(
                f"{self.name} needs {' or '.join(self.keys)}" + (f" and {self.account}" if self.account else "")
            )
        url = self.url.format(account=env[self.account].strip()) if self.account else self.url
        return ChatClient(url, self.token(env), lock, transport, sleep)


# the priority when MODEL_PROVIDER is not set: the largest free allowance first, the two trial tiers last
PROVIDERS = (
    Provider(
        "groq",
        "https://api.groq.com/openai/v1/chat/completions",
        "openai/gpt-oss-120b",
        ("GROQ_KEY", "GROQ_API_KEY"),
        reasoning_prefix="openai/gpt-oss",
        # measured limits for this model: 8,000 tokens a minute, 200,000 a day, 1,000 requests a day
        asks=(2, 45),
    ),
    Provider("cerebras", "https://api.cerebras.ai/v1/chat/completions", "gpt-oss-120b", ("CEREBRAS_API_KEY",)),
    Provider(
        "gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "gemini-3.5-flash-lite",
        ("GEMINI_API_KEY",),
    ),
    Provider(
        "openrouter",
        "https://openrouter.ai/api/v1/chat/completions",
        "nvidia/nemotron-3-super-120b-a12b:free",
        ("OPENROUTER_API_KEY",),
    ),
    Provider(
        "cohere",
        "https://api.cohere.com/compatibility/v1/chat/completions",
        "command-a-03-2025",
        ("COHERE_CHAT_KEY", "CH"),
    ),
    Provider(
        "workers",
        "https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1/chat/completions",
        "@cf/openai/gpt-oss-20b",
        ("CLOUDFLARE_API_TOKEN",),
        account="CLOUDFLARE_ACCOUNT_ID",
    ),
)

BY_NAME = {p.name: p for p in PROVIDERS}


def candidates(env: Mapping[str, str]) -> tuple[Provider, ...]:
    wanted = env.get("MODEL_PROVIDER", "").strip().lower()
    if wanted:
        if wanted not in BY_NAME:
            raise ValueError(f"refusing MODEL_PROVIDER {wanted!r}: choose one of {', '.join(BY_NAME)}")
        return (BY_NAME[wanted],)
    configured = tuple(p for p in PROVIDERS if p.configured(env))
    # MODEL is one provider's model id, so it pins the first provider rather than being tried on the others
    return configured[:1] if env.get("MODEL") else configured


# the provider cannot serve right now (quota, credentials, outage, a request over its token budget), as opposed to
# this request being malformed; after one of these the next question starts on another provider
_UNAVAILABLE = frozenset({401, 402, 403, 413, 429, 500, 502, 503, 504})
_REST_SECONDS = 600.0


class _Reporting:
    def __init__(self, inner: ChatClient, rest: Callable[[], None]) -> None:
        self._inner, self._rest = inner, rest

    @property
    def usage(self) -> list[Usage]:
        return self._inner.usage

    def chat(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> Reply:
        try:
            return self._inner.chat(messages, tools)
        except LLMError as err:
            if err.status in _UNAVAILABLE:
                self._rest()
            raise


def ask_limits(env: Mapping[str, str]) -> tuple[int, int] | None:
    # sized to the provider that answers first; after a failover the stricter limits just stay in force
    chain = candidates(env)
    return chain[0].asks if chain else None


def llm_factory(
    env: Mapping[str, str],
    transport: Transport = https_transport,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Callable[[], LLM]:
    chain = candidates(env)
    # when each provider may be tried again; a question keeps the provider it started on, so this is read only
    # between questions, and the question that finds a provider out of quota still fails rather than switch models
    rests_until: dict[str, float] = {}

    def make() -> LLM:
        if not chain:
            raise LLMError("no model credentials configured")
        now = clock()
        # best first among the providers not resting; if all are, the one that rests the least
        chosen = min(chain, key=lambda p: max(rests_until.get(p.name, 0.0), now))
        client = chosen.client(env, chosen.lock(env.get("MODEL", "")), transport, sleep)
        return _Reporting(client, lambda: rests_until.__setitem__(chosen.name, clock() + _REST_SECONDS))

    return make
