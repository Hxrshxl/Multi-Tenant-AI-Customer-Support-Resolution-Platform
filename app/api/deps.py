"""Shared FastAPI dependencies.

Services are built once when the app is created and resolved from
``app.state``, so handlers never construct their own collaborators and tests
can swap in a double.
"""

from __future__ import annotations

from fastapi import Request

from app.config import Settings
from app.services.health import HealthService


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_health_service(request: Request) -> HealthService:
    service: HealthService = request.app.state.health_service
    return service
