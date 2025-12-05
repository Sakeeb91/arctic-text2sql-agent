"""
Shared API models for responses.
"""

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Standard error payload."""

    code: str = Field(..., description="Machine readable error code")
    message: str = Field(..., description="Human readable error message")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Optional contextual details"
    )
    request_id: str | None = Field(
        default=None, description="Request identifier for tracing"
    )


class ErrorResponse(BaseModel):
    """Envelope for error responses."""

    error: ErrorDetail
