"""Liveness stays up; readiness tells the truth about dependencies."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.health import DependencyStatus, ReadinessReport


class _StubHealthService:
    """Stands in for the real service so the healthy path is testable."""

    def __init__(self, report: ReadinessReport) -> None:
        self._report = report

    async def readiness(self) -> ReadinessReport:
        return self._report


def test_liveness_is_independent_of_dependencies(settings: Settings) -> None:
    # The configured stores are unreachable, yet liveness must still pass —
    # otherwise a database blip gets healthy containers restarted.
    client = TestClient(create_app(settings))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_503_when_dependencies_are_down(settings: Settings) -> None:
    client = TestClient(create_app(settings))

    response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False

    by_name = {dep["name"]: dep for dep in body["dependencies"]}
    assert by_name["postgres"]["healthy"] is False
    assert by_name["redis"]["healthy"] is False


def test_readiness_failure_does_not_leak_connection_details(settings: Settings) -> None:
    client = TestClient(create_app(settings))

    raw = client.get("/ready").text

    # Driver errors routinely contain the DSN. None of it may reach the client.
    assert "sup3rsecret" not in raw
    assert "postgresql://" not in raw
    assert "59999" not in raw


def test_readiness_reports_200_when_everything_is_up(settings: Settings) -> None:
    app = create_app(settings)
    healthy = ReadinessReport(
        ready=True,
        dependencies=(
            DependencyStatus(name="postgres", healthy=True),
            DependencyStatus(name="redis", healthy=True),
        ),
    )
    app.state.health_service = _StubHealthService(healthy)

    response = TestClient(app).get("/ready")

    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert body["ready"] is True
    assert len(body["dependencies"]) == 2


def test_partial_outage_is_not_ready(settings: Settings) -> None:
    app = create_app(settings)
    degraded = ReadinessReport(
        ready=False,
        dependencies=(
            DependencyStatus(name="postgres", healthy=True),
            DependencyStatus(name="redis", healthy=False, detail="unreachable"),
        ),
    )
    app.state.health_service = _StubHealthService(degraded)

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert response.json()["ready"] is False
