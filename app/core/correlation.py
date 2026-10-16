"""Per-request correlation IDs.

The ID is held in a :class:`~contextvars.ContextVar`, so every log line emitted
while handling a request carries it without any layer having to pass it down
explicitly. Each ASGI request runs in its own task, so the value cannot leak
between concurrent requests.
"""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

#: Header used both to accept an upstream ID and to return the one in effect.
HEADER_NAME = "X-Request-ID"

#: An inbound ID reaches the logs, so it is untrusted input. Accept only short,
#: boring identifiers; anything else is discarded and replaced with our own,
#: which prevents newline and control-character log injection.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_correlation_id() -> str:
    """Generate a fresh correlation ID."""
    return uuid.uuid4().hex


def sanitize_correlation_id(value: str | None) -> str | None:
    """Return ``value`` if it is a safe identifier, otherwise ``None``."""
    if value is None:
        return None
    return value if _SAFE_ID.match(value) else None


def get_correlation_id() -> str | None:
    """Return the correlation ID for the current context, if one is set."""
    return _correlation_id.get()


def set_correlation_id(value: str) -> None:
    """Bind a correlation ID to the current context."""
    _correlation_id.set(value)


def reset_correlation_id() -> None:
    """Clear the correlation ID. Mainly useful in tests."""
    _correlation_id.set(None)
