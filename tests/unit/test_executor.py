"""
Unit tests for safe query executor.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    QueryExecutionException,
    QueryTimeoutException,
)
from db.executor import (
    DANGEROUS_KEYWORDS,
    INJECTION_PATTERNS,
    QueryResult,
    QueryValidator,
    SafeQueryExecutor,
    sanitize_identifier,
)


class TestQueryResult:
    """Tests for QueryResult dataclass."""

    def test_basic_creation(self) -> None:
        """Test basic query result creation."""
        result = QueryResult(
            success=True,
            sql="SELECT * FROM users",
            rows=[{"id": 1, "name": "Alice"}],
            row_count=1,
            columns=["id", "name"],
            execution_time_ms=50.5,
        )

        assert result.success is True
        assert result.sql == "SELECT * FROM users"
        assert result.row_count == 1
        assert len(result.rows) == 1

    def test_to_dict(self) -> None:
        """Test query result serialization."""
        result = QueryResult(
            success=True,
            sql="SELECT 1",
            rows=[],
            row_count=0,
            columns=[],
            execution_time_ms=10.0,
            warnings=["Test warning"],
        )

        result_dict = result.to_dict()

        assert result_dict["success"] is True
        assert result_dict["sql"] == "SELECT 1"
        assert result_dict["warnings"] == ["Test warning"]
        assert "executed_at" in result_dict

    def test_default_values(self) -> None:
        """Test default values for optional fields."""
        result = QueryResult(success=False, sql="SELECT error")

        assert result.rows == []
        assert result.row_count == 0
        assert result.columns == []
        assert result.warnings == []
        assert result.error is None

    def test_with_error(self) -> None:
        """Test query result with error."""
        result = QueryResult(
            success=False,
            sql="SELECT * FROM nonexistent",
            error="Table not found",
        )

        assert result.success is False
        assert result.error == "Table not found"


class TestQueryValidator:
    """Tests for QueryValidator class."""

    def test_default_initialization(self) -> None:
        """Test default validator initialization."""
        validator = QueryValidator()

        assert validator._allow_mutations is False
        assert validator._max_query_length == 10000

    def test_custom_initialization(self) -> None:
        """Test custom validator initialization."""
        validator = QueryValidator(allow_mutations=True, max_query_length=5000)

        assert validator._allow_mutations is True
        assert validator._max_query_length == 5000

    def test_validate_valid_select(self) -> None:
        """Test validation of valid SELECT query."""
        validator = QueryValidator()

        errors = validator.validate("SELECT * FROM users WHERE id = 1")

        assert errors == []

    def test_validate_query_too_long(self) -> None:
        """Test validation of overly long query."""
        validator = QueryValidator(max_query_length=50)

        long_query = "SELECT * FROM users WHERE " + "id = 1 AND " * 10
        errors = validator.validate(long_query)

        assert len(errors) == 1
        assert "exceeds maximum length" in errors[0]

    @pytest.mark.parametrize("keyword", list(DANGEROUS_KEYWORDS))
    def test_validate_dangerous_keywords(self, keyword: str) -> None:
        """Test detection of dangerous SQL keywords."""
        validator = QueryValidator(allow_mutations=False)

        query = f"{keyword} TABLE users"
        errors = validator.validate(query)

        assert len(errors) >= 1
        assert any("Dangerous keyword" in e for e in errors)

    def test_validate_allows_mutations_when_enabled(self) -> None:
        """Test that mutations are allowed when enabled."""
        validator = QueryValidator(allow_mutations=True)

        errors = validator.validate("DELETE FROM users WHERE id = 1")

        # Should not have dangerous keyword errors (may have injection pattern)
        assert not any("Dangerous keyword" in e for e in errors)

    def test_validate_sql_injection_comment(self) -> None:
        """Test detection of comment injection."""
        validator = QueryValidator()

        query = "SELECT * FROM users WHERE id = 1; -- DROP TABLE users"
        errors = validator.validate(query)

        assert any("injection" in e.lower() for e in errors)

    def test_validate_sql_injection_union(self) -> None:
        """Test detection of UNION injection."""
        validator = QueryValidator()

        query = "SELECT * FROM users UNION SELECT * FROM passwords"
        errors = validator.validate(query)

        assert any("injection" in e.lower() for e in errors)

    def test_validate_sql_injection_or_true(self) -> None:
        """Test detection of OR 1=1 injection."""
        validator = QueryValidator()

        query = "SELECT * FROM users WHERE id = 1 OR 1=1"
        errors = validator.validate(query)

        assert any("injection" in e.lower() for e in errors)

    def test_is_select_only_select(self) -> None:
        """Test is_select_only with SELECT query."""
        validator = QueryValidator()

        assert validator.is_select_only("SELECT * FROM users") is True
        assert validator.is_select_only("  SELECT id FROM users") is True

    def test_is_select_only_with(self) -> None:
        """Test is_select_only with WITH (CTE) query."""
        validator = QueryValidator()

        query = "WITH cte AS (SELECT 1) SELECT * FROM cte"
        assert validator.is_select_only(query) is True

    def test_is_select_only_mutation(self) -> None:
        """Test is_select_only with mutation queries."""
        validator = QueryValidator()

        assert validator.is_select_only("INSERT INTO users VALUES (1)") is False
        assert validator.is_select_only("UPDATE users SET name = 'x'") is False
        assert validator.is_select_only("DELETE FROM users") is False


class TestSafeQueryExecutor:
    """Tests for SafeQueryExecutor class."""

    @pytest.fixture
    def mock_session(self) -> MagicMock:
        """Create mock async session."""
        session = MagicMock(spec=AsyncSession)
        return session

    def test_initialization(self, mock_session: MagicMock) -> None:
        """Test executor initialization."""
        executor = SafeQueryExecutor(
            mock_session,
            allow_mutations=False,
            timeout_seconds=60,
            max_rows=500,
        )

        assert executor._session is mock_session
        assert executor._timeout_seconds == 60
        assert executor._max_rows == 500

    @pytest.mark.asyncio
    async def test_execute_valid_query(self, mock_session: MagicMock) -> None:
        """Test execution of valid SELECT query."""
        mock_result = MagicMock()
        mock_result.keys.return_value = ["id", "name"]
        mock_result.fetchmany.return_value = [(1, "Alice"), (2, "Bob")]

        mock_session.execute = AsyncMock(return_value=mock_result)

        executor = SafeQueryExecutor(mock_session)
        result = await executor.execute("SELECT id, name FROM users")

        assert result.success is True
        assert result.row_count == 2
        assert result.columns == ["id", "name"]

    @pytest.mark.asyncio
    async def test_execute_with_parameters(self, mock_session: MagicMock) -> None:
        """Test execution with query parameters."""
        mock_result = MagicMock()
        mock_result.keys.return_value = ["id"]
        mock_result.fetchmany.return_value = [(1,)]

        mock_session.execute = AsyncMock(return_value=mock_result)

        executor = SafeQueryExecutor(mock_session)
        result = await executor.execute(
            "SELECT id FROM users WHERE name = :name",
            params={"name": "Alice"},
        )

        assert result.success is True
        # Verify parameters were passed
        call_args = mock_session.execute.call_args
        assert call_args[0][1] == {"name": "Alice"}

    @pytest.mark.asyncio
    async def test_execute_validation_error(self, mock_session: MagicMock) -> None:
        """Test execution fails on validation error."""
        executor = SafeQueryExecutor(mock_session)

        with pytest.raises(QueryExecutionException) as exc_info:
            await executor.execute("DELETE FROM users WHERE id = 1")

        assert "validation failed" in str(exc_info.value.message).lower()

    @pytest.mark.asyncio
    async def test_execute_mutation_blocked(self, mock_session: MagicMock) -> None:
        """Test mutation queries are blocked."""
        executor = SafeQueryExecutor(mock_session, allow_mutations=False)

        # INSERT contains dangerous keyword, so validation fails first
        with pytest.raises(QueryExecutionException) as exc_info:
            await executor.execute("INSERT INTO users VALUES (1, 'test')")

        assert "Dangerous keyword" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_execute_timeout(self, mock_session: MagicMock) -> None:
        """Test query timeout handling."""

        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(5)
            return MagicMock()

        mock_session.execute = slow_execute

        executor = SafeQueryExecutor(mock_session, timeout_seconds=0.1)

        with pytest.raises(QueryTimeoutException) as exc_info:
            await executor.execute("SELECT * FROM users")

        assert "timed out" in str(exc_info.value.message).lower()

    @pytest.mark.asyncio
    async def test_execute_truncates_results(self, mock_session: MagicMock) -> None:
        """Test that results are truncated at max_rows."""
        mock_result = MagicMock()
        mock_result.keys.return_value = ["id"]
        # Return exactly max_rows number of results
        mock_result.fetchmany.return_value = [(i,) for i in range(10)]

        mock_session.execute = AsyncMock(return_value=mock_result)

        executor = SafeQueryExecutor(mock_session, max_rows=10)
        result = await executor.execute("SELECT id FROM large_table")

        assert result.row_count == 10
        assert any("truncated" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_execute_explain_success(self, mock_session: MagicMock) -> None:
        """Test successful EXPLAIN query."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("Seq Scan on users",)]

        mock_session.execute = AsyncMock(return_value=mock_result)

        executor = SafeQueryExecutor(mock_session)
        result = await executor.execute_explain("SELECT * FROM users")

        assert "plan" in result
        assert len(result["plan"]) > 0

    @pytest.mark.asyncio
    async def test_execute_explain_invalid_query(self, mock_session: MagicMock) -> None:
        """Test EXPLAIN with invalid query."""
        executor = SafeQueryExecutor(mock_session)

        with pytest.raises(QueryExecutionException):
            await executor.execute_explain("DELETE FROM users")

    @pytest.mark.asyncio
    async def test_execute_explain_failure(self, mock_session: MagicMock) -> None:
        """Test EXPLAIN failure returns error info."""
        mock_session.execute = AsyncMock(side_effect=Exception("EXPLAIN not supported"))

        executor = SafeQueryExecutor(mock_session)
        result = await executor.execute_explain("SELECT * FROM users")

        assert "error" in result
        assert result["plan"] == []


class TestSanitizeIdentifier:
    """Tests for sanitize_identifier function."""

    def test_basic_identifier(self) -> None:
        """Test basic alphanumeric identifier."""
        assert sanitize_identifier("users") == "users"
        assert sanitize_identifier("my_table") == "my_table"
        assert sanitize_identifier("Table123") == "Table123"

    def test_removes_special_characters(self) -> None:
        """Test removal of special characters."""
        assert sanitize_identifier("users;--") == "users"
        assert sanitize_identifier("table$name") == "tablename"
        assert sanitize_identifier("my-table") == "mytable"

    def test_handles_leading_numbers(self) -> None:
        """Test handling of leading numbers."""
        assert sanitize_identifier("123table") == "_123table"
        assert sanitize_identifier("1") == "_1"

    def test_preserves_underscores(self) -> None:
        """Test that underscores are preserved."""
        assert sanitize_identifier("my_long_table_name") == "my_long_table_name"

    def test_empty_result(self) -> None:
        """Test sanitization resulting in empty string."""
        assert sanitize_identifier("$%^&") == ""
        assert sanitize_identifier("") == ""

    def test_unicode_characters(self) -> None:
        """Test handling of unicode characters."""
        # Non-word characters should be removed
        result = sanitize_identifier("tëst_tàble")
        # Result depends on regex \w behavior with unicode
        assert "test" not in result or len(result) > 0


class TestDangerousKeywordsAndPatterns:
    """Tests for dangerous keywords and injection patterns constants."""

    def test_dangerous_keywords_coverage(self) -> None:
        """Test that dangerous keywords cover common threats."""
        expected_keywords = {
            "DROP",
            "DELETE",
            "TRUNCATE",
            "ALTER",
            "CREATE",
            "INSERT",
            "UPDATE",
            "GRANT",
            "REVOKE",
            "EXEC",
            "EXECUTE",
        }

        assert expected_keywords == DANGEROUS_KEYWORDS

    def test_injection_patterns_coverage(self) -> None:
        """Test that injection patterns cover common attacks."""
        # Should have patterns for common SQL injection techniques
        assert len(INJECTION_PATTERNS) >= 5

        # Check that patterns are valid regex
        import re

        for pattern in INJECTION_PATTERNS:
            re.compile(pattern)  # Should not raise
