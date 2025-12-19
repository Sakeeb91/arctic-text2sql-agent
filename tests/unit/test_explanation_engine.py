"""
Unit tests for explanation engine (Issue #15).

Tests for the main ExplanationEngine class.
"""

import pytest

from app.explanations.engine import (
    ExplanationEngine,
    get_explanation_engine,
    reset_explanation_engine,
)
from app.explanations.models import VisualizationFormat
from app.exceptions import ExplanationNotFoundException, SQLParsingException


class TestExplanationEngine:
    """Tests for ExplanationEngine class."""

    @pytest.fixture
    def engine(self) -> ExplanationEngine:
        """Create engine instance."""
        return ExplanationEngine()

    @pytest.mark.asyncio
    async def test_explain_simple_query(self, engine: ExplanationEngine) -> None:
        """Test explaining a simple query."""
        sql = "SELECT id, name FROM users WHERE status = 'active'"
        result = await engine.explain(sql)

        assert result.query_id is not None
        assert result.sql == sql
        assert result.explanation.summary != ""
        assert result.complexity.level in [
            "simple",
            "moderate",
            "complex",
            "very_complex",
        ]
        assert 0 <= result.complexity.score <= 1.0

    @pytest.mark.asyncio
    async def test_explain_with_database_id(self, engine: ExplanationEngine) -> None:
        """Test explaining with database context."""
        sql = "SELECT * FROM orders"
        result = await engine.explain(sql, database_id="test_db")

        assert result.metadata.get("database_id") == "test_db"

    @pytest.mark.asyncio
    async def test_explain_complex_query(self, engine: ExplanationEngine) -> None:
        """Test explaining a complex query."""
        sql = """
        SELECT u.id, u.name, COUNT(o.id) as order_count
        FROM users u
        LEFT JOIN orders o ON u.id = o.user_id
        WHERE u.status = 'active'
        GROUP BY u.id, u.name
        HAVING COUNT(o.id) > 5
        ORDER BY order_count DESC
        LIMIT 10
        """
        result = await engine.explain(sql)

        assert result.query_id is not None
        assert result.complexity.score > 0.1  # Should have some complexity
        assert result.complexity.table_count >= 2
        assert result.complexity.join_count >= 1
        assert len(result.breakdown.steps) > 0

    @pytest.mark.asyncio
    async def test_explain_includes_visualization(
        self, engine: ExplanationEngine
    ) -> None:
        """Test that explain includes visualization when requested."""
        sql = "SELECT * FROM users"
        result = await engine.explain(sql, include_visualization=True)

        assert result.visualization is not None
        assert result.visualization.format == "ascii"
        assert result.visualization.content != ""

    @pytest.mark.asyncio
    async def test_explain_without_visualization(
        self, engine: ExplanationEngine
    ) -> None:
        """Test that explain excludes visualization when not requested."""
        sql = "SELECT * FROM users"
        result = await engine.explain(sql, include_visualization=False)

        assert result.visualization is None

    @pytest.mark.asyncio
    async def test_explain_includes_optimization_hints(
        self, engine: ExplanationEngine
    ) -> None:
        """Test that explain includes optimization hints."""
        sql = "SELECT * FROM users WHERE status = 'active'"
        result = await engine.explain(sql, include_optimization_hints=True)

        # Should have at least the SELECT * hint
        assert len(result.optimization_hints) > 0

    @pytest.mark.asyncio
    async def test_explain_different_visualization_formats(
        self, engine: ExplanationEngine
    ) -> None:
        """Test different visualization formats."""
        sql = "SELECT * FROM users"

        # Test ASCII format
        result = await engine.explain(
            sql,
            include_visualization=True,
            visualization_format=VisualizationFormat.ASCII,
        )
        assert result.visualization is not None
        assert result.visualization.format == "ascii"

        # Verify visualization contains expected content
        assert (
            "SELECT" in result.visualization.content
            or "users" in result.visualization.content
        )

    @pytest.mark.asyncio
    async def test_explain_query_with_join(self, engine: ExplanationEngine) -> None:
        """Test explaining query with JOIN."""
        sql = """
        SELECT u.name, o.total
        FROM users u
        INNER JOIN orders o ON u.id = o.user_id
        """
        result = await engine.explain(sql)

        assert result.complexity.join_count >= 1
        assert (
            "users" in result.explanation.tables_used
            or len(result.explanation.tables_used) > 0
        )

    @pytest.mark.asyncio
    async def test_explain_query_with_aggregation(
        self, engine: ExplanationEngine
    ) -> None:
        """Test explaining query with aggregation."""
        sql = "SELECT COUNT(*), SUM(amount) FROM orders GROUP BY status"
        result = await engine.explain(sql)

        assert result.complexity.aggregate_count >= 1
        assert len(result.explanation.aggregations) > 0

    @pytest.mark.asyncio
    async def test_breakdown_steps(self, engine: ExplanationEngine) -> None:
        """Test that breakdown has proper steps."""
        sql = "SELECT id FROM users WHERE status = 'active' ORDER BY id LIMIT 10"
        result = await engine.explain(sql)

        assert result.breakdown.total_steps > 0
        assert len(result.breakdown.steps) == result.breakdown.total_steps

        for step in result.breakdown.steps:
            assert step.step_number > 0
            assert step.clause_type != ""
            assert step.description != ""

    @pytest.mark.asyncio
    async def test_execution_order(self, engine: ExplanationEngine) -> None:
        """Test that breakdown includes execution order."""
        sql = "SELECT * FROM users"
        result = await engine.explain(sql)

        assert len(result.breakdown.execution_order) > 0
        # FROM should typically come before SELECT in execution
        assert "FROM" in result.breakdown.execution_order[0]


class TestExplanationCaching:
    """Tests for explanation caching."""

    @pytest.fixture
    def engine(self) -> ExplanationEngine:
        """Create engine instance."""
        return ExplanationEngine()

    @pytest.mark.asyncio
    async def test_explanation_cached(self, engine: ExplanationEngine) -> None:
        """Test that explanations are cached."""
        sql = "SELECT * FROM users"

        # First call
        result1 = await engine.explain(sql)
        query_id1 = result1.query_id

        # Second call should return cached result
        result2 = await engine.explain(sql)

        # They should have the same query_id since it's cached
        assert result2.query_id == query_id1

    @pytest.mark.asyncio
    async def test_get_cached_explanation(self, engine: ExplanationEngine) -> None:
        """Test retrieving cached explanation."""
        sql = "SELECT id FROM users"
        result = await engine.explain(sql)

        # Should be able to retrieve by query_id
        cached = await engine.get_cached_explanation(result.query_id)
        assert cached.query_id == result.query_id
        assert cached.sql == result.sql

    @pytest.mark.asyncio
    async def test_get_cached_explanation_not_found(
        self, engine: ExplanationEngine
    ) -> None:
        """Test that missing cache raises exception."""
        with pytest.raises(ExplanationNotFoundException):
            await engine.get_cached_explanation("non-existent-id")

    def test_clear_cache(self, engine: ExplanationEngine) -> None:
        """Test clearing cache."""
        count = engine.clear_cache()
        assert count >= 0

    def test_get_cache_stats(self, engine: ExplanationEngine) -> None:
        """Test getting cache statistics."""
        stats = engine.get_cache_stats()
        assert "total_entries" in stats
        assert "total_hits" in stats
        assert "expired_entries" in stats


class TestBatchExplanation:
    """Tests for batch explanation."""

    @pytest.fixture
    def engine(self) -> ExplanationEngine:
        """Create engine instance."""
        return ExplanationEngine()

    @pytest.mark.asyncio
    async def test_explain_batch(self, engine: ExplanationEngine) -> None:
        """Test batch explanation."""
        queries = [
            "SELECT * FROM users",
            "SELECT id, name FROM orders",
            "SELECT COUNT(*) FROM products",
        ]
        results = await engine.explain_batch(queries)

        assert len(results) == 3
        for i, result in enumerate(results):
            assert result.sql == queries[i]
            assert result.query_id is not None

    @pytest.mark.asyncio
    async def test_explain_batch_with_errors(self, engine: ExplanationEngine) -> None:
        """Test batch explanation with some errors."""
        queries = [
            "SELECT * FROM users",
            "INVALID SQL QUERY",  # This might fail
        ]
        results = await engine.explain_batch(queries)

        # Should return results for all queries
        assert len(results) == 2


class TestVisualization:
    """Tests for visualization generation."""

    @pytest.fixture
    def engine(self) -> ExplanationEngine:
        """Create engine instance."""
        return ExplanationEngine()

    @pytest.mark.asyncio
    async def test_visualize_simple(self, engine: ExplanationEngine) -> None:
        """Test simple visualization."""
        sql = "SELECT * FROM users"
        viz = await engine.visualize(sql)

        assert viz.format == "ascii"
        assert viz.content != ""

    @pytest.mark.asyncio
    async def test_visualize_json_format(self, engine: ExplanationEngine) -> None:
        """Test JSON visualization format."""
        sql = "SELECT * FROM users"
        viz = await engine.visualize(sql, format_type=VisualizationFormat.JSON)

        assert viz.format == "json"
        # Should be valid JSON
        import json

        parsed = json.loads(viz.content)
        assert "clauses" in parsed or isinstance(parsed, dict)


class TestSingletonEngine:
    """Tests for singleton engine instance."""

    @pytest.mark.asyncio
    async def test_get_explanation_engine_singleton(self) -> None:
        """Test singleton pattern."""
        reset_explanation_engine()

        engine1 = await get_explanation_engine()
        engine2 = await get_explanation_engine()
        assert engine1 is engine2

    @pytest.mark.asyncio
    async def test_reset_explanation_engine(self) -> None:
        """Test resetting singleton."""
        engine1 = await get_explanation_engine()
        reset_explanation_engine()
        engine2 = await get_explanation_engine()

        # Should be different instances after reset
        assert engine1 is not engine2
