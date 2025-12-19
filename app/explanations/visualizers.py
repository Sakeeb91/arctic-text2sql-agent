"""
Query visualization generators (Issue #15).

This module provides visualization capabilities for SQL queries,
including ASCII tree diagrams, flow charts, and execution plan
visualizations.
"""

from typing import Any

from app.explanations.models import (
    ClauseBreakdown,
    ExecutionPlanNode,
    JoinInfo,
    QueryVisualization,
    SQLClauseType,
    TableReference,
    VisualizationFormat,
)
from app.logging_config import get_logger

logger = get_logger(__name__)


# =============================================================================
# ASCII Tree Visualizer
# =============================================================================


class ASCIITreeVisualizer:
    """Generate ASCII tree visualizations of SQL query structure."""

    def __init__(self, max_width: int = 80) -> None:
        """Initialize with maximum width."""
        self.max_width = max_width
        self.box_chars = {
            "horizontal": "─",
            "vertical": "│",
            "top_left": "┌",
            "top_right": "┐",
            "bottom_left": "└",
            "bottom_right": "┘",
            "tee_right": "├",
            "tee_left": "┤",
            "tee_down": "┬",
            "tee_up": "┴",
            "cross": "┼",
            "arrow_right": "→",
            "arrow_down": "↓",
        }

    def visualize_query_structure(
        self,
        clauses: list[ClauseBreakdown],
        tables: list[TableReference],
        joins: list[JoinInfo],
    ) -> QueryVisualization:
        """
        Generate ASCII visualization of query structure.

        Args:
            clauses: List of SQL clause breakdowns
            tables: List of table references
            joins: List of join information

        Returns:
            QueryVisualization with ASCII content
        """
        lines = []

        # Header
        lines.append(self._create_box("SQL QUERY STRUCTURE", width=40))
        lines.append("")

        # Clause flow
        lines.append("Clause Flow:")
        lines.append(self._create_clause_flow(clauses))
        lines.append("")

        # Table relationships
        if tables:
            lines.append("Tables:")
            lines.append(self._create_table_tree(tables, joins))
            lines.append("")

        # Join relationships
        if joins:
            lines.append("Join Relationships:")
            lines.append(self._create_join_diagram(joins))

        content = "\n".join(lines)
        return QueryVisualization(
            format=VisualizationFormat.ASCII.value,
            content=content,
            width=self.max_width,
            height=len(lines),
        )

    def visualize_execution_plan(self, root: ExecutionPlanNode) -> QueryVisualization:
        """
        Generate ASCII visualization of execution plan.

        Args:
            root: Root node of execution plan tree

        Returns:
            QueryVisualization with ASCII content
        """
        lines = [
            self._create_box("EXECUTION PLAN", width=40),
            "",
        ]

        self._render_plan_node(root, lines, prefix="", is_last=True)

        content = "\n".join(lines)
        return QueryVisualization(
            format=VisualizationFormat.ASCII.value,
            content=content,
            width=self.max_width,
            height=len(lines),
        )

    def _create_box(self, text: str, width: int | None = None) -> str:
        """Create a text box."""
        if width is None:
            width = len(text) + 4

        top = (
            self.box_chars["top_left"]
            + self.box_chars["horizontal"] * (width - 2)
            + self.box_chars["top_right"]
        )
        middle = (
            self.box_chars["vertical"]
            + f" {text.center(width - 4)} "
            + self.box_chars["vertical"]
        )
        bottom = (
            self.box_chars["bottom_left"]
            + self.box_chars["horizontal"] * (width - 2)
            + self.box_chars["bottom_right"]
        )

        return f"{top}\n{middle}\n{bottom}"

    def _create_clause_flow(self, clauses: list[ClauseBreakdown]) -> str:
        """Create a flow diagram of SQL clauses."""
        if not clauses:
            return "  (no clauses)"

        lines = []
        clause_order = [
            SQLClauseType.SELECT,
            SQLClauseType.FROM,
            SQLClauseType.JOIN,
            SQLClauseType.WHERE,
            SQLClauseType.GROUP_BY,
            SQLClauseType.HAVING,
            SQLClauseType.ORDER_BY,
            SQLClauseType.LIMIT,
        ]

        clause_map = {c.clause_type: c for c in clauses}

        prev_had_clause = False
        for clause_type in clause_order:
            if clause_type in clause_map:
                clause = clause_map[clause_type]
                if prev_had_clause:
                    lines.append(f"      {self.box_chars['arrow_down']}")
                lines.append(f"  [{clause_type.value.upper():^12}]")
                # Truncate raw text if too long
                raw_text = (
                    clause.raw_text[:40] + "..."
                    if len(clause.raw_text) > 40
                    else clause.raw_text
                )
                lines.append(f"  └{self.box_chars['arrow_right']} {raw_text}")
                prev_had_clause = True

        return "\n".join(lines)

    def _create_table_tree(
        self, tables: list[TableReference], _joins: list[JoinInfo]
    ) -> str:
        """Create a tree diagram of table relationships."""
        lines = []

        for i, table in enumerate(tables):
            is_last = i == len(tables) - 1
            prefix = (
                self.box_chars["bottom_left"]
                if is_last
                else self.box_chars["tee_right"]
            )

            table_display = table.table_name
            if table.alias:
                table_display += f" AS {table.alias}"
            if table.schema_name:
                table_display = f"{table.schema_name}.{table_display}"

            lines.append(f"  {prefix}{self.box_chars['horizontal']*2} {table_display}")

        return "\n".join(lines)

    def _create_join_diagram(self, joins: list[JoinInfo]) -> str:
        """Create a diagram of join relationships."""
        lines = []

        for join in joins:
            join_type = join.join_type.value.upper()
            left = join.left_table
            right = join.right_table
            condition = (
                join.condition[:30] + "..."
                if len(join.condition) > 30
                else join.condition
            )

            lines.append(f"  {left} ─[{join_type}]─ {right}")
            lines.append(f"     └─ ON: {condition}")

        return "\n".join(lines)

    def _render_plan_node(
        self,
        node: ExecutionPlanNode,
        lines: list[str],
        prefix: str,
        is_last: bool,
    ) -> None:
        """Recursively render execution plan node."""
        connector = (
            self.box_chars["bottom_left"] if is_last else self.box_chars["tee_right"]
        )

        # Node header
        cost_str = f" (cost: {node.estimated_cost:.2f})" if node.estimated_cost else ""
        lines.append(
            f"{prefix}{connector}{self.box_chars['horizontal']*2} {node.node_type}{cost_str}"
        )

        # Node description
        child_prefix = prefix + (
            "   " if is_last else f"{self.box_chars['vertical']}  "
        )
        lines.append(f"{child_prefix}   {node.description}")

        # Render children
        for i, child in enumerate(node.children):
            self._render_plan_node(
                child,
                lines,
                child_prefix,
                i == len(node.children) - 1,
            )


# =============================================================================
# Mermaid Visualizer
# =============================================================================


class MermaidVisualizer:
    """Generate Mermaid diagram visualizations."""

    def visualize_query_flow(
        self,
        clauses: list[ClauseBreakdown],
        tables: list[TableReference],
        joins: list[JoinInfo],
    ) -> QueryVisualization:
        """
        Generate Mermaid flowchart of query structure.

        Args:
            clauses: List of SQL clause breakdowns
            tables: List of table references
            joins: List of join information

        Returns:
            QueryVisualization with Mermaid content
        """
        lines = [
            "```mermaid",
            "flowchart TD",
        ]

        # Add clauses as nodes
        clause_ids: dict[SQLClauseType, str] = {}
        for i, clause in enumerate(clauses):
            node_id = f"C{i}"
            clause_ids[clause.clause_type] = node_id
            label = clause.clause_type.value.upper()
            lines.append(f"    {node_id}[{label}]")

        # Connect clauses
        prev_id = None
        for clause in clauses:
            curr_id = clause_ids.get(clause.clause_type)
            if prev_id and curr_id:
                lines.append(f"    {prev_id} --> {curr_id}")
            prev_id = curr_id

        # Add table subgraph
        if tables:
            lines.append("    subgraph Tables")
            for i, table in enumerate(tables):
                table_name = table.alias or table.table_name
                lines.append(f"        T{i}(({table_name}))")
            lines.append("    end")

        # Add join relationships
        for join in joins:
            left_idx = self._find_table_idx(tables, join.left_table)
            right_idx = self._find_table_idx(tables, join.right_table)
            if left_idx >= 0 and right_idx >= 0:
                lines.append(
                    f"    T{left_idx} -.->|{join.join_type.value}| T{right_idx}"
                )

        lines.append("```")

        return QueryVisualization(
            format=VisualizationFormat.MERMAID.value,
            content="\n".join(lines),
        )

    def visualize_execution_plan(self, root: ExecutionPlanNode) -> QueryVisualization:
        """
        Generate Mermaid flowchart of execution plan.

        Args:
            root: Root node of execution plan tree

        Returns:
            QueryVisualization with Mermaid content
        """
        lines = [
            "```mermaid",
            "flowchart TD",
        ]

        node_counter = [0]
        self._render_mermaid_node(root, lines, node_counter, None)

        lines.append("```")

        return QueryVisualization(
            format=VisualizationFormat.MERMAID.value,
            content="\n".join(lines),
        )

    def _render_mermaid_node(
        self,
        node: ExecutionPlanNode,
        lines: list[str],
        counter: list[int],
        parent_id: str | None,
    ) -> str:
        """Recursively render node to Mermaid format."""
        node_id = f"N{counter[0]}"
        counter[0] += 1

        # Create node
        label = node.node_type
        if node.estimated_cost:
            label += f"<br/>cost: {node.estimated_cost:.2f}"
        lines.append(f'    {node_id}["{label}"]')

        # Connect to parent
        if parent_id:
            lines.append(f"    {parent_id} --> {node_id}")

        # Render children
        for child in node.children:
            self._render_mermaid_node(child, lines, counter, node_id)

        return node_id

    def _find_table_idx(self, tables: list[TableReference], name: str) -> int:
        """Find table index by name or alias."""
        for i, table in enumerate(tables):
            if table.table_name == name or table.alias == name:
                return i
        return -1


# =============================================================================
# JSON Visualizer
# =============================================================================


class JSONVisualizer:
    """Generate JSON structure visualizations."""

    def visualize_query_structure(
        self,
        clauses: list[ClauseBreakdown],
        tables: list[TableReference],
        joins: list[JoinInfo],
    ) -> QueryVisualization:
        """
        Generate JSON representation of query structure.

        Args:
            clauses: List of SQL clause breakdowns
            tables: List of table references
            joins: List of join information

        Returns:
            QueryVisualization with JSON content
        """
        import json

        structure = {
            "clauses": [
                {
                    "type": c.clause_type.value,
                    "raw_text": c.raw_text,
                    "explanation": c.explanation,
                }
                for c in clauses
            ],
            "tables": [t.to_dict() for t in tables],
            "joins": [j.to_dict() for j in joins],
        }

        return QueryVisualization(
            format=VisualizationFormat.JSON.value,
            content=json.dumps(structure, indent=2),
        )

    def visualize_execution_plan(self, root: ExecutionPlanNode) -> QueryVisualization:
        """
        Generate JSON representation of execution plan.

        Args:
            root: Root node of execution plan tree

        Returns:
            QueryVisualization with JSON content
        """
        import json

        return QueryVisualization(
            format=VisualizationFormat.JSON.value,
            content=json.dumps(root.to_dict(), indent=2),
        )


# =============================================================================
# Factory Function
# =============================================================================


def get_visualizer(
    format_type: VisualizationFormat | str,
) -> ASCIITreeVisualizer | MermaidVisualizer | JSONVisualizer:
    """
    Get a visualizer for the specified format.

    Args:
        format_type: The visualization format

    Returns:
        An appropriate visualizer instance
    """
    if isinstance(format_type, str):
        format_type = VisualizationFormat(format_type.lower())

    visualizers: dict[
        VisualizationFormat, ASCIITreeVisualizer | MermaidVisualizer | JSONVisualizer
    ] = {
        VisualizationFormat.ASCII: ASCIITreeVisualizer(),
        VisualizationFormat.MERMAID: MermaidVisualizer(),
        VisualizationFormat.JSON: JSONVisualizer(),
        VisualizationFormat.HTML: ASCIITreeVisualizer(),  # HTML uses ASCII wrapped
    }

    result = visualizers.get(format_type)
    if result is None:
        return ASCIITreeVisualizer()
    return result


def visualize_query(
    clauses: list[ClauseBreakdown],
    tables: list[TableReference],
    joins: list[JoinInfo],
    format_type: VisualizationFormat = VisualizationFormat.ASCII,
) -> QueryVisualization:
    """
    Convenience function to visualize query structure.

    Args:
        clauses: List of SQL clause breakdowns
        tables: List of table references
        joins: List of join information
        format_type: Output format

    Returns:
        QueryVisualization
    """
    visualizer = get_visualizer(format_type)
    if hasattr(visualizer, "visualize_query_structure"):
        return visualizer.visualize_query_structure(clauses, tables, joins)
    if hasattr(visualizer, "visualize_query_flow"):
        return visualizer.visualize_query_flow(clauses, tables, joins)
    # Fallback to ASCII
    return ASCIITreeVisualizer().visualize_query_structure(clauses, tables, joins)
