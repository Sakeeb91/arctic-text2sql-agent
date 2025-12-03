"""
Data models for the agent-based Text2SQL engine.

This module defines data classes used throughout the agent module
for representing results, reasoning steps, and query history.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class AgentStepType(str, Enum):
    """Types of agent reasoning steps."""

    THOUGHT = "thought"
    ACTION = "action"
    OBSERVATION = "observation"
    FINAL_ANSWER = "final_answer"
    ERROR = "error"


class ValidationOutcome(str, Enum):
    """Outcomes of result validation."""

    VALID = "valid"
    NEEDS_CORRECTION = "needs_correction"
    INVALID = "invalid"
    UNCERTAIN = "uncertain"


@dataclass
class AgentStep:
    """
    A single step in the agent's ReAct reasoning process.

    The agent follows a Thought → Action → Observation loop:
    - Thought: Agent's reasoning about what to do next
    - Action: Tool call or code execution
    - Observation: Result of the action

    Attributes:
        step_number: Sequential step number (1-indexed)
        step_type: Type of step (thought, action, observation, etc.)
        content: The actual content of this step
        tool_name: Name of tool if this is an action step
        tool_input: Input provided to the tool
        tool_output: Output received from the tool
        timestamp: When this step occurred
        duration_ms: How long this step took
    """

    step_number: int
    step_type: AgentStepType
    content: str
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "step_number": self.step_number,
            "step_type": self.step_type.value,
            "content": self.content,
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
            "tool_output": self.tool_output,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
        }


@dataclass
class ValidationResult:
    """
    Result of validating generated SQL or query results.

    Attributes:
        outcome: The validation outcome
        message: Human-readable explanation
        suggestions: List of correction suggestions
        confidence: Confidence in the validation result
    """

    outcome: ValidationOutcome
    message: str
    suggestions: list[str] = field(default_factory=list)
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "outcome": self.outcome.value,
            "message": self.message,
            "suggestions": self.suggestions,
            "confidence": self.confidence,
        }


@dataclass
class AgentResult:
    """
    Complete result of agent-based SQL generation.

    This is the primary output from AgentText2SQL.generate_sql(),
    containing the generated SQL, execution results, and full
    reasoning trace.

    Attributes:
        sql: Generated SQL query
        confidence: Overall confidence score (0.0-1.0)
        execution_time_ms: Total time for agent execution
        reasoning_trace: List of all agent steps
        validation_result: Result of output validation
        execution_results: Query results if executed
        row_count: Number of rows returned if executed
        total_steps: Number of reasoning steps taken
        retries: Number of retry attempts
        warnings: Any warnings generated
        metadata: Additional metadata
    """

    sql: str
    confidence: float
    execution_time_ms: float
    reasoning_trace: list[AgentStep] = field(default_factory=list)
    validation_result: ValidationResult | None = None
    execution_results: list[dict[str, Any]] | None = None
    row_count: int | None = None
    total_steps: int = 0
    retries: int = 0
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "sql": self.sql,
            "confidence": self.confidence,
            "execution_time_ms": self.execution_time_ms,
            "reasoning_trace": [step.to_dict() for step in self.reasoning_trace],
            "validation_result": (
                self.validation_result.to_dict() if self.validation_result else None
            ),
            "execution_results": self.execution_results,
            "row_count": self.row_count,
            "total_steps": self.total_steps,
            "retries": self.retries,
            "warnings": self.warnings,
            "metadata": self.metadata,
        }


@dataclass
class QueryHistoryEntry:
    """
    A historical query entry for retry functionality.

    Stores information about previous query attempts to enable
    intelligent retry with context.

    Attributes:
        query_id: Unique identifier for this query
        natural_query: Original natural language question
        database_id: Target database identifier
        sql: Generated SQL query
        confidence: Confidence score
        success: Whether the query succeeded
        error_message: Error message if failed
        correction_hint: Hint for correction if provided
        created_at: When this entry was created
        reasoning_trace: Agent reasoning steps
    """

    query_id: str
    natural_query: str
    database_id: str
    sql: str
    confidence: float
    success: bool
    error_message: str | None = None
    correction_hint: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    reasoning_trace: list[AgentStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "query_id": self.query_id,
            "natural_query": self.natural_query,
            "database_id": self.database_id,
            "sql": self.sql,
            "confidence": self.confidence,
            "success": self.success,
            "error_message": self.error_message,
            "correction_hint": self.correction_hint,
            "created_at": self.created_at.isoformat(),
            "reasoning_trace": [step.to_dict() for step in self.reasoning_trace],
        }
