"""
Explanation formatters for different output formats (Issue #15).

This module provides formatters to convert SQL explanations into
various output formats suitable for different use cases.
"""

import json
from abc import ABC, abstractmethod

from app.explanations.models import (
    ComplexityAnalysis,
    OptimizationSuggestion,
    QueryBreakdown,
    QueryExplanationResult,
    SQLExplanation,
    VisualizationFormat,
)
from app.logging_config import get_logger

logger = get_logger(__name__)


# =============================================================================
# Abstract Base Formatter
# =============================================================================


class ExplanationFormatter(ABC):
    """Abstract base class for explanation formatters."""

    @abstractmethod
    def format_explanation(self, explanation: SQLExplanation) -> str:
        """Format SQL explanation."""
        pass

    @abstractmethod
    def format_breakdown(self, breakdown: QueryBreakdown) -> str:
        """Format query breakdown."""
        pass

    @abstractmethod
    def format_complexity(self, complexity: ComplexityAnalysis) -> str:
        """Format complexity analysis."""
        pass

    @abstractmethod
    def format_full(self, result: QueryExplanationResult) -> str:
        """Format complete explanation result."""
        pass


# =============================================================================
# Plain Text Formatter
# =============================================================================


class PlainTextFormatter(ExplanationFormatter):
    """Format explanations as plain text."""

    def __init__(self, line_width: int = 80) -> None:
        """Initialize formatter with line width."""
        self.line_width = line_width

    def format_explanation(self, explanation: SQLExplanation) -> str:
        """Format SQL explanation as plain text."""
        lines = [
            "=" * self.line_width,
            "QUERY EXPLANATION",
            "=" * self.line_width,
            "",
            "Summary:",
            f"  {explanation.summary}",
            "",
            "Data Retrieved:",
            f"  {explanation.data_retrieval}",
            "",
        ]

        if explanation.tables_used:
            lines.append("Tables Used:")
            for table in explanation.tables_used:
                lines.append(f"  - {table}")
            lines.append("")

        if explanation.filters_applied:
            lines.append("Filters Applied:")
            for filter_desc in explanation.filters_applied:
                lines.append(f"  - {filter_desc}")
            lines.append("")

        if explanation.aggregations:
            lines.append("Aggregations:")
            for agg in explanation.aggregations:
                lines.append(f"  - {agg}")
            lines.append("")

        if explanation.sorting:
            lines.append(f"Sorting: {explanation.sorting}")
            lines.append("")

        if explanation.limitations:
            lines.append(f"Limitations: {explanation.limitations}")
            lines.append("")

        lines.append("Detailed Explanation:")
        lines.append(self._wrap_text(explanation.detailed_explanation, 2))

        return "\n".join(lines)

    def format_breakdown(self, breakdown: QueryBreakdown) -> str:
        """Format query breakdown as plain text."""
        lines = [
            "=" * self.line_width,
            "STEP-BY-STEP BREAKDOWN",
            "=" * self.line_width,
            "",
        ]

        for step in breakdown.steps:
            lines.append(f"Step {step.step_number}: {step.clause_type.upper()}")
            lines.append("-" * 40)
            lines.append(f"  SQL: {step.sql_fragment}")
            lines.append(f"  Description: {step.description}")
            lines.append("")

        if breakdown.execution_order:
            lines.append("Logical Execution Order:")
            for i, step_name in enumerate(breakdown.execution_order, 1):
                lines.append(f"  {i}. {step_name}")

        return "\n".join(lines)

    def format_complexity(self, complexity: ComplexityAnalysis) -> str:
        """Format complexity analysis as plain text."""
        lines = [
            "=" * self.line_width,
            "COMPLEXITY ANALYSIS",
            "=" * self.line_width,
            "",
            f"Level: {complexity.level.upper()}",
            f"Score: {complexity.score:.2f} / 1.00",
            f"Difficulty: {complexity.estimated_difficulty}",
            "",
            "Metrics:",
            f"  - Tables: {complexity.table_count}",
            f"  - Joins: {complexity.join_count}",
            f"  - Subqueries: {complexity.subquery_count}",
            f"  - Conditions: {complexity.condition_count}",
            f"  - Aggregates: {complexity.aggregate_count}",
            "",
        ]

        if complexity.factors:
            lines.append("Complexity Factors:")
            for factor in complexity.factors:
                lines.append(f"  - {factor}")

        return "\n".join(lines)

    def format_full(self, result: QueryExplanationResult) -> str:
        """Format complete explanation result as plain text."""
        sections = [
            f"Query ID: {result.query_id}",
            f"Generated: {result.created_at.isoformat()}",
            "",
            "ORIGINAL SQL:",
            self._format_sql(result.sql),
            "",
            self.format_explanation(result.explanation),
            "",
            self.format_breakdown(result.breakdown),
            "",
            self.format_complexity(result.complexity),
        ]

        if result.optimization_hints:
            sections.append("")
            sections.append(self._format_optimization_hints(result.optimization_hints))

        if result.visualization:
            sections.append("")
            sections.append("VISUALIZATION:")
            sections.append(result.visualization.content)

        return "\n".join(sections)

    def _format_sql(self, sql: str) -> str:
        """Format SQL with indentation."""
        return "  " + sql.replace("\n", "\n  ")

    def _format_optimization_hints(self, hints: list[OptimizationSuggestion]) -> str:
        """Format optimization hints."""
        lines = [
            "=" * self.line_width,
            "OPTIMIZATION SUGGESTIONS",
            "=" * self.line_width,
            "",
        ]

        for i, hint in enumerate(hints, 1):
            severity_marker = {"info": "ℹ", "warning": "⚠", "critical": "❌"}.get(
                hint.severity, "•"
            )
            lines.append(f"{i}. [{severity_marker}] {hint.title}")
            lines.append(f"   Category: {hint.category}")
            lines.append(f"   {hint.description}")
            if hint.affected_tables:
                lines.append(f"   Affected tables: {', '.join(hint.affected_tables)}")
            lines.append("")

        return "\n".join(lines)

    def _wrap_text(self, text: str, indent: int = 0) -> str:
        """Wrap text to line width with indentation."""
        prefix = " " * indent
        words = text.split()
        lines = []
        current_line = prefix

        for word in words:
            if len(current_line) + len(word) + 1 <= self.line_width:
                current_line += word + " "
            else:
                lines.append(current_line.rstrip())
                current_line = prefix + word + " "

        if current_line.strip():
            lines.append(current_line.rstrip())

        return "\n".join(lines)


# =============================================================================
# JSON Formatter
# =============================================================================


class JSONFormatter(ExplanationFormatter):
    """Format explanations as JSON."""

    def __init__(self, indent: int = 2) -> None:
        """Initialize formatter with JSON indentation."""
        self.indent = indent

    def format_explanation(self, explanation: SQLExplanation) -> str:
        """Format SQL explanation as JSON."""
        data = {
            "summary": explanation.summary,
            "detailed_explanation": explanation.detailed_explanation,
            "data_retrieval": explanation.data_retrieval,
            "tables_used": explanation.tables_used,
            "filters_applied": explanation.filters_applied,
            "aggregations": explanation.aggregations,
            "sorting": explanation.sorting,
            "limitations": explanation.limitations,
        }
        return json.dumps(data, indent=self.indent)

    def format_breakdown(self, breakdown: QueryBreakdown) -> str:
        """Format query breakdown as JSON."""
        data = {
            "steps": [
                {
                    "step_number": step.step_number,
                    "clause_type": step.clause_type,
                    "description": step.description,
                    "sql_fragment": step.sql_fragment,
                    "elements": step.elements,
                }
                for step in breakdown.steps
            ],
            "total_steps": breakdown.total_steps,
            "execution_order": breakdown.execution_order,
        }
        return json.dumps(data, indent=self.indent)

    def format_complexity(self, complexity: ComplexityAnalysis) -> str:
        """Format complexity analysis as JSON."""
        data = {
            "level": complexity.level,
            "score": complexity.score,
            "table_count": complexity.table_count,
            "join_count": complexity.join_count,
            "subquery_count": complexity.subquery_count,
            "condition_count": complexity.condition_count,
            "aggregate_count": complexity.aggregate_count,
            "factors": complexity.factors,
            "estimated_difficulty": complexity.estimated_difficulty,
        }
        return json.dumps(data, indent=self.indent)

    def format_full(self, result: QueryExplanationResult) -> str:
        """Format complete explanation result as JSON."""
        data = result.model_dump()
        # Convert datetime to ISO format
        data["created_at"] = result.created_at.isoformat()
        return json.dumps(data, indent=self.indent, default=str)


# =============================================================================
# HTML Formatter
# =============================================================================


class HTMLFormatter(ExplanationFormatter):
    """Format explanations as HTML."""

    def format_explanation(self, explanation: SQLExplanation) -> str:
        """Format SQL explanation as HTML."""
        html = [
            '<div class="sql-explanation">',
            "<h2>Query Explanation</h2>",
            f'<div class="summary"><strong>Summary:</strong> {explanation.summary}</div>',
            f'<div class="data-retrieval"><strong>Data Retrieved:</strong> {explanation.data_retrieval}</div>',
        ]

        if explanation.tables_used:
            html.append('<div class="tables"><strong>Tables Used:</strong><ul>')
            for table in explanation.tables_used:
                html.append(f"<li>{self._escape(table)}</li>")
            html.append("</ul></div>")

        if explanation.filters_applied:
            html.append('<div class="filters"><strong>Filters Applied:</strong><ul>')
            for f in explanation.filters_applied:
                html.append(f"<li>{self._escape(f)}</li>")
            html.append("</ul></div>")

        if explanation.aggregations:
            html.append('<div class="aggregations"><strong>Aggregations:</strong><ul>')
            for agg in explanation.aggregations:
                html.append(f"<li>{self._escape(agg)}</li>")
            html.append("</ul></div>")

        if explanation.sorting:
            html.append(
                f'<div class="sorting"><strong>Sorting:</strong> {self._escape(explanation.sorting)}</div>'
            )

        if explanation.limitations:
            html.append(
                f'<div class="limitations"><strong>Limitations:</strong> {self._escape(explanation.limitations)}</div>'
            )

        html.append(
            f'<div class="detailed"><strong>Detailed Explanation:</strong><p>{self._escape(explanation.detailed_explanation)}</p></div>'
        )
        html.append("</div>")

        return "\n".join(html)

    def format_breakdown(self, breakdown: QueryBreakdown) -> str:
        """Format query breakdown as HTML."""
        html = [
            '<div class="query-breakdown">',
            "<h2>Step-by-Step Breakdown</h2>",
            '<ol class="steps">',
        ]

        for step in breakdown.steps:
            html.append('<li class="step">')
            html.append(
                f'<span class="clause-type">{self._escape(step.clause_type)}</span>'
            )
            html.append(
                f'<code class="sql-fragment">{self._escape(step.sql_fragment)}</code>'
            )
            html.append(f'<p class="description">{self._escape(step.description)}</p>')
            html.append("</li>")

        html.append("</ol>")

        if breakdown.execution_order:
            html.append('<div class="execution-order">')
            html.append("<h3>Logical Execution Order:</h3>")
            html.append("<ol>")
            for step_name in breakdown.execution_order:
                html.append(f"<li>{self._escape(step_name)}</li>")
            html.append("</ol></div>")

        html.append("</div>")
        return "\n".join(html)

    def format_complexity(self, complexity: ComplexityAnalysis) -> str:
        """Format complexity analysis as HTML."""
        level_class = f"level-{complexity.level.lower()}"
        html = [
            f'<div class="complexity-analysis {level_class}">',
            "<h2>Complexity Analysis</h2>",
            f'<div class="level"><strong>Level:</strong> <span class="badge">{self._escape(complexity.level.upper())}</span></div>',
            f'<div class="score"><strong>Score:</strong> {complexity.score:.2f} / 1.00</div>',
            f'<div class="difficulty"><strong>Difficulty:</strong> {self._escape(complexity.estimated_difficulty)}</div>',
            '<div class="metrics">',
            "<h3>Metrics</h3>",
            "<table>",
            f"<tr><td>Tables</td><td>{complexity.table_count}</td></tr>",
            f"<tr><td>Joins</td><td>{complexity.join_count}</td></tr>",
            f"<tr><td>Subqueries</td><td>{complexity.subquery_count}</td></tr>",
            f"<tr><td>Conditions</td><td>{complexity.condition_count}</td></tr>",
            f"<tr><td>Aggregates</td><td>{complexity.aggregate_count}</td></tr>",
            "</table>",
            "</div>",
        ]

        if complexity.factors:
            html.append('<div class="factors"><h3>Complexity Factors</h3><ul>')
            for factor in complexity.factors:
                html.append(f"<li>{self._escape(factor)}</li>")
            html.append("</ul></div>")

        html.append("</div>")
        return "\n".join(html)

    def format_full(self, result: QueryExplanationResult) -> str:
        """Format complete explanation result as HTML."""
        html = [
            "<!DOCTYPE html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="UTF-8">',
            "<title>SQL Query Explanation</title>",
            "<style>",
            self._get_css(),
            "</style>",
            "</head>",
            "<body>",
            '<div class="container">',
            f"<h1>Query Explanation: {self._escape(result.query_id)}</h1>",
            f'<div class="timestamp">Generated: {result.created_at.isoformat()}</div>',
            '<div class="original-sql">',
            "<h2>Original SQL</h2>",
            f"<pre><code>{self._escape(result.sql)}</code></pre>",
            "</div>",
            self.format_explanation(result.explanation),
            self.format_breakdown(result.breakdown),
            self.format_complexity(result.complexity),
        ]

        if result.optimization_hints:
            html.append(self._format_optimization_hints(result.optimization_hints))

        if result.visualization:
            html.append('<div class="visualization">')
            html.append("<h2>Query Visualization</h2>")
            html.append(f"<pre>{self._escape(result.visualization.content)}</pre>")
            html.append("</div>")

        html.extend(["</div>", "</body>", "</html>"])
        return "\n".join(html)

    def _format_optimization_hints(self, hints: list[OptimizationSuggestion]) -> str:
        """Format optimization hints as HTML."""
        html = [
            '<div class="optimization-hints">',
            "<h2>Optimization Suggestions</h2>",
            "<ul>",
        ]

        for hint in hints:
            severity_class = f"severity-{hint.severity}"
            html.append(f'<li class="{severity_class}">')
            html.append(f"<strong>{self._escape(hint.title)}</strong>")
            html.append(
                f"<span class='category'>[{self._escape(hint.category)}]</span>"
            )
            html.append(f"<p>{self._escape(hint.description)}</p>")
            if hint.affected_tables:
                html.append(
                    f"<small>Affected tables: {', '.join(hint.affected_tables)}</small>"
                )
            html.append("</li>")

        html.append("</ul></div>")
        return "\n".join(html)

    def _escape(self, text: str) -> str:
        """Escape HTML special characters."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;")
        )

    def _get_css(self) -> str:
        """Get CSS styles for HTML output."""
        return """
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }
            .container { max-width: 900px; margin: 0 auto; padding: 20px; }
            h1, h2, h3 { color: #2c3e50; }
            .timestamp { color: #7f8c8d; font-size: 0.9em; margin-bottom: 20px; }
            .original-sql pre { background: #f4f4f4; padding: 15px; border-radius: 5px; overflow-x: auto; }
            code { font-family: 'Consolas', 'Monaco', monospace; }
            table { border-collapse: collapse; width: 100%; }
            td { padding: 8px; border: 1px solid #ddd; }
            .badge { background: #3498db; color: white; padding: 2px 8px; border-radius: 3px; }
            .level-simple .badge { background: #27ae60; }
            .level-moderate .badge { background: #f39c12; }
            .level-complex .badge { background: #e74c3c; }
            .level-very_complex .badge { background: #8e44ad; }
            .severity-info { border-left: 3px solid #3498db; padding-left: 10px; }
            .severity-warning { border-left: 3px solid #f39c12; padding-left: 10px; }
            .severity-critical { border-left: 3px solid #e74c3c; padding-left: 10px; }
            .sql-fragment { background: #ecf0f1; padding: 2px 6px; border-radius: 3px; }
        """


# =============================================================================
# Markdown Formatter
# =============================================================================


class MarkdownFormatter(ExplanationFormatter):
    """Format explanations as Markdown."""

    def format_explanation(self, explanation: SQLExplanation) -> str:
        """Format SQL explanation as Markdown."""
        lines = [
            "## Query Explanation",
            "",
            f"**Summary:** {explanation.summary}",
            "",
            f"**Data Retrieved:** {explanation.data_retrieval}",
            "",
        ]

        if explanation.tables_used:
            lines.append("**Tables Used:**")
            for table in explanation.tables_used:
                lines.append(f"- {table}")
            lines.append("")

        if explanation.filters_applied:
            lines.append("**Filters Applied:**")
            for f in explanation.filters_applied:
                lines.append(f"- {f}")
            lines.append("")

        if explanation.aggregations:
            lines.append("**Aggregations:**")
            for agg in explanation.aggregations:
                lines.append(f"- {agg}")
            lines.append("")

        if explanation.sorting:
            lines.append(f"**Sorting:** {explanation.sorting}")
            lines.append("")

        if explanation.limitations:
            lines.append(f"**Limitations:** {explanation.limitations}")
            lines.append("")

        lines.extend(
            [
                "**Detailed Explanation:**",
                "",
                explanation.detailed_explanation,
            ]
        )

        return "\n".join(lines)

    def format_breakdown(self, breakdown: QueryBreakdown) -> str:
        """Format query breakdown as Markdown."""
        lines = [
            "## Step-by-Step Breakdown",
            "",
        ]

        for step in breakdown.steps:
            lines.append(f"### Step {step.step_number}: {step.clause_type}")
            lines.append(f"```sql\n{step.sql_fragment}\n```")
            lines.append(f"_{step.description}_")
            lines.append("")

        if breakdown.execution_order:
            lines.append("### Logical Execution Order")
            for i, step_name in enumerate(breakdown.execution_order, 1):
                lines.append(f"{i}. {step_name}")

        return "\n".join(lines)

    def format_complexity(self, complexity: ComplexityAnalysis) -> str:
        """Format complexity analysis as Markdown."""
        lines = [
            "## Complexity Analysis",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Level | **{complexity.level.upper()}** |",
            f"| Score | {complexity.score:.2f} / 1.00 |",
            f"| Difficulty | {complexity.estimated_difficulty} |",
            f"| Tables | {complexity.table_count} |",
            f"| Joins | {complexity.join_count} |",
            f"| Subqueries | {complexity.subquery_count} |",
            f"| Conditions | {complexity.condition_count} |",
            f"| Aggregates | {complexity.aggregate_count} |",
            "",
        ]

        if complexity.factors:
            lines.append("### Complexity Factors")
            for factor in complexity.factors:
                lines.append(f"- {factor}")

        return "\n".join(lines)

    def format_full(self, result: QueryExplanationResult) -> str:
        """Format complete explanation result as Markdown."""
        lines = [
            "# SQL Query Explanation",
            "",
            f"**Query ID:** `{result.query_id}`",
            f"**Generated:** {result.created_at.isoformat()}",
            "",
            "## Original SQL",
            "```sql",
            result.sql,
            "```",
            "",
            self.format_explanation(result.explanation),
            "",
            self.format_breakdown(result.breakdown),
            "",
            self.format_complexity(result.complexity),
        ]

        if result.optimization_hints:
            lines.append("")
            lines.append("## Optimization Suggestions")
            for i, hint in enumerate(result.optimization_hints, 1):
                severity_emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "❌"}.get(
                    hint.severity, "•"
                )
                lines.append(
                    f"{i}. {severity_emoji} **{hint.title}** [{hint.category}]"
                )
                lines.append(f"   {hint.description}")
                if hint.affected_tables:
                    lines.append(
                        f"   _Affected tables: {', '.join(hint.affected_tables)}_"
                    )
                lines.append("")

        if result.visualization:
            lines.append("## Query Visualization")
            lines.append("```")
            lines.append(result.visualization.content)
            lines.append("```")

        return "\n".join(lines)


# =============================================================================
# Formatter Factory
# =============================================================================


def get_formatter(format_type: VisualizationFormat | str) -> ExplanationFormatter:
    """
    Get an explanation formatter for the specified format.

    Args:
        format_type: The output format type

    Returns:
        An appropriate formatter instance
    """
    if isinstance(format_type, str):
        format_type = VisualizationFormat(format_type.lower())

    formatters: dict[VisualizationFormat, ExplanationFormatter] = {
        VisualizationFormat.ASCII: PlainTextFormatter(),
        VisualizationFormat.JSON: JSONFormatter(),
        VisualizationFormat.HTML: HTMLFormatter(),
    }

    return formatters.get(format_type, PlainTextFormatter())


def format_as_markdown(result: QueryExplanationResult) -> str:
    """Convenience function to format result as Markdown."""
    return MarkdownFormatter().format_full(result)
