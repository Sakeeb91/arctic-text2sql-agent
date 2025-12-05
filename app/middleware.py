"""
FastAPI middleware configuration.

This module provides middleware for:
- Request logging and timing
- Request ID generation
- CORS handling
- Error handling
- Security headers
"""

import time
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api_models import ErrorDetail, ErrorResponse
from app.exceptions import Text2SQLException
from app.logging_config import get_logger, request_id_context

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for logging HTTP requests and responses.

    Logs request start, completion, and timing information.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Any]
    ) -> Response:
        """Process request with logging."""
        # Generate request ID
        request_id = str(uuid.uuid4())
        request_id_context.set(request_id)

        # Log request start
        logger.info(
            "request_started",
            method=request.method,
            path=request.url.path,
            query_params=str(request.query_params),
            client_host=request.client.host if request.client else None,
        )

        # Process request and measure time
        start_time = time.perf_counter()

        try:
            response = await call_next(request)
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Log request completion
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
            )

            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id

            return response

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000

            logger.error(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 2),
                error=str(e),
                error_type=type(e).__name__,
            )
            raise
        finally:
            # Clear request ID context
            request_id_context.set(None)


async def exception_handler(request: Request, exc: Text2SQLException) -> JSONResponse:
    """
    Global exception handler for Text2SQLException.

    Converts exceptions to JSON responses with appropriate status codes.
    """
    request_id = request_id_context.get()
    logger.error(
        "exception_raised",
        error_code=exc.error_code,
        message=exc.message,
        details=exc.details,
        path=request.url.path,
    )

    payload = ErrorResponse(
        error=ErrorDetail(
            code=exc.error_code,
            message=exc.message,
            details=exc.details,
            request_id=request_id,
        )
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=payload.model_dump(),
        headers={"X-Request-ID": request_id or "unknown"},
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Fallback handler for unhandled exceptions.

    Logs the full exception and returns a generic error response.
    """
    logger.exception(
        "unhandled_exception",
        error=str(exc),
        error_type=type(exc).__name__,
        path=request.url.path,
    )

    request_id = request_id_context.get()
    payload = ErrorResponse(
        error=ErrorDetail(
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected error occurred",
            details={},
            request_id=request_id,
        )
    )

    return JSONResponse(
        status_code=500,
        content=payload.model_dump(),
        headers={"X-Request-ID": request_id or "unknown"},
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Normalize HTTPException responses to the standard error envelope."""
    request_id = request_id_context.get()
    detail_payload: dict[str, Any]

    if isinstance(exc.detail, dict):
        detail_payload = exc.detail
    else:
        detail_payload = {"message": str(exc.detail)}

    message = (
        detail_payload.get("message")
        or detail_payload.get("error")
        or str(exc.detail)
    )

    payload = ErrorResponse(
        error=ErrorDetail(
            code=detail_payload.get("code", "HTTP_ERROR"),
            message=message,
            details={k: v for k, v in detail_payload.items() if k != "message"},
            request_id=request_id,
        )
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=payload.model_dump(),
        headers={"X-Request-ID": request_id or "unknown"},
    )


def setup_middleware(app: FastAPI, cors_origins: list[str] | None = None) -> None:
    """
    Configure all middleware for the FastAPI application.

    Args:
        app: FastAPI application instance
        cors_origins: List of allowed CORS origins

    Usage:
        from fastapi import FastAPI
        from app.middleware import setup_middleware

        app = FastAPI()
        setup_middleware(app, cors_origins=["http://localhost:3000"])
    """
    # Import security headers middleware here to avoid circular imports
    from app.security.headers import SecurityHeadersMiddleware

    # Security headers middleware (first in chain)
    app.add_middleware(SecurityHeadersMiddleware)

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # Request logging middleware
    app.add_middleware(RequestLoggingMiddleware)

    # Exception handlers
    app.add_exception_handler(Text2SQLException, exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    logger.info(
        "middleware_configured",
        cors_origins=cors_origins,
    )

