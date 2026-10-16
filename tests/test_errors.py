"""Nothing escapes the envelope, and nothing internal escapes at all."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.correlation import HEADER_NAME
from app.core.errors import NotFoundError
from app.main import create_app

LEAKY_MESSAGE = "connection to postgresql://support:sup3rsecret@db:5432/support failed"


def _app_with_failing_routes(settings: Settings) -> FastAPI:
    app = create_app(settings)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError(LEAKY_MESSAGE)

    @app.get("/missing")
    async def missing() -> None:
        raise NotFoundError("No ticket with that id.")

    return app


def test_unhandled_exception_returns_envelope_without_internals(settings: Settings) -> None:
    client = TestClient(_app_with_failing_routes(settings), raise_server_exceptions=False)

    response = client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["requestId"] == response.headers[HEADER_NAME]

    raw = response.text
    assert "RuntimeError" not in raw
    assert "Traceback" not in raw
    assert "sup3rsecret" not in raw
    assert "postgresql://" not in raw


def test_known_error_keeps_its_code_and_message(settings: Settings) -> None:
    client = TestClient(_app_with_failing_routes(settings), raise_server_exceptions=False)

    response = client.get("/missing")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"] == "No ticket with that id."
    assert body["error"]["requestId"]


def test_unknown_route_uses_the_same_envelope(settings: Settings) -> None:
    client = TestClient(create_app(settings))

    response = client.get("/no-such-route")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_validation_failure_reports_the_offending_field(settings: Settings) -> None:
    app = create_app(settings)

    @app.get("/items")
    async def items(limit: int) -> dict[str, int]:
        return {"limit": limit}

    client = TestClient(app)
    response = client.get("/items", params={"limit": "not-a-number"})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert any("limit" in detail["field"] for detail in body["error"]["details"])
