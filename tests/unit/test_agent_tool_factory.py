"""Unit tests for agent tool factory."""

import pytest

pytest.importorskip("smolagents")

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.agent.tool_factory import build_agent_tools
from app.agent.tools import result_validator
from app.config import Settings


def _settings(agent_overrides: dict) -> Settings:
    return Settings(agent=agent_overrides)


def _db_context() -> SimpleNamespace:
    return SimpleNamespace(
        session_provider=MagicMock(),
        engine=MagicMock(),
        database_id="test-db",
        dialect="postgresql",
    )


def test_build_agent_tools_local_backend() -> None:
    settings = _settings({"model_backend": "local"})
    model_loader = MagicMock()
    db_context = _db_context()

    with (
        patch("app.agent.tool_factory.create_sql_executor_tool") as exec_tool,
        patch("app.agent.tool_factory.create_schema_inspector_tool") as schema_tool,
        patch("app.agent.tool_factory.create_sql_generator_tool") as generator_tool,
    ):
        exec_tool.return_value = "executor"
        schema_tool.return_value = "schema"
        generator_tool.return_value = "generator"

        tools = build_agent_tools(
            settings=settings,
            model_loader=model_loader,
            schema_description="schema",
            db_context=db_context,
            max_rows=10,
        )

        assert tools == ["executor", "schema", result_validator, "generator"]
        generator_tool.assert_called_once()


def test_build_agent_tools_hf_inference_backend() -> None:
    settings = _settings({"model_backend": "hf_inference"})
    model_loader = MagicMock()
    db_context = _db_context()

    with (
        patch("app.agent.tool_factory.create_sql_executor_tool") as exec_tool,
        patch("app.agent.tool_factory.create_schema_inspector_tool") as schema_tool,
        patch("app.agent.tool_factory.create_sql_generator_tool") as generator_tool,
    ):
        exec_tool.return_value = "executor"
        schema_tool.return_value = "schema"

        tools = build_agent_tools(
            settings=settings,
            model_loader=model_loader,
            schema_description="schema",
            db_context=db_context,
            max_rows=10,
        )

        assert tools == ["executor", "schema", result_validator]
        generator_tool.assert_not_called()
