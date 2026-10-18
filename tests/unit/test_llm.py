import hashlib
import io
import json
import urllib.error
import urllib.request
from email.message import Message
from typing import Any

import pytest

from constellation.agents.llm import ChatClient, LLMError, ModelLock, https_transport
from constellation.agents.providers import BY_NAME, llm_factory

LOCK = ModelLock(model="@cf/openai/gpt-oss-20b", temperature=0.0, max_tokens=512)


class Scripted:
    # a transport that replays canned HTTP outcomes and records every request
    def __init__(self, outcomes: list[tuple[int, dict[str, Any]]]) -> None:
        self.outcomes = outcomes
        self.requests: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    def __call__(self, url: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, Any]]:
        self.requests.append((url, headers, json.loads(body)))
        return self.outcomes.pop(0)


OK = (
    200,
    {
        "choices": [{"message": {"role": "assistant", "content": "{}"}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    },
)


ENV = {"CLOUDFLARE_ACCOUNT_ID": "acct", "CLOUDFLARE_API_TOKEN": "secret-token", "COHERE_CHAT_KEY": "secret-token"}


def client(transport: Scripted, provider: str = "workers") -> ChatClient:
    return BY_NAME[provider].client(ENV, LOCK, transport, sleep=lambda _s: None)


def test_every_request_uses_the_locked_model_and_parameters() -> None:
    transport = Scripted([OK])
    client(transport).chat([{"role": "user", "content": "hi"}], tools=[])
    _url, _headers, body = transport.requests[0]
    assert (body["model"], body["temperature"], body["max_tokens"]) == (LOCK.model, 0.0, 512)


def test_rate_limits_retry_on_the_same_model() -> None:
    transport = Scripted([(429, {}), (503, {}), OK])
    reply = client(transport).chat([{"role": "user", "content": "hi"}], tools=[])
    assert reply.content == "{}"
    assert {r[2]["model"] for r in transport.requests} == {LOCK.model}


def test_exhausted_retries_fail_loudly_instead_of_switching_models() -> None:
    with pytest.raises(LLMError, match="429"):
        client(Scripted([(429, {})] * 5)).chat([{"role": "user", "content": "hi"}], tools=[])


def test_tokens_are_accounted_per_call() -> None:
    llm = client(Scripted([OK, OK]))
    llm.chat([{"role": "user", "content": "a"}], tools=[])
    llm.chat([{"role": "user", "content": "b"}], tools=[])
    assert [(u.prompt_tokens, u.completion_tokens) for u in llm.usage] == [(7, 3), (7, 3)]


def test_the_lock_has_a_stable_fingerprint_for_the_run_ledger() -> None:
    assert LOCK.sha256 == ModelLock("@cf/openai/gpt-oss-20b", 0.0, 512).sha256
    assert LOCK.sha256 != ModelLock("@cf/openai/gpt-oss-120b", 0.0, 512).sha256


def test_the_token_never_appears_in_errors() -> None:
    with pytest.raises(LLMError) as err:
        client(Scripted([(400, {"errors": [{"message": "bad"}]})])).chat([], tools=[])
    assert "secret-token" not in str(err.value)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://api.cloudflare.com/x", "https://evil.example/ai"])
def test_the_real_transport_refuses_any_url_outside_the_provider_origin(url: str) -> None:
    with pytest.raises(LLMError, match="origin"):
        https_transport(url, {}, b"{}")


class Response(io.BytesIO):
    status = 200


class Opened:
    # stands in for urlopen: records the request it was given and answers 200 with an empty JSON object
    def __init__(self) -> None:
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> Response:
        self.requests.append(request)
        return Response(b"{}")


def test_the_real_transport_names_itself_instead_of_urllibs_default_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    opened = Opened()
    monkeypatch.setattr(urllib.request, "urlopen", opened)
    https_transport("https://api.cohere.com/compatibility/v1/chat/completions", {"Authorization": "Bearer t"}, b"{}")
    request = opened.requests[0]
    assert request.get_header("User-agent") == "constellation/1.0"
    assert request.get_header("Authorization") == "Bearer t"


def refusing(code: int, body: bytes) -> Any:
    # a urlopen that fails the way a provider's HTTP error does, with the body the provider sent
    def urlopen(request: urllib.request.Request, timeout: float) -> Response:
        raise urllib.error.HTTPError(request.full_url, code, "refused", Message(), io.BytesIO(body))

    return urlopen


def test_an_error_list_from_the_real_transport_is_read_like_any_other_error(monkeypatch: pytest.MonkeyPatch) -> None:
    gemini = b'[{"error": {"code": 429, "message": "You exceeded your current quota", "status": "RESOURCE_EXHAUSTED"}}]'
    monkeypatch.setattr(urllib.request, "urlopen", refusing(429, gemini))
    llm = ChatClient("https://api.cohere.com/x", "secret-token", LOCK, https_transport, sleep=lambda _s: None)
    with pytest.raises(LLMError, match="HTTP 429: You exceeded your current quota") as err:
        llm.chat([], tools=[])
    assert "secret-token" not in str(err.value)


def test_a_body_that_is_not_json_still_fails_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", refusing(403, b"error code: 1010"))
    llm = ChatClient("https://api.cohere.com/x", "secret-token", LOCK, https_transport, sleep=lambda _s: None)
    with pytest.raises(LLMError, match="HTTP 403: no error body"):
        llm.chat([], tools=[])


def test_an_error_inside_a_200_is_an_error_not_an_answer() -> None:
    body = {"error": {"message": "Provider returned error", "code": 502}}
    with pytest.raises(LLMError, match="returned no answer: Provider returned error"):
        client(Scripted([(200, body)])).chat([], tools=[])


def test_a_200_without_choices_is_an_error_not_an_answer() -> None:
    with pytest.raises(LLMError, match="returned no answer: no error body"):
        client(Scripted([(200, {"choices": []})])).chat([], tools=[])


def test_echoed_assistant_messages_carry_only_role_content_and_tool_calls() -> None:
    noisy = {
        "role": "assistant",
        "content": None,
        "refusal": None,
        "audio": None,
        "function_call": None,
        "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "f", "arguments": "{}"}}],
    }
    reply = client(Scripted([(200, {"choices": [{"message": noisy}], "usage": {}})])).chat([], tools=[])
    assert set(reply.message) == {"role", "content", "tool_calls"}
    assert reply.message["content"] == ""


def test_provider_errors_are_reported_without_the_token() -> None:
    body = {"errors": [{"message": "Invalid input: unexpected key 'audio'"}]}
    with pytest.raises(LLMError, match="unexpected key 'audio'") as err:
        client(Scripted([(400, body)])).chat([], tools=[])
    assert "secret-token" not in str(err.value)


def test_workers_ai_puts_the_account_in_its_address() -> None:
    transport = Scripted([OK])
    client(transport).chat([{"role": "user", "content": "hi"}], tools=[])
    url, headers, _body = transport.requests[0]
    assert url == "https://api.cloudflare.com/client/v4/accounts/acct/ai/v1/chat/completions"
    assert headers["Authorization"] == "Bearer secret-token"


def test_cohere_uses_its_compatible_endpoint_with_the_same_body() -> None:
    transport = Scripted([OK])
    client(transport, "cohere").chat([{"role": "user", "content": "hi"}], tools=[])
    url, headers, body = transport.requests[0]
    assert url == "https://api.cohere.com/compatibility/v1/chat/completions"
    assert headers["Authorization"] == "Bearer secret-token"
    assert body["model"] == LOCK.model


def test_cohere_errors_name_the_provider_message() -> None:
    transport = Scripted([(400, {"message": "bad tool schema"})])
    with pytest.raises(LLMError, match="bad tool schema"):
        client(transport, "cohere").chat([], tools=[])


def test_a_cohere_key_wins_over_workers_ai_and_pins_its_model() -> None:
    transport = Scripted([OK])
    llm_factory(ENV, transport, sleep=lambda _s: None)().chat([], tools=[])
    url, _headers, body = transport.requests[0]
    assert url.startswith("https://api.cohere.com/")
    assert body["model"] == "command-a-03-2025"


def test_workers_ai_answers_when_no_other_key_is_set() -> None:
    transport = Scripted([OK])
    env = {"CLOUDFLARE_ACCOUNT_ID": "acct", "CLOUDFLARE_API_TOKEN": "secret-token"}
    llm_factory(env, transport, sleep=lambda _s: None)().chat([], tools=[])
    url, _headers, body = transport.requests[0]
    assert url.startswith("https://api.cloudflare.com/client/v4/accounts/acct/")
    assert body["model"] == "@cf/openai/gpt-oss-20b"


def test_the_model_variable_overrides_the_pinned_model() -> None:
    transport = Scripted([OK])
    llm_factory({**ENV, "MODEL": "command-r7b-12-2024"}, transport, sleep=lambda _s: None)().chat([], tools=[])
    assert transport.requests[0][2]["model"] == "command-r7b-12-2024"


@pytest.mark.parametrize("env", [{}, {"CLOUDFLARE_API_TOKEN": "t"}, {"COHERE_CHAT_KEY": " "}])
def test_without_credentials_asking_fails_with_a_model_error(env: dict[str, str]) -> None:
    make = llm_factory(env)
    with pytest.raises(LLMError, match="credentials"):
        make()


def test_the_legacy_ch_variable_still_names_the_cohere_key() -> None:
    transport = Scripted([OK])
    llm_factory({"CH": "secret-token"}, transport, sleep=lambda _s: None)().chat([], tools=[])
    assert transport.requests[0][1]["Authorization"] == "Bearer secret-token"


# name, token variable, address, pinned default model
FREE_TIERS = [
    ("groq", "GROQ_KEY", "https://api.groq.com/openai/v1/chat/completions", "openai/gpt-oss-120b"),
    ("cerebras", "CEREBRAS_API_KEY", "https://api.cerebras.ai/v1/chat/completions", "gpt-oss-120b"),
    (
        "gemini",
        "GEMINI_API_KEY",
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "gemini-3.5-flash-lite",
    ),
    (
        "openrouter",
        "OPENROUTER_API_KEY",
        "https://openrouter.ai/api/v1/chat/completions",
        "nvidia/nemotron-3-super-120b-a12b:free",
    ),
]
TOOL = {"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}


@pytest.mark.parametrize(("name", "variable", "url", "model"), FREE_TIERS)
def test_each_free_provider_gets_its_address_token_and_pinned_model(
    name: str, variable: str, url: str, model: str
) -> None:
    transport = Scripted([OK])
    lock = ModelLock(BY_NAME[name].model, temperature=0.0, max_tokens=512)
    BY_NAME[name].client({variable: "secret-token"}, lock, transport).chat([{"role": "user", "content": "hi"}], [TOOL])
    sent_url, headers, body = transport.requests[0]
    assert sent_url == url
    assert headers == {"Authorization": "Bearer secret-token", "Content-Type": "application/json"}
    assert (body["model"], body["temperature"], body["max_tokens"]) == (model, 0.0, 512)
    assert (body["tools"], body["tool_choice"]) == ([TOOL], "auto")


# the error body each provider documents, as the transport hands it over
PROVIDER_ERRORS = [
    ("groq", {"error": {"message": "Rate limit reached for model", "type": "tokens", "code": "rate_limit_exceeded"}}),
    ("cerebras", {"message": "Rate limit reached for model", "type": "too_many_tokens_error", "code": "quota"}),
    ("gemini", {"errors": [{"error": {"code": 429, "message": "Rate limit reached for model", "status": "X"}}]}),
    ("openrouter", {"error": {"message": "Rate limit reached for model", "code": 429}}),
]


@pytest.mark.parametrize(("name", "body"), PROVIDER_ERRORS)
def test_each_providers_error_message_is_surfaced_without_the_token(name: str, body: dict[str, Any]) -> None:
    variable = next(v for n, v, _u, _m in FREE_TIERS if n == name)
    transport = Scripted([(429, body)] * 4)
    llm = BY_NAME[name].client({variable: "secret-token"}, LOCK, transport, sleep=lambda _s: None)
    with pytest.raises(LLMError, match="HTTP 429: Rate limit reached for model") as err:
        llm.chat([], tools=[])
    assert "secret-token" not in str(err.value)
    assert len(transport.requests) == 4


def sent_body(provider: str, model: str = "") -> dict[str, Any]:
    transport = Scripted([OK])
    pinned = BY_NAME[provider]
    variable = pinned.keys[0]
    env = {variable: "secret-token", "CLOUDFLARE_ACCOUNT_ID": "acct"}
    pinned.client(env, pinned.lock(model), transport).chat([], [TOOL])
    return transport.requests[0][2]


def test_groq_gpt_oss_runs_at_low_reasoning_effort() -> None:
    body = sent_body("groq")
    assert (body["model"], body["reasoning_effort"]) == ("openai/gpt-oss-120b", "low")
    assert sent_body("groq", "openai/gpt-oss-20b")["reasoning_effort"] == "low"


def test_groq_models_that_do_not_reason_are_not_sent_the_field() -> None:
    assert "reasoning_effort" not in sent_body("groq", "llama-3.3-70b-versatile")


@pytest.mark.parametrize("provider", ["cohere", "workers", "cerebras", "gemini", "openrouter"])
def test_only_groq_is_sent_reasoning_effort(provider: str) -> None:
    assert "reasoning_effort" not in sent_body(provider)


def test_the_reasoning_effort_belongs_to_the_locked_setup() -> None:
    plain = ModelLock("m", 0.0, 512)
    # recorded before the field existed: the fingerprint must not move
    assert plain.sha256 == hashlib.sha256(b'["m",0.0,512]').hexdigest()
    assert ModelLock("m", 0.0, 512, "low").sha256 != plain.sha256


def test_groq_takes_its_key_from_either_variable() -> None:
    groq = BY_NAME["groq"]
    assert groq.token({"GROQ_KEY": "a"}) == "a"
    assert groq.token({"GROQ_API_KEY": "b"}) == "b"
    assert groq.token({"GROQ_KEY": "a", "GROQ_API_KEY": "b"}) == "a"


@pytest.mark.parametrize(
    "url",
    [
        "https://api.cloudflare.com/client/v4/accounts/a/ai/v1/chat/completions",
        "https://api.cohere.com/compatibility/v1/chat/completions",
        *(url for _n, _v, url, _m in FREE_TIERS),
    ],
)
def test_the_real_transport_opens_each_provider_origin(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    opened = Opened()
    monkeypatch.setattr(urllib.request, "urlopen", opened)
    https_transport(url, {}, b"{}")
    assert [r.full_url for r in opened.requests] == [url]


@pytest.mark.parametrize(
    "url",
    [
        "https://api.groq.com.evil.example/openai/v1/chat/completions",
        "http://api.groq.com/openai/v1/chat/completions",
        "https://evil.example/https://api.cerebras.ai/v1/chat/completions",
        "https://openrouter.ai.evil.example/api/v1/chat/completions",
        "https://generativelanguage.googleapis.com.evil.example/v1beta/openai/",
        "https://api.openai.com/v1/chat/completions",
        "https://api.anthropic.com/v1/messages",
    ],
)
def test_the_real_transport_refuses_lookalike_and_other_origins(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    opened = Opened()
    monkeypatch.setattr(urllib.request, "urlopen", opened)
    with pytest.raises(LLMError, match="origin"):
        https_transport(url, {}, b"{}")
    assert opened.requests == []
