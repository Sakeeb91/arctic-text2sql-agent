"""
Agent tools for Text2SQL operations.

This module defines the tools used by the smolagents CodeAgent
for SQL generation, execution, and validation.

Tools:
- sql_executor: Execute SQL queries with schema context
- result_validator: Validate query results against intent
- schema_inspector: Inspect database schema
"""

import re
from typing import Any

from smolagents import tool

from app.logging_config import get_logger

logger = get_logger(__name__)


# =============================================================================
# SQL Executor Tool
# =============================================================================


def create_sql_executor_tool(
    db_manager: Any,
    schema_description: str,
    max_rows: int = 100,
) -> Any:
    """
    Create a SQL executor tool with embedded schema description.

    The schema is embedded directly in the tool's docstring so the
    agent knows what tables and columns are available.

    Args:
        db_manager: Database manager for executing queries
        schema_description: Formatted schema description for the tool docstring
        max_rows: Maximum rows to return

    Returns:
        A tool function for SQL execution
    """

    @tool  # type: ignore[misc]
    def sql_executor(query: str) -> str:
        """
        Execute SQL queries on the database and return results.

        Use this tool to run SELECT queries against the database.
        Always use proper SQL syntax for the database dialect.

        Args:
            query: SQL query to execute. Must be a SELECT or WITH statement.

        Returns:
            String representation of query results, or error message if failed.

        {schema_placeholder}
        """
        import asyncio

        from db.executor import SafeQueryExecutor

        logger.info(
            "sql_executor_tool_called",
            query_preview=query[:100] if query else "",
        )

        try:
            # Get or create event loop
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            # Execute the query
            async def execute_query() -> str:
                async with db_manager.session() as session:
                    executor = SafeQueryExecutor(
                        session=session,
                        allow_mutations=False,
                        max_rows=max_rows,
                    )

                    result = await executor.execute(query)

                    if not result.rows:
                        return "Query executed successfully but returned no rows."

                    # Format results as readable text
                    output_lines = [f"Query returned {result.row_count} rows:"]

                    # Add column headers
                    if result.columns:
                        output_lines.append("Columns: " + ", ".join(result.columns))
                        output_lines.append("-" * 50)

                    # Add rows (limit display for readability)
                    display_rows = result.rows[:10]
                    for i, row in enumerate(display_rows, 1):
                        row_str = ", ".join(f"{k}={v}" for k, v in row.items())
                        output_lines.append(f"Row {i}: {row_str}")

                    if result.row_count > 10:
                        output_lines.append(
                            f"... and {result.row_count - 10} more rows"
                        )

                    if result.warnings:
                        output_lines.append("Warnings: " + "; ".join(result.warnings))

                    return "\n".join(output_lines)

            return loop.run_until_complete(execute_query())

        except Exception as e:
            error_msg = f"Error executing query: {e!s}"
            logger.error("sql_executor_tool_error", error=str(e), query=query[:100])
            return error_msg

    # Update the docstring with actual schema
    sql_executor.__doc__ = sql_executor.__doc__.replace(
        "{schema_placeholder}",
        f"Available Database Schema:\n\n{schema_description}",
    )

    return sql_executor


# =============================================================================
# Result Validator Tool
# =============================================================================


@tool  # type: ignore[misc]
def result_validator(results: str, original_question: str, sql_query: str) -> str:
    """
    Validate if query results make sense for the original question.

    Use this tool to check if the SQL query results correctly answer
    the user's question. It will return VALID if results seem correct,
    or provide suggestions for correction if there are issues.

    Args:
        results: The query results as a string (from sql_executor)
        original_question: The original natural language question
        sql_query: The SQL query that was executed

    Returns:
        'VALID' if results seem correct, or a suggestion message for correction.
    """
    logger.info(
        "result_validator_tool_called",
        question_length=len(original_question),
        has_results=bool(results),
    )

    results_lower = results.lower()
    question_lower = original_question.lower()
    sql_upper = sql_query.upper()

    warnings: list[str] = []

    # Check for execution errors
    if "error" in results_lower:
        return f"INVALID: Query execution failed. Error: {results}"

    # Check for empty results when they shouldn't be
    no_results = "no rows" in results_lower or "returned 0 rows" in results_lower
    expects_list = any(
        word in question_lower for word in ["all", "every", "list", "show"]
    )
    if no_results and expects_list:
        warnings.append(
            "Query returned no results but question asks for a list. "
            "Check if table name is correct or if WHERE clause is too restrictive."
        )

    # Check for aggregation mismatch
    aggregation_words = ["total", "sum", "average", "count", "how many", "max", "min"]
    needs_aggregation = any(word in question_lower for word in aggregation_words)

    has_aggregation = any(
        func in sql_upper
        for func in ["SUM(", "COUNT(", "AVG(", "MAX(", "MIN(", "GROUP BY"]
    )

    if needs_aggregation and not has_aggregation:
        warnings.append(
            "Question asks for aggregation (total/count/average) but SQL has no "
            "aggregation functions. Consider using SUM(), COUNT(), AVG(), etc."
        )

    # Check if multiple rows returned when expecting single value
    has_multiple_rows = "row 2:" in results_lower
    superlative_words = ["the most", "the highest", "the lowest", "the best", "which"]
    expects_single = any(word in question_lower for word in superlative_words)
    missing_order_limit = "LIMIT 1" not in sql_upper and "ORDER BY" not in sql_upper
    if has_multiple_rows and expects_single and missing_order_limit:
        warnings.append(
            "Question asks for 'the most/highest/lowest' but query "
            "returned multiple rows. Consider adding ORDER BY and LIMIT 1."
        )

    # Check for join requirements
    join_indicators = ["with their", "and their", "along with", "for each", "per"]
    needs_join = any(indicator in question_lower for indicator in join_indicators)

    if needs_join and "JOIN" not in sql_upper:
        warnings.append(
            "Question seems to need data from multiple tables but SQL has no JOIN. "
            "Consider joining related tables."
        )

    # Check for specific column issues
    if "customer" in question_lower and "customer" not in sql_upper.lower():
        warnings.append(
            "Question mentions 'customer' but it's not in the query. "
            "Check if correct table/column is being used."
        )

    if warnings:
        return "NEEDS_CORRECTION: " + " | ".join(warnings)

    return "VALID: Results appear to correctly answer the question."


# =============================================================================
# Schema Inspector Tool
# =============================================================================


def create_schema_inspector_tool(db_manager: Any) -> Any:
    """
    Create a schema inspector tool for looking up table details.

    Args:
        db_manager: Database manager for schema introspection

    Returns:
        A tool function for schema inspection
    """

    @tool  # type: ignore[misc]
    def schema_inspector(table_name: str) -> str:
        """
        Get detailed information about a specific database table.

        Use this tool when you need more details about a table's columns,
        types, primary keys, or foreign key relationships.

        Args:
            table_name: Name of the table to inspect

        Returns:
            Detailed schema information for the table, or error if not found.
        """
        import asyncio

        from db.schema import SchemaIntrospector

        logger.info("schema_inspector_tool_called", table_name=table_name)

        try:
            # Get or create event loop
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            async def get_table_info() -> str:
                introspector = SchemaIntrospector(db_manager.engine)
                schema = await introspector.get_schema(
                    database_id="default",
                    include_row_counts=False,
                )

                # Find the requested table
                target_table = None
                available_tables: list[str] = []

                for table in schema.tables:
                    available_tables.append(table.name)
                    if table.name.lower() == table_name.lower():
                        target_table = table
                        break

                if target_table is None:
                    return (
                        f"Table '{table_name}' not found. "
                        f"Available tables: {', '.join(available_tables)}"
                    )

                # Format table information
                output_lines = [f"Table: {target_table.name}"]
                output_lines.append("")
                output_lines.append("Columns:")

                for col in target_table.columns:
                    col_info = f"  - {col.name} ({col.data_type})"
                    if col.primary_key:
                        col_info += " PRIMARY KEY"
                    if not col.nullable:
                        col_info += " NOT NULL"
                    if col.foreign_key:
                        col_info += f" FOREIGN KEY -> {col.foreign_key}"
                    if col.default:
                        col_info += f" DEFAULT {col.default}"
                    output_lines.append(col_info)

                if target_table.foreign_keys:
                    output_lines.append("")
                    output_lines.append("Foreign Key Relationships:")
                    for fk in target_table.foreign_keys:
                        fk_info = (
                            f"  - {fk.column} -> "
                            f"{fk.references_table}({fk.references_column})"
                        )
                        output_lines.append(fk_info)

                return "\n".join(output_lines)

            return loop.run_until_complete(get_table_info())

        except Exception as e:
            error_msg = f"Error inspecting table '{table_name}': {e!s}"
            logger.error("schema_inspector_tool_error", error=str(e), table=table_name)
            return error_msg

    return schema_inspector


# =============================================================================
# SQL Generator Tool (for local model)
# =============================================================================


def create_sql_generator_tool(model_loader: Any, schema_description: str) -> Any:
    """
    Create a SQL generator tool using the local Text2SQL model.

    This tool uses the Snowflake Arctic model to generate SQL from
    natural language, providing an alternative to the agent's own
    code generation.

    Args:
        model_loader: Model loader with Text2SQL model
        schema_description: Schema description for prompt

    Returns:
        A tool function for SQL generation
    """

    @tool  # type: ignore[misc]
    def sql_generator(question: str) -> str:
        """
        Generate SQL query from a natural language question.

        Use this tool to convert a natural language question into
        a SQL query using the specialized Text2SQL model.

        Args:
            question: Natural language question about the data

        Returns:
            Generated SQL query or error message.
        """
        import asyncio

        from models.inference import InferenceEngine
        from models.prompts import build_prompt

        logger.info(
            "sql_generator_tool_called",
            question_length=len(question),
        )

        try:
            # Get or create event loop
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            async def generate_sql() -> str:
                # Ensure model is loaded
                if not model_loader.is_loaded:
                    await model_loader.load()

                # Build prompt with schema
                prompt = build_prompt(
                    question=question,
                    schema=schema_description,
                    template_type="arctic",
                    dialect="postgresql",
                )

                # Create inference engine and generate
                inference_engine = InferenceEngine(model_loader)
                result = await inference_engine.generate(prompt, extract_sql=True)

                if result.sql:
                    confidence_info = f" (confidence: {result.confidence:.2f})"
                    return f"{result.sql}{confidence_info}"
                else:
                    return f"Could not extract SQL from model output: {result.generated_text[:200]}"

            return loop.run_until_complete(generate_sql())

        except Exception as e:
            error_msg = f"Error generating SQL: {e!s}"
            logger.error("sql_generator_tool_error", error=str(e))
            return error_msg

    return sql_generator


# =============================================================================
# Utility Functions
# =============================================================================


def extract_sql_from_text(text: str) -> str | None:
    """
    Extract SQL query from agent output text.

    The agent may output SQL in various formats, so we try multiple
    extraction patterns.

    Args:
        text: Text containing SQL query

    Returns:
        Extracted SQL or None if not found
    """
    text = text.strip()

    # Try code blocks first
    patterns = [
        r"```sql\s*(.*?)\s*```",
        r"```\s*(SELECT.*?)```",
        r"```\s*(WITH.*?)```",
        r"<sql>(.*?)</sql>",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()

    # Check if the whole text looks like SQL
    if re.match(r"^\s*(SELECT|WITH)\s", text, re.IGNORECASE):
        # Take until double newline or end
        lines: list[str] = []
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped and lines:
                break
            if stripped:
                lines.append(line)
        return "\n".join(lines).strip()

    # Look for SQL anywhere in text
    sql_match = re.search(
        r"(SELECT\s+.*?(?:;|$))",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if sql_match:
        return sql_match.group(1).strip().rstrip(";") + ";"

    return None
