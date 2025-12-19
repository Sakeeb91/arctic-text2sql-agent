"""
Query Explanation and Visualization module (Issue #15).

This module provides comprehensive capabilities for explaining SQL queries
in natural language, analyzing their complexity, and generating visualizations.

Features:
- Natural language explanations of SQL queries
- Step-by-step query breakdown
- Complexity analysis with scoring
- Query structure visualization (ASCII, Mermaid, JSON, HTML)
- Optimization suggestions
- Explanation caching

Usage:
    from app.explanations import get_explanation_engine

    engine = await get_explanation_engine()
    result = await engine.explain(
        sql="SELECT * FROM users WHERE status = 'active'",
        database_id="my_database",
    )

    print(result.explanation.summary)
    print(result.complexity.level)
"""

from app.explanations.complexity import (
    ComplexityAnalyzer,
    analyze_complexity,
    get_complexity_analyzer,
)
from app.explanations.engine import (
    ExplanationEngine,
    get_explanation_engine,
    reset_explanation_engine,
)
from app.explanations.formatters import (
    ExplanationFormatter,
    HTMLFormatter,
    JSONFormatter,
    MarkdownFormatter,
    PlainTextFormatter,
    format_as_markdown,
    get_formatter,
)
from app.explanations.models import (
    ClauseBreakdown,
    ColumnReference,
    ComplexityAnalysis,
    ComplexityLevel,
    ComplexityMetrics,
    ExecutionPlan,
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
from app.explanations.parsers import (
    SQLParser,
    get_sql_parser,
)
from app.explanations.visualizers import (
    ASCIITreeVisualizer,
    JSONVisualizer,
    MermaidVisualizer,
    get_visualizer,
    visualize_query,
)

__all__ = [
    # Engine
    "ExplanationEngine",
    "get_explanation_engine",
    "reset_explanation_engine",
    # Parser
    "SQLParser",
    "get_sql_parser",
    # Complexity
    "ComplexityAnalyzer",
    "get_complexity_analyzer",
    "analyze_complexity",
    # Formatters
    "ExplanationFormatter",
    "PlainTextFormatter",
    "JSONFormatter",
    "HTMLFormatter",
    "MarkdownFormatter",
    "get_formatter",
    "format_as_markdown",
    # Visualizers
    "ASCIITreeVisualizer",
    "MermaidVisualizer",
    "JSONVisualizer",
    "get_visualizer",
    "visualize_query",
    # Models - Enums
    "SQLClauseType",
    "JoinType",
    "ComplexityLevel",
    "VisualizationFormat",
    # Models - Dataclasses
    "ColumnReference",
    "TableReference",
    "JoinInfo",
    "FilterCondition",
    "ClauseBreakdown",
    "ComplexityMetrics",
    "OptimizationHint",
    "ExecutionPlanNode",
    "ExplanationCacheEntry",
    # Models - Pydantic
    "QueryBreakdownStep",
    "QueryBreakdown",
    "SQLExplanation",
    "ComplexityAnalysis",
    "OptimizationSuggestion",
    "ExecutionPlan",
    "QueryVisualization",
    "QueryExplanationResult",
]
