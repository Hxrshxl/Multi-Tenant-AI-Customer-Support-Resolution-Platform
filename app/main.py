"""FastAPI application entry point.

Exposed as a factory rather than a module-level ``app`` so importing this
module has no side effects: configuration is read when the app is built, not
when the module is imported. Run it with ``python -m app``, which also selects
a database-compatible event loop (ADR-005).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.routes import health as health_routes
from app.api.routes import tickets as ticket_routes
from app.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import CorrelationIdMiddleware
from app.db.session import create_engine, create_session_factory
from app.services.health import HealthService
from app.services.intake import IntakeService
from app.services.resolution import PlaceholderResolver


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    Takes optional settings so tests can supply their own without touching the
    process environment.
    """
    resolved = settings or get_settings()
    configure_logging(resolved.log_level)

    engine = create_engine(resolved)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        # Release pooled connections on shutdown rather than leaving the
        # database to time them out.
        await engine.dispose()

    app = FastAPI(
        title="Support Resolution Platform",
        version=__version__,
        docs_url="/docs" if not resolved.is_production else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    # Collaborators built once, here. Handlers resolve them via dependencies.
    app.state.settings = resolved
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.health_service = HealthService(resolved)
    # The seam: E5 replaces PlaceholderResolver with the LangGraph workflow
    # and nothing else on this line changes.
    app.state.intake_service = IntakeService(resolver=PlaceholderResolver())

    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(health_routes.router)
    app.include_router(ticket_routes.router)

    @app.get("/", tags=["meta"])
    async def root() -> dict[str, str]:
        return {
            "service": "support-resolution-platform",
            "version": __version__,
            "env": resolved.app_env,
        }

    return app
