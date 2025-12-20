"""Tool assembly for the agent runtime."""

from __future__ import annotations

from typing import Any

from app.agent.tools import (
    create_schema_inspector_tool,
    create_sql_executor_tool,
    create_sql_generator_tool,
    result_validator,
)
from app.config import Settings


def build_agent_tools(
    settings: Settings,
    model_loader: Any,
    schema_description: str,
    db_context: Any,
    max_rows: int,
) -> list[Any]:
    """Create the tool list based on the configured backend."""
    tools = [
        create_sql_executor_tool(
            session_provider=db_context.session_provider,
            schema_description=schema_description,
            max_rows=max_rows,
            execution_timeout=settings.agent.execution_timeout,
            allow_mutations=settings.multi_database.allow_mutations,
            database_id=db_context.database_id,
        ),
        create_schema_inspector_tool(
            engine=db_context.engine,
            database_id=db_context.database_id,
        ),
        result_validator,
    ]

    if settings.agent.model_backend == "local":
        tools.append(
            create_sql_generator_tool(
                model_loader=model_loader,
                schema_description=schema_description,
                database_id=db_context.database_id,
                dialect=db_context.dialect,
            )
        )

    return tools
