"""Application configuration.

Settings come from environment variables, with a local ``.env`` file read when
present. Everything is validated the first time settings are requested, so a
missing or malformed value fails immediately with a message naming the variable
rather than surfacing later as an obscure error inside a request.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["local", "test", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class ConfigurationError(RuntimeError):
    """Raised when configuration is missing or invalid.

    Carries a message listing every offending variable, so one run surfaces all
    of the problems instead of one per attempt.
    """


class Settings(BaseSettings):
    """Validated application settings.

    Fields without a default are required. Add any new required variable to
    ``.env.example`` in the same change, or a fresh clone will not start.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Runtime -----------------------------------------------------------
    app_env: AppEnv = "local"
    log_level: LogLevel = "INFO"

    # --- Data stores (required) --------------------------------------------
    database_url: PostgresDsn = Field(
        description="PostgreSQL connection URL, e.g. postgresql://user:pass@host:5432/db",
    )
    redis_url: RedisDsn = Field(
        description="Redis connection URL, e.g. redis://localhost:6379/0",
    )

    # --- Tenancy -----------------------------------------------------------
    # Carried from the first commit so multi-tenancy (E9) is an enforcement
    # change rather than a retrofit through every query. See KAN-15.
    default_tenant_slug: str = "acme"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


def _format_validation_error(exc: ValidationError) -> str:
    """Turn a pydantic error into something actionable at 3 a.m."""
    lines = ["Configuration is invalid. Fix these environment variables:", ""]
    for error in exc.errors():
        variable = ".".join(str(part) for part in error["loc"]).upper()
        reason = error["msg"]
        if error["type"] == "missing":
            reason = "is required but was not set"
        lines.append(f"  {variable}: {reason}")
    lines.extend(["", "See .env.example for the full list and example values."])
    return "\n".join(lines)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the validated settings, building them on first use.

    Raises:
        ConfigurationError: if any required variable is missing or invalid.
    """
    try:
        # pydantic-settings populates these from the environment, which mypy
        # cannot see, so the call looks like it is missing arguments.
        return Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        raise ConfigurationError(_format_validation_error(exc)) from exc
