"""FastAPI application entry point.

Exposed as a factory rather than a module-level ``app`` so importing this
module has no side effects: configuration is read when the app is built, not
when the module is imported. Run it with uvicorn's ``--factory`` flag.
"""

from __future__ import annotations

from fastapi import FastAPI

from app import __version__
from app.api.routes import health as health_routes
from app.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import CorrelationIdMiddleware
from app.services.health import HealthService


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    Takes optional settings so tests can supply their own without touching the
    process environment.
    """
    resolved = settings or get_settings()
    configure_logging(resolved.log_level)

    app = FastAPI(
        title="Support Resolution Platform",
        version=__version__,
        docs_url="/docs" if not resolved.is_production else None,
        redoc_url=None,
    )

    # Collaborators are built once, here, and resolved by dependencies.
    # Handlers never construct their own.
    app.state.settings = resolved
    app.state.health_service = HealthService(resolved)

    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(health_routes.router)

    @app.get("/", tags=["meta"])
    async def root() -> dict[str, str]:
        return {
            "service": "support-resolution-platform",
            "version": __version__,
            "env": resolved.app_env,
        }

    return app
