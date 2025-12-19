"""
Data models for query explanation and visualization (Issue #15).

This module defines Pydantic models and dataclasses used throughout
the explanation feature for representing SQL analysis, breakdowns,
complexity metrics, and visualizations.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# =============================================================================
# Enums
# =============================================================================


class SQLClauseType(str, Enum):
    """Types of SQL clauses for breakdown analysis."""

    SELECT = "select"
    FROM = "from"
    JOIN = "join"
    WHERE = "where"
    GROUP_BY = "group_by"
    HAVING = "having"
    ORDER_BY = "order_by"
    LIMIT = "limit"
    OFFSET = "offset"
    UNION = "union"
    SUBQUERY = "subquery"
    CTE = "cte"
    WINDOW = "window"


class JoinType(str, Enum):
    """Types of SQL joins."""

    INNER = "inner"
    LEFT = "left"
    RIGHT = "right"
    FULL = "full"
    CROSS = "cross"
    NATURAL = "natural"


class AggregateFunction(str, Enum):
    """Common SQL aggregate functions."""

    COUNT = "count"
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    GROUP_CONCAT = "group_concat"
    STRING_AGG = "string_agg"


class ComplexityLevel(str, Enum):
    """Query complexity levels."""

    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"
    VERY_COMPLEX = "very_complex"


class VisualizationFormat(str, Enum):
    """Output formats for visualizations."""

    ASCII = "ascii"
    JSON = "json"
    HTML = "html"
    MERMAID = "mermaid"


# =============================================================================
# Dataclasses for Internal Use
# =============================================================================


@dataclass
class ColumnReference:
    """Reference to a column in SQL."""

    column_name: str
    table_name: str | None = None
    alias: str | None = None
    is_aggregate: bool = False
    aggregate_function: AggregateFunction | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "column_name": self.column_name,
            "table_name": self.table_name,
            "alias": self.alias,
            "is_aggregate": self.is_aggregate,
            "aggregate_function": (
                self.aggregate_function.value if self.aggregate_function else None
            ),
        }


@dataclass
class TableReference:
    """Reference to a table in SQL."""

    table_name: str
    alias: str | None = None
    schema_name: str | None = None
    is_subquery: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "table_name": self.table_name,
            "alias": self.alias,
            "schema_name": self.schema_name,
            "is_subquery": self.is_subquery,
        }


@dataclass
class JoinInfo:
    """Information about a SQL join."""

    join_type: JoinType
    left_table: str
    right_table: str
    condition: str
    columns_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "join_type": self.join_type.value,
            "left_table": self.left_table,
            "right_table": self.right_table,
            "condition": self.condition,
            "columns_used": self.columns_used,
        }


@dataclass
class FilterCondition:
    """Information about a WHERE/HAVING condition."""

    column: str
    operator: str
    value: str | None = None
    is_complex: bool = False
    has_subquery: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "column": self.column,
            "operator": self.operator,
            "value": self.value,
            "is_complex": self.is_complex,
            "has_subquery": self.has_subquery,
        }


@dataclass
class ClauseBreakdown:
    """Breakdown of a single SQL clause."""

    clause_type: SQLClauseType
    raw_text: str
    explanation: str
    elements: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "clause_type": self.clause_type.value,
            "raw_text": self.raw_text,
            "explanation": self.explanation,
            "elements": self.elements,
        }


@dataclass
class ComplexityMetrics:
    """Metrics for SQL query complexity analysis."""

    level: ComplexityLevel
    score: float  # 0.0 - 1.0
    table_count: int = 0
    join_count: int = 0
    subquery_count: int = 0
    condition_count: int = 0
    aggregate_count: int = 0
    cte_count: int = 0
    has_window_functions: bool = False
    has_distinct: bool = False
    has_union: bool = False
    estimated_difficulty: str = ""
    factors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "level": self.level.value,
            "score": self.score,
            "table_count": self.table_count,
            "join_count": self.join_count,
            "subquery_count": self.subquery_count,
            "condition_count": self.condition_count,
            "aggregate_count": self.aggregate_count,
            "cte_count": self.cte_count,
            "has_window_functions": self.has_window_functions,
            "has_distinct": self.has_distinct,
            "has_union": self.has_union,
            "estimated_difficulty": self.estimated_difficulty,
            "factors": self.factors,
        }


@dataclass
class OptimizationHint:
    """Optimization suggestion for a SQL query."""

    category: str  # e.g., "indexing", "join_order", "subquery"
    title: str
    description: str
    severity: str = "info"  # info, warning, critical
    affected_tables: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "affected_tables": self.affected_tables,
        }


@dataclass
class ExecutionPlanNode:
    """Node in a query execution plan tree."""

    node_type: str
    description: str
    estimated_cost: float | None = None
    actual_time: float | None = None
    rows_estimated: int | None = None
    rows_actual: int | None = None
    children: list["ExecutionPlanNode"] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary recursively."""
        return {
            "node_type": self.node_type,
            "description": self.description,
            "estimated_cost": self.estimated_cost,
            "actual_time": self.actual_time,
            "rows_estimated": self.rows_estimated,
            "rows_actual": self.rows_actual,
            "children": [child.to_dict() for child in self.children],
            "properties": self.properties,
        }


# =============================================================================
# Pydantic Models for API
# =============================================================================


class QueryBreakdownStep(BaseModel):
    """A single step in the query breakdown."""

    step_number: int = Field(..., description="Step number (1-indexed)")
    clause_type: str = Field(..., description="Type of SQL clause")
    description: str = Field(..., description="Human-readable description")
    sql_fragment: str = Field(..., description="SQL fragment for this step")
    elements: list[dict[str, Any]] = Field(
        default_factory=list, description="Parsed elements"
    )


class QueryBreakdown(BaseModel):
    """Complete breakdown of a SQL query into steps."""

    steps: list[QueryBreakdownStep] = Field(..., description="Query breakdown steps")
    total_steps: int = Field(..., description="Total number of steps")
    execution_order: list[str] = Field(
        default_factory=list, description="Logical execution order"
    )


class SQLExplanation(BaseModel):
    """Natural language explanation of a SQL query."""

    summary: str = Field(..., description="Brief summary of what the query does")
    detailed_explanation: str = Field(
        ..., description="Detailed explanation of the query"
    )
    data_retrieval: str = Field(..., description="What data is being retrieved")
    tables_used: list[str] = Field(
        default_factory=list, description="Tables referenced"
    )
    filters_applied: list[str] = Field(
        default_factory=list, description="Filters applied to data"
    )
    aggregations: list[str] = Field(
        default_factory=list, description="Aggregations performed"
    )
    sorting: str | None = Field(default=None, description="How results are sorted")
    limitations: str | None = Field(default=None, description="Any row limits applied")


class ComplexityAnalysis(BaseModel):
    """Complexity analysis of a SQL query."""

    level: str = Field(..., description="Complexity level")
    score: float = Field(..., ge=0.0, le=1.0, description="Complexity score")
    table_count: int = Field(..., description="Number of tables")
    join_count: int = Field(..., description="Number of joins")
    subquery_count: int = Field(..., description="Number of subqueries")
    condition_count: int = Field(..., description="Number of conditions")
    aggregate_count: int = Field(..., description="Number of aggregates")
    factors: list[str] = Field(
        default_factory=list, description="Factors affecting complexity"
    )
    estimated_difficulty: str = Field(..., description="Difficulty description")


class OptimizationSuggestion(BaseModel):
    """Optimization suggestion for a query."""

    category: str = Field(..., description="Category of optimization")
    title: str = Field(..., description="Short title")
    description: str = Field(..., description="Detailed description")
    severity: str = Field(default="info", description="Severity level")
    affected_tables: list[str] = Field(
        default_factory=list, description="Tables affected"
    )


class ExecutionPlan(BaseModel):
    """Query execution plan."""

    plan_text: str = Field(..., description="Raw execution plan text")
    total_cost: float | None = Field(None, description="Total estimated cost")
    actual_time_ms: float | None = Field(None, description="Actual execution time")
    nodes: list[dict[str, Any]] = Field(
        default_factory=list, description="Execution plan nodes"
    )


class QueryVisualization(BaseModel):
    """Visualization of a query structure."""

    format: str = Field(..., description="Visualization format")
    content: str = Field(..., description="Visualization content")
    width: int | None = Field(default=None, description="Width for text visualizations")
    height: int | None = Field(
        default=None, description="Height for text visualizations"
    )


class QueryExplanationResult(BaseModel):
    """Complete result of query explanation."""

    query_id: str = Field(..., description="Unique identifier for this explanation")
    sql: str = Field(..., description="Original SQL query")
    explanation: SQLExplanation = Field(..., description="Natural language explanation")
    breakdown: QueryBreakdown = Field(..., description="Step-by-step breakdown")
    complexity: ComplexityAnalysis = Field(..., description="Complexity analysis")
    optimization_hints: list[OptimizationSuggestion] = Field(
        default_factory=list, description="Optimization suggestions"
    )
    execution_plan: ExecutionPlan | None = Field(
        default=None, description="Execution plan if available"
    )
    visualization: QueryVisualization | None = Field(
        default=None, description="Query visualization"
    )
    created_at: datetime = Field(
        default_factory=datetime.now, description="When explanation was created"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )


# =============================================================================
# Cache Entry Model
# =============================================================================


@dataclass
class ExplanationCacheEntry:
    """Cache entry for stored explanations."""

    query_id: str
    sql_hash: str
    explanation: QueryExplanationResult
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime | None = None
    hit_count: int = 0

    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at
