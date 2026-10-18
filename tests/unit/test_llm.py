import json
from typing import Any

import pytest

from constellation.agents.llm import CohereChat, LLMError, ModelLock, WorkersAI, https_transport

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


def client(transport: Scripted) -> WorkersAI:
    return WorkersAI(account="acct", token="secret-token", lock=LOCK, transport=transport, sleep=lambda _s: None)


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


def test_cohere_uses_its_compatible_endpoint_with_the_same_body() -> None:
    transport = Scripted([OK])
    llm = CohereChat("", "secret-token", LOCK, transport=transport, sleep=lambda _s: None)
    llm.chat([{"role": "user", "content": "hi"}], tools=[])
    url, headers, body = transport.requests[0]
    assert url == "https://api.cohere.com/compatibility/v1/chat/completions"
    assert headers["Authorization"] == "Bearer secret-token"
    assert body["model"] == LOCK.model


def test_cohere_errors_name_the_provider_message() -> None:
    transport = Scripted([(400, {"message": "bad tool schema"})])
    with pytest.raises(LLMError, match="bad tool schema"):
        CohereChat("", "secret-token", LOCK, transport=transport, sleep=lambda _s: None).chat([], tools=[])
