"""Liveness and readiness endpoints.

These handlers contain no logic beyond translating a service result into a
status code and body.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.deps import get_health_service
from app.services.health import HealthService

router = APIRouter(tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["ok"]


class DependencyView(BaseModel):
    name: str
    healthy: bool
    detail: str | None = None


class ReadinessResponse(BaseModel):
    ready: bool
    dependencies: list[DependencyView]


@router.get("/health", response_model=LivenessResponse, summary="Liveness probe")
async def health() -> LivenessResponse:
    """Report that the process is running.

    Deliberately checks nothing else: a dependency outage must not cause the
    orchestrator to restart an otherwise healthy container.
    """
    return LivenessResponse(status="ok")


@router.get(
    "/ready",
    summary="Readiness probe",
    responses={503: {"description": "One or more dependencies are unavailable"}},
)
async def ready(service: Annotated[HealthService, Depends(get_health_service)]) -> JSONResponse:
    """Report whether every dependency needed to serve traffic is reachable."""
    report = await service.readiness()
    body = ReadinessResponse(
        ready=report.ready,
        dependencies=[
            DependencyView(name=dep.name, healthy=dep.healthy, detail=dep.detail)
            for dep in report.dependencies
        ],
    )
    return JSONResponse(status_code=200 if report.ready else 503, content=body.model_dump())
