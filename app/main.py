"""FastAPI application entry point.

Deliberately minimal. This exists so the scaffold is provably runnable end to
end (KAN-13). The layered structure, correlation-ID logging, standard error
envelope and real health/readiness probes arrive with KAN-14.

Exposed as a factory rather than a module-level ``app`` so that importing this
module has no side effects: configuration is read when the app is built, not
when the module is imported. Run it with uvicorn's ``--factory`` flag.
"""

from __future__ import annotations

from fastapi import FastAPI

from app import __version__
from app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    Takes optional settings so tests can supply their own without touching the
    process environment.
    """
    resolved = settings or get_settings()

    app = FastAPI(
        title="Support Resolution Platform",
        version=__version__,
        docs_url="/docs" if not resolved.is_production else None,
    )

    @app.get("/")
    def root() -> dict[str, str]:
        return {
            "service": "support-resolution-platform",
            "version": __version__,
            "env": resolved.app_env,
        }

    return app
