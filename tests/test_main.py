"""The scaffold must actually come up."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import __version__
from app.config import Settings
from app.main import create_app


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "database_url": "postgresql://support:support@localhost:5432/support",
        "redis_url": "redis://localhost:6379/0",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_root_reports_service_identity() -> None:
    client = TestClient(create_app(_settings()))

    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "service": "support-resolution-platform",
        "version": __version__,
        "env": "local",
    }


def test_docs_are_disabled_in_production() -> None:
    client = TestClient(create_app(_settings(app_env="production")))

    assert client.get("/docs").status_code == 404
