"""
SQL complexity analysis (Issue #15).

This module provides complexity analysis for SQL queries, calculating
metrics and scores to help users understand query difficulty and
potential performance implications.
"""

from typing import Any

from app.explanations.models import (
    ComplexityLevel,
    ComplexityMetrics,
    OptimizationHint,
)
from app.explanations.parsers import SQLParser, get_sql_parser
from app.logging_config import get_logger

logger = get_logger(__name__)


# =============================================================================
# Complexity Weights
# =============================================================================

# Weights for complexity scoring (0.0 to 1.0 contribution each)
COMPLEXITY_WEIGHTS = {
    "table_count": 0.10,
    "join_count": 0.15,
    "subquery_count": 0.20,
    "condition_count": 0.10,
    "aggregate_count": 0.10,
    "cte_count": 0.15,
    "window_function": 0.10,
    "distinct": 0.05,
    "union": 0.05,
}

# Thresholds for complexity levels
COMPLEXITY_THRESHOLDS = {
    ComplexityLevel.SIMPLE: 0.25,
    ComplexityLevel.MODERATE: 0.50,
    ComplexityLevel.COMPLEX: 0.75,
    ComplexityLevel.VERY_COMPLEX: 1.0,
}

# Factor descriptions
COMPLEXITY_FACTORS = {
    "multiple_tables": "Query involves multiple tables",
    "multiple_joins": "Query has multiple JOIN operations",
    "subqueries": "Query contains subqueries",
    "complex_conditions": "Query has complex WHERE/HAVING conditions",
    "aggregations": "Query uses aggregate functions",
    "cte": "Query uses Common Table Expressions (WITH clause)",
    "window_functions": "Query uses window functions",
    "distinct": "Query uses DISTINCT to eliminate duplicates",
    "union": "Query combines results with UNION",
    "nested_subqueries": "Query has deeply nested subqueries",
    "correlated_subquery": "Query contains correlated subqueries",
    "many_columns": "Query selects many columns",
    "complex_joins": "Query has complex join conditions",
}


# =============================================================================
# Complexity Analyzer
# =============================================================================


class ComplexityAnalyzer:
    """
    Analyze SQL query complexity.

    This analyzer examines SQL queries to determine their complexity
    level, identify contributing factors, and suggest optimizations.
    """

    def __init__(self, parser: SQLParser | None = None) -> None:
        """
        Initialize the complexity analyzer.

        Args:
            parser: SQL parser instance (uses singleton if not provided)
        """
        self.parser = parser or get_sql_parser()

    def analyze(self, sql: str) -> ComplexityMetrics:
        """
        Analyze the complexity of a SQL query.

        Args:
            sql: SQL query string

        Returns:
            ComplexityMetrics with complexity information
        """
        parsed = self.parser.parse(sql)

        # Count elements
        table_count = len(parsed.get("tables", []))
        join_count = len(parsed.get("joins", []))
        subquery_count = self._count_subqueries(sql)
        condition_count = len(parsed.get("conditions", []))
        aggregate_count = self._count_aggregates(parsed)
        cte_count = self._count_ctes(sql)

        # Boolean features
        has_window_functions = parsed.get("has_window_function", False)
        has_distinct = parsed.get("has_distinct", False)
        has_union = parsed.get("has_union", False)

        # Calculate complexity score
        score = self._calculate_score(
            table_count=table_count,
            join_count=join_count,
            subquery_count=subquery_count,
            condition_count=condition_count,
            aggregate_count=aggregate_count,
            cte_count=cte_count,
            has_window_functions=has_window_functions,
            has_distinct=has_distinct,
            has_union=has_union,
        )

        # Determine complexity level
        level = self._determine_level(score)

        # Identify contributing factors
        factors = self._identify_factors(
            table_count=table_count,
            join_count=join_count,
            subquery_count=subquery_count,
            condition_count=condition_count,
            aggregate_count=aggregate_count,
            cte_count=cte_count,
            has_window_functions=has_window_functions,
            has_distinct=has_distinct,
            has_union=has_union,
        )

        # Generate difficulty description
        estimated_difficulty = self._describe_difficulty(level, factors)

        return ComplexityMetrics(
            level=level,
            score=min(score, 1.0),
            table_count=table_count,
            join_count=join_count,
            subquery_count=subquery_count,
            condition_count=condition_count,
            aggregate_count=aggregate_count,
            cte_count=cte_count,
            has_window_functions=has_window_functions,
            has_distinct=has_distinct,
            has_union=has_union,
            estimated_difficulty=estimated_difficulty,
            factors=factors,
        )

    def get_optimization_hints(
        self, sql: str, metrics: ComplexityMetrics | None = None
    ) -> list[OptimizationHint]:
        """
        Generate optimization hints based on query complexity.

        Args:
            sql: SQL query string
            metrics: Pre-computed complexity metrics (computed if not provided)

        Returns:
            List of optimization hints
        """
        if metrics is None:
            metrics = self.analyze(sql)

        hints: list[OptimizationHint] = []
        parsed = self.parser.parse(sql)

        # Check for missing indexes (based on WHERE conditions)
        conditions = parsed.get("conditions", [])
        if conditions:
            columns_in_conditions = [c.column for c in conditions]
            hints.append(
                OptimizationHint(
                    category="indexing",
                    title="Consider adding indexes",
                    description=f"The query filters on these columns: {', '.join(columns_in_conditions)}. "
                    "Ensure appropriate indexes exist for frequently queried columns.",
                    severity="info",
                    affected_tables=[t.table_name for t in parsed.get("tables", [])],
                )
            )

        # Check for SELECT *
        columns = parsed.get("columns", [])
        if any(c.column_name == "*" for c in columns):
            hints.append(
                OptimizationHint(
                    category="query_design",
                    title="Avoid SELECT *",
                    description="Using SELECT * retrieves all columns, which may include unnecessary data. "
                    "Specify only the columns you need to reduce data transfer and improve performance.",
                    severity="warning",
                    affected_tables=[t.table_name for t in parsed.get("tables", [])],
                )
            )

        # Check for multiple subqueries
        if metrics.subquery_count > 2:
            hints.append(
                OptimizationHint(
                    category="query_design",
                    title="Consider using CTEs or JOINs",
                    description="Multiple subqueries can impact performance. Consider refactoring to use "
                    "Common Table Expressions (WITH clause) or JOINs for better readability and potential optimization.",
                    severity="warning",
                )
            )

        # Check for missing LIMIT on complex queries
        has_limit = "limit" in parsed.get("clauses", {})
        if not has_limit and metrics.level in (
            ComplexityLevel.COMPLEX,
            ComplexityLevel.VERY_COMPLEX,
        ):
            hints.append(
                OptimizationHint(
                    category="performance",
                    title="Consider adding LIMIT",
                    description="Complex queries without a LIMIT clause may return large result sets. "
                    "Consider adding a LIMIT to prevent excessive data transfer.",
                    severity="info",
                )
            )

        # Check for DISTINCT with many columns
        if metrics.has_distinct and len(columns) > 5:
            hints.append(
                OptimizationHint(
                    category="performance",
                    title="DISTINCT with many columns",
                    description="DISTINCT operations on many columns can be expensive. "
                    "Consider if all columns are necessary or if a subquery could reduce the dataset first.",
                    severity="info",
                )
            )

        # Check for complex join conditions
        joins = parsed.get("joins", [])
        for join in joins:
            if " and " in join.condition.lower() or " or " in join.condition.lower():
                hints.append(
                    OptimizationHint(
                        category="join_optimization",
                        title="Complex join condition detected",
                        description=f"The join between {join.left_table} and {join.right_table} has a complex condition. "
                        "Ensure appropriate indexes exist on join columns.",
                        severity="info",
                        affected_tables=[join.left_table, join.right_table],
                    )
                )
                break

        # Check for cartesian products (CROSS JOIN or missing join conditions)
        for join in joins:
            if join.join_type.value == "cross":
                hints.append(
                    OptimizationHint(
                        category="query_design",
                        title="Cartesian product detected",
                        description=f"A CROSS JOIN between {join.left_table} and {join.right_table} produces "
                        "a cartesian product. Ensure this is intentional as it can produce very large result sets.",
                        severity="critical",
                        affected_tables=[join.left_table, join.right_table],
                    )
                )

        return hints

    def _count_subqueries(self, sql: str) -> int:
        """Count subqueries in SQL."""
        import re

        # Count occurrences of SELECT within parentheses
        pattern = r"\(\s*select\b"
        return len(re.findall(pattern, sql, re.IGNORECASE))

    def _count_aggregates(self, parsed: dict[str, Any]) -> int:
        """Count aggregate functions in parsed SQL."""
        columns = parsed.get("columns", [])
        return sum(1 for c in columns if c.is_aggregate)

    def _count_ctes(self, sql: str) -> int:
        """Count CTEs in SQL."""
        import re

        if not re.match(r"^\s*with\b", sql, re.IGNORECASE):
            return 0
        # Count AS ( patterns before the main SELECT
        pattern = r"\bas\s*\("
        # Find the position of the main SELECT
        main_select = re.search(r"\bselect\b(?!\s*\*?\s*from)", sql, re.IGNORECASE)
        if main_select:
            cte_section = sql[: main_select.start()]
            return len(re.findall(pattern, cte_section, re.IGNORECASE))
        return 0

    def _calculate_score(
        self,
        table_count: int,
        join_count: int,
        subquery_count: int,
        condition_count: int,
        aggregate_count: int,
        cte_count: int,
        has_window_functions: bool,
        has_distinct: bool,
        has_union: bool,
    ) -> float:
        """Calculate overall complexity score."""
        score = 0.0

        # Table contribution (normalized to max 5 tables)
        score += min(table_count / 5, 1.0) * COMPLEXITY_WEIGHTS["table_count"]

        # Join contribution (normalized to max 4 joins)
        score += min(join_count / 4, 1.0) * COMPLEXITY_WEIGHTS["join_count"]

        # Subquery contribution (normalized to max 3 subqueries)
        score += min(subquery_count / 3, 1.0) * COMPLEXITY_WEIGHTS["subquery_count"]

        # Condition contribution (normalized to max 6 conditions)
        score += min(condition_count / 6, 1.0) * COMPLEXITY_WEIGHTS["condition_count"]

        # Aggregate contribution (normalized to max 4 aggregates)
        score += min(aggregate_count / 4, 1.0) * COMPLEXITY_WEIGHTS["aggregate_count"]

        # CTE contribution (normalized to max 3 CTEs)
        score += min(cte_count / 3, 1.0) * COMPLEXITY_WEIGHTS["cte_count"]

        # Boolean features
        if has_window_functions:
            score += COMPLEXITY_WEIGHTS["window_function"]
        if has_distinct:
            score += COMPLEXITY_WEIGHTS["distinct"]
        if has_union:
            score += COMPLEXITY_WEIGHTS["union"]

        return score

    def _determine_level(self, score: float) -> ComplexityLevel:
        """Determine complexity level from score."""
        if score <= COMPLEXITY_THRESHOLDS[ComplexityLevel.SIMPLE]:
            return ComplexityLevel.SIMPLE
        if score <= COMPLEXITY_THRESHOLDS[ComplexityLevel.MODERATE]:
            return ComplexityLevel.MODERATE
        if score <= COMPLEXITY_THRESHOLDS[ComplexityLevel.COMPLEX]:
            return ComplexityLevel.COMPLEX
        return ComplexityLevel.VERY_COMPLEX

    def _identify_factors(
        self,
        table_count: int,
        join_count: int,
        subquery_count: int,
        condition_count: int,
        aggregate_count: int,
        cte_count: int,
        has_window_functions: bool,
        has_distinct: bool,
        has_union: bool,
    ) -> list[str]:
        """Identify factors contributing to complexity."""
        factors = []

        if table_count > 1:
            factors.append(COMPLEXITY_FACTORS["multiple_tables"])
        if join_count > 1:
            factors.append(COMPLEXITY_FACTORS["multiple_joins"])
        if subquery_count > 0:
            factors.append(COMPLEXITY_FACTORS["subqueries"])
        if condition_count > 3:
            factors.append(COMPLEXITY_FACTORS["complex_conditions"])
        if aggregate_count > 0:
            factors.append(COMPLEXITY_FACTORS["aggregations"])
        if cte_count > 0:
            factors.append(COMPLEXITY_FACTORS["cte"])
        if has_window_functions:
            factors.append(COMPLEXITY_FACTORS["window_functions"])
        if has_distinct:
            factors.append(COMPLEXITY_FACTORS["distinct"])
        if has_union:
            factors.append(COMPLEXITY_FACTORS["union"])

        return factors

    def _describe_difficulty(self, level: ComplexityLevel, factors: list[str]) -> str:
        """Generate a human-readable difficulty description."""
        descriptions = {
            ComplexityLevel.SIMPLE: "This is a straightforward query that should execute quickly.",
            ComplexityLevel.MODERATE: "This query has moderate complexity and may benefit from indexing.",
            ComplexityLevel.COMPLEX: "This is a complex query that requires careful optimization.",
            ComplexityLevel.VERY_COMPLEX: "This is a highly complex query that may have significant performance implications.",
        }

        base = descriptions[level]

        if factors:
            factor_summary = " Contributing factors include: " + ", ".join(factors[:3])
            if len(factors) > 3:
                factor_summary += f", and {len(factors) - 3} more."
            else:
                factor_summary += "."
            return base + factor_summary

        return base


# =============================================================================
# Singleton Instance
# =============================================================================

_analyzer: ComplexityAnalyzer | None = None


def get_complexity_analyzer() -> ComplexityAnalyzer:
    """Get or create the singleton complexity analyzer instance."""
    global _analyzer
    if _analyzer is None:
        _analyzer = ComplexityAnalyzer()
    return _analyzer


def analyze_complexity(sql: str) -> ComplexityMetrics:
    """
    Convenience function to analyze SQL complexity.

    Args:
        sql: SQL query string

    Returns:
        ComplexityMetrics
    """
    return get_complexity_analyzer().analyze(sql)
