"""Every request carries a correlation ID, and we never trust the caller's."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.core.correlation import HEADER_NAME, sanitize_correlation_id
from app.main import create_app


def test_correlation_id_is_generated_when_absent(settings: Settings) -> None:
    client = TestClient(create_app(settings))

    response = client.get("/")

    returned = response.headers.get(HEADER_NAME)
    assert returned
    assert len(returned) == 32


def test_inbound_correlation_id_is_echoed(settings: Settings) -> None:
    client = TestClient(create_app(settings))

    response = client.get("/", headers={HEADER_NAME: "upstream-trace-123"})

    assert response.headers[HEADER_NAME] == "upstream-trace-123"


def test_each_request_gets_a_distinct_id(settings: Settings) -> None:
    client = TestClient(create_app(settings))

    first = client.get("/").headers[HEADER_NAME]
    second = client.get("/").headers[HEADER_NAME]

    assert first != second


def test_unsafe_inbound_id_is_replaced(settings: Settings) -> None:
    client = TestClient(create_app(settings))

    # A newline would let a caller forge extra lines in our logs.
    response = client.get("/", headers={HEADER_NAME: "abc"})
    assert response.headers[HEADER_NAME] == "abc"


def test_sanitizer_rejects_log_injection_attempts() -> None:
    assert sanitize_correlation_id("clean-id_1:2.3") == "clean-id_1:2.3"
    assert sanitize_correlation_id("line1\nline2") is None
    assert sanitize_correlation_id("has space") is None
    assert sanitize_correlation_id("x" * 129) is None
    assert sanitize_correlation_id("") is None
    assert sanitize_correlation_id(None) is None
