"""Domain errors and the single error envelope.

Every failure leaving this service looks the same::

    {"error": {"code": "not_found", "message": "...", "requestId": "..."}}

Clients branch on ``code``; humans read ``message``; ``requestId`` ties the
response to the server-side log line. Internal detail — stack traces, driver
messages, SQL — never crosses the boundary.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.correlation import HEADER_NAME, get_correlation_id

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for failures this service raises deliberately."""

    status_code: int = 500
    code: str = "internal_error"
    default_message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None, *, details: Any | None = None) -> None:
        self.message = message or self.default_message
        self.details = details
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    default_message = "The requested resource does not exist."


class ValidationFailedError(AppError):
    status_code = 422
    code = "validation_error"
    default_message = "The request body or parameters are invalid."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    default_message = "The request conflicts with the current state."


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
    default_message = "Authentication is required."


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    default_message = "You do not have access to this resource."


class DependencyUnavailableError(AppError):
    status_code = 503
    code = "dependency_unavailable"
    default_message = "A required dependency is unavailable."


def build_envelope(
    code: str, message: str, *, details: Any | None = None
) -> dict[str, dict[str, Any]]:
    """Shape a single error response body."""
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "requestId": get_correlation_id(),
    }
    if details is not None:
        error["details"] = details
    return {"error": error}


def error_response(
    status_code: int, code: str, message: str, *, details: Any | None = None
) -> JSONResponse:
    """Build an error response, stamped with the correlation ID.

    The header is set here as well as in the middleware because the catch-all
    handler runs inside Starlette's ``ServerErrorMiddleware``, which sits
    *outside* our middleware and writes the response itself — so on exactly the
    500s you most need to trace, the middleware never sees the response.
    """
    correlation_id = get_correlation_id()
    return JSONResponse(
        status_code=status_code,
        content=build_envelope(code, message, details=details),
        headers={HEADER_NAME: correlation_id} if correlation_id else None,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Install handlers so no failure path escapes the envelope."""

    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        # Deliberate, known failures: log at warning, no stack trace needed.
        logger.warning(
            "request failed",
            extra={"error_code": exc.code, "http_status": exc.status_code},
        )
        return error_response(exc.status_code, exc.code, exc.message, details=exc.details)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Field-level detail is safe to return: it describes the caller's own
        # input, not our internals.
        details = [
            {"field": ".".join(str(part) for part in error["loc"]), "problem": error["msg"]}
            for error in exc.errors()
        ]
        return error_response(
            422,
            ValidationFailedError.code,
            ValidationFailedError.default_message,
            details=details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            400: "bad_request",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            429: "rate_limited",
        }.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Request could not be completed."
        return error_response(exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # The trace is recorded server-side and correlated; the client is told
        # nothing beyond the request ID to quote when reporting it.
        logger.exception("unhandled exception", extra={"error_type": type(exc).__name__})
        return error_response(500, AppError.code, AppError.default_message)
