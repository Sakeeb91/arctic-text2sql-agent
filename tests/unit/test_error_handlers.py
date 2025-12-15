"""
Unit tests for error handlers and error response models.
"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.error_handlers import (
    ErrorDetail,
    ErrorResponse,
    ValidationErrorDetail,
    ValidationErrorResponse,
    http_exception_handler,
    setup_exception_handlers,
    text2sql_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.exceptions import (
    AuthenticationException,
    CircuitBreakerOpenException,
    DatabaseConnectionException,
    ModelInferenceException,
    QueryNotFoundException,
    RateLimitExceededException,
    SchemaNotFoundException,
    Text2SQLException,
)

# =============================================================================
# Error Response Model Tests
# =============================================================================


class TestErrorDetail:
    """Tests for ErrorDetail model."""

    def test_basic_creation(self) -> None:
        """Test creating a basic error detail."""
        detail = ErrorDetail(
            code="TEST_ERROR",
            message="Test error message",
        )
        assert detail.code == "TEST_ERROR"
        assert detail.message == "Test error message"
        assert detail.details == {}

    def test_with_details(self) -> None:
        """Test creating error detail with additional details."""
        detail = ErrorDetail(
            code="TEST_ERROR",
            message="Test error message",
            details={"field": "value", "count": 42},
        )
        assert detail.details["field"] == "value"
        assert detail.details["count"] == 42


class TestErrorResponse:
    """Tests for ErrorResponse model."""

    def test_basic_creation(self) -> None:
        """Test creating a basic error response."""
        response = ErrorResponse(
            error=ErrorDetail(
                code="TEST_ERROR",
                message="Test error message",
            ),
        )
        assert response.error.code == "TEST_ERROR"
        assert response.request_id is None
        assert response.path is None
        assert isinstance(response.timestamp, datetime)

    def test_with_all_fields(self) -> None:
        """Test creating error response with all fields."""
        response = ErrorResponse(
            error=ErrorDetail(
                code="TEST_ERROR",
                message="Test error message",
                details={"key": "value"},
            ),
            request_id="req-123",
            path="/api/test",
        )
        assert response.request_id == "req-123"
        assert response.path == "/api/test"

    def test_serialization(self) -> None:
        """Test error response serialization to JSON."""
        response = ErrorResponse(
            error=ErrorDetail(
                code="TEST_ERROR",
                message="Test message",
            ),
            request_id="req-123",
        )
        data = response.model_dump(mode="json")
        assert data["error"]["code"] == "TEST_ERROR"
        assert data["request_id"] == "req-123"
        assert "timestamp" in data


class TestValidationErrorResponse:
    """Tests for ValidationErrorResponse model."""

    def test_creation_with_errors(self) -> None:
        """Test creating validation error response."""
        response = ValidationErrorResponse(
            error=ErrorDetail(
                code="VALIDATION_ERROR",
                message="Request validation failed",
            ),
            validation_errors=[
                ValidationErrorDetail(
                    loc=["body", "query"],
                    msg="field required",
                    type="value_error.missing",
                ),
            ],
        )
        assert len(response.validation_errors) == 1
        assert response.validation_errors[0].loc == ["body", "query"]


# =============================================================================
# Exception Handler Tests
# =============================================================================


@pytest.fixture
def mock_request() -> MagicMock:
    """Create a mock request object."""
    request = MagicMock()
    request.url.path = "/api/test"
    request.state.request_id = "req-test-123"
    return request


@pytest.fixture
def mock_request_no_id() -> MagicMock:
    """Create a mock request without request_id."""
    request = MagicMock()
    request.url.path = "/api/test"
    # Simulate missing request_id attribute
    del request.state.request_id
    return request


class TestText2SQLExceptionHandler:
    """Tests for text2sql_exception_handler."""

    @pytest.mark.asyncio
    async def test_handles_base_exception(self, mock_request: MagicMock) -> None:
        """Test handling base Text2SQLException."""
        exc = Text2SQLException(
            message="Test error",
            error_code="TEST_CODE",
            status_code=400,
        )
        response = await text2sql_exception_handler(mock_request, exc)
        assert response.status_code == 400
        data = response.body.decode()
        assert "TEST_CODE" in data
        assert "Test error" in data

    @pytest.mark.asyncio
    async def test_handles_database_exception(self, mock_request: MagicMock) -> None:
        """Test handling DatabaseConnectionException."""
        exc = DatabaseConnectionException(message="Connection failed")
        response = await text2sql_exception_handler(mock_request, exc)
        assert response.status_code == 503
        data = response.body.decode()
        assert "DATABASE_CONNECTION_ERROR" in data

    @pytest.mark.asyncio
    async def test_handles_model_inference_exception(
        self, mock_request: MagicMock
    ) -> None:
        """Test handling ModelInferenceException."""
        exc = ModelInferenceException(message="Inference failed")
        response = await text2sql_exception_handler(mock_request, exc)
        assert response.status_code == 500
        data = response.body.decode()
        assert "MODEL_INFERENCE_ERROR" in data

    @pytest.mark.asyncio
    async def test_handles_schema_not_found(self, mock_request: MagicMock) -> None:
        """Test handling SchemaNotFoundException."""
        exc = SchemaNotFoundException(database_id="test_db")
        response = await text2sql_exception_handler(mock_request, exc)
        assert response.status_code == 404
        data = response.body.decode()
        assert "SCHEMA_NOT_FOUND" in data
        assert "test_db" in data

    @pytest.mark.asyncio
    async def test_handles_query_not_found(self, mock_request: MagicMock) -> None:
        """Test handling QueryNotFoundException."""
        exc = QueryNotFoundException(query_id="query-123")
        response = await text2sql_exception_handler(mock_request, exc)
        assert response.status_code == 404
        data = response.body.decode()
        assert "QUERY_NOT_FOUND" in data

    @pytest.mark.asyncio
    async def test_handles_authentication_exception(
        self, mock_request: MagicMock
    ) -> None:
        """Test handling AuthenticationException adds WWW-Authenticate header."""
        exc = AuthenticationException(message="Invalid token")
        response = await text2sql_exception_handler(mock_request, exc)
        assert response.status_code == 401
        assert response.headers.get("WWW-Authenticate") == "Bearer"

    @pytest.mark.asyncio
    async def test_handles_circuit_breaker_exception(
        self, mock_request: MagicMock
    ) -> None:
        """Test handling CircuitBreakerOpenException adds Retry-After header."""
        exc = CircuitBreakerOpenException(retry_after_seconds=30)
        response = await text2sql_exception_handler(mock_request, exc)
        assert response.status_code == 503
        assert response.headers.get("Retry-After") == "30"

    @pytest.mark.asyncio
    async def test_handles_rate_limit_exception(self, mock_request: MagicMock) -> None:
        """Test handling RateLimitExceededException adds Retry-After header."""
        exc = RateLimitExceededException(limit=10, window_seconds=60, retry_after=45)
        response = await text2sql_exception_handler(mock_request, exc)
        assert response.status_code == 429
        assert response.headers.get("Retry-After") == "45"

    @pytest.mark.asyncio
    async def test_includes_request_id(self, mock_request: MagicMock) -> None:
        """Test that request_id is included in response."""
        exc = Text2SQLException(message="Test", error_code="TEST", status_code=400)
        response = await text2sql_exception_handler(mock_request, exc)
        data = response.body.decode()
        assert "req-test-123" in data

    @pytest.mark.asyncio
    async def test_handles_missing_request_id(
        self, mock_request_no_id: MagicMock
    ) -> None:
        """Test handling request without request_id attribute."""
        exc = Text2SQLException(message="Test", error_code="TEST", status_code=400)
        response = await text2sql_exception_handler(mock_request_no_id, exc)
        assert response.status_code == 400


class TestValidationExceptionHandler:
    """Tests for validation_exception_handler."""

    @pytest.mark.asyncio
    async def test_handles_validation_error(self, mock_request: MagicMock) -> None:
        """Test handling RequestValidationError."""
        errors = [
            {
                "loc": ("body", "query"),
                "msg": "field required",
                "type": "value_error.missing",
            }
        ]
        exc = RequestValidationError(errors=errors)
        response = await validation_exception_handler(mock_request, exc)
        assert response.status_code == 422
        data = response.body.decode()
        assert "VALIDATION_ERROR" in data
        assert "body" in data
        assert "query" in data

    @pytest.mark.asyncio
    async def test_handles_multiple_errors(self, mock_request: MagicMock) -> None:
        """Test handling multiple validation errors."""
        errors = [
            {
                "loc": ("body", "field1"),
                "msg": "field required",
                "type": "value_error.missing",
            },
            {
                "loc": ("body", "field2"),
                "msg": "invalid value",
                "type": "value_error.invalid",
            },
        ]
        exc = RequestValidationError(errors=errors)
        response = await validation_exception_handler(mock_request, exc)
        assert response.status_code == 422
        data = response.body.decode()
        assert "field1" in data
        assert "field2" in data


class TestHTTPExceptionHandler:
    """Tests for http_exception_handler."""

    @pytest.mark.asyncio
    async def test_handles_404(self, mock_request: MagicMock) -> None:
        """Test handling 404 HTTP exception."""
        exc = StarletteHTTPException(status_code=404, detail="Not found")
        response = await http_exception_handler(mock_request, exc)
        assert response.status_code == 404
        data = response.body.decode()
        assert "NOT_FOUND" in data

    @pytest.mark.asyncio
    async def test_handles_500(self, mock_request: MagicMock) -> None:
        """Test handling 500 HTTP exception."""
        exc = StarletteHTTPException(status_code=500, detail="Server error")
        response = await http_exception_handler(mock_request, exc)
        assert response.status_code == 500
        data = response.body.decode()
        assert "INTERNAL_SERVER_ERROR" in data

    @pytest.mark.asyncio
    async def test_handles_429(self, mock_request: MagicMock) -> None:
        """Test handling 429 HTTP exception."""
        exc = StarletteHTTPException(status_code=429, detail="Too many requests")
        response = await http_exception_handler(mock_request, exc)
        assert response.status_code == 429
        data = response.body.decode()
        assert "TOO_MANY_REQUESTS" in data

    @pytest.mark.asyncio
    async def test_preserves_headers(self, mock_request: MagicMock) -> None:
        """Test that headers are preserved from original exception."""
        exc = StarletteHTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
        response = await http_exception_handler(mock_request, exc)
        assert response.headers.get("WWW-Authenticate") == "Bearer"


class TestUnhandledExceptionHandler:
    """Tests for unhandled_exception_handler."""

    @pytest.mark.asyncio
    async def test_handles_generic_exception(self, mock_request: MagicMock) -> None:
        """Test handling generic unhandled exception."""
        exc = RuntimeError("Something went wrong")
        response = await unhandled_exception_handler(mock_request, exc)
        assert response.status_code == 500
        data = response.body.decode()
        assert "INTERNAL_SERVER_ERROR" in data
        # Should NOT expose internal error details
        assert "Something went wrong" not in data

    @pytest.mark.asyncio
    async def test_includes_request_id(self, mock_request: MagicMock) -> None:
        """Test that request_id is included in response."""
        exc = RuntimeError("Test")
        response = await unhandled_exception_handler(mock_request, exc)
        data = response.body.decode()
        assert "req-test-123" in data


# =============================================================================
# Integration Tests
# =============================================================================


class TestExceptionHandlerRegistration:
    """Tests for exception handler registration with FastAPI."""

    def test_setup_registers_handlers(self) -> None:
        """Test that setup_exception_handlers registers all handlers."""
        app = FastAPI()
        setup_exception_handlers(app)

        # Check handlers are registered
        assert Text2SQLException in app.exception_handlers
        assert RequestValidationError in app.exception_handlers
        assert StarletteHTTPException in app.exception_handlers
        assert Exception in app.exception_handlers

    def test_text2sql_exceptions_handled_by_app(self) -> None:
        """Test that Text2SQLException subclasses are handled properly."""
        app = FastAPI()
        setup_exception_handlers(app)

        @app.get("/test")
        async def test_endpoint() -> dict[str, str]:
            raise SchemaNotFoundException(database_id="test_db")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test")
        assert response.status_code == 404
        data = response.json()
        assert data["error"]["code"] == "SCHEMA_NOT_FOUND"

    def test_validation_exceptions_handled_by_app(self) -> None:
        """Test that validation errors are handled properly."""
        app = FastAPI()
        setup_exception_handlers(app)

        class TestModel(BaseModel):
            required_field: str = Field(..., min_length=1)

        @app.post("/test")
        async def test_endpoint(data: TestModel) -> dict[str, str]:
            return {"status": "ok"}

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/test", json={})
        assert response.status_code == 422
        data = response.json()
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "validation_errors" in data

    def test_unhandled_exceptions_caught(self) -> None:
        """Test that unhandled exceptions are caught."""
        app = FastAPI()
        setup_exception_handlers(app)

        @app.get("/test")
        async def test_endpoint() -> dict[str, str]:
            raise RuntimeError("Unexpected error")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/test")
        assert response.status_code == 500
        data = response.json()
        assert data["error"]["code"] == "INTERNAL_SERVER_ERROR"
        # Should not expose internal details
        assert "Unexpected error" not in str(data)
