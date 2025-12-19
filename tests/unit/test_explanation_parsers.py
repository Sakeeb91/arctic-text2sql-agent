"""
Unit tests for SQL parsers (Issue #15).

Tests for SQL parsing utilities used in query explanation.
"""

import pytest

from app.explanations.models import JoinType, SQLClauseType
from app.explanations.parsers import SQLParser, get_sql_parser


class TestSQLParser:
    """Tests for SQLParser class."""

    @pytest.fixture
    def parser(self) -> SQLParser:
        """Create parser instance."""
        return SQLParser()

    def test_parse_simple_select(self, parser: SQLParser) -> None:
        """Test parsing simple SELECT query."""
        sql = "SELECT id, name FROM users"
        result = parser.parse(sql)

        assert result["query_type"] == "SELECT"
        assert "select" in result["clauses"]
        assert "from" in result["clauses"]
        assert len(result["tables"]) == 1
        assert result["tables"][0].table_name == "users"

    def test_parse_select_star(self, parser: SQLParser) -> None:
        """Test parsing SELECT * query."""
        sql = "SELECT * FROM users"
        result = parser.parse(sql)

        assert result["query_type"] == "SELECT"
        assert len(result["columns"]) == 1
        assert result["columns"][0].column_name == "*"

    def test_parse_select_with_where(self, parser: SQLParser) -> None:
        """Test parsing SELECT with WHERE clause."""
        sql = "SELECT id, name FROM users WHERE status = 'active'"
        result = parser.parse(sql)

        assert "where" in result["clauses"]
        assert len(result["conditions"]) >= 1

    def test_parse_select_with_join(self, parser: SQLParser) -> None:
        """Test parsing SELECT with JOIN."""
        sql = """
        SELECT u.id, o.order_id
        FROM users u
        INNER JOIN orders o ON u.id = o.user_id
        """
        result = parser.parse(sql)

        # Should detect at least one join
        assert len(result["joins"]) >= 1
        # One of the joins should be INNER
        join_types = [j.join_type for j in result["joins"]]
        assert JoinType.INNER in join_types

    def test_parse_left_join(self, parser: SQLParser) -> None:
        """Test parsing LEFT JOIN."""
        sql = """
        SELECT * FROM users u
        LEFT JOIN orders o ON u.id = o.user_id
        """
        result = parser.parse(sql)

        # Should detect at least one join
        assert len(result["joins"]) >= 1
        # One of the joins should be LEFT
        join_types = [j.join_type for j in result["joins"]]
        assert JoinType.LEFT in join_types

    def test_parse_multiple_joins(self, parser: SQLParser) -> None:
        """Test parsing multiple JOINs."""
        sql = """
        SELECT u.id, o.order_id, p.name
        FROM users u
        INNER JOIN orders o ON u.id = o.user_id
        LEFT JOIN products p ON o.product_id = p.id
        """
        result = parser.parse(sql)

        assert len(result["joins"]) >= 2

    def test_parse_group_by(self, parser: SQLParser) -> None:
        """Test parsing GROUP BY clause."""
        sql = """
        SELECT status, COUNT(*) as count
        FROM users
        GROUP BY status
        """
        result = parser.parse(sql)

        assert "group_by" in result["clauses"]

    def test_parse_having(self, parser: SQLParser) -> None:
        """Test parsing HAVING clause."""
        sql = """
        SELECT status, COUNT(*) as count
        FROM users
        GROUP BY status
        HAVING COUNT(*) > 5
        """
        result = parser.parse(sql)

        assert "having" in result["clauses"]

    def test_parse_order_by(self, parser: SQLParser) -> None:
        """Test parsing ORDER BY clause."""
        sql = "SELECT * FROM users ORDER BY created_at DESC"
        result = parser.parse(sql)

        assert "order_by" in result["clauses"]

    def test_parse_limit(self, parser: SQLParser) -> None:
        """Test parsing LIMIT clause."""
        sql = "SELECT * FROM users LIMIT 10"
        result = parser.parse(sql)

        assert "limit" in result["clauses"]
        assert result["clauses"]["limit"] == "10"

    def test_parse_offset(self, parser: SQLParser) -> None:
        """Test parsing OFFSET clause."""
        sql = "SELECT * FROM users LIMIT 10 OFFSET 20"
        result = parser.parse(sql)

        assert "offset" in result["clauses"]
        assert result["clauses"]["offset"] == "20"

    def test_detect_subquery(self, parser: SQLParser) -> None:
        """Test subquery detection."""
        sql = """
        SELECT * FROM users
        WHERE id IN (SELECT user_id FROM orders WHERE total > 100)
        """
        result = parser.parse(sql)

        assert result["has_subquery"] is True

    def test_detect_cte(self, parser: SQLParser) -> None:
        """Test CTE detection."""
        sql = """
        WITH active_users AS (
            SELECT * FROM users WHERE status = 'active'
        )
        SELECT * FROM active_users
        """
        result = parser.parse(sql)

        assert result["has_cte"] is True

    def test_detect_union(self, parser: SQLParser) -> None:
        """Test UNION detection."""
        sql = """
        SELECT id FROM users
        UNION
        SELECT id FROM admins
        """
        result = parser.parse(sql)

        assert result["has_union"] is True

    def test_detect_distinct(self, parser: SQLParser) -> None:
        """Test DISTINCT detection."""
        sql = "SELECT DISTINCT status FROM users"
        result = parser.parse(sql)

        assert result["has_distinct"] is True

    def test_detect_window_function(self, parser: SQLParser) -> None:
        """Test window function detection."""
        sql = """
        SELECT id, name, ROW_NUMBER() OVER (ORDER BY created_at) as rn
        FROM users
        """
        result = parser.parse(sql)

        assert result["has_window_function"] is True

    def test_normalize_sql(self, parser: SQLParser) -> None:
        """Test SQL normalization."""
        sql = """
        SELECT   id,   name
        FROM     users
        WHERE    status = 'active'
        """
        result = parser.parse(sql)

        # Should parse correctly despite extra whitespace
        assert result["query_type"] == "SELECT"
        assert len(result["tables"]) == 1

    def test_remove_comments(self, parser: SQLParser) -> None:
        """Test comment removal."""
        sql = """
        SELECT id, name -- Get user info
        FROM users
        /* Filter active users */
        WHERE status = 'active'
        """
        result = parser.parse(sql)

        assert result["query_type"] == "SELECT"
        assert "where" in result["clauses"]

    def test_extract_table_with_alias(self, parser: SQLParser) -> None:
        """Test table extraction with alias."""
        sql = "SELECT u.id FROM users u"
        result = parser.parse(sql)

        # Should find the table
        assert len(result["tables"]) >= 1

    def test_extract_columns_with_aggregates(self, parser: SQLParser) -> None:
        """Test column extraction with aggregates."""
        sql = "SELECT COUNT(id), SUM(amount) FROM orders"
        result = parser.parse(sql)

        assert len(result["columns"]) == 2
        # At least one should be aggregate
        aggregates = [c for c in result["columns"] if c.is_aggregate]
        assert len(aggregates) >= 1


class TestClauseBreakdown:
    """Tests for clause breakdown functionality."""

    @pytest.fixture
    def parser(self) -> SQLParser:
        """Create parser instance."""
        return SQLParser()

    def test_get_clause_breakdown_simple(self, parser: SQLParser) -> None:
        """Test clause breakdown for simple query."""
        sql = "SELECT id, name FROM users"
        breakdowns = parser.get_clause_breakdown(sql)

        assert len(breakdowns) >= 2
        clause_types = [b.clause_type for b in breakdowns]
        assert SQLClauseType.SELECT in clause_types
        assert SQLClauseType.FROM in clause_types

    def test_get_clause_breakdown_complex(self, parser: SQLParser) -> None:
        """Test clause breakdown for complex query."""
        sql = """
        SELECT u.id, COUNT(o.id) as order_count
        FROM users u
        LEFT JOIN orders o ON u.id = o.user_id
        WHERE u.status = 'active'
        GROUP BY u.id
        HAVING COUNT(o.id) > 5
        ORDER BY order_count DESC
        LIMIT 10
        """
        breakdowns = parser.get_clause_breakdown(sql)

        # Should have multiple breakdowns
        assert len(breakdowns) >= 5

        clause_types = [b.clause_type for b in breakdowns]
        assert SQLClauseType.SELECT in clause_types
        assert SQLClauseType.FROM in clause_types
        assert SQLClauseType.WHERE in clause_types
        assert SQLClauseType.GROUP_BY in clause_types

    def test_breakdown_has_explanation(self, parser: SQLParser) -> None:
        """Test that breakdowns have explanations."""
        sql = "SELECT * FROM users WHERE id = 1"
        breakdowns = parser.get_clause_breakdown(sql)

        for breakdown in breakdowns:
            assert breakdown.explanation != ""
            assert len(breakdown.explanation) > 0


class TestSingletonParser:
    """Tests for singleton parser instance."""

    def test_get_sql_parser_returns_singleton(self) -> None:
        """Test that get_sql_parser returns singleton."""
        parser1 = get_sql_parser()
        parser2 = get_sql_parser()
        assert parser1 is parser2

    def test_singleton_parser_works(self) -> None:
        """Test that singleton parser works correctly."""
        parser = get_sql_parser()
        sql = "SELECT * FROM users"
        result = parser.parse(sql)
        assert result["query_type"] == "SELECT"
