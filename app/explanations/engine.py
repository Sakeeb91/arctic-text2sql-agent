"""
Query Explanation Engine (Issue #15).

This module provides the main ExplanationEngine class that orchestrates
SQL query explanation, visualization, and complexity analysis.
"""

import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Any

from app.config import get_settings
from app.exceptions import (
    ExplanationGenerationException,
    ExplanationNotFoundException,
    SQLParsingException,
)
from app.explanations.complexity import ComplexityAnalyzer, get_complexity_analyzer
from app.explanations.formatters import get_formatter
from app.explanations.models import (
    ClauseBreakdown,
    ComplexityAnalysis,
    ExplanationCacheEntry,
    OptimizationSuggestion,
    QueryBreakdown,
    QueryBreakdownStep,
    QueryExplanationResult,
    QueryVisualization,
    SQLExplanation,
    VisualizationFormat,
)
from app.explanations.parsers import SQLParser, get_sql_parser
from app.explanations.visualizers import (
    visualize_query,
)
from app.logging_config import get_logger

logger = get_logger(__name__)


# =============================================================================
# Explanation Engine
# =============================================================================


class ExplanationEngine:
    """
    Main engine for generating SQL query explanations.

    This engine coordinates SQL parsing, complexity analysis,
    visualization, and natural language explanation generation.
    """

    def __init__(
        self,
        parser: SQLParser | None = None,
        complexity_analyzer: ComplexityAnalyzer | None = None,
    ) -> None:
        """
        Initialize the explanation engine.

        Args:
            parser: SQL parser instance
            complexity_analyzer: Complexity analyzer instance
        """
        self.parser = parser or get_sql_parser()
        self.complexity_analyzer = complexity_analyzer or get_complexity_analyzer()
        self._cache: dict[str, ExplanationCacheEntry] = {}
        self._settings = get_settings()

    async def explain(
        self,
        sql: str,
        database_id: str | None = None,
        include_visualization: bool = True,
        include_optimization_hints: bool = True,
        visualization_format: VisualizationFormat = VisualizationFormat.ASCII,
    ) -> QueryExplanationResult:
        """
        Generate a comprehensive explanation for a SQL query.

        Args:
            sql: SQL query to explain
            database_id: Optional database ID for context
            include_visualization: Whether to include visualization
            include_optimization_hints: Whether to include optimization hints
            visualization_format: Format for visualization output

        Returns:
            QueryExplanationResult with full explanation

        Raises:
            SQLParsingException: If SQL parsing fails
            ExplanationGenerationException: If explanation generation fails
        """
        # Check cache first
        cache_key = self._get_cache_key(sql)
        if self._settings.explanation.cache_explanations:
            cached = self._get_from_cache(cache_key)
            if cached:
                logger.debug("explanation_cache_hit", cache_key=cache_key[:16])
                return cached.explanation

        try:
            # Parse SQL
            parsed = self.parser.parse(sql)
            if parsed["query_type"] == "UNKNOWN":
                raise SQLParsingException(
                    message="Unable to parse SQL query",
                    sql=sql,
                )

            # Generate unique query ID
            query_id = str(uuid.uuid4())

            # Get clause breakdown
            clause_breakdowns = self.parser.get_clause_breakdown(sql)

            # Analyze complexity
            complexity_metrics = self.complexity_analyzer.analyze(sql)

            # Generate natural language explanation
            nl_explanation = self._generate_nl_explanation(parsed, clause_breakdowns)

            # Create breakdown
            breakdown = self._create_breakdown(clause_breakdowns)

            # Create complexity analysis
            complexity = ComplexityAnalysis(
                level=complexity_metrics.level.value,
                score=complexity_metrics.score,
                table_count=complexity_metrics.table_count,
                join_count=complexity_metrics.join_count,
                subquery_count=complexity_metrics.subquery_count,
                condition_count=complexity_metrics.condition_count,
                aggregate_count=complexity_metrics.aggregate_count,
                factors=complexity_metrics.factors,
                estimated_difficulty=complexity_metrics.estimated_difficulty,
            )

            # Get optimization hints
            optimization_hints: list[OptimizationSuggestion] = []
            if include_optimization_hints:
                hints = self.complexity_analyzer.get_optimization_hints(
                    sql, complexity_metrics
                )
                optimization_hints = [
                    OptimizationSuggestion(
                        category=h.category,
                        title=h.title,
                        description=h.description,
                        severity=h.severity,
                        affected_tables=h.affected_tables,
                    )
                    for h in hints
                ]

            # Generate visualization
            visualization: QueryVisualization | None = None
            if include_visualization:
                visualization = visualize_query(
                    clauses=clause_breakdowns,
                    tables=parsed.get("tables", []),
                    joins=parsed.get("joins", []),
                    format_type=visualization_format,
                )

            # Create result
            result = QueryExplanationResult(
                query_id=query_id,
                sql=sql,
                explanation=nl_explanation,
                breakdown=breakdown,
                complexity=complexity,
                optimization_hints=optimization_hints,
                visualization=visualization,
                metadata={
                    "database_id": database_id,
                    "query_type": parsed["query_type"],
                    "has_subquery": parsed.get("has_subquery", False),
                    "has_cte": parsed.get("has_cte", False),
                },
            )

            # Cache the result
            if self._settings.explanation.cache_explanations:
                self._add_to_cache(cache_key, result)

            logger.info(
                "explanation_generated",
                query_id=query_id,
                complexity_level=complexity.level,
                complexity_score=complexity.score,
            )

            return result

        except SQLParsingException:
            raise
        except Exception as e:
            logger.error("explanation_generation_failed", error=str(e), sql=sql[:100])
            raise ExplanationGenerationException(
                message=f"Failed to generate explanation: {str(e)}",
                sql=sql,
            ) from e

    async def get_cached_explanation(self, query_id: str) -> QueryExplanationResult:
        """
        Retrieve a cached explanation by query ID.

        Args:
            query_id: Query ID to look up

        Returns:
            Cached QueryExplanationResult

        Raises:
            ExplanationNotFoundException: If not found in cache
        """
        for entry in self._cache.values():
            if entry.explanation.query_id == query_id:
                entry.hit_count += 1
                return entry.explanation

        raise ExplanationNotFoundException(query_id=query_id)

    async def explain_batch(
        self,
        queries: list[str],
        database_id: str | None = None,
    ) -> list[QueryExplanationResult]:
        """
        Generate explanations for multiple SQL queries.

        Args:
            queries: List of SQL queries
            database_id: Optional database ID

        Returns:
            List of QueryExplanationResult
        """
        results = []
        for sql in queries:
            try:
                result = await self.explain(
                    sql=sql,
                    database_id=database_id,
                    include_visualization=False,  # Skip for batch
                    include_optimization_hints=True,
                )
                results.append(result)
            except Exception as e:
                logger.warning("batch_explanation_failed", error=str(e))
                # Create a minimal error result
                results.append(
                    QueryExplanationResult(
                        query_id=str(uuid.uuid4()),
                        sql=sql,
                        explanation=SQLExplanation(
                            summary="Failed to generate explanation",
                            detailed_explanation=str(e),
                            data_retrieval="Unknown",
                        ),
                        breakdown=QueryBreakdown(steps=[], total_steps=0),
                        complexity=ComplexityAnalysis(
                            level="unknown",
                            score=0.0,
                            table_count=0,
                            join_count=0,
                            subquery_count=0,
                            condition_count=0,
                            aggregate_count=0,
                            estimated_difficulty="Unable to analyze",
                        ),
                        metadata={"error": str(e)},
                    )
                )
        return results

    async def visualize(
        self,
        sql: str,
        format_type: VisualizationFormat = VisualizationFormat.ASCII,
    ) -> QueryVisualization:
        """
        Generate visualization for a SQL query.

        Args:
            sql: SQL query to visualize
            format_type: Output format

        Returns:
            QueryVisualization
        """
        parsed = self.parser.parse(sql)
        clause_breakdowns = self.parser.get_clause_breakdown(sql)

        return visualize_query(
            clauses=clause_breakdowns,
            tables=parsed.get("tables", []),
            joins=parsed.get("joins", []),
            format_type=format_type,
        )

    def format_explanation(
        self,
        result: QueryExplanationResult,
        format_type: VisualizationFormat = VisualizationFormat.ASCII,
    ) -> str:
        """
        Format an explanation result for output.

        Args:
            result: Explanation result to format
            format_type: Output format

        Returns:
            Formatted string
        """
        formatter = get_formatter(format_type)
        return formatter.format_full(result)

    def _generate_nl_explanation(
        self,
        parsed: dict[str, Any],
        breakdowns: list[ClauseBreakdown],
    ) -> SQLExplanation:
        """
        Generate natural language explanation of SQL.

        This uses rule-based generation. For LLM-based generation,
        this could be extended to call the model.
        """
        # Extract key information
        query_type = parsed.get("query_type", "UNKNOWN")
        tables = parsed.get("tables", [])
        columns = parsed.get("columns", [])
        joins = parsed.get("joins", [])
        conditions = parsed.get("conditions", [])

        # Build explanation components
        table_names = [t.table_name for t in tables]
        column_names = [
            c.alias or c.column_name for c in columns if c.column_name != "*"
        ]

        # Summary
        if query_type == "SELECT":
            if len(tables) == 1:
                summary = f"This query retrieves data from the '{tables[0].table_name}' table."
            else:
                summary = f"This query retrieves data from {len(tables)} tables: {', '.join(table_names)}."
        else:
            summary = f"This is a {query_type} query."

        # Data retrieval description
        if columns and columns[0].column_name == "*":
            data_retrieval = "All columns from the table(s)"
        elif columns:
            data_retrieval = f"Specific columns: {', '.join(column_names[:5])}"
            if len(column_names) > 5:
                data_retrieval += f" and {len(column_names) - 5} more"
        else:
            data_retrieval = "Unknown columns"

        # Filters description
        filters_applied = []
        for cond in conditions:
            filters_applied.append(
                f"{cond.column} {cond.operator} {cond.value or 'value'}"
            )

        # Aggregations description
        aggregations = []
        for col in columns:
            if col.is_aggregate and col.aggregate_function:
                aggregations.append(
                    f"{col.aggregate_function.value.upper()}({col.column_name})"
                )

        # Sorting description
        sorting = None
        for breakdown in breakdowns:
            if breakdown.clause_type.value == "order_by":
                sorting = f"Results ordered by: {breakdown.raw_text}"
                break

        # Limitations description
        limitations = None
        for breakdown in breakdowns:
            if breakdown.clause_type.value == "limit":
                limitations = f"Limited to {breakdown.raw_text} rows"
                break

        # Detailed explanation
        detailed_parts = [summary]

        if joins:
            join_desc = []
            for join in joins:
                join_desc.append(
                    f"{join.join_type.value.upper()} JOIN with {join.right_table}"
                )
            detailed_parts.append("The query performs joins: " + ", ".join(join_desc))

        if conditions:
            detailed_parts.append(
                f"The query filters data using {len(conditions)} condition(s)."
            )

        if aggregations:
            detailed_parts.append(
                f"The query performs aggregations: {', '.join(aggregations)}"
            )

        detailed_explanation = " ".join(detailed_parts)

        return SQLExplanation(
            summary=summary,
            detailed_explanation=detailed_explanation,
            data_retrieval=data_retrieval,
            tables_used=table_names,
            filters_applied=filters_applied[:5],
            aggregations=aggregations,
            sorting=sorting,
            limitations=limitations,
        )

    def _create_breakdown(
        self, clause_breakdowns: list[ClauseBreakdown]
    ) -> QueryBreakdown:
        """Create QueryBreakdown from clause breakdowns."""
        steps = []
        for i, breakdown in enumerate(clause_breakdowns, 1):
            steps.append(
                QueryBreakdownStep(
                    step_number=i,
                    clause_type=breakdown.clause_type.value,
                    description=breakdown.explanation,
                    sql_fragment=breakdown.raw_text,
                    elements=breakdown.elements,
                )
            )

        # Logical execution order for SQL
        execution_order = [
            "FROM (identify data sources)",
            "JOIN (combine tables)",
            "WHERE (filter rows)",
            "GROUP BY (aggregate rows)",
            "HAVING (filter groups)",
            "SELECT (choose columns)",
            "DISTINCT (remove duplicates)",
            "ORDER BY (sort results)",
            "LIMIT/OFFSET (restrict output)",
        ]

        return QueryBreakdown(
            steps=steps,
            total_steps=len(steps),
            execution_order=execution_order,
        )

    def _get_cache_key(self, sql: str) -> str:
        """Generate cache key from SQL."""
        normalized = " ".join(sql.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()

    def _get_from_cache(self, key: str) -> ExplanationCacheEntry | None:
        """Get entry from cache if valid."""
        entry = self._cache.get(key)
        if entry and not entry.is_expired():
            return entry
        if entry:
            del self._cache[key]
        return None

    def _add_to_cache(self, key: str, result: QueryExplanationResult) -> None:
        """Add result to cache."""
        ttl = self._settings.explanation.cache_ttl
        expires_at = datetime.now() + timedelta(seconds=ttl)

        self._cache[key] = ExplanationCacheEntry(
            query_id=result.query_id,
            sql_hash=key,
            explanation=result,
            expires_at=expires_at,
        )

        # Clean up old entries if cache is too large
        max_entries = 1000
        if len(self._cache) > max_entries:
            # Remove oldest entries
            sorted_entries = sorted(
                self._cache.items(),
                key=lambda x: x[1].created_at,
            )
            for old_key, _ in sorted_entries[: len(self._cache) - max_entries]:
                del self._cache[old_key]

    def clear_cache(self) -> int:
        """Clear the explanation cache."""
        count = len(self._cache)
        self._cache.clear()
        logger.info("explanation_cache_cleared", entries_removed=count)
        return count

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total_entries = len(self._cache)
        total_hits = sum(e.hit_count for e in self._cache.values())
        expired = sum(1 for e in self._cache.values() if e.is_expired())

        return {
            "total_entries": total_entries,
            "total_hits": total_hits,
            "expired_entries": expired,
            "active_entries": total_entries - expired,
        }


# =============================================================================
# Singleton Instance
# =============================================================================

_engine: ExplanationEngine | None = None


async def get_explanation_engine() -> ExplanationEngine:
    """Get or create the singleton explanation engine instance."""
    global _engine
    if _engine is None:
        _engine = ExplanationEngine()
    return _engine


def reset_explanation_engine() -> None:
    """Reset the singleton (for testing)."""
    global _engine
    _engine = None
