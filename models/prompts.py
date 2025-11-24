"""
Prompt templates for SQL generation.

This module provides prompt engineering utilities for
constructing effective prompts for the Text2SQL model.
"""

from dataclasses import dataclass
from typing import Any

from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class FewShotExample:
    """A few-shot learning example."""

    question: str
    sql: str
    explanation: str | None = None

    def format(self, include_explanation: bool = False) -> str:
        """Format example for prompt."""
        parts = [f"Question: {self.question}", f"SQL: {self.sql}"]
        if include_explanation and self.explanation:
            parts.append(f"Explanation: {self.explanation}")
        return "\n".join(parts)


# Default few-shot examples for common query patterns
DEFAULT_FEW_SHOT_EXAMPLES = [
    FewShotExample(
        question="Show all customers from California",
        sql="SELECT * FROM customers WHERE state = 'California'",
        explanation="Simple filter on state column",
    ),
    FewShotExample(
        question="How many orders were placed in 2024?",
        sql="SELECT COUNT(*) FROM orders WHERE YEAR(order_date) = 2024",
        explanation="Count with date filter",
    ),
    FewShotExample(
        question="What is the total revenue by product category?",
        sql="SELECT category, SUM(revenue) as total_revenue FROM products GROUP BY category ORDER BY total_revenue DESC",
        explanation="Aggregation with grouping and sorting",
    ),
    FewShotExample(
        question="Which customer has the most orders?",
        sql="SELECT c.name, COUNT(o.id) as order_count FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.id, c.name ORDER BY order_count DESC LIMIT 1",
        explanation="Join with aggregation to find maximum",
    ),
]


class PromptTemplate:
    """
    Base class for prompt templates.

    Provides common functionality for building prompts with
    schema context, examples, and instructions.
    """

    # System instructions for the model
    SYSTEM_INSTRUCTION = """You are an expert SQL query generator. Your task is to convert natural language questions into accurate SQL queries.

Rules:
1. Generate only valid SQL that matches the provided schema
2. Use proper table and column names from the schema
3. Include appropriate JOINs for related tables
4. Use aggregations (COUNT, SUM, AVG) when questions ask for totals or averages
5. Add ORDER BY when the question implies ranking or sorting
6. Use LIMIT when the question asks for "top N" or "first N"
7. Output only the SQL query, no explanations"""

    def __init__(
        self,
        dialect: str = "postgresql",
        include_system_instruction: bool = True,
    ) -> None:
        """
        Initialize prompt template.

        Args:
            dialect: SQL dialect (postgresql, mysql, sqlite)
            include_system_instruction: Include system instruction in prompt
        """
        self.dialect = dialect
        self.include_system_instruction = include_system_instruction

    def build(
        self,
        question: str,
        schema: str,
        few_shot_examples: list[FewShotExample] | None = None,
        context: str | None = None,
    ) -> str:
        """
        Build the complete prompt.

        Args:
            question: User's natural language question
            schema: Database schema description
            few_shot_examples: Optional examples for in-context learning
            context: Additional context or constraints

        Returns:
            Complete prompt string
        """
        raise NotImplementedError


class ArcticPromptTemplate(PromptTemplate):
    """
    Prompt template optimized for Snowflake Arctic-Text2SQL model.

    The Arctic model expects a specific format with schema and question.
    """

    def build(
        self,
        question: str,
        schema: str,
        few_shot_examples: list[FewShotExample] | None = None,
        context: str | None = None,
    ) -> str:
        """Build Arctic-optimized prompt."""
        parts = []

        # System instruction
        if self.include_system_instruction:
            parts.append(self.SYSTEM_INSTRUCTION)
            parts.append("")

        # Schema
        parts.append(f"Database Schema ({self.dialect}):")
        parts.append(schema)
        parts.append("")

        # Few-shot examples
        if few_shot_examples:
            parts.append("Examples:")
            for example in few_shot_examples:
                parts.append(example.format())
                parts.append("")

        # Additional context
        if context:
            parts.append(f"Context: {context}")
            parts.append("")

        # Question
        parts.append(f"Question: {question}")
        parts.append("SQL:")

        return "\n".join(parts)


class ChainOfThoughtPromptTemplate(PromptTemplate):
    """
    Prompt template with chain-of-thought reasoning.

    Encourages the model to think step-by-step before generating SQL.
    """

    COT_INSTRUCTION = """Think step by step:
1. Identify the tables needed from the schema
2. Determine the columns to select
3. Figure out the JOIN conditions (if needed)
4. Add WHERE filters based on the question
5. Add GROUP BY for aggregations
6. Add ORDER BY and LIMIT if needed
7. Write the final SQL query"""

    def build(
        self,
        question: str,
        schema: str,
        few_shot_examples: list[FewShotExample] | None = None,
        context: str | None = None,
    ) -> str:
        """Build chain-of-thought prompt."""
        parts = []

        # System instruction
        if self.include_system_instruction:
            parts.append(self.SYSTEM_INSTRUCTION)
            parts.append("")
            parts.append(self.COT_INSTRUCTION)
            parts.append("")

        # Schema
        parts.append(f"Database Schema ({self.dialect}):")
        parts.append(schema)
        parts.append("")

        # Few-shot examples with reasoning
        if few_shot_examples:
            parts.append("Examples:")
            for example in few_shot_examples:
                parts.append(example.format(include_explanation=True))
                parts.append("")

        # Additional context
        if context:
            parts.append(f"Context: {context}")
            parts.append("")

        # Question with reasoning prompt
        parts.append(f"Question: {question}")
        parts.append("")
        parts.append("Let me think step by step:")

        return "\n".join(parts)


class AgentPromptTemplate(PromptTemplate):
    """
    Prompt template for agent-based SQL generation.

    Designed for use with smolagents CodeAgent where the model
    can use tools and iterate on solutions.
    """

    AGENT_INSTRUCTION = """You are a SQL agent that can execute queries and validate results.

Available tools:
- sql_engine(query: str) -> str: Execute a SQL query and return results
- validate_results(results: str, expected: str) -> str: Validate if results match expectations

Process:
1. Analyze the question and schema
2. Generate a SQL query
3. Execute the query using sql_engine
4. Validate the results
5. If results are wrong, regenerate and try again
6. Return the final correct query"""

    def build(
        self,
        question: str,
        schema: str,
        few_shot_examples: list[FewShotExample] | None = None,
        context: str | None = None,
    ) -> str:
        """Build agent-style prompt."""
        parts = []

        # Agent instruction
        parts.append(self.AGENT_INSTRUCTION)
        parts.append("")

        # Schema
        parts.append(f"Database Schema ({self.dialect}):")
        parts.append(schema)
        parts.append("")

        # Additional context
        if context:
            parts.append(f"Context: {context}")
            parts.append("")

        # Task
        parts.append(f"Task: Generate SQL to answer: {question}")
        parts.append("")
        parts.append("Begin:")

        return "\n".join(parts)


def get_prompt_template(
    template_type: str = "arctic",
    dialect: str = "postgresql",
) -> PromptTemplate:
    """
    Get a prompt template by type.

    Args:
        template_type: Type of template (arctic, cot, agent)
        dialect: SQL dialect

    Returns:
        PromptTemplate instance
    """
    templates: dict[str, type[PromptTemplate]] = {
        "arctic": ArcticPromptTemplate,
        "cot": ChainOfThoughtPromptTemplate,
        "agent": AgentPromptTemplate,
    }

    template_class = templates.get(template_type, ArcticPromptTemplate)
    return template_class(dialect=dialect)


def build_prompt(
    question: str,
    schema: str,
    template_type: str = "arctic",
    dialect: str = "postgresql",
    few_shot_examples: list[FewShotExample] | None = None,
    use_default_examples: bool = False,
    context: str | None = None,
) -> str:
    """
    Build a prompt with the specified template.

    Args:
        question: Natural language question
        schema: Database schema description
        template_type: Type of prompt template
        dialect: SQL dialect
        few_shot_examples: Custom few-shot examples
        use_default_examples: Include default examples
        context: Additional context

    Returns:
        Complete prompt string
    """
    template = get_prompt_template(template_type, dialect)

    examples = few_shot_examples or []
    if use_default_examples:
        examples = DEFAULT_FEW_SHOT_EXAMPLES + examples

    prompt = template.build(
        question=question,
        schema=schema,
        few_shot_examples=examples if examples else None,
        context=context,
    )

    logger.debug(
        "prompt_built",
        template_type=template_type,
        dialect=dialect,
        prompt_length=len(prompt),
        num_examples=len(examples),
    )

    return prompt


def format_schema_for_prompt(
    tables: list[dict[str, Any]],
    include_types: bool = True,
    include_foreign_keys: bool = True,
) -> str:
    """
    Format schema dictionary for prompt inclusion.

    Args:
        tables: List of table dictionaries from SchemaInfo
        include_types: Include column data types
        include_foreign_keys: Include foreign key relationships

    Returns:
        Formatted schema string
    """
    lines = []

    for table in tables:
        lines.append(f"Table: {table['name']}")

        for col in table.get("columns", []):
            col_str = f"  - {col['name']}"
            if include_types:
                col_str += f" ({col['data_type']})"
            if col.get("primary_key"):
                col_str += " [PK]"
            if col.get("foreign_key") and include_foreign_keys:
                col_str += f" [FK -> {col['foreign_key']}]"
            if not col.get("nullable", True):
                col_str += " [NOT NULL]"
            lines.append(col_str)

        if include_foreign_keys and table.get("foreign_keys"):
            lines.append("  Foreign Keys:")
            for fk in table["foreign_keys"]:
                lines.append(
                    f"    {fk['column']} -> {fk['references_table']}.{fk['references_column']}"
                )

        lines.append("")

    return "\n".join(lines)
