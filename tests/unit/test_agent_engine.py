"""
Unit tests for the AgentText2SQL engine module.

These tests verify the agent-based SQL generation engine,
including the ReAct loop, validation, and retry functionality.
"""

import pytest

pytest.importorskip("smolagents")

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.engine import (
    AgentText2SQL,
    execute_sql_with_context,
    get_agent_engine,
    resolve_database_context,
    reset_agent_engine,
)
from app.agent.models import (
    AgentStep,
    AgentStepType,
    QueryHistoryEntry,
    ValidationOutcome,
    ValidationResult,
)
from app.exceptions import QueryNotFoundException

# =============================================================================
# Test AgentText2SQL Initialization
# =============================================================================


class TestAgentText2SQLInitialization:
    """Tests for AgentText2SQL initialization."""

    def test_initialization_defaults(self) -> None:
        """Test initialization with default values."""
        mock_db_manager = MagicMock()
        mock_db_manager.engine = MagicMock()
        mock_db_manager.dialect = "postgresql"

        with patch("app.agent.engine.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                agent=MagicMock(
                    max_steps=5,
                    min_confidence=0.7,
                    verbosity=1,
                ),
                cache=MagicMock(enabled=False),
            )

            engine = AgentText2SQL(mock_db_manager)

            assert engine._max_steps == 5
            assert engine._min_confidence == 0.7
            assert engine._verbosity == 1

    def test_initialization_custom_params(self) -> None:
        """Test initialization with custom parameters."""
        mock_db_manager = MagicMock()
        mock_db_manager.engine = MagicMock()

        with patch("app.agent.engine.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                agent=MagicMock(
                    max_steps=5,
                    min_confidence=0.7,
                    verbosity=1,
                ),
                cache=MagicMock(enabled=False),
            )

            engine = AgentText2SQL(
                mock_db_manager,
                max_steps=10,
                min_confidence=0.5,
                verbosity=2,
            )

            assert engine._max_steps == 10
            assert engine._min_confidence == 0.5
            assert engine._verbosity == 2


# =============================================================================
# Test Query History
# =============================================================================


class TestQueryHistory:
    """Tests for query history functionality."""

    def test_get_query_history_not_found(self) -> None:
        """Test getting non-existent query history."""
        mock_db_manager = MagicMock()
        mock_db_manager.engine = MagicMock()

        with patch("app.agent.engine.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                agent=MagicMock(
                    max_steps=5,
                    min_confidence=0.7,
                    verbosity=1,
                ),
                cache=MagicMock(enabled=False),
            )

            engine = AgentText2SQL(mock_db_manager)
            result = engine.get_query_history("nonexistent-id")

            assert result is None

    def test_get_query_history_found(self) -> None:
        """Test getting existing query history."""
        mock_db_manager = MagicMock()
        mock_db_manager.engine = MagicMock()

        with patch("app.agent.engine.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                agent=MagicMock(
                    max_steps=5,
                    min_confidence=0.7,
                    verbosity=1,
                ),
                cache=MagicMock(enabled=False),
            )

            engine = AgentText2SQL(mock_db_manager)

            # Add a history entry
            entry = QueryHistoryEntry(
                query_id="test-id",
                natural_query="Show users",
                database_id="db",
                sql="SELECT * FROM users",
                confidence=0.9,
                success=True,
            )
            engine._query_history["test-id"] = entry

            result = engine.get_query_history("test-id")

            assert result is not None
            assert result.query_id == "test-id"


# =============================================================================
# Test Schema Cache
# =============================================================================


class TestSchemaCache:
    """Tests for schema cache functionality."""

    def test_invalidate_specific_cache(self) -> None:
        """Test invalidating specific database cache."""
        mock_db_manager = MagicMock()
        mock_db_manager.engine = MagicMock()

        with patch("app.agent.engine.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                agent=MagicMock(
                    max_steps=5,
                    min_confidence=0.7,
                    verbosity=1,
                ),
                cache=MagicMock(enabled=False),
            )

            engine = AgentText2SQL(mock_db_manager)

            # Add cache entries
            engine._schema_cache["db1"] = "schema1"
            engine._schema_cache["db2"] = "schema2"

            # Invalidate specific
            engine.invalidate_schema_cache("db1")

            assert "db1" not in engine._schema_cache
            assert "db2" in engine._schema_cache

    def test_invalidate_all_cache(self) -> None:
        """Test invalidating all schema cache."""
        mock_db_manager = MagicMock()
        mock_db_manager.engine = MagicMock()

        with patch("app.agent.engine.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                agent=MagicMock(
                    max_steps=5,
                    min_confidence=0.7,
                    verbosity=1,
                ),
                cache=MagicMock(enabled=False),
            )

            engine = AgentText2SQL(mock_db_manager)

            # Add cache entries
            engine._schema_cache["db1"] = "schema1"
            engine._schema_cache["db2"] = "schema2"

            # Invalidate all
            engine.invalidate_schema_cache()

            assert len(engine._schema_cache) == 0


# =============================================================================
# Test Confidence Calculation
# =============================================================================


class TestConfidenceCalculation:
    """Tests for confidence calculation."""

    def test_confidence_with_valid_validation(self) -> None:
        """Test confidence boost for valid validation."""
        mock_db_manager = MagicMock()
        mock_db_manager.engine = MagicMock()

        with patch("app.agent.engine.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                agent=MagicMock(
                    max_steps=5,
                    min_confidence=0.7,
                    verbosity=1,
                )
            )

            engine = AgentText2SQL(mock_db_manager)

            validation = ValidationResult(
                outcome=ValidationOutcome.VALID,
                message="OK",
            )

            confidence = engine._calculate_confidence(
                model_confidence=0.8,
                validation_result=validation,
                steps_taken=3,
            )

            # Should get a boost for valid validation
            assert confidence >= 0.8

    def test_confidence_with_needs_correction(self) -> None:
        """Test confidence penalty for needs correction."""
        mock_db_manager = MagicMock()
        mock_db_manager.engine = MagicMock()

        with patch("app.agent.engine.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                agent=MagicMock(
                    max_steps=5,
                    min_confidence=0.7,
                    verbosity=1,
                )
            )

            engine = AgentText2SQL(mock_db_manager)

            validation = ValidationResult(
                outcome=ValidationOutcome.NEEDS_CORRECTION,
                message="Needs work",
            )

            confidence = engine._calculate_confidence(
                model_confidence=0.8,
                validation_result=validation,
                steps_taken=3,
            )

            # Should get a penalty
            assert confidence < 0.8

    def test_confidence_with_many_steps(self) -> None:
        """Test confidence penalty for many steps."""
        mock_db_manager = MagicMock()
        mock_db_manager.engine = MagicMock()

        with patch("app.agent.engine.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                agent=MagicMock(
                    max_steps=5,
                    min_confidence=0.7,
                    verbosity=1,
                )
            )

            engine = AgentText2SQL(mock_db_manager)

            confidence_3_steps = engine._calculate_confidence(
                model_confidence=0.8,
                validation_result=None,
                steps_taken=3,
            )

            confidence_10_steps = engine._calculate_confidence(
                model_confidence=0.8,
                validation_result=None,
                steps_taken=10,
            )

            # More steps should mean lower confidence
            assert confidence_10_steps < confidence_3_steps

    def test_confidence_bounds(self) -> None:
        """Test confidence stays within 0-1 bounds."""
        mock_db_manager = MagicMock()
        mock_db_manager.engine = MagicMock()

        with patch("app.agent.engine.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                agent=MagicMock(
                    max_steps=5,
                    min_confidence=0.7,
                    verbosity=1,
                )
            )

            engine = AgentText2SQL(mock_db_manager)

            # Very high confidence
            high = engine._calculate_confidence(
                model_confidence=1.0,
                validation_result=ValidationResult(
                    outcome=ValidationOutcome.VALID,
                    message="OK",
                ),
                steps_taken=1,
            )
            assert high <= 1.0

            # Very low confidence
            low = engine._calculate_confidence(
                model_confidence=0.1,
                validation_result=ValidationResult(
                    outcome=ValidationOutcome.INVALID,
                    message="Bad",
                ),
                steps_taken=20,
            )
            assert low >= 0.0


# =============================================================================
# Test Retry Functionality
# =============================================================================


class TestRetryFunctionality:
    """Tests for retry query functionality."""

    @pytest.mark.asyncio
    async def test_retry_query_not_found(self) -> None:
        """Test retry raises exception when query not found."""
        mock_db_manager = MagicMock()
        mock_db_manager.engine = MagicMock()

        with patch("app.agent.engine.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                agent=MagicMock(
                    max_steps=5,
                    min_confidence=0.7,
                    verbosity=1,
                )
            )

            engine = AgentText2SQL(mock_db_manager)

            with pytest.raises(QueryNotFoundException):
                await engine.retry_query("nonexistent-id")


# =============================================================================
# Test Global Engine Management
# =============================================================================


class TestGlobalEngineManagement:
    """Tests for global engine management functions."""

    def test_reset_agent_engine(self) -> None:
        """Test resetting the global engine."""
        import app.agent.engine as module

        # Set a mock engine
        module._agent_engine = MagicMock()
        assert module._agent_engine is not None

        # Reset
        reset_agent_engine()
        assert module._agent_engine is None

    @pytest.mark.asyncio
    async def test_get_agent_engine(self) -> None:
        """Test getting the global engine."""
        reset_agent_engine()

        with patch("db.connection.get_database") as mock_get_db:
            mock_db = MagicMock()
            mock_db.engine = MagicMock()
            mock_db.dialect = "postgresql"
            mock_get_db.return_value = mock_db

            with patch("app.agent.engine.get_settings") as mock_settings:
                mock_settings.return_value = MagicMock(
                    agent=MagicMock(
                        max_steps=5,
                        min_confidence=0.7,
                        verbosity=1,
                    )
                )

                engine = await get_agent_engine()

                assert engine is not None
                assert isinstance(engine, AgentText2SQL)

                # Should return same instance
                engine2 = await get_agent_engine()
                assert engine is engine2

        # Clean up
        reset_agent_engine()


# =============================================================================
# Test Database Context Resolution
# =============================================================================


class TestDatabaseContextResolution:
    """Tests for database context resolution."""

    @pytest.mark.asyncio
    async def test_resolve_database_context_uses_registry(self) -> None:
        """Test registry-based database resolution when enabled."""
        mock_db_manager = MagicMock()
        mock_db_manager.engine = MagicMock()
        mock_db_manager.dialect = "sqlite"

        mock_settings = MagicMock()
        mock_settings.multi_database.enabled = True

        registered = MagicMock()
        registered.engine = MagicMock()
        registered.config.dialect.value = "postgresql"

        registry = MagicMock()
        registry.get_database.return_value = registered
        registry.session.return_value = "session_ctx"

        with (
            patch("app.agent.engine.get_settings", return_value=mock_settings),
            patch("app.agent.engine.get_database_registry", return_value=registry),
        ):
            context = await resolve_database_context(mock_db_manager, "analytics")

        assert context.database_id == "analytics"
        assert context.dialect == "postgresql"
        assert context.session_provider() == "session_ctx"


# =============================================================================
# Test Query Execution Helper
# =============================================================================


class TestExecuteSqlWithContext:
    """Tests for execute_sql_with_context helper."""

    @pytest.mark.asyncio
    async def test_execute_sql_with_context_returns_result(self) -> None:
        """Test query execution helper returns QueryResult."""
        from contextlib import asynccontextmanager
        from db.executor import QueryResult

        @asynccontextmanager
        async def session_provider():
            yield MagicMock()

        context = MagicMock()
        context.session_provider = session_provider

        expected = QueryResult(
            success=True,
            sql="SELECT 1",
            rows=[{"value": 1}],
            row_count=1,
        )

        executor = MagicMock()
        executor.execute = AsyncMock(return_value=expected)

        with patch("app.agent.engine.SafeQueryExecutor", return_value=executor):
            result = await execute_sql_with_context(
                db_context=context,
                sql="SELECT 1",
                max_rows=10,
                timeout_seconds=30,
                allow_mutations=False,
            )

        assert result.success is True
        assert result.row_count == 1


# =============================================================================
# Test AgentStep Creation During Generation
# =============================================================================


class TestAgentStepCreation:
    """Tests for agent step creation patterns."""

    def test_thought_step_creation(self) -> None:
        """Test creating a thought step."""
        step = AgentStep(
            step_number=1,
            step_type=AgentStepType.THOUGHT,
            content="Analyzing the query to determine if it needs joins.",
        )

        assert step.step_type == AgentStepType.THOUGHT
        assert "Analyzing" in step.content

    def test_action_step_creation(self) -> None:
        """Test creating an action step."""
        step = AgentStep(
            step_number=2,
            step_type=AgentStepType.ACTION,
            content="Executing SQL query.",
            tool_name="sql_executor",
            tool_input={"query": "SELECT * FROM users"},
            tool_output="Query returned 5 rows",
        )

        assert step.step_type == AgentStepType.ACTION
        assert step.tool_name == "sql_executor"
        assert step.tool_input is not None

    def test_observation_step_creation(self) -> None:
        """Test creating an observation step."""
        step = AgentStep(
            step_number=3,
            step_type=AgentStepType.OBSERVATION,
            content="Query returned valid results.",
            duration_ms=150.5,
        )

        assert step.step_type == AgentStepType.OBSERVATION
        assert step.duration_ms == 150.5

    def test_final_answer_step_creation(self) -> None:
        """Test creating a final answer step."""
        step = AgentStep(
            step_number=4,
            step_type=AgentStepType.FINAL_ANSWER,
            content="Final SQL: SELECT * FROM users WHERE state = 'CA'",
        )

        assert step.step_type == AgentStepType.FINAL_ANSWER
        assert "Final SQL" in step.content
