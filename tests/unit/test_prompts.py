"""
Unit tests for prompt templates module.
"""

import pytest

from models.prompts import (
    ArcticPromptTemplate,
    AgentPromptTemplate,
    ChainOfThoughtPromptTemplate,
    FewShotExample,
    build_prompt,
    extract_sql_from_output,
    format_schema_for_prompt,
    get_prompt_template,
)


class TestFewShotExample:
    """Tests for FewShotExample dataclass."""

    def test_basic_format(self) -> None:
        """Test basic example formatting."""
        example = FewShotExample(
            question="Show all users",
            sql="SELECT * FROM users",
        )
        formatted = example.format()

        assert "Question: Show all users" in formatted
        assert "SQL: SELECT * FROM users" in formatted

    def test_format_with_explanation(self) -> None:
        """Test formatting with explanation."""
        example = FewShotExample(
            question="Show all users",
            sql="SELECT * FROM users",
            explanation="Simple select query",
        )
        formatted = example.format(include_explanation=True)

        assert "Explanation: Simple select query" in formatted


class TestArcticPromptTemplate:
    """Tests for ArcticPromptTemplate."""

    def test_basic_build(self) -> None:
        """Test basic prompt building."""
        template = ArcticPromptTemplate(dialect="postgresql")
        prompt = template.build(
            question="Show all users",
            schema="Table: users\n  - id (INTEGER)\n  - name (VARCHAR)",
        )

        assert "Database Schema (postgresql):" in prompt
        assert "Question: Show all users" in prompt
        assert "SQL:" in prompt

    def test_with_few_shot_examples(self) -> None:
        """Test prompt with few-shot examples."""
        template = ArcticPromptTemplate()
        examples = [
            FewShotExample(question="Count users", sql="SELECT COUNT(*) FROM users")
        ]
        prompt = template.build(
            question="Show all users",
            schema="Table: users",
            few_shot_examples=examples,
        )

        assert "Examples:" in prompt
        assert "Count users" in prompt

    def test_with_context(self) -> None:
        """Test prompt with additional context."""
        template = ArcticPromptTemplate()
        prompt = template.build(
            question="Show all users",
            schema="Table: users",
            context="Only return active users",
        )

        assert "Context: Only return active users" in prompt


class TestChainOfThoughtPromptTemplate:
    """Tests for ChainOfThoughtPromptTemplate."""

    def test_includes_cot_instruction(self) -> None:
        """Test that CoT instruction is included."""
        template = ChainOfThoughtPromptTemplate()
        prompt = template.build(
            question="Show all users",
            schema="Table: users",
        )

        assert "Think step by step" in prompt
        assert "Let me think step by step" in prompt


class TestAgentPromptTemplate:
    """Tests for AgentPromptTemplate."""

    def test_includes_tool_descriptions(self) -> None:
        """Test that tool descriptions are included."""
        template = AgentPromptTemplate()
        prompt = template.build(
            question="Show all users",
            schema="Table: users",
        )

        assert "sql_engine" in prompt
        assert "validate_results" in prompt


class TestGetPromptTemplate:
    """Tests for get_prompt_template function."""

    def test_arctic_template(self) -> None:
        """Test getting Arctic template."""
        template = get_prompt_template("arctic")
        assert isinstance(template, ArcticPromptTemplate)

    def test_cot_template(self) -> None:
        """Test getting CoT template."""
        template = get_prompt_template("cot")
        assert isinstance(template, ChainOfThoughtPromptTemplate)

    def test_agent_template(self) -> None:
        """Test getting agent template."""
        template = get_prompt_template("agent")
        assert isinstance(template, AgentPromptTemplate)

    def test_default_fallback(self) -> None:
        """Test fallback to Arctic template."""
        template = get_prompt_template("unknown")
        assert isinstance(template, ArcticPromptTemplate)


class TestBuildPrompt:
    """Tests for build_prompt function."""

    def test_basic_build(self) -> None:
        """Test basic prompt building."""
        prompt = build_prompt(
            question="Show users",
            schema="Table: users",
        )

        assert "Table: users" in prompt
        assert "Show users" in prompt

    def test_with_dialect(self) -> None:
        """Test prompt with specific dialect."""
        prompt = build_prompt(
            question="Show users",
            schema="Table: users",
            dialect="mysql",
        )

        assert "(mysql)" in prompt


class TestFormatSchemaForPrompt:
    """Tests for format_schema_for_prompt function."""

    def test_basic_formatting(self) -> None:
        """Test basic schema formatting."""
        tables = [
            {
                "name": "users",
                "columns": [
                    {
                        "name": "id",
                        "data_type": "INTEGER",
                        "primary_key": True,
                        "nullable": False,
                    },
                    {
                        "name": "name",
                        "data_type": "VARCHAR",
                        "primary_key": False,
                        "nullable": True,
                    },
                ],
                "foreign_keys": [],
            }
        ]

        result = format_schema_for_prompt(tables)

        assert "Table: users" in result
        assert "id (INTEGER)" in result
        assert "[PK]" in result
        assert "[NOT NULL]" in result

    def test_with_foreign_keys(self) -> None:
        """Test schema formatting with foreign keys."""
        tables = [
            {
                "name": "orders",
                "columns": [
                    {
                        "name": "customer_id",
                        "data_type": "INTEGER",
                        "foreign_key": "customers.id",
                        "nullable": False,
                    },
                ],
                "foreign_keys": [
                    {
                        "column": "customer_id",
                        "references_table": "customers",
                        "references_column": "id",
                    }
                ],
            }
        ]

        result = format_schema_for_prompt(tables)

        assert "FK -> customers.id" in result
