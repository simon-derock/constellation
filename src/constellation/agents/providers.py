import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from constellation.agents.epistemic import LLM
from constellation.agents.llm import ChatClient, LLMError, ModelLock, Transport, https_transport

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


def llm_factory(
    env: Mapping[str, str], transport: Transport = https_transport, sleep: Callable[[float], None] = time.sleep
) -> Callable[[], LLM]:
    chain = candidates(env)

    def make() -> LLM:
        if not chain:
            raise LLMError("no model credentials configured")
        return chain[0].client(env, chain[0].lock(env.get("MODEL", "")), transport, sleep)

    return make
