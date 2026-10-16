"""Run the API server.

    python -m app

Preferred over invoking uvicorn directly, because the event loop policy must
be selected before the loop is created (ADR-005). Running
``uvicorn app.main:create_app --factory`` works on Linux but reproduces the
Proactor incompatibility on Windows.
"""

from __future__ import annotations

from app.core.runtime import configure_event_loop_policy


def main() -> None:
    configure_event_loop_policy()

    import uvicorn

    from app.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        log_level=settings.log_level.lower(),
        reload=settings.app_env == "local",
    )


if __name__ == "__main__":
    main()
