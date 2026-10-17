from pathlib import Path

import pytest

from constellation.api.main import settings_from_env


def test_defaults_are_safe_and_apex_is_the_only_tenant() -> None:
    settings = settings_from_env({})
    assert list(settings.tenants) == ["apex"]
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
