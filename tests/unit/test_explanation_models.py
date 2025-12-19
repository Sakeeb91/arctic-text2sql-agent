"""
Unit tests for explanation models (Issue #15).

Tests for the data models used in the query explanation feature.
"""

from datetime import datetime, timedelta

import pytest

from app.explanations.models import (
    AggregateFunction,
    ClauseBreakdown,
    ColumnReference,
    ComplexityAnalysis,
    ComplexityLevel,
    ComplexityMetrics,
    ExecutionPlanNode,
    ExplanationCacheEntry,
    FilterCondition,
    JoinInfo,
    JoinType,
    OptimizationHint,
    OptimizationSuggestion,
    QueryBreakdown,
    QueryBreakdownStep,
    QueryExplanationResult,
    QueryVisualization,
    SQLClauseType,
    SQLExplanation,
    TableReference,
    VisualizationFormat,
)


class TestEnums:
    """Tests for enum classes."""

    def test_sql_clause_type_values(self) -> None:
        """Test SQLClauseType enum values."""
        assert SQLClauseType.SELECT.value == "select"
        assert SQLClauseType.FROM.value == "from"
        assert SQLClauseType.JOIN.value == "join"
        assert SQLClauseType.WHERE.value == "where"
        assert SQLClauseType.GROUP_BY.value == "group_by"

    def test_join_type_values(self) -> None:
        """Test JoinType enum values."""
        assert JoinType.INNER.value == "inner"
        assert JoinType.LEFT.value == "left"
        assert JoinType.RIGHT.value == "right"
        assert JoinType.FULL.value == "full"

    def test_complexity_level_values(self) -> None:
        """Test ComplexityLevel enum values."""
        assert ComplexityLevel.SIMPLE.value == "simple"
        assert ComplexityLevel.MODERATE.value == "moderate"
        assert ComplexityLevel.COMPLEX.value == "complex"
        assert ComplexityLevel.VERY_COMPLEX.value == "very_complex"

    def test_visualization_format_values(self) -> None:
        """Test VisualizationFormat enum values."""
        assert VisualizationFormat.ASCII.value == "ascii"
        assert VisualizationFormat.JSON.value == "json"
        assert VisualizationFormat.HTML.value == "html"
        assert VisualizationFormat.MERMAID.value == "mermaid"


class TestColumnReference:
    """Tests for ColumnReference dataclass."""

    def test_basic_column(self) -> None:
        """Test basic column reference."""
        col = ColumnReference(column_name="id")
        assert col.column_name == "id"
        assert col.table_name is None
        assert col.alias is None
        assert col.is_aggregate is False

    def test_column_with_table(self) -> None:
        """Test column with table reference."""
        col = ColumnReference(
            column_name="name",
            table_name="users",
            alias="user_name",
        )
        assert col.column_name == "name"
        assert col.table_name == "users"
        assert col.alias == "user_name"

    def test_aggregate_column(self) -> None:
        """Test aggregate column reference."""
        col = ColumnReference(
            column_name="id",
            is_aggregate=True,
            aggregate_function=AggregateFunction.COUNT,
        )
        assert col.is_aggregate is True
        assert col.aggregate_function == AggregateFunction.COUNT

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        col = ColumnReference(
            column_name="id",
            table_name="users",
            is_aggregate=True,
            aggregate_function=AggregateFunction.COUNT,
        )
        result = col.to_dict()
        assert result["column_name"] == "id"
        assert result["table_name"] == "users"
        assert result["aggregate_function"] == "count"


class TestTableReference:
    """Tests for TableReference dataclass."""

    def test_basic_table(self) -> None:
        """Test basic table reference."""
        table = TableReference(table_name="users")
        assert table.table_name == "users"
        assert table.alias is None
        assert table.schema_name is None
        assert table.is_subquery is False

    def test_table_with_alias(self) -> None:
        """Test table with alias."""
        table = TableReference(
            table_name="users",
            alias="u",
            schema_name="public",
        )
        assert table.table_name == "users"
        assert table.alias == "u"
        assert table.schema_name == "public"

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        table = TableReference(
            table_name="orders",
            alias="o",
            is_subquery=True,
        )
        result = table.to_dict()
        assert result["table_name"] == "orders"
        assert result["alias"] == "o"
        assert result["is_subquery"] is True


class TestJoinInfo:
    """Tests for JoinInfo dataclass."""

    def test_basic_join(self) -> None:
        """Test basic join info."""
        join = JoinInfo(
            join_type=JoinType.INNER,
            left_table="users",
            right_table="orders",
            condition="users.id = orders.user_id",
        )
        assert join.join_type == JoinType.INNER
        assert join.left_table == "users"
        assert join.right_table == "orders"
        assert join.condition == "users.id = orders.user_id"

    def test_join_with_columns(self) -> None:
        """Test join with column list."""
        join = JoinInfo(
            join_type=JoinType.LEFT,
            left_table="users",
            right_table="orders",
            condition="users.id = orders.user_id",
            columns_used=["id", "user_id"],
        )
        assert join.columns_used == ["id", "user_id"]

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        join = JoinInfo(
            join_type=JoinType.FULL,
            left_table="a",
            right_table="b",
            condition="a.id = b.id",
        )
        result = join.to_dict()
        assert result["join_type"] == "full"
        assert result["left_table"] == "a"
        assert result["right_table"] == "b"


class TestComplexityMetrics:
    """Tests for ComplexityMetrics dataclass."""

    def test_simple_metrics(self) -> None:
        """Test simple complexity metrics."""
        metrics = ComplexityMetrics(
            level=ComplexityLevel.SIMPLE,
            score=0.2,
            table_count=1,
        )
        assert metrics.level == ComplexityLevel.SIMPLE
        assert metrics.score == 0.2
        assert metrics.table_count == 1

    def test_complex_metrics(self) -> None:
        """Test complex metrics."""
        metrics = ComplexityMetrics(
            level=ComplexityLevel.COMPLEX,
            score=0.8,
            table_count=5,
            join_count=4,
            subquery_count=2,
            condition_count=6,
            aggregate_count=3,
            has_window_functions=True,
            factors=["Multiple tables", "Subqueries"],
        )
        assert metrics.level == ComplexityLevel.COMPLEX
        assert metrics.join_count == 4
        assert metrics.has_window_functions is True
        assert len(metrics.factors) == 2

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        metrics = ComplexityMetrics(
            level=ComplexityLevel.MODERATE,
            score=0.5,
            estimated_difficulty="Moderate query",
        )
        result = metrics.to_dict()
        assert result["level"] == "moderate"
        assert result["score"] == 0.5
        assert result["estimated_difficulty"] == "Moderate query"


class TestExecutionPlanNode:
    """Tests for ExecutionPlanNode dataclass."""

    def test_leaf_node(self) -> None:
        """Test leaf execution plan node."""
        node = ExecutionPlanNode(
            node_type="Seq Scan",
            description="Sequential scan on users",
            estimated_cost=10.5,
            rows_estimated=100,
        )
        assert node.node_type == "Seq Scan"
        assert node.estimated_cost == 10.5
        assert len(node.children) == 0

    def test_nested_nodes(self) -> None:
        """Test nested execution plan nodes."""
        child1 = ExecutionPlanNode(
            node_type="Index Scan",
            description="Index scan on users_pkey",
        )
        child2 = ExecutionPlanNode(
            node_type="Seq Scan",
            description="Sequential scan on orders",
        )
        parent = ExecutionPlanNode(
            node_type="Hash Join",
            description="Hash join",
            children=[child1, child2],
        )
        assert len(parent.children) == 2
        assert parent.children[0].node_type == "Index Scan"

    def test_to_dict_recursive(self) -> None:
        """Test recursive to_dict conversion."""
        child = ExecutionPlanNode(
            node_type="Scan",
            description="Table scan",
        )
        parent = ExecutionPlanNode(
            node_type="Sort",
            description="Sort",
            children=[child],
        )
        result = parent.to_dict()
        assert result["node_type"] == "Sort"
        assert len(result["children"]) == 1
        assert result["children"][0]["node_type"] == "Scan"


class TestQueryExplanationResult:
    """Tests for QueryExplanationResult Pydantic model."""

    def test_basic_result(self) -> None:
        """Test basic explanation result."""
        result = QueryExplanationResult(
            query_id="test-123",
            sql="SELECT * FROM users",
            explanation=SQLExplanation(
                summary="Retrieves all users",
                detailed_explanation="This query retrieves all columns from the users table.",
                data_retrieval="All columns from users",
            ),
            breakdown=QueryBreakdown(steps=[], total_steps=0),
            complexity=ComplexityAnalysis(
                level="simple",
                score=0.1,
                table_count=1,
                join_count=0,
                subquery_count=0,
                condition_count=0,
                aggregate_count=0,
                estimated_difficulty="Simple query",
            ),
        )
        assert result.query_id == "test-123"
        assert result.explanation.summary == "Retrieves all users"
        assert result.complexity.level == "simple"

    def test_result_with_visualization(self) -> None:
        """Test result with visualization."""
        result = QueryExplanationResult(
            query_id="test-456",
            sql="SELECT * FROM users",
            explanation=SQLExplanation(
                summary="Test",
                detailed_explanation="Test",
                data_retrieval="Test",
            ),
            breakdown=QueryBreakdown(steps=[], total_steps=0),
            complexity=ComplexityAnalysis(
                level="simple",
                score=0.1,
                table_count=1,
                join_count=0,
                subquery_count=0,
                condition_count=0,
                aggregate_count=0,
                estimated_difficulty="Simple",
            ),
            visualization=QueryVisualization(
                format="ascii",
                content="[SELECT] -> [FROM]",
            ),
        )
        assert result.visualization is not None
        assert result.visualization.format == "ascii"


class TestExplanationCacheEntry:
    """Tests for ExplanationCacheEntry dataclass."""

    def test_cache_entry_not_expired(self) -> None:
        """Test cache entry that is not expired."""
        entry = ExplanationCacheEntry(
            query_id="test-123",
            sql_hash="abc123",
            explanation=QueryExplanationResult(
                query_id="test-123",
                sql="SELECT 1",
                explanation=SQLExplanation(
                    summary="Test",
                    detailed_explanation="Test",
                    data_retrieval="Test",
                ),
                breakdown=QueryBreakdown(steps=[], total_steps=0),
                complexity=ComplexityAnalysis(
                    level="simple",
                    score=0.1,
                    table_count=0,
                    join_count=0,
                    subquery_count=0,
                    condition_count=0,
                    aggregate_count=0,
                    estimated_difficulty="Simple",
                ),
            ),
            expires_at=datetime.now() + timedelta(hours=1),
        )
        assert entry.is_expired() is False

    def test_cache_entry_expired(self) -> None:
        """Test cache entry that is expired."""
        entry = ExplanationCacheEntry(
            query_id="test-123",
            sql_hash="abc123",
            explanation=QueryExplanationResult(
                query_id="test-123",
                sql="SELECT 1",
                explanation=SQLExplanation(
                    summary="Test",
                    detailed_explanation="Test",
                    data_retrieval="Test",
                ),
                breakdown=QueryBreakdown(steps=[], total_steps=0),
                complexity=ComplexityAnalysis(
                    level="simple",
                    score=0.1,
                    table_count=0,
                    join_count=0,
                    subquery_count=0,
                    condition_count=0,
                    aggregate_count=0,
                    estimated_difficulty="Simple",
                ),
            ),
            expires_at=datetime.now() - timedelta(hours=1),
        )
        assert entry.is_expired() is True

    def test_cache_entry_no_expiry(self) -> None:
        """Test cache entry with no expiry."""
        entry = ExplanationCacheEntry(
            query_id="test-123",
            sql_hash="abc123",
            explanation=QueryExplanationResult(
                query_id="test-123",
                sql="SELECT 1",
                explanation=SQLExplanation(
                    summary="Test",
                    detailed_explanation="Test",
                    data_retrieval="Test",
                ),
                breakdown=QueryBreakdown(steps=[], total_steps=0),
                complexity=ComplexityAnalysis(
                    level="simple",
                    score=0.1,
                    table_count=0,
                    join_count=0,
                    subquery_count=0,
                    condition_count=0,
                    aggregate_count=0,
                    estimated_difficulty="Simple",
                ),
            ),
            expires_at=None,
        )
        assert entry.is_expired() is False
