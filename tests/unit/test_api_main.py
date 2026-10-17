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
