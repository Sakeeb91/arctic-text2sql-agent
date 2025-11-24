"""
Unit tests for exception classes.
"""

import pytest

from app.exceptions import (
    AgentMaxStepsExceededException,
    AuthenticationException,
    DatabaseConnectionException,
    InvalidQueryException,
    LowConfidenceException,
    ModelInferenceException,
    ModelLoadException,
    QueryExecutionException,
    QueryTimeoutException,
    RateLimitExceededException,
    SchemaNotFoundException,
    Text2SQLException,
    TokenLimitExceededException,
)


class TestText2SQLException:
    """Tests for base Text2SQLException."""

    def test_basic_exception(self) -> None:
        """Test basic exception creation."""
        exc = Text2SQLException("Test error")
        assert str(exc) == "Test error"
        assert exc.message == "Test error"
        assert exc.error_code == "TEXT2SQL_ERROR"
        assert exc.status_code == 500
        assert exc.details == {}

    def test_custom_values(self) -> None:
        """Test exception with custom values."""
        exc = Text2SQLException(
            message="Custom error",
            error_code="CUSTOM_ERROR",
            status_code=400,
            details={"key": "value"},
        )
        assert exc.error_code == "CUSTOM_ERROR"
        assert exc.status_code == 400
        assert exc.details == {"key": "value"}

    def test_to_dict(self) -> None:
        """Test exception to_dict conversion."""
        exc = Text2SQLException("Test", error_code="TEST", details={"foo": "bar"})
        result = exc.to_dict()

        assert result["error"]["code"] == "TEST"
        assert result["error"]["message"] == "Test"
        assert result["error"]["details"] == {"foo": "bar"}


class TestDatabaseExceptions:
    """Tests for database-related exceptions."""

    def test_connection_exception(self) -> None:
        """Test DatabaseConnectionException."""
        exc = DatabaseConnectionException()
        assert exc.status_code == 503
        assert exc.error_code == "DATABASE_CONNECTION_ERROR"

    def test_schema_not_found(self) -> None:
        """Test SchemaNotFoundException."""
        exc = SchemaNotFoundException("test_db")
        assert "test_db" in exc.message
        assert exc.status_code == 404
        assert exc.details["database_id"] == "test_db"

    def test_query_execution_exception(self) -> None:
        """Test QueryExecutionException with SQL preview."""
        long_sql = "SELECT " + "x" * 200
        exc = QueryExecutionException(sql=long_sql)
        assert len(exc.details["sql_preview"]) <= 103  # 100 + "..."

    def test_query_timeout(self) -> None:
        """Test QueryTimeoutException."""
        exc = QueryTimeoutException(timeout_seconds=30)
        assert "30" in exc.message
        assert exc.status_code == 408


class TestModelExceptions:
    """Tests for model-related exceptions."""

    def test_model_load_exception(self) -> None:
        """Test ModelLoadException."""
        exc = ModelLoadException("test/model", reason="Out of memory")
        assert "test/model" in exc.message
        assert "Out of memory" in exc.message
        assert exc.status_code == 503

    def test_model_inference_exception(self) -> None:
        """Test ModelInferenceException."""
        exc = ModelInferenceException()
        assert exc.status_code == 500
        assert exc.error_code == "MODEL_INFERENCE_ERROR"

    def test_token_limit_exceeded(self) -> None:
        """Test TokenLimitExceededException."""
        exc = TokenLimitExceededException(max_tokens=1000, actual_tokens=1500)
        assert "1000" in exc.message
        assert "1500" in exc.message
        assert exc.status_code == 400


class TestQueryExceptions:
    """Tests for query-related exceptions."""

    def test_invalid_query(self) -> None:
        """Test InvalidQueryException."""
        exc = InvalidQueryException(validation_errors=["Error 1", "Error 2"])
        assert exc.details["validation_errors"] == ["Error 1", "Error 2"]

    def test_low_confidence(self) -> None:
        """Test LowConfidenceException."""
        exc = LowConfidenceException(confidence=0.5, threshold=0.7)
        assert "0.50" in exc.message
        assert "0.70" in exc.message
        assert exc.status_code == 422


class TestAgentExceptions:
    """Tests for agent-related exceptions."""

    def test_max_steps_exceeded(self) -> None:
        """Test AgentMaxStepsExceededException."""
        exc = AgentMaxStepsExceededException(max_steps=5)
        assert "5" in exc.message
        assert exc.status_code == 408


class TestAPIExceptions:
    """Tests for API-related exceptions."""

    def test_authentication_exception(self) -> None:
        """Test AuthenticationException."""
        exc = AuthenticationException()
        assert exc.status_code == 401

    def test_rate_limit_exceeded(self) -> None:
        """Test RateLimitExceededException."""
        exc = RateLimitExceededException(limit=60, window_seconds=60, retry_after=30)
        assert exc.status_code == 429
        assert exc.details["retry_after"] == 30
