import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

type Transport = Callable[[str, dict[str, str], bytes], tuple[int, dict[str, Any]]]

_RETRYABLE = frozenset({429, 500, 502, 503, 504})
_ATTEMPTS = 4


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ModelLock:
    # one model and one decoding setup per run; its hash goes into the run ledger
    model: str
    temperature: float
    max_tokens: int

    @property
    def sha256(self) -> str:
        blob = json.dumps([self.model, self.temperature, self.max_tokens], separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float


@dataclass(frozen=True, slots=True)
class Reply:
    content: str
    tool_calls: tuple[dict[str, Any], ...]
    message: dict[str, Any]


_ALLOWED_ORIGINS = ("https://api.cloudflare.com/", "https://api.cohere.com/")
# Cloudflare-fronted providers (Groq) answer HTTP 403 "error code: 1010" to urllib's default agent
_USER_AGENT = "constellation/1.0"


def https_transport(url: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, Any]]:
    # enforced, not assumed: only the providers' https origins are ever opened, so file:// and other schemes cannot be
    if not url.startswith(_ALLOWED_ORIGINS):
        raise LLMError("refusing to open a URL outside the provider origin")
    request = urllib.request.Request(url, data=body, headers={"User-Agent": _USER_AGENT, **headers}, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310  # nosec B310
            return response.status, json.load(response)
    except urllib.error.HTTPError as err:
        try:
            return err.code, json.loads(err.read() or b"{}")
        except json.JSONDecodeError:
            return err.code, {}


@dataclass
class ChatClient:
    # any OpenAI-compatible chat-completions endpoint with tools; the address is the only thing that differs by provider
    url: str
    token: str
    lock: ModelLock
    transport: Transport = https_transport
    sleep: Callable[[float], None] = time.sleep
    usage: list[Usage] = field(default_factory=list)

    def chat(self, messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]]) -> Reply:
        body: dict[str, Any] = {
            "model": self.lock.model,
            "messages": list(messages),
            "temperature": self.lock.temperature,
            "max_tokens": self.lock.max_tokens,
        }
        if tools:
            body["tools"], body["tool_choice"] = list(tools), "auto"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        status: int = 0
        payload: dict[str, Any] = {}
        for attempt in range(_ATTEMPTS):
            start = time.perf_counter()
            status, payload = self.transport(self.url, headers, json.dumps(body).encode())
            if status == 200:
                return self._reply(payload, (time.perf_counter() - start) * 1_000)
            if status not in _RETRYABLE:
                break
            # same model, exponential backoff: a run never changes model mid-question
            self.sleep(2.0**attempt)
        raise LLMError(f"{self.lock.model} failed with HTTP {status}: {_provider_error(payload)}")

    def _reply(self, payload: dict[str, Any], latency_ms: float) -> Reply:
        message = payload["choices"][0]["message"]
        tokens = payload.get("usage") or {}
        self.usage.append(
            Usage(int(tokens.get("prompt_tokens", 0)), int(tokens.get("completion_tokens", 0)), latency_ms)
        )
        content, calls = str(message.get("content") or ""), tuple(message.get("tool_calls") or ())
        # echo back only what the endpoint accepts as input; providers add null fields it then rejects
        clean: dict[str, Any] = {"role": "assistant", "content": content}
        if calls:
            clean["tool_calls"] = list(calls)
        return Reply(content, calls, clean)


def _provider_error(payload: dict[str, Any]) -> str:
    # provider messages describe the request, never our credentials; capped so a huge body cannot flood logs
    errors = payload.get("errors") or [payload.get("error") or payload.get("message") or {}]
    messages = [str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in errors]
    return "; ".join(m for m in messages if m)[:300] or "no error body"
