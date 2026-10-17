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


_ALLOWED_ORIGIN = "https://api.cloudflare.com/"


def https_transport(url: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, Any]]:
    # enforced, not assumed: only the provider's https origin is ever opened, so file:// and other schemes cannot be
    if not url.startswith(_ALLOWED_ORIGIN):
        raise LLMError("refusing to open a URL outside the provider origin")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310  # nosec B310 — origin checked above
            return response.status, json.load(response)
    except urllib.error.HTTPError as err:
        try:
            return err.code, json.loads(err.read() or b"{}")
        except json.JSONDecodeError:
            return err.code, {}


@dataclass
class WorkersAI:
    account: str
    token: str
    lock: ModelLock
    transport: Transport = https_transport
    sleep: Callable[[float], None] = time.sleep
    usage: list[Usage] = field(default_factory=list)

    @property
    def _url(self) -> str:
        return f"https://api.cloudflare.com/client/v4/accounts/{self.account}/ai/v1/chat/completions"

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
        status = 0
        for attempt in range(_ATTEMPTS):
            start = time.perf_counter()
            status, payload = self.transport(self._url, headers, json.dumps(body).encode())
            if status == 200:
                return self._reply(payload, (time.perf_counter() - start) * 1_000)
            if status not in _RETRYABLE:
                break
            # same model, exponential backoff: a run never changes model mid-question
            self.sleep(2.0**attempt)
        raise LLMError(f"{self.lock.model} failed with HTTP {status}")

    def _reply(self, payload: dict[str, Any], latency_ms: float) -> Reply:
        message = payload["choices"][0]["message"]
        tokens = payload.get("usage") or {}
        self.usage.append(
            Usage(int(tokens.get("prompt_tokens", 0)), int(tokens.get("completion_tokens", 0)), latency_ms)
        )
        return Reply(str(message.get("content") or ""), tuple(message.get("tool_calls") or ()), message)
