"""Configuration must fail fast, and say exactly what is wrong."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import ConfigurationError, Settings, get_settings

REQUIRED_VARS = ("DATABASE_URL", "REDIS_URL")


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()


def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Remove every known variable and move off any real .env file."""
    for var in (*REQUIRED_VARS, "APP_ENV", "LOG_LEVEL", "DEFAULT_TENANT_SLUG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)


def test_missing_required_variables_raise_configuration_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_env(monkeypatch, tmp_path)

    with pytest.raises(ConfigurationError) as excinfo:
        get_settings()

    message = str(excinfo.value)
    # Every missing variable is named, so one run surfaces all the problems.
    for var in REQUIRED_VARS:
        assert var in message, f"{var} should be named in: {message}"
    assert "is required but was not set" in message
    assert ".env.example" in message


def test_malformed_url_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolate_env(monkeypatch, tmp_path)
    monkeypatch.setenv("DATABASE_URL", "not-a-url")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    with pytest.raises(ConfigurationError) as excinfo:
        get_settings()

    assert "DATABASE_URL" in str(excinfo.value)


def test_valid_environment_loads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolate_env(monkeypatch, tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://support:support@localhost:5432/support")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    settings = get_settings()

    assert settings.app_env == "local"
    assert settings.is_production is False
    assert settings.default_tenant_slug == "acme"


def test_unknown_app_env_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_env="banana",  # type: ignore[arg-type]
            database_url="postgresql://support:support@localhost:5432/support",  # type: ignore[arg-type]
            redis_url="redis://localhost:6379/0",  # type: ignore[arg-type]
        )
