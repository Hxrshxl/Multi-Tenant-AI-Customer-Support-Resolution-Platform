"""Logs are structured, correlated, and free of credentials."""

from __future__ import annotations

import json
import logging

from app.core.correlation import reset_correlation_id, set_correlation_id
from app.core.logging import REDACTED, JsonFormatter, redact_urls


def _record(message: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_record_is_valid_json_with_expected_fields() -> None:
    reset_correlation_id()
    payload = json.loads(JsonFormatter().format(_record("something happened")))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["message"] == "something happened"
    assert payload["timestamp"].endswith("+00:00")


def test_correlation_id_is_attached_when_set() -> None:
    set_correlation_id("trace-abc")
    try:
        payload = json.loads(JsonFormatter().format(_record("hello")))
        assert payload["correlation_id"] == "trace-abc"
    finally:
        reset_correlation_id()


def test_extra_fields_are_included() -> None:
    reset_correlation_id()
    payload = json.loads(
        JsonFormatter().format(_record("request completed", http_status=200, duration_ms=12.5))
    )

    assert payload["http_status"] == 200
    assert payload["duration_ms"] == 12.5


def test_sensitive_extra_fields_are_redacted() -> None:
    reset_correlation_id()
    payload = json.loads(
        JsonFormatter().format(
            _record(
                "authenticating",
                password="hunter2",
                api_key="sk-live-abc123",
                authorization="Bearer abc",
                user_id="u-1",
            )
        )
    )

    assert payload["password"] == REDACTED
    assert payload["api_key"] == REDACTED
    assert payload["authorization"] == REDACTED
    # Non-sensitive fields survive untouched.
    assert payload["user_id"] == "u-1"


def test_connection_url_credentials_are_masked_in_messages() -> None:
    reset_correlation_id()
    message = "could not connect to postgresql://support:sup3rsecret@db:5432/support"
    payload = json.loads(JsonFormatter().format(_record(message)))

    assert "sup3rsecret" not in payload["message"]
    assert REDACTED in payload["message"]
    # The non-secret part stays, so the line is still useful for debugging.
    assert "db:5432/support" in payload["message"]


def test_redact_urls_handles_several_schemes() -> None:
    assert "sup3rsecret" not in redact_urls("postgresql://u:sup3rsecret@h/db")
    assert "p4ss" not in redact_urls("redis://default:p4ss@cache:6379/0")
    assert redact_urls("no credentials here") == "no credentials here"


def test_exception_text_is_redacted() -> None:
    reset_correlation_id()
    try:
        raise RuntimeError("failed for postgresql://u:topsecret@h/db")
    except RuntimeError:
        import sys

        record = _record("boom")
        record.exc_info = sys.exc_info()

    payload = json.loads(JsonFormatter().format(record))

    assert "topsecret" not in payload["exception"]
