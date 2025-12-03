"""
Safe SQL query execution with validation and security.

This module provides secure SQL execution with:
- Query validation and sanitization
- Timeout handling
- Result serialization
- Transaction management
- Retry logic for transient failures
"""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.exceptions import (
    QueryExecutionException,
    QueryTimeoutException,
    UnsupportedQueryTypeException,
)
from app.logging_config import get_logger

logger = get_logger(__name__)

# Dangerous SQL keywords that should be blocked in read-only mode
DANGEROUS_KEYWORDS = {
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

# SQL injection patterns to detect
INJECTION_PATTERNS = [
    r";\s*--",  # Comment injection
    r";\s*DROP",  # Stacked query with DROP
    r";\s*DELETE",  # Stacked query with DELETE
    r"UNION\s+SELECT",  # UNION injection
    r"OR\s+1\s*=\s*1",  # Always true condition
    r"OR\s+'\w*'\s*=\s*'\w*'",  # String comparison injection
]


@dataclass
class QueryResult:
    """Result of SQL query execution."""

    success: bool
    sql: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    columns: list[str] = field(default_factory=list)
    execution_time_ms: float = 0.0
    executed_at: datetime = field(default_factory=datetime.now)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "sql": self.sql,
            "rows": self.rows,
            "row_count": self.row_count,
            "columns": self.columns,
            "execution_time_ms": self.execution_time_ms,
            "executed_at": self.executed_at.isoformat(),
            "warnings": self.warnings,
            "error": self.error,
        }


class QueryValidator:
    """
    Validates SQL queries for safety and compliance.

    Checks for:
    - Dangerous operations (DROP, DELETE, etc.)
    - SQL injection patterns
    - Query complexity limits
    """

    def __init__(
        self,
        allow_mutations: bool = False,
        max_query_length: int = 10000,
    ) -> None:
        """
        Initialize query validator.

        Args:
            allow_mutations: Allow INSERT/UPDATE/DELETE operations
            max_query_length: Maximum allowed query length
        """
        self._allow_mutations = allow_mutations
        self._max_query_length = max_query_length

    def validate(self, sql: str) -> list[str]:
        """
        Validate SQL query for safety.

        Args:
            sql: SQL query to validate

        Returns:
            List of validation errors (empty if valid)
        """
        errors: list[str] = []
        sql_upper = sql.upper()

        # Check query length
        if len(sql) > self._max_query_length:
            errors.append(
                f"Query exceeds maximum length ({len(sql)} > {self._max_query_length})"
            )

        # Check for dangerous keywords
        if not self._allow_mutations:
            for keyword in DANGEROUS_KEYWORDS:
                if re.search(rf"\b{keyword}\b", sql_upper):
                    errors.append(f"Dangerous keyword detected: {keyword}")

        # Check for SQL injection patterns
        for pattern in INJECTION_PATTERNS:
            if re.search(pattern, sql_upper):
                errors.append(f"Potential SQL injection pattern detected")
                break

        return errors

    def is_select_only(self, sql: str) -> bool:
        """Check if query is SELECT only (no mutations)."""
        sql_upper = sql.strip().upper()
        return sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")


class SafeQueryExecutor:
    """
    Execute SQL queries safely with validation and timeout.

    Usage:
        executor = SafeQueryExecutor(session)
        result = await executor.execute("SELECT * FROM users WHERE id = :id", {"id": 1})
    """

    def __init__(
        self,
        session: AsyncSession,
        allow_mutations: bool = False,
        timeout_seconds: int = 30,
        max_rows: int = 1000,
    ) -> None:
        """
        Initialize query executor.

        Args:
            session: SQLAlchemy async session
            allow_mutations: Allow INSERT/UPDATE/DELETE operations
            timeout_seconds: Query timeout in seconds
            max_rows: Maximum rows to return
        """
        self._session = session
        self._validator = QueryValidator(allow_mutations=allow_mutations)
        self._timeout_seconds = timeout_seconds
        self._max_rows = max_rows

    async def execute(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> QueryResult:
        """
        Execute SQL query safely.

        Args:
            sql: SQL query (use :param_name for parameters)
            params: Query parameters
            timeout: Override default timeout

        Returns:
            QueryResult with execution results

        Raises:
            QueryExecutionException: If query fails
            QueryTimeoutException: If query times out
            UnsupportedQueryTypeException: If query type not allowed
        """
        import time

        start_time = time.perf_counter()
        timeout = timeout or self._timeout_seconds

        # Validate query
        validation_errors = self._validator.validate(sql)
        if validation_errors:
            raise QueryExecutionException(
                message=f"Query validation failed: {', '.join(validation_errors)}",
                sql=sql,
                details={"validation_errors": validation_errors},
            )

        # Check if mutation is attempted without permission
        if not self._validator.is_select_only(sql):
            raise UnsupportedQueryTypeException(
                query_type="mutation",
                supported_types=["SELECT", "WITH"],
                details={"message": "Only SELECT queries are allowed"},
            )

        logger.debug(
            "executing_query",
            sql_preview=sql[:100],
            has_params=params is not None,
        )

        try:
            # Execute with timeout
            result = await asyncio.wait_for(
                self._execute_query(sql, params),
                timeout=timeout,
            )

            execution_time_ms = (time.perf_counter() - start_time) * 1000

            logger.info(
                "query_executed",
                row_count=result.row_count,
                execution_time_ms=round(execution_time_ms, 2),
            )

            result.execution_time_ms = execution_time_ms
            return result

        except asyncio.TimeoutError as e:
            logger.error(
                "query_timeout",
                timeout_seconds=timeout,
                sql_preview=sql[:100],
            )
            raise QueryTimeoutException(
                timeout_seconds=timeout,
                details={"sql_preview": sql[:100]},
            ) from e

        except Exception as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "query_execution_error",
                error=str(e),
                sql_preview=sql[:100],
            )
            raise QueryExecutionException(
                message=f"Query execution failed: {e}",
                sql=sql,
                details={"error": str(e)},
            ) from e

    @retry(
        retry=retry_if_exception_type((ConnectionError, OSError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _execute_query(
        self,
        sql: str,
        params: dict[str, Any] | None,
    ) -> QueryResult:
        """
        Execute query and return result.

        Includes retry logic for transient connection failures.
        Will retry up to 3 times with exponential backoff.
        """
        # Always use parameterized query
        stmt = text(sql)
        result = await self._session.execute(stmt, params or {})

        # Get column names
        columns = list(result.keys()) if result.keys() else []

        # Fetch rows with limit
        rows_raw = result.fetchmany(self._max_rows)
        rows = [dict(zip(columns, row, strict=False)) for row in rows_raw]

        warnings = []
        if len(rows) == self._max_rows:
            warnings.append(f"Results truncated to {self._max_rows} rows")

        return QueryResult(
            success=True,
            sql=sql,
            rows=rows,
            row_count=len(rows),
            columns=columns,
            warnings=warnings,
        )

    async def execute_explain(self, sql: str) -> dict[str, Any]:
        """
        Get query execution plan.

        Args:
            sql: SQL query to explain

        Returns:
            Execution plan details
        """
        # Validate first
        validation_errors = self._validator.validate(sql)
        if validation_errors:
            raise QueryExecutionException(
                message=f"Query validation failed: {', '.join(validation_errors)}",
                sql=sql,
            )

        try:
            explain_sql = f"EXPLAIN {sql}"
            result = await self._session.execute(text(explain_sql))
            plan_rows = result.fetchall()

            return {
                "sql": sql,
                "plan": [str(row) for row in plan_rows],
            }

        except Exception as e:
            logger.warning(
                "explain_failed",
                error=str(e),
            )
            return {
                "sql": sql,
                "plan": [],
                "error": str(e),
            }


def sanitize_identifier(identifier: str) -> str:
    """
    Sanitize SQL identifier (table/column name).

    Only allows alphanumeric characters and underscores.

    Args:
        identifier: Identifier to sanitize

    Returns:
        Sanitized identifier
    """
    # Remove any non-alphanumeric/underscore characters
    sanitized = re.sub(r"[^\w]", "", identifier)

    # Ensure it doesn't start with a number
    if sanitized and sanitized[0].isdigit():
        sanitized = "_" + sanitized

    return sanitized
