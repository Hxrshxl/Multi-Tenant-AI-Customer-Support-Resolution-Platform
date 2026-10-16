"""Shared fixtures.

The data-store URLs point at closed ports on purpose: dependency checks fail
immediately with connection-refused, which lets the readiness tests run with
nothing installed and without waiting on a timeout.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.core.runtime import configure_event_loop_policy

# pytest creates the event loop itself, so it is a process entry point like
# any other and needs the same policy applied (ADR-005). Without this, every
# database-backed test fails with the Proactor incompatibility on Windows.
configure_event_loop_policy()

UNREACHABLE_POSTGRES = "postgresql://support:sup3rsecret@127.0.0.1:59999/support"
UNREACHABLE_REDIS = "redis://127.0.0.1:59998/0"


@pytest.fixture
def settings() -> Settings:
    # model_validate takes a plain mapping, so the DSN strings are coerced by
    # pydantic rather than needing a type ignore at every call site.
    return Settings.model_validate(
        {
            "app_env": "test",
            "log_level": "INFO",
            "database_url": UNREACHABLE_POSTGRES,
            "redis_url": UNREACHABLE_REDIS,
        }
    )
