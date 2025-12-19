"""
SQL parsing utilities for query explanation (Issue #15).

This module provides SQL parsing capabilities to extract structural
information from SQL queries for explanation and visualization.
"""

import re
from typing import Any

from app.explanations.models import (
    AggregateFunction,
    ClauseBreakdown,
    ColumnReference,
    FilterCondition,
    JoinInfo,
    JoinType,
    SQLClauseType,
    TableReference,
)
from app.logging_config import get_logger

logger = get_logger(__name__)

# =============================================================================
# SQL Keyword Patterns
# =============================================================================

# Common SQL keywords for detection
SQL_KEYWORDS = {
    "select",
    "from",
    "where",
    "join",
    "inner",
    "left",
    "right",
    "full",
    "outer",
    "cross",
    "natural",
    "on",
    "and",
    "or",
    "not",
    "in",
    "between",
    "like",
    "is",
    "null",
    "group",
    "by",
    "having",
    "order",
    "asc",
    "desc",
    "limit",
    "offset",
    "union",
    "all",
    "distinct",
    "as",
    "case",
    "when",
    "then",
    "else",
    "end",
    "with",
    "over",
    "partition",
    "window",
    "exists",
}

# Aggregate function patterns
AGGREGATE_FUNCTIONS = {
    "count": AggregateFunction.COUNT,
    "sum": AggregateFunction.SUM,
    "avg": AggregateFunction.AVG,
    "min": AggregateFunction.MIN,
    "max": AggregateFunction.MAX,
    "group_concat": AggregateFunction.GROUP_CONCAT,
    "string_agg": AggregateFunction.STRING_AGG,
}

# Join type patterns
JOIN_PATTERNS = {
    r"\binner\s+join\b": JoinType.INNER,
    r"\bleft\s+(?:outer\s+)?join\b": JoinType.LEFT,
    r"\bright\s+(?:outer\s+)?join\b": JoinType.RIGHT,
    r"\bfull\s+(?:outer\s+)?join\b": JoinType.FULL,
    r"\bcross\s+join\b": JoinType.CROSS,
    r"\bnatural\s+join\b": JoinType.NATURAL,
    r"\bjoin\b": JoinType.INNER,  # Default join is INNER
}


# =============================================================================
# SQL Parser Class
# =============================================================================


class SQLParser:
    """
    Parser for extracting structural information from SQL queries.

    This parser uses regex-based pattern matching to identify SQL
    clauses and extract relevant information without requiring a
    full SQL grammar parser.
    """

    def __init__(self) -> None:
        """Initialize the SQL parser."""
        self._clause_patterns = self._compile_clause_patterns()

    def _compile_clause_patterns(self) -> dict[SQLClauseType, re.Pattern[str]]:
        """Compile regex patterns for SQL clause extraction."""
        return {
            SQLClauseType.SELECT: re.compile(
                r"\bselect\s+(.*?)(?=\bfrom\b|\Z)", re.IGNORECASE | re.DOTALL
            ),
            SQLClauseType.FROM: re.compile(
                r"\bfrom\s+(.*?)(?=\bwhere\b|\bjoin\b|\bgroup\b|\border\b|\blimit\b|\Z)",
                re.IGNORECASE | re.DOTALL,
            ),
            SQLClauseType.WHERE: re.compile(
                r"\bwhere\s+(.*?)(?=\bgroup\b|\border\b|\blimit\b|\bunion\b|\Z)",
                re.IGNORECASE | re.DOTALL,
            ),
            SQLClauseType.GROUP_BY: re.compile(
                r"\bgroup\s+by\s+(.*?)(?=\bhaving\b|\border\b|\blimit\b|\bunion\b|\Z)",
                re.IGNORECASE | re.DOTALL,
            ),
            SQLClauseType.HAVING: re.compile(
                r"\bhaving\s+(.*?)(?=\border\b|\blimit\b|\bunion\b|\Z)",
                re.IGNORECASE | re.DOTALL,
            ),
            SQLClauseType.ORDER_BY: re.compile(
                r"\border\s+by\s+(.*?)(?=\blimit\b|\boffset\b|\bunion\b|\Z)",
                re.IGNORECASE | re.DOTALL,
            ),
            SQLClauseType.LIMIT: re.compile(r"\blimit\s+(\d+)", re.IGNORECASE),
            SQLClauseType.OFFSET: re.compile(r"\boffset\s+(\d+)", re.IGNORECASE),
        }

    def parse(self, sql: str) -> dict[str, Any]:
        """
        Parse a SQL query and extract structural information.

        Args:
            sql: SQL query string to parse

        Returns:
            Dictionary containing parsed SQL components
        """
        # Normalize whitespace
        normalized_sql = self._normalize_sql(sql)

        result: dict[str, Any] = {
            "original_sql": sql,
            "normalized_sql": normalized_sql,
            "query_type": self._detect_query_type(normalized_sql),
            "clauses": {},
            "tables": [],
            "columns": [],
            "joins": [],
            "conditions": [],
            "has_subquery": self._has_subquery(normalized_sql),
            "has_cte": self._has_cte(normalized_sql),
            "has_union": self._has_union(normalized_sql),
            "has_distinct": self._has_distinct(normalized_sql),
            "has_window_function": self._has_window_function(normalized_sql),
        }

        # Extract clauses
        for clause_type, pattern in self._clause_patterns.items():
            match = pattern.search(normalized_sql)
            if match:
                result["clauses"][clause_type.value] = match.group(1).strip()

        # Extract tables
        result["tables"] = self._extract_tables(normalized_sql)

        # Extract columns
        result["columns"] = self._extract_columns(normalized_sql)

        # Extract joins
        result["joins"] = self._extract_joins(normalized_sql)

        # Extract conditions
        result["conditions"] = self._extract_conditions(normalized_sql)

        return result

    def _normalize_sql(self, sql: str) -> str:
        """Normalize SQL for consistent parsing."""
        # Remove comments
        sql = re.sub(r"--.*$", "", sql, flags=re.MULTILINE)
        sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
        # Normalize whitespace
        sql = " ".join(sql.split())
        return sql.strip()

    def _detect_query_type(self, sql: str) -> str:
        """Detect the type of SQL query."""
        sql_upper = sql.upper().strip()
        if sql_upper.startswith("SELECT"):
            return "SELECT"
        if sql_upper.startswith("INSERT"):
            return "INSERT"
        if sql_upper.startswith("UPDATE"):
            return "UPDATE"
        if sql_upper.startswith("DELETE"):
            return "DELETE"
        if sql_upper.startswith("WITH"):
            return "CTE"
        return "UNKNOWN"

    def _has_subquery(self, sql: str) -> bool:
        """Check if query contains a subquery."""
        # Count parentheses with SELECT inside
        pattern = r"\(\s*select\b"
        return bool(re.search(pattern, sql, re.IGNORECASE))

    def _has_cte(self, sql: str) -> bool:
        """Check if query uses Common Table Expressions."""
        return bool(re.match(r"^\s*with\b", sql, re.IGNORECASE))

    def _has_union(self, sql: str) -> bool:
        """Check if query contains UNION."""
        return bool(re.search(r"\bunion\b", sql, re.IGNORECASE))

    def _has_distinct(self, sql: str) -> bool:
        """Check if query uses DISTINCT."""
        return bool(re.search(r"\bselect\s+distinct\b", sql, re.IGNORECASE))

    def _has_window_function(self, sql: str) -> bool:
        """Check if query uses window functions."""
        return bool(re.search(r"\bover\s*\(", sql, re.IGNORECASE))

    def _extract_tables(self, sql: str) -> list[TableReference]:
        """Extract table references from SQL."""
        tables: list[TableReference] = []

        # Extract from FROM clause
        from_match = re.search(
            r"\bfrom\s+([\w\s,\.\"'`]+?)(?=\b(?:where|join|group|order|limit|$))",
            sql,
            re.IGNORECASE,
        )
        if from_match:
            from_clause = from_match.group(1)
            # Split by comma and parse each table
            for table_str in from_clause.split(","):
                table_str = table_str.strip()
                if table_str:
                    table = self._parse_table_reference(table_str)
                    if table:
                        tables.append(table)

        # Extract from JOINs
        join_pattern = r"\bjoin\s+([\w\s\.\"'`]+?)(?:\s+(?:as\s+)?(\w+))?\s+on\b"
        for match in re.finditer(join_pattern, sql, re.IGNORECASE):
            table_name = match.group(1).strip()
            alias = match.group(2)
            tables.append(TableReference(table_name=table_name, alias=alias))

        return tables

    def _parse_table_reference(self, table_str: str) -> TableReference | None:
        """Parse a table reference string."""
        # Handle alias patterns: "table AS alias" or "table alias"
        match = re.match(
            r"([\w\.\"`']+)\s+(?:as\s+)?(\w+)?",
            table_str.strip(),
            re.IGNORECASE,
        )
        if match:
            table_name = match.group(1).strip("\"'`")
            alias = match.group(2)
            # Handle schema.table pattern
            schema_name = None
            if "." in table_name:
                parts = table_name.split(".")
                schema_name = parts[0]
                table_name = parts[1]
            return TableReference(
                table_name=table_name,
                alias=alias,
                schema_name=schema_name,
            )
        # Simple table name
        table_name = table_str.strip().strip("\"'`")
        if table_name and table_name.lower() not in SQL_KEYWORDS:
            return TableReference(table_name=table_name)
        return None

    def _extract_columns(self, sql: str) -> list[ColumnReference]:
        """Extract column references from SELECT clause."""
        columns: list[ColumnReference] = []

        select_match = re.search(
            r"\bselect\s+(.*?)\s+from\b",
            sql,
            re.IGNORECASE | re.DOTALL,
        )
        if not select_match:
            return columns

        select_clause = select_match.group(1)

        # Handle SELECT *
        if select_clause.strip() == "*":
            columns.append(ColumnReference(column_name="*"))
            return columns

        # Split by comma, handling nested parentheses
        column_strs = self._split_columns(select_clause)

        for col_str in column_strs:
            col_str = col_str.strip()
            if not col_str:
                continue

            column = self._parse_column_reference(col_str)
            if column:
                columns.append(column)

        return columns

    def _split_columns(self, select_clause: str) -> list[str]:
        """Split SELECT clause by commas, respecting parentheses."""
        columns = []
        current = ""
        paren_depth = 0

        for char in select_clause:
            if char == "(":
                paren_depth += 1
                current += char
            elif char == ")":
                paren_depth -= 1
                current += char
            elif char == "," and paren_depth == 0:
                columns.append(current.strip())
                current = ""
            else:
                current += char

        if current.strip():
            columns.append(current.strip())

        return columns

    def _parse_column_reference(self, col_str: str) -> ColumnReference | None:
        """Parse a column reference string."""
        # Check for aggregate function
        agg_match = re.match(
            r"(\w+)\s*\((.*?)\)(?:\s+as\s+(\w+))?",
            col_str,
            re.IGNORECASE,
        )
        if agg_match:
            func_name = agg_match.group(1).lower()
            inner = agg_match.group(2).strip()
            alias = agg_match.group(3)

            if func_name in AGGREGATE_FUNCTIONS:
                return ColumnReference(
                    column_name=inner,
                    alias=alias,
                    is_aggregate=True,
                    aggregate_function=AGGREGATE_FUNCTIONS[func_name],
                )

        # Handle table.column AS alias pattern
        match = re.match(
            r"(?:(\w+)\.)?(\w+|\*)(?:\s+as\s+(\w+))?",
            col_str,
            re.IGNORECASE,
        )
        if match:
            return ColumnReference(
                column_name=match.group(2),
                table_name=match.group(1),
                alias=match.group(3),
            )

        return None

    def _extract_joins(self, sql: str) -> list[JoinInfo]:
        """Extract JOIN information from SQL."""
        joins: list[JoinInfo] = []

        for pattern_str, join_type in JOIN_PATTERNS.items():
            pattern = re.compile(
                pattern_str
                + r"\s+([\w\.]+)(?:\s+(?:as\s+)?(\w+))?\s+on\s+(.*?)(?=\b(?:where|join|group|order|$))",
                re.IGNORECASE | re.DOTALL,
            )
            for match in pattern.finditer(sql):
                right_table = match.group(1)
                condition = match.group(3).strip()

                # Try to extract left table from condition
                left_table = self._extract_left_table(condition)

                joins.append(
                    JoinInfo(
                        join_type=join_type,
                        left_table=left_table,
                        right_table=right_table,
                        condition=condition,
                        columns_used=self._extract_columns_from_condition(condition),
                    )
                )

        return joins

    def _extract_left_table(self, condition: str) -> str:
        """Try to extract left table from join condition."""
        # Look for table.column pattern
        match = re.search(r"(\w+)\.\w+\s*=", condition)
        if match:
            return match.group(1)
        return "unknown"

    def _extract_columns_from_condition(self, condition: str) -> list[str]:
        """Extract column references from a condition."""
        columns = []
        # Find table.column or just column patterns
        pattern = r"(?:(\w+)\.)?(\w+)(?=\s*[=<>!])"
        for match in re.finditer(pattern, condition):
            col = match.group(2)
            if col.lower() not in SQL_KEYWORDS:
                columns.append(col)
        return columns

    def _extract_conditions(self, sql: str) -> list[FilterCondition]:
        """Extract WHERE/HAVING conditions from SQL."""
        conditions: list[FilterCondition] = []

        # Extract WHERE clause
        where_match = re.search(
            r"\bwhere\s+(.*?)(?=\bgroup\b|\border\b|\blimit\b|\bunion\b|\Z)",
            sql,
            re.IGNORECASE | re.DOTALL,
        )
        if where_match:
            where_clause = where_match.group(1)
            conditions.extend(self._parse_conditions(where_clause))

        # Extract HAVING clause
        having_match = re.search(
            r"\bhaving\s+(.*?)(?=\border\b|\blimit\b|\bunion\b|\Z)",
            sql,
            re.IGNORECASE | re.DOTALL,
        )
        if having_match:
            having_clause = having_match.group(1)
            conditions.extend(self._parse_conditions(having_clause))

        return conditions

    def _parse_conditions(self, clause: str) -> list[FilterCondition]:
        """Parse conditions from a WHERE or HAVING clause."""
        conditions: list[FilterCondition] = []

        # Split by AND/OR at top level
        # This is simplified - doesn't handle nested parentheses perfectly
        parts = re.split(r"\s+(?:and|or)\s+", clause, flags=re.IGNORECASE)

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Try to parse comparison
            match = re.match(
                r"(?:(\w+)\.)?(\w+)\s*([=<>!]+|like|in|between|is)\s*(.*)",
                part,
                re.IGNORECASE,
            )
            if match:
                column = match.group(2)
                operator = match.group(3)
                value = match.group(4)

                conditions.append(
                    FilterCondition(
                        column=column,
                        operator=operator.upper(),
                        value=value,
                        has_subquery="select" in value.lower() if value else False,
                    )
                )

        return conditions

    def get_clause_breakdown(self, sql: str) -> list[ClauseBreakdown]:
        """
        Get a breakdown of SQL clauses with explanations.

        Args:
            sql: SQL query to break down

        Returns:
            List of clause breakdowns
        """
        parsed = self.parse(sql)
        breakdowns: list[ClauseBreakdown] = []

        clause_order = [
            SQLClauseType.SELECT,
            SQLClauseType.FROM,
            SQLClauseType.WHERE,
            SQLClauseType.GROUP_BY,
            SQLClauseType.HAVING,
            SQLClauseType.ORDER_BY,
            SQLClauseType.LIMIT,
            SQLClauseType.OFFSET,
        ]

        for clause_type in clause_order:
            clause_value = parsed["clauses"].get(clause_type.value)
            if clause_value:
                explanation = self._explain_clause(clause_type, clause_value, parsed)
                elements = self._get_clause_elements(clause_type, clause_value, parsed)

                breakdowns.append(
                    ClauseBreakdown(
                        clause_type=clause_type,
                        raw_text=clause_value,
                        explanation=explanation,
                        elements=elements,
                    )
                )

        # Handle JOINs separately
        if parsed["joins"]:
            for join in parsed["joins"]:
                breakdowns.append(
                    ClauseBreakdown(
                        clause_type=SQLClauseType.JOIN,
                        raw_text=f"{join.join_type.value.upper()} JOIN {join.right_table} ON {join.condition}",
                        explanation=self._explain_join(join),
                        elements=[join.to_dict()],
                    )
                )

        return breakdowns

    def _explain_clause(
        self, clause_type: SQLClauseType, clause_value: str, _parsed: dict[str, Any]
    ) -> str:
        """Generate explanation for a SQL clause."""
        explanations: dict[SQLClauseType, str] = {
            SQLClauseType.SELECT: f"Selecting columns: {clause_value}",
            SQLClauseType.FROM: f"From table(s): {clause_value}",
            SQLClauseType.WHERE: f"Filtering where: {clause_value}",
            SQLClauseType.GROUP_BY: f"Grouping by: {clause_value}",
            SQLClauseType.HAVING: f"Having condition: {clause_value}",
            SQLClauseType.ORDER_BY: f"Ordering by: {clause_value}",
            SQLClauseType.LIMIT: f"Limiting results to {clause_value} rows",
            SQLClauseType.OFFSET: f"Skipping first {clause_value} rows",
        }
        return explanations.get(clause_type, f"{clause_type.value}: {clause_value}")

    def _explain_join(self, join: JoinInfo) -> str:
        """Generate explanation for a JOIN."""
        join_desc = {
            JoinType.INNER: "matching rows from both",
            JoinType.LEFT: "all rows from left table, matching from right",
            JoinType.RIGHT: "all rows from right table, matching from left",
            JoinType.FULL: "all rows from both tables",
            JoinType.CROSS: "cartesian product of both tables",
            JoinType.NATURAL: "matching on common columns",
        }
        desc = join_desc.get(join.join_type, "joining tables")
        return f"{join.join_type.value.upper()} JOIN: Combining {join.left_table} and {join.right_table} ({desc}) where {join.condition}"

    def _get_clause_elements(
        self, clause_type: SQLClauseType, _clause_value: str, parsed: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Get structured elements for a clause."""
        if clause_type == SQLClauseType.SELECT:
            return [col.to_dict() for col in parsed.get("columns", [])]
        if clause_type == SQLClauseType.FROM:
            return [table.to_dict() for table in parsed.get("tables", [])]
        if clause_type in (SQLClauseType.WHERE, SQLClauseType.HAVING):
            return [cond.to_dict() for cond in parsed.get("conditions", [])]
        return []


# =============================================================================
# Singleton Instance
# =============================================================================

_parser: SQLParser | None = None


def get_sql_parser() -> SQLParser:
    """Get or create the singleton SQL parser instance."""
    global _parser
    if _parser is None:
        _parser = SQLParser()
    return _parser
