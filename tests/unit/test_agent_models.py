"""
Unit tests for the agent models module.

These tests verify the data classes used for agent results,
reasoning steps, and query history.
"""

import pytest

pytest.importorskip("smolagents")

from datetime import datetime

from app.agent.models import (
    AgentResult,
    AgentStep,
    AgentStepType,
    QueryHistoryEntry,
    ValidationOutcome,
    ValidationResult,
)

# =============================================================================
# Test AgentStepType Enum
# =============================================================================


class TestAgentStepType:
    """Tests for AgentStepType enum."""

    def test_enum_values(self) -> None:
        """Test all enum values are correct."""
        assert AgentStepType.THOUGHT.value == "thought"
        assert AgentStepType.ACTION.value == "action"
        assert AgentStepType.OBSERVATION.value == "observation"
        assert AgentStepType.FINAL_ANSWER.value == "final_answer"
        assert AgentStepType.ERROR.value == "error"

    def test_enum_string_conversion(self) -> None:
        """Test enum converts to string properly."""
        assert str(AgentStepType.THOUGHT) == "AgentStepType.THOUGHT"
        assert AgentStepType.THOUGHT == "thought"


# =============================================================================
# Test ValidationOutcome Enum
# =============================================================================


class TestValidationOutcome:
    """Tests for ValidationOutcome enum."""

    def test_enum_values(self) -> None:
        """Test all enum values are correct."""
        assert ValidationOutcome.VALID.value == "valid"
        assert ValidationOutcome.NEEDS_CORRECTION.value == "needs_correction"
        assert ValidationOutcome.INVALID.value == "invalid"
        assert ValidationOutcome.UNCERTAIN.value == "uncertain"


# =============================================================================
# Test AgentStep
# =============================================================================


class TestAgentStep:
    """Tests for AgentStep dataclass."""

    def test_creation_minimal(self) -> None:
        """Test creation with minimal fields."""
        step = AgentStep(
            step_number=1,
            step_type=AgentStepType.THOUGHT,
            content="Analyzing the query structure.",
        )

        assert step.step_number == 1
        assert step.step_type == AgentStepType.THOUGHT
        assert step.content == "Analyzing the query structure."
        assert step.tool_name is None
        assert step.tool_input is None
        assert step.tool_output is None
        assert isinstance(step.timestamp, datetime)
        assert step.duration_ms == 0.0

    def test_creation_full(self) -> None:
        """Test creation with all fields."""
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        step = AgentStep(
            step_number=2,
            step_type=AgentStepType.ACTION,
            content="Executing SQL query.",
            tool_name="sql_executor",
            tool_input={"query": "SELECT * FROM users"},
            tool_output="Query returned 5 rows",
            timestamp=timestamp,
            duration_ms=150.5,
        )

        assert step.step_number == 2
        assert step.step_type == AgentStepType.ACTION
        assert step.content == "Executing SQL query."
        assert step.tool_name == "sql_executor"
        assert step.tool_input == {"query": "SELECT * FROM users"}
        assert step.tool_output == "Query returned 5 rows"
        assert step.timestamp == timestamp
        assert step.duration_ms == 150.5

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        step = AgentStep(
            step_number=1,
            step_type=AgentStepType.THOUGHT,
            content="Test content",
            tool_name="test_tool",
            duration_ms=100.0,
        )

        result = step.to_dict()

        assert result["step_number"] == 1
        assert result["step_type"] == "thought"
        assert result["content"] == "Test content"
        assert result["tool_name"] == "test_tool"
        assert result["tool_input"] is None
        assert result["tool_output"] is None
        assert "timestamp" in result
        assert result["duration_ms"] == 100.0


# =============================================================================
# Test ValidationResult
# =============================================================================


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_creation_minimal(self) -> None:
        """Test creation with minimal fields."""
        result = ValidationResult(
            outcome=ValidationOutcome.VALID,
            message="Results are correct.",
        )

        assert result.outcome == ValidationOutcome.VALID
        assert result.message == "Results are correct."
        assert result.suggestions == []
        assert result.confidence == 1.0

    def test_creation_full(self) -> None:
        """Test creation with all fields."""
        result = ValidationResult(
            outcome=ValidationOutcome.NEEDS_CORRECTION,
            message="Missing aggregation function.",
            suggestions=["Use SUM() or COUNT()", "Add GROUP BY clause"],
            confidence=0.8,
        )

        assert result.outcome == ValidationOutcome.NEEDS_CORRECTION
        assert result.message == "Missing aggregation function."
        assert len(result.suggestions) == 2
        assert result.confidence == 0.8

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        result = ValidationResult(
            outcome=ValidationOutcome.VALID,
            message="OK",
            suggestions=["hint"],
            confidence=0.95,
        )

        data = result.to_dict()

        assert data["outcome"] == "valid"
        assert data["message"] == "OK"
        assert data["suggestions"] == ["hint"]
        assert data["confidence"] == 0.95


# =============================================================================
# Test AgentResult
# =============================================================================


class TestAgentResult:
    """Tests for AgentResult dataclass."""

    def test_creation_minimal(self) -> None:
        """Test creation with minimal fields."""
        result = AgentResult(
            sql="SELECT * FROM users",
            confidence=0.9,
            execution_time_ms=500.0,
        )

        assert result.sql == "SELECT * FROM users"
        assert result.confidence == 0.9
        assert result.execution_time_ms == 500.0
        assert result.reasoning_trace == []
        assert result.validation_result is None
        assert result.execution_results is None
        assert result.row_count is None
        assert result.total_steps == 0
        assert result.retries == 0
        assert result.warnings == []
        assert result.metadata == {}

    def test_creation_full(self) -> None:
        """Test creation with all fields."""
        step = AgentStep(
            step_number=1,
            step_type=AgentStepType.THOUGHT,
            content="Test",
        )
        validation = ValidationResult(
            outcome=ValidationOutcome.VALID,
            message="OK",
        )

        result = AgentResult(
            sql="SELECT * FROM users",
            confidence=0.95,
            execution_time_ms=1000.0,
            reasoning_trace=[step],
            validation_result=validation,
            execution_results=[{"id": 1, "name": "Alice"}],
            row_count=1,
            total_steps=3,
            retries=1,
            warnings=["Low confidence warning"],
            metadata={"query_id": "123"},
        )

        assert len(result.reasoning_trace) == 1
        assert result.validation_result is not None
        assert result.row_count == 1
        assert result.total_steps == 3
        assert result.retries == 1
        assert len(result.warnings) == 1
        assert result.metadata["query_id"] == "123"

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        step = AgentStep(
            step_number=1,
            step_type=AgentStepType.THOUGHT,
            content="Test",
        )
        validation = ValidationResult(
            outcome=ValidationOutcome.VALID,
            message="OK",
        )

        result = AgentResult(
            sql="SELECT 1",
            confidence=0.9,
            execution_time_ms=100.0,
            reasoning_trace=[step],
            validation_result=validation,
            total_steps=1,
        )

        data = result.to_dict()

        assert data["sql"] == "SELECT 1"
        assert data["confidence"] == 0.9
        assert data["execution_time_ms"] == 100.0
        assert len(data["reasoning_trace"]) == 1
        assert data["validation_result"]["outcome"] == "valid"
        assert data["total_steps"] == 1


# =============================================================================
# Test QueryHistoryEntry
# =============================================================================


class TestQueryHistoryEntry:
    """Tests for QueryHistoryEntry dataclass."""

    def test_creation_minimal(self) -> None:
        """Test creation with minimal fields."""
        entry = QueryHistoryEntry(
            query_id="abc123",
            natural_query="Show all users",
            database_id="test_db",
            sql="SELECT * FROM users",
            confidence=0.9,
            success=True,
        )

        assert entry.query_id == "abc123"
        assert entry.natural_query == "Show all users"
        assert entry.database_id == "test_db"
        assert entry.sql == "SELECT * FROM users"
        assert entry.confidence == 0.9
        assert entry.success is True
        assert entry.error_message is None
        assert entry.correction_hint is None
        assert isinstance(entry.created_at, datetime)
        assert entry.reasoning_trace == []

    def test_creation_failed_query(self) -> None:
        """Test creation for a failed query."""
        entry = QueryHistoryEntry(
            query_id="def456",
            natural_query="Count all orders",
            database_id="test_db",
            sql="SELECT * FROM orders",
            confidence=0.6,
            success=False,
            error_message="Missing COUNT aggregation",
            correction_hint="Use COUNT(*) instead",
        )

        assert entry.success is False
        assert entry.error_message == "Missing COUNT aggregation"
        assert entry.correction_hint == "Use COUNT(*) instead"

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        step = AgentStep(
            step_number=1,
            step_type=AgentStepType.THOUGHT,
            content="Test",
        )

        entry = QueryHistoryEntry(
            query_id="xyz789",
            natural_query="Test query",
            database_id="db",
            sql="SELECT 1",
            confidence=0.8,
            success=True,
            reasoning_trace=[step],
        )

        data = entry.to_dict()

        assert data["query_id"] == "xyz789"
        assert data["natural_query"] == "Test query"
        assert data["database_id"] == "db"
        assert data["sql"] == "SELECT 1"
        assert data["confidence"] == 0.8
        assert data["success"] is True
        assert len(data["reasoning_trace"]) == 1
        assert "created_at" in data


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_sql(self) -> None:
        """Test result with empty SQL."""
        result = AgentResult(
            sql="",
            confidence=0.0,
            execution_time_ms=0.0,
        )

        assert result.sql == ""
        assert result.confidence == 0.0

    def test_very_long_sql(self) -> None:
        """Test result with very long SQL."""
        long_sql = "SELECT " + ", ".join([f"col{i}" for i in range(1000)]) + " FROM t"
        result = AgentResult(
            sql=long_sql,
            confidence=0.5,
            execution_time_ms=1000.0,
        )

        assert len(result.sql) > 5000

    def test_many_reasoning_steps(self) -> None:
        """Test result with many reasoning steps."""
        steps = [
            AgentStep(
                step_number=i,
                step_type=AgentStepType.THOUGHT,
                content=f"Step {i}",
            )
            for i in range(20)
        ]

        result = AgentResult(
            sql="SELECT 1",
            confidence=0.5,
            execution_time_ms=5000.0,
            reasoning_trace=steps,
            total_steps=20,
        )

        assert len(result.reasoning_trace) == 20
        assert result.total_steps == 20

    def test_special_characters_in_content(self) -> None:
        """Test handling of special characters."""
        step = AgentStep(
            step_number=1,
            step_type=AgentStepType.THOUGHT,
            content="Query contains special chars: 'quotes', \"double\", \n newlines",
        )

        data = step.to_dict()
        assert "quotes" in data["content"]
        assert "newlines" in data["content"]
