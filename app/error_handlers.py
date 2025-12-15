"""
Global exception handlers for FastAPI.

This module provides centralized exception handling that automatically
converts Text2SQLException hierarchy into proper HTTP responses with
consistent error formatting.
"""

from datetime import datetime
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exceptions import (
    AuthenticationException,
    CircuitBreakerOpenException,
    RateLimitExceededException,
    Text2SQLException,
)
from app.logging_config import get_logger

logger = get_logger(__name__)


# =============================================================================
# Error Response Models
# =============================================================================


class ErrorDetail(BaseModel):
    """Detailed error information."""

    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error message")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Additional error details"
    )


class ErrorResponse(BaseModel):
    """Standard error response format for all API errors."""

    error: ErrorDetail = Field(..., description="Error details")
    request_id: str | None = Field(None, description="Request ID for tracking")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="Error timestamp"
    )
    path: str | None = Field(None, description="Request path that caused the error")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Request validation failed",
                        "details": {"field": "query", "issue": "too short"},
                    },
                    "request_id": "req-123-abc",
                    "timestamp": "2025-01-15T10:30:00Z",
                    "path": "/api/v1/query",
                }
            ]
        }
    }


class ValidationErrorDetail(BaseModel):
    """Details for validation errors."""

    loc: list[str | int] = Field(..., description="Location of the error")
    msg: str = Field(..., description="Error message")
    type: str = Field(..., description="Error type")


class ValidationErrorResponse(BaseModel):
    """Response format for validation errors."""

    error: ErrorDetail = Field(..., description="Error details")
    validation_errors: list[ValidationErrorDetail] = Field(
        ..., description="List of validation errors"
    )
    request_id: str | None = Field(None, description="Request ID for tracking")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="Error timestamp"
    )


# =============================================================================
# Exception Handlers
# =============================================================================


def _get_request_id(request: Request) -> str | None:
    """Extract request ID from request state if available."""
    return getattr(request.state, "request_id", None)


async def text2sql_exception_handler(
    request: Request, exc: Text2SQLException
) -> JSONResponse:
    """
    Handle all Text2SQLException subclasses.

    Automatically maps exception status_code and error_code to response.
    """
    request_id = _get_request_id(request)

    logger.warning(
        "text2sql_exception",
        error_code=exc.error_code,
        status_code=exc.status_code,
        message=exc.message,
        request_id=request_id,
        path=str(request.url.path),
    )

    error_response = ErrorResponse(
        error=ErrorDetail(
            code=exc.error_code,
            message=exc.message,
            details=exc.details,
        ),
        request_id=request_id,
        path=str(request.url.path),
    )

    # Add Retry-After header for certain exceptions
    headers: dict[str, str] = {}
    if isinstance(exc, CircuitBreakerOpenException):
        retry_after = exc.details.get("retry_after_seconds")
        if retry_after:
            headers["Retry-After"] = str(retry_after)
    elif isinstance(exc, RateLimitExceededException):
        retry_after = exc.details.get("retry_after")
        if retry_after:
            headers["Retry-After"] = str(retry_after)

    # Add WWW-Authenticate for auth failures
    if isinstance(exc, AuthenticationException):
        headers["WWW-Authenticate"] = "Bearer"

    return JSONResponse(
        status_code=exc.status_code,
        content=error_response.model_dump(mode="json"),
        headers=headers if headers else None,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Handle Pydantic validation errors.

    Converts FastAPI validation errors into our standard format.
    """
    request_id = _get_request_id(request)

    validation_errors = [
        ValidationErrorDetail(
            loc=list(error["loc"]),
            msg=error["msg"],
            type=error["type"],
        )
        for error in exc.errors()
    ]

    logger.warning(
        "validation_error",
        error_count=len(validation_errors),
        request_id=request_id,
        path=str(request.url.path),
    )

    response = ValidationErrorResponse(
        error=ErrorDetail(
            code="VALIDATION_ERROR",
            message="Request validation failed",
            details={"error_count": len(validation_errors)},
        ),
        validation_errors=validation_errors,
        request_id=request_id,
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=response.model_dump(mode="json"),
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """
    Handle generic HTTP exceptions.

    Wraps standard HTTP exceptions in our error format.
    """
    request_id = _get_request_id(request)

    # Map status codes to error codes
    error_code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        408: "REQUEST_TIMEOUT",
        409: "CONFLICT",
        410: "GONE",
        422: "UNPROCESSABLE_ENTITY",
        429: "TOO_MANY_REQUESTS",
        500: "INTERNAL_SERVER_ERROR",
        502: "BAD_GATEWAY",
        503: "SERVICE_UNAVAILABLE",
        504: "GATEWAY_TIMEOUT",
    }

    error_code = error_code_map.get(exc.status_code, "HTTP_ERROR")

    logger.warning(
        "http_exception",
        status_code=exc.status_code,
        detail=exc.detail,
        request_id=request_id,
        path=str(request.url.path),
    )

    error_response = ErrorResponse(
        error=ErrorDetail(
            code=error_code,
            message=str(exc.detail) if exc.detail else "An error occurred",
            details={},
        ),
        request_id=request_id,
        path=str(request.url.path),
    )

    headers: dict[str, str] = {}
    if exc.headers:
        headers.update(exc.headers)

    return JSONResponse(
        status_code=exc.status_code,
        content=error_response.model_dump(mode="json"),
        headers=headers if headers else None,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle any unhandled exceptions.

    Catches all exceptions not handled by other handlers and returns
    a generic 500 error while logging the full exception.
    """
    request_id = _get_request_id(request)

    logger.error(
        "unhandled_exception",
        error_type=type(exc).__name__,
        error_message=str(exc),
        request_id=request_id,
        path=str(request.url.path),
        exc_info=True,
    )

    error_response = ErrorResponse(
        error=ErrorDetail(
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected error occurred",
            details={},  # Don't expose internal details
        ),
        request_id=request_id,
        path=str(request.url.path),
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response.model_dump(mode="json"),
    )


# =============================================================================
# Handler Registration
# =============================================================================


def setup_exception_handlers(app: FastAPI) -> None:
    """
    Register all exception handlers with the FastAPI application.

    Args:
        app: FastAPI application instance
    """
    # Register Text2SQLException handler (catches all subclasses)
    app.add_exception_handler(Text2SQLException, text2sql_exception_handler)  # type: ignore

    # Register validation error handler
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore

    # Register HTTP exception handler
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore

    # Register catch-all handler for unhandled exceptions
    app.add_exception_handler(Exception, unhandled_exception_handler)

    logger.info("exception_handlers_registered")
