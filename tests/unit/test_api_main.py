from pathlib import Path

import pytest

from constellation.api.main import settings_from_env


def test_defaults_are_safe_and_the_two_tenants_are_apex_and_live() -> None:
    settings = settings_from_env({})
    assert list(settings.tenants) == ["apex", "falkordb"]
    assert settings.tenants["apex"].graph == "brain:apex"
    assert settings.allowed_origins == ()
    assert settings.asks_per_minute <= 10
    assert settings.tenants["apex"].roles["Jax"] == "engineering_backend"


def test_origins_and_limits_come_from_the_environment() -> None:
    settings = settings_from_env(
        {
            "ALLOWED_ORIGINS": "https://a.example, https://b.example",
            "ASKS_PER_MINUTE": "3",
            "ASKS_PER_DAY": "40",
            "PUBLISHED_DIR": "somewhere",
        }
    )
    assert settings.allowed_origins == ("https://a.example", "https://b.example")
    assert (settings.asks_per_minute, settings.asks_per_day) == (3, 40)
    assert settings.published == Path("somewhere")


@pytest.mark.parametrize("origin", ["*", "http://insecure.example", "javascript:alert(1)"])
def test_a_wildcard_or_non_https_origin_is_refused(origin: str) -> None:
    with pytest.raises(ValueError, match="origin"):
        settings_from_env({"ALLOWED_ORIGINS": origin})


def test_localhost_origins_are_allowed_for_development() -> None:
    assert settings_from_env({"ALLOWED_ORIGINS": "http://localhost:5173"}).allowed_origins == ("http://localhost:5173",)


def test_real_actions_are_off_unless_both_a_key_and_a_token_are_configured() -> None:
    from constellation.api.main import real_sink_from_env

    assert real_sink_from_env({}) is None
    assert real_sink_from_env({"GITHUB_ACTIONS_TOKEN": "t"}) is None
    assert real_sink_from_env({"APPROVER_KEY": "k"}) is None
    assert real_sink_from_env({"APPROVER_KEY": "k", "GITHUB_ACTIONS_TOKEN": "t"}) is not None


def test_the_operator_key_and_caps_come_from_the_environment() -> None:
    settings = settings_from_env({"APPROVER_KEY": "k", "REAL_ACTIONS_PER_DAY": "2"})
    assert (settings.approver_key, settings.real_actions_per_day) == ("k", 2)
    assert settings_from_env({}).approver_key == ""


def test_a_malformed_actions_repository_is_refused_at_startup() -> None:
    from constellation.api.main import real_sink_from_env

    with pytest.raises(ValueError, match="repository"):
        real_sink_from_env({"APPROVER_KEY": "k", "GITHUB_ACTIONS_TOKEN": "t", "ACTIONS_REPO": "../x"})


def limits(env: dict[str, str]) -> tuple[int, int]:
    settings = settings_from_env(env)
    return settings.asks_per_minute, settings.asks_per_day


def test_ask_limits_default_to_the_api_defaults_without_a_groq_key() -> None:
    assert limits({}) == (6, 150)
    assert limits({"CEREBRAS_API_KEY": "k"}) == (6, 150)
    assert limits({"COHERE_CHAT_KEY": "k"}) == (6, 150)


@pytest.mark.parametrize("env", [{"GROQ_KEY": "k"}, {"GROQ_API_KEY": "k"}, {"GROQ_KEY": "k", "CEREBRAS_API_KEY": "k"}])
def test_ask_limits_shrink_to_groqs_free_allowance_when_groq_answers(env: dict[str, str]) -> None:
    assert limits(env) == (2, 45)


def test_a_named_provider_decides_which_ask_limits_apply() -> None:
    assert limits({"GROQ_KEY": "k", "CEREBRAS_API_KEY": "k", "MODEL_PROVIDER": "cerebras"}) == (6, 150)
    assert limits({"MODEL_PROVIDER": "groq"}) == (2, 45)


def test_explicit_ask_limits_override_the_groq_defaults_one_by_one() -> None:
    assert limits({"GROQ_KEY": "k", "ASKS_PER_MINUTE": "5"}) == (5, 45)
    assert limits({"GROQ_KEY": "k", "ASKS_PER_DAY": "100"}) == (2, 100)
    assert limits({"GROQ_KEY": "k", "ASKS_PER_MINUTE": "", "ASKS_PER_DAY": ""}) == (2, 45)


def test_groqs_ask_limits_stay_inside_its_measured_free_allowance() -> None:
    # one Ask is about 4 model calls and 3,800 tokens; Groq's gpt-oss-120b allows 8,000 tokens a minute,
    # 200,000 a day and 1,000 requests a day
    per_minute, per_day = limits({"GROQ_KEY": "k"})
    assert per_minute * 3_800 <= 8_000
    assert per_day * 3_800 <= 200_000
    assert per_day * 4 <= 1_000


def test_the_live_tenant_is_configured_and_never_takes_questions() -> None:
    live = settings_from_env({}).tenants["falkordb"]
    assert (live.graph, live.live, dict(live.roles)) == ("brain:falkordb", True, {})
