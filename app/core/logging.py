"""Structured JSON logging.

One line per event, machine-parseable, always carrying the correlation ID of
the request that produced it. Credentials are scrubbed on the way out: logs
outlive the data they describe and are read by more people than the database
is, so a leaked DSN in a log line is a real exposure.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import sys
from typing import Any

from app.core.correlation import get_correlation_id

REDACTED = "***redacted***"

#: Field names whose values are never logged, matched as substrings.
_SENSITIVE_FRAGMENTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "private_key",
)

#: Credentials embedded in a connection URL, e.g. postgresql://user:pw@host.
_URL_CREDENTIALS = re.compile(
    r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<user>[^:/@\s]+):[^@/\s]+@"
)

#: Attributes the stdlib puts on every record; anything else is caller `extra`.
_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "stacklevel",
        "thread",
        "threadName",
        "taskName",
    }
)


def redact_urls(text: str) -> str:
    """Mask the password in any connection URL inside ``text``."""
    return _URL_CREDENTIALS.sub(r"\g<scheme>\g<user>:" + REDACTED + "@", text)


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SENSITIVE_FRAGMENTS)


def redact_value(key: str, value: Any) -> Any:
    """Redact a single structured field."""
    if _is_sensitive(key):
        return REDACTED
    if isinstance(value, str):
        return redact_urls(value)
    if isinstance(value, dict):
        return {k: redact_value(str(k), v) for k, v in value.items()}
    return value


class JsonFormatter(logging.Formatter):
    """Render a log record as a single JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": dt.datetime.fromtimestamp(record.created, tz=dt.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_urls(record.getMessage()),
        }

        correlation_id = get_correlation_id()
        if correlation_id is not None:
            payload["correlation_id"] = correlation_id

        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            payload[key] = redact_value(key, value)

        if record.exc_info:
            payload["exception"] = redact_urls(self.formatException(record.exc_info))

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON handler on the root logger.

    Idempotent: calling it again replaces the handler rather than stacking
    another one, so building several app instances in tests does not produce
    duplicate output.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn installs its own handlers; route them through ours instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
