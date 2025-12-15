"""
Unit tests for the agent tools module.

These tests verify the tool functions used by the agent for
SQL execution, validation, and schema inspection.
"""

import pytest

pytest.importorskip("smolagents")

from app.agent.tools import extract_sql_from_text, result_validator

# =============================================================================
# Test SQL Extraction
# =============================================================================


class TestExtractSQLFromText:
    """Tests for extract_sql_from_text function."""

    def test_extract_from_markdown_code_block(self) -> None:
        """Test extraction from markdown SQL code block."""
        text = """Here's the SQL:
```sql
SELECT * FROM users WHERE id = 1;
```
This query gets the user."""

        result = extract_sql_from_text(text)
        assert result is not None
        assert "SELECT * FROM users WHERE id = 1" in result

    def test_extract_from_generic_code_block(self) -> None:
        """Test extraction from generic code block with SELECT."""
        text = """```
SELECT name, email FROM customers
```"""

        result = extract_sql_from_text(text)
        assert result is not None
        assert "SELECT name, email FROM customers" in result

    def test_extract_from_xml_tags(self) -> None:
        """Test extraction from XML-style tags."""
        text = """The query is:
<sql>SELECT COUNT(*) FROM orders</sql>"""

        result = extract_sql_from_text(text)
        assert result is not None
        assert "SELECT COUNT(*) FROM orders" in result

    def test_extract_plain_select(self) -> None:
        """Test extraction from plain SELECT statement."""
        text = "SELECT id, name FROM products"

        result = extract_sql_from_text(text)
        assert result is not None
        assert "SELECT id, name FROM products" in result

    def test_extract_with_cte(self) -> None:
        """Test extraction from CTE (WITH clause)."""
        text = """WITH top_customers AS (
    SELECT customer_id FROM orders GROUP BY customer_id
)
SELECT * FROM top_customers"""

        result = extract_sql_from_text(text)
        assert result is not None
        assert "WITH top_customers AS" in result

    def test_extract_multiline_sql(self) -> None:
        """Test extraction of multiline SQL."""
        text = """SELECT
    c.name,
    COUNT(o.id) as order_count
FROM customers c
JOIN orders o ON c.id = o.customer_id
GROUP BY c.name"""

        result = extract_sql_from_text(text)
        assert result is not None
        assert "SELECT" in result
        assert "FROM customers" in result

    def test_no_sql_found(self) -> None:
        """Test when no SQL is present."""
        text = "This is just some regular text without any SQL."

        result = extract_sql_from_text(text)
        assert result is None

    def test_extract_sql_with_explanation(self) -> None:
        """Test extraction when SQL is embedded in explanation."""
        text = """To answer your question, I'll use:
SELECT customer_name, SUM(amount) FROM orders GROUP BY customer_name

This aggregates the order amounts by customer."""

        result = extract_sql_from_text(text)
        assert result is not None
        assert "SELECT customer_name" in result
        assert "SUM(amount)" in result

    def test_empty_string(self) -> None:
        """Test with empty string."""
        result = extract_sql_from_text("")
        assert result is None

    def test_whitespace_only(self) -> None:
        """Test with whitespace only."""
        result = extract_sql_from_text("   \n\t  ")
        assert result is None


# =============================================================================
# Test Result Validator
# =============================================================================


class TestResultValidator:
    """Tests for result_validator tool function."""

    def test_valid_simple_query(self) -> None:
        """Test validation of valid simple query."""
        results = """Query returned 5 rows:
Row 1: id=1, name=Alice
Row 2: id=2, name=Bob"""
        question = "Show all users"
        sql = "SELECT id, name FROM users"

        validation = result_validator(results, question, sql)
        assert "VALID" in validation

    def test_empty_results_warning(self) -> None:
        """Test warning for empty results when expecting data."""
        results = "Query returned 0 rows."
        question = "Show all customers"
        sql = "SELECT * FROM customers WHERE state = 'XX'"

        validation = result_validator(results, question, sql)
        assert "NEEDS_CORRECTION" in validation or "no results" in validation.lower()

    def test_missing_aggregation(self) -> None:
        """Test detection of missing aggregation."""
        results = """Query returned 10 rows:
Row 1: amount=100
Row 2: amount=200"""
        question = "What is the total amount?"
        sql = "SELECT amount FROM orders"

        validation = result_validator(results, question, sql)
        assert "NEEDS_CORRECTION" in validation
        assert "aggregation" in validation.lower()

    def test_missing_count(self) -> None:
        """Test detection of missing COUNT for 'how many' question."""
        results = """Query returned 5 rows:
Row 1: id=1
Row 2: id=2"""
        question = "How many customers are there?"
        sql = "SELECT id FROM customers"

        validation = result_validator(results, question, sql)
        assert "NEEDS_CORRECTION" in validation

    def test_multiple_rows_for_superlative(self) -> None:
        """Test warning when expecting single value but got multiple."""
        results = """Query returned 5 rows:
Row 1: name=Alice, total=1000
Row 2: name=Bob, total=800"""
        question = "Which customer has the highest order total?"
        sql = "SELECT name, SUM(amount) as total FROM orders GROUP BY name"

        validation = result_validator(results, question, sql)
        assert "NEEDS_CORRECTION" in validation
        assert "ORDER BY" in validation or "LIMIT" in validation

    def test_execution_error(self) -> None:
        """Test handling of execution error."""
        results = "Error executing query: table 'userz' not found"
        question = "Show all users"
        sql = "SELECT * FROM userz"

        validation = result_validator(results, question, sql)
        assert "INVALID" in validation
        assert "Error" in validation

    def test_join_suggestion(self) -> None:
        """Test suggestion for JOIN when question implies multiple tables."""
        results = """Query returned 5 rows:
Row 1: name=Alice"""
        question = "Show customers with their orders"
        sql = "SELECT name FROM customers"

        validation = result_validator(results, question, sql)
        assert "NEEDS_CORRECTION" in validation
        assert "JOIN" in validation

    def test_valid_aggregation(self) -> None:
        """Test validation of correct aggregation query."""
        results = """Query returned 1 rows:
Row 1: total=5000"""
        question = "What is the total revenue?"
        sql = "SELECT SUM(amount) as total FROM orders"

        validation = result_validator(results, question, sql)
        assert "VALID" in validation

    def test_valid_with_limit(self) -> None:
        """Test validation of query with proper LIMIT."""
        results = """Query returned 1 rows:
Row 1: name=Alice, total=5000"""
        question = "Who has the highest order total?"
        sql = "SELECT name, SUM(amount) as total FROM orders GROUP BY name ORDER BY total DESC LIMIT 1"

        validation = result_validator(results, question, sql)
        assert "VALID" in validation

    def test_special_characters_in_results(self) -> None:
        """Test handling of special characters in results."""
        results = """Query returned 1 rows:
Row 1: name=O'Brien, email=test@example.com"""
        question = "Find customer O'Brien"
        sql = "SELECT * FROM customers WHERE name = 'O''Brien'"

        validation = result_validator(results, question, sql)
        # Should not crash and return valid result
        assert validation is not None


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases in tools."""

    def test_extract_sql_with_semicolons(self) -> None:
        """Test extraction handles semicolons correctly."""
        text = "SELECT * FROM users; This is additional text."

        result = extract_sql_from_text(text)
        assert result is not None
        assert "SELECT * FROM users" in result

    def test_extract_sql_case_insensitive(self) -> None:
        """Test extraction works with various cases."""
        texts = [
            "select * from users",
            "SELECT * FROM users",
            "Select * From Users",
            "sElEcT * fRoM users",
        ]

        for text in texts:
            result = extract_sql_from_text(text)
            assert result is not None, f"Failed for: {text}"

    def test_validator_empty_inputs(self) -> None:
        """Test validator with empty inputs."""
        validation = result_validator("", "test question", "SELECT 1")
        assert validation is not None

    def test_validator_long_results(self) -> None:
        """Test validator with very long results."""
        long_results = "Query returned 1000 rows:\n"
        long_results += "\n".join([f"Row {i}: value={i}" for i in range(1000)])

        validation = result_validator(
            long_results, "Show everything", "SELECT * FROM t"
        )
        assert validation is not None
