"""
Custom exception classes for Arctic Text2SQL Agent.

This module provides a comprehensive exception hierarchy for handling
different error scenarios with appropriate HTTP status codes and messages.
"""

from typing import Any


class Text2SQLException(Exception):
    """
    Base exception for all Arctic Text2SQL errors.

    Attributes:
        message: Human-readable error message
        error_code: Machine-readable error code
        status_code: HTTP status code for API responses
        details: Additional error details
    """

    def __init__(
        self,
        message: str,
        error_code: str = "TEXT2SQL_ERROR",
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the exception."""
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for API responses."""
        return {
            "error": {
                "code": self.error_code,
                "message": self.message,
                "details": self.details,
            }
        }


# =============================================================================
# Database Exceptions
# =============================================================================


class DatabaseException(Text2SQLException):
    """Base exception for database-related errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "DATABASE_ERROR",
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, error_code, status_code, details)


class DatabaseConnectionException(DatabaseException):
    """Database connection failed."""

    def __init__(
        self,
        message: str = "Failed to connect to database",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="DATABASE_CONNECTION_ERROR",
            status_code=503,
            details=details,
        )


class SchemaNotFoundException(DatabaseException):
    """Database schema not found."""

    def __init__(
        self,
        database_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=f"Schema not found for database: {database_id}",
            error_code="SCHEMA_NOT_FOUND",
            status_code=404,
            details=details or {"database_id": database_id},
        )


class TableNotFoundException(DatabaseException):
    """Database table not found."""

    def __init__(
        self,
        table_name: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=f"Table not found: {table_name}",
            error_code="TABLE_NOT_FOUND",
            status_code=404,
            details=details or {"table_name": table_name},
        )


class QueryExecutionException(DatabaseException):
    """SQL query execution failed."""

    def __init__(
        self,
        message: str = "Query execution failed",
        sql: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        error_details = details or {}
        if sql:
            # Don't include potentially sensitive SQL in details
            error_details["sql_preview"] = sql[:100] + "..." if len(sql) > 100 else sql
        super().__init__(
            message=message,
            error_code="QUERY_EXECUTION_ERROR",
            status_code=400,
            details=error_details,
        )


class QueryTimeoutException(DatabaseException):
    """SQL query timed out."""

    def __init__(
        self,
        timeout_seconds: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=f"Query timed out after {timeout_seconds} seconds",
            error_code="QUERY_TIMEOUT",
            status_code=408,
            details=details or {"timeout_seconds": timeout_seconds},
        )


# =============================================================================
# Model Exceptions
# =============================================================================


class ModelException(Text2SQLException):
    """Base exception for model-related errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "MODEL_ERROR",
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, error_code, status_code, details)


class ModelLoadException(ModelException):
    """Model loading failed."""

    def __init__(
        self,
        model_name: str,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        message = f"Failed to load model: {model_name}"
        if reason:
            message += f" - {reason}"
        super().__init__(
            message=message,
            error_code="MODEL_LOAD_ERROR",
            status_code=503,
            details=details or {"model_name": model_name},
        )


class ModelInferenceException(ModelException):
    """Model inference failed."""

    def __init__(
        self,
        message: str = "Model inference failed",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="MODEL_INFERENCE_ERROR",
            status_code=500,
            details=details,
        )


class TokenLimitExceededException(ModelException):
    """Input exceeded model's token limit."""

    def __init__(
        self,
        max_tokens: int,
        actual_tokens: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=f"Input exceeds token limit: {actual_tokens} > {max_tokens}",
            error_code="TOKEN_LIMIT_EXCEEDED",
            status_code=400,
            details=details
            or {"max_tokens": max_tokens, "actual_tokens": actual_tokens},
        )


# =============================================================================
# Query/SQL Exceptions
# =============================================================================


class QueryException(Text2SQLException):
    """Base exception for query-related errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "QUERY_ERROR",
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, error_code, status_code, details)


class InvalidQueryException(QueryException):
    """Generated SQL is invalid."""

    def __init__(
        self,
        message: str = "Generated SQL query is invalid",
        sql: str | None = None,
        validation_errors: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        error_details = details or {}
        if validation_errors:
            error_details["validation_errors"] = validation_errors
        if sql:
            # Include SQL preview in details (truncated for security)
            error_details["sql_preview"] = sql[:100] + "..." if len(sql) > 100 else sql
        super().__init__(
            message=message,
            error_code="INVALID_SQL_QUERY",
            status_code=400,
            details=error_details,
        )


class UnsupportedQueryTypeException(QueryException):
    """Query type is not supported."""

    def __init__(
        self,
        query_type: str,
        supported_types: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        error_details = details or {}
        error_details["query_type"] = query_type
        if supported_types:
            error_details["supported_types"] = supported_types
        super().__init__(
            message=f"Unsupported query type: {query_type}",
            error_code="UNSUPPORTED_QUERY_TYPE",
            status_code=400,
            details=error_details,
        )


class LowConfidenceException(QueryException):
    """Generated query has low confidence score."""

    def __init__(
        self,
        confidence: float,
        threshold: float,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=f"Query confidence ({confidence:.2f}) below threshold ({threshold:.2f})",
            error_code="LOW_CONFIDENCE",
            status_code=422,
            details=details or {"confidence": confidence, "threshold": threshold},
        )


# =============================================================================
# Agent Exceptions
# =============================================================================


class AgentException(Text2SQLException):
    """Base exception for agent-related errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "AGENT_ERROR",
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, error_code, status_code, details)


class AgentMaxStepsExceededException(AgentException):
    """Agent exceeded maximum reasoning steps."""

    def __init__(
        self,
        max_steps: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=f"Agent exceeded maximum steps ({max_steps})",
            error_code="AGENT_MAX_STEPS_EXCEEDED",
            status_code=408,
            details=details or {"max_steps": max_steps},
        )


class AgentValidationException(AgentException):
    """Agent validation failed."""

    def __init__(
        self,
        message: str = "Agent output validation failed",
        validation_errors: list[str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        error_details = details or {}
        if validation_errors:
            error_details["validation_errors"] = validation_errors
        super().__init__(
            message=message,
            error_code="AGENT_VALIDATION_ERROR",
            status_code=422,
            details=error_details,
        )


class AgentExecutionException(AgentException):
    """Agent execution failed during ReAct loop."""

    def __init__(
        self,
        message: str = "Agent execution failed",
        step_number: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        error_details = details or {}
        if step_number is not None:
            error_details["step_number"] = step_number
        super().__init__(
            message=message,
            error_code="AGENT_EXECUTION_ERROR",
            status_code=500,
            details=error_details,
        )


class AgentToolException(AgentException):
    """Agent tool execution failed."""

    def __init__(
        self,
        tool_name: str,
        message: str = "Tool execution failed",
        details: dict[str, Any] | None = None,
    ) -> None:
        error_details = details or {}
        error_details["tool_name"] = tool_name
        super().__init__(
            message=f"Tool '{tool_name}' failed: {message}",
            error_code="AGENT_TOOL_ERROR",
            status_code=500,
            details=error_details,
        )


class AgentRetryException(AgentException):
    """Agent retry operation failed."""

    def __init__(
        self,
        query_id: str,
        message: str = "Retry operation failed",
        details: dict[str, Any] | None = None,
    ) -> None:
        error_details = details or {}
        error_details["query_id"] = query_id
        super().__init__(
            message=message,
            error_code="AGENT_RETRY_ERROR",
            status_code=400,
            details=error_details,
        )


class QueryNotFoundException(AgentException):
    """Query not found in history for retry."""

    def __init__(
        self,
        query_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=f"Query not found in history: {query_id}",
            error_code="QUERY_NOT_FOUND",
            status_code=404,
            details=details or {"query_id": query_id},
        )


# =============================================================================
# API/Authentication Exceptions
# =============================================================================


class APIException(Text2SQLException):
    """Base exception for API-related errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "API_ERROR",
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, error_code, status_code, details)


class AuthenticationException(APIException):
    """Authentication failed."""

    def __init__(
        self,
        message: str = "Authentication failed",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="AUTHENTICATION_ERROR",
            status_code=401,
            details=details,
        )


class AuthorizationException(APIException):
    """Authorization failed."""

    def __init__(
        self,
        message: str = "Access denied",
        resource: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        error_details = details or {}
        if resource:
            error_details["resource"] = resource
        super().__init__(
            message=message,
            error_code="AUTHORIZATION_ERROR",
            status_code=403,
            details=error_details,
        )


class RateLimitExceededException(APIException):
    """Rate limit exceeded."""

    def __init__(
        self,
        limit: int,
        window_seconds: int,
        retry_after: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        error_details = details or {}
        error_details["limit"] = limit
        error_details["window_seconds"] = window_seconds
        if retry_after:
            error_details["retry_after"] = retry_after
        super().__init__(
            message=f"Rate limit exceeded: {limit} requests per {window_seconds}s",
            error_code="RATE_LIMIT_EXCEEDED",
            status_code=429,
            details=error_details,
        )


class ValidationException(APIException):
    """Request validation failed."""

    def __init__(
        self,
        message: str = "Request validation failed",
        validation_errors: list[dict[str, Any]] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        error_details = details or {}
        if validation_errors:
            error_details["validation_errors"] = validation_errors
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            status_code=422,
            details=error_details,
        )
