"""Shared FastAPI dependencies.

Collaborators are built once when the app is created and resolved from
``app.state``, so handlers never construct their own and tests can swap in a
double by assigning to state.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.session import session_scope
from app.services.health import HealthService

if TYPE_CHECKING:
    from app.services.intake import IntakeService


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_health_service(request: Request) -> HealthService:
    service: HealthService = request.app.state.health_service
    return service


def get_intake_service(request: Request) -> IntakeService:
    service: IntakeService = request.app.state.intake_service
    return service


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One database transaction per request.

    Committed when the handler returns, rolled back if it raises. That is what
    makes "a failure anywhere leaves no partial ticket" true rather than
    aspirational: the ticket, its messages and its resolution are written
    together or not at all.
    """
    async with session_scope(request.app.state.session_factory) as session:
        yield session
