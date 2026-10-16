"""ASGI middleware.

Written as raw ASGI rather than Starlette's ``BaseHTTPMiddleware`` on purpose.
``BaseHTTPMiddleware`` runs the downstream app in a separate anyio task, so a
:class:`~contextvars.ContextVar` set around it does not reliably reach the
outermost error handler — which is exactly where the correlation ID matters
most, because that is the 500 someone will ask you to trace.
"""

from __future__ import annotations

import logging
import time

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.correlation import (
    HEADER_NAME,
    new_correlation_id,
    sanitize_correlation_id,
    set_correlation_id,
)

logger = logging.getLogger(__name__)


class CorrelationIdMiddleware:
    """Bind a correlation ID to every request, echo it back, and log the result.

    An upstream caller may supply an ID so one trace spans several hops. If it
    supplies nothing — or something unsafe for a log file — we mint our own.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        correlation_id = sanitize_correlation_id(headers.get(HEADER_NAME)) or new_correlation_id()
        set_correlation_id(correlation_id)
        scope.setdefault("state", {})["correlation_id"] = correlation_id

        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                # Set rather than append: error handlers also stamp this header
                # (they have to, see below), and appending would emit it twice.
                MutableHeaders(scope=message)[HEADER_NAME] = correlation_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            logger.info(
                "request completed",
                extra={
                    "http_method": scope.get("method"),
                    "http_path": scope.get("path"),
                    "http_status": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
