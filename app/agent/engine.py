"""
Agent-based Text2SQL Engine with smolagents CodeAgent.

This module provides the main AgentText2SQL class that uses smolagents
CodeAgent to implement multi-step reasoning and self-correction for
SQL generation.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, Coroutine, TypeVar
from collections.abc import Callable

from smolagents import CodeAgent
from smolagents.agents import LogLevel
from smolagents.models import ChatMessage, MessageRole, Model, get_clean_message_list
from smolagents.monitoring import TokenUsage
from smolagents.utils import AgentError, AgentMaxStepsError

from app.agent.models import (
    AgentResult,
    AgentStep,
    AgentStepType,
    QueryHistoryEntry,
    ValidationOutcome,
    ValidationResult,
)
from app.agent.tools import (
    create_schema_inspector_tool,
    create_sql_executor_tool,
    create_sql_generator_tool,
    extract_sql_from_text,
    result_validator,
)
from app.config import get_settings
from app.exceptions import (
    AgentExecutionException,
    AgentMaxStepsExceededException,
    QueryNotFoundException,
)
from app.logging_config import get_logger
from app.monitoring.model_instrumentation import ModelInstrumentor
from db.connection import DatabaseManager
from db.executor import QueryResult, QueryValidator, SafeQueryExecutor
from db.registry import get_database_registry
from db.schema import SchemaIntrospector

logger = get_logger(__name__)

T = TypeVar("T")


def _run_coroutine_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine from sync code paths."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None

    if loop is None or loop.is_running():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(coro)


@dataclass(frozen=True)
class DatabaseContext:
    """Resolved database context for a specific database id."""

    database_id: str
    engine: Any
    dialect: str
    session_provider: Callable[[], Any]


def _render_prompt(messages: list[ChatMessage | dict[str, Any]]) -> str:
    """Render agent messages to a plain text prompt."""
    cleaned = get_clean_message_list(messages, flatten_messages_as_text=True)
    rendered: list[str] = []

    for message in cleaned:
        role = message.get("role")
        role_text = role.value if hasattr(role, "value") else str(role)
        content = message.get("content") or ""
        rendered.append(f"{role_text}: {content}")

    return "\n\n".join(rendered)


def _truncate_on_stop_sequences(text: str, stop_sequences: list[str] | None) -> str:
    """Truncate output at the first stop sequence if present."""
    if not stop_sequences:
        return text

    positions = [
        text.find(seq) for seq in stop_sequences if seq and text.find(seq) != -1
    ]
    if not positions:
        return text

    return text[: min(positions)]


class LocalInferenceModel(Model):
    """smolagents Model wrapper for the local Text2SQL inference engine."""

    def __init__(
        self,
        model_loader: Any,
        model_id: str | None,
        instrumentor: ModelInstrumentor,
    ) -> None:
        super().__init__(model_id=model_id, flatten_messages_as_text=True)
        from models.inference import InferenceEngine

        self._model_loader = model_loader
        self._instrumentor = instrumentor
        self._inference_engine = InferenceEngine(model_loader)
        self._last_inference: Any | None = None
        self._confidence_history: list[float] = []

    @property
    def last_confidence(self) -> float:
        if self._last_inference is None:
            return 0.5
        return float(getattr(self._last_inference, "confidence", 0.5))

    def generate(
        self,
        messages: list[ChatMessage | dict],
        stop_sequences: list[str] | None = None,
        response_format: dict[str, str] | None = None,
        tools_to_call_from: list[Any] | None = None,
        **kwargs: Any,
    ) -> ChatMessage:
        if response_format is not None:
            raise ValueError("LocalInferenceModel does not support structured outputs.")

        completion_kwargs = self._prepare_completion_kwargs(
            messages=messages,
            stop_sequences=stop_sequences,
            response_format=response_format,
            tools_to_call_from=tools_to_call_from,
            **kwargs,
        )
        prompt = _render_prompt(completion_kwargs["messages"])

        with self._instrumentor.trace_inference(
            operation="code_agent"
        ) as trace_context:
            result = _run_coroutine_sync(self._generate_async(prompt))
            trace_context["input_tokens"] = getattr(result, "input_tokens", 0)
            trace_context["output_tokens"] = getattr(result, "output_tokens", 0)
            trace_context["confidence"] = getattr(result, "confidence", 0.0)

        self._last_inference = result
        if hasattr(result, "confidence"):
            self._confidence_history.append(float(result.confidence))

        content = _truncate_on_stop_sequences(result.generated_text, stop_sequences)
        token_usage = TokenUsage(
            input_tokens=getattr(result, "input_tokens", 0),
            output_tokens=getattr(result, "output_tokens", 0),
        )

        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content=content,
            raw=getattr(result, "raw_output", None),
            token_usage=token_usage,
        )

    async def _generate_async(self, prompt: str) -> Any:
        if not self._model_loader.is_loaded:
            await self._model_loader.load()
        return await self._inference_engine.generate(prompt, extract_sql=False)


async def resolve_database_context(
    db_manager: DatabaseManager,
    database_id: str,
) -> DatabaseContext:
    """Resolve database context, using registry when enabled."""
    settings = get_settings()

    if settings.multi_database.enabled:
        registry = await get_database_registry()
        registered = registry.get_database(database_id)
        dialect = (
            registered.config.dialect.value
            if registered.config.dialect is not None
            else "unknown"
        )
        return DatabaseContext(
            database_id=database_id,
            engine=registered.engine,
            dialect=dialect,
            session_provider=lambda: registry.session(database_id),
        )

    return DatabaseContext(
        database_id=database_id,
        engine=db_manager.engine,
        dialect=db_manager.dialect,
        session_provider=db_manager.session,
    )


async def execute_sql_with_context(
    db_context: DatabaseContext,
    sql: str,
    max_rows: int,
    timeout_seconds: int,
    allow_mutations: bool,
) -> QueryResult:
    """Execute SQL using the provided database context."""
    async with db_context.session_provider() as session:
        executor = SafeQueryExecutor(
            session=session,
            allow_mutations=allow_mutations,
            timeout_seconds=timeout_seconds,
            max_rows=max_rows,
        )
        return await executor.execute(sql)


def format_results_for_validation(result: QueryResult) -> str:
    """Format query results for the result_validator tool."""
    if not result.success:
        return f"Error executing query: {result.error or 'Unknown error'}"

    if not result.rows:
        return "Query returned 0 rows."

    lines = [f"Query returned {result.row_count} rows:"]
    for i, row in enumerate(result.rows[:10], 1):
        row_str = ", ".join(f"{k}={v}" for k, v in row.items())
        lines.append(f"Row {i}: {row_str}")
    if result.row_count > 10:
        lines.append(f"... and {result.row_count - 10} more rows")

    return "\n".join(lines)


def parse_validation_result(validation_str: str) -> ValidationResult:
    """Parse validator output into a ValidationResult."""
    if "VALID" in validation_str and "NEEDS" not in validation_str:
        return ValidationResult(
            outcome=ValidationOutcome.VALID,
            message="Results appear to correctly answer the question.",
        )

    if "NEEDS_CORRECTION" in validation_str:
        suggestions = validation_str.split(" | ")[1:] if " | " in validation_str else []
        return ValidationResult(
            outcome=ValidationOutcome.NEEDS_CORRECTION,
            message=validation_str.replace("NEEDS_CORRECTION: ", ""),
            suggestions=suggestions,
        )

    if "INVALID" in validation_str:
        return ValidationResult(
            outcome=ValidationOutcome.INVALID,
            message=validation_str.replace("INVALID: ", ""),
        )

    return ValidationResult(
        outcome=ValidationOutcome.UNCERTAIN,
        message=validation_str,
    )


class AgentRunner:
    """Builds and runs a smolagents CodeAgent per request."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        schema_cache: dict[str, str],
        settings: Any,
    ) -> None:
        self._db_manager = db_manager
        self._schema_cache = schema_cache
        self._settings = settings

        model_name = getattr(getattr(settings, "huggingface", None), "model_name", None)
        self._instrumentor = ModelInstrumentor(
            model_name=model_name or "arctic-text2sql"
        )

    async def run(
        self,
        natural_query: str,
        database_id: str,
        execute: bool,
        show_reasoning: bool,
        max_rows: int,
        correction_hint: str | None = None,
        previous_sql: str | None = None,
    ) -> AgentResult:
        start_time = time.perf_counter()
        warnings: list[str] = []

        db_context = await resolve_database_context(self._db_manager, database_id)
        schema_description = await self._get_schema_description(db_context)

        from models.loader import get_model_loader

        model_loader = await get_model_loader()
        agent_model = LocalInferenceModel(
            model_loader=model_loader,
            model_id=getattr(
                getattr(self._settings, "huggingface", None), "model_name", None
            ),
            instrumentor=self._instrumentor,
        )

        tools = [
            create_sql_executor_tool(
                session_provider=db_context.session_provider,
                schema_description=schema_description,
                max_rows=max_rows,
                execution_timeout=self._settings.agent.execution_timeout,
                allow_mutations=self._settings.multi_database.allow_mutations,
                database_id=db_context.database_id,
            ),
            create_schema_inspector_tool(
                engine=db_context.engine,
                database_id=db_context.database_id,
            ),
            result_validator,
            create_sql_generator_tool(
                model_loader=model_loader,
                schema_description=schema_description,
                database_id=db_context.database_id,
                dialect=db_context.dialect,
            ),
        ]

        instructions = self._build_instructions(db_context, execute)
        agent = CodeAgent(
            tools=tools,
            model=agent_model,
            max_steps=self._settings.agent.max_steps,
            verbosity_level=self._map_verbosity(self._settings.agent.verbosity),
            instructions=instructions,
        )

        additional_args: dict[str, Any] = {}
        if correction_hint:
            additional_args["correction_hint"] = correction_hint
        if previous_sql:
            additional_args["previous_sql"] = previous_sql
        if additional_args:
            additional_args["database_id"] = database_id

        try:
            run_result = await asyncio.to_thread(
                agent.run,
                natural_query,
                return_full_result=True,
                max_steps=self._settings.agent.max_steps,
                additional_args=additional_args or None,
            )
        except AgentMaxStepsError as e:
            raise AgentMaxStepsExceededException(
                max_steps=self._settings.agent.max_steps,
                details={"max_steps": self._settings.agent.max_steps},
            ) from e
        except AgentError as e:
            raise AgentExecutionException(
                message=f"Agent execution failed: {e}",
                details={"database_id": database_id},
            ) from e

        if run_result.state == "max_steps_error":
            raise AgentMaxStepsExceededException(
                max_steps=self._settings.agent.max_steps,
                details={"max_steps": self._settings.agent.max_steps},
            )

        sql = self._extract_sql(run_result.output)
        if not sql:
            raise AgentExecutionException(
                message="Agent did not return SQL output",
                details={"database_id": database_id},
            )

        reasoning_trace = self._build_reasoning_trace(run_result.steps, sql)
        total_steps = len(reasoning_trace)

        validation_result: ValidationResult | None = None
        execution_results: list[dict[str, Any]] | None = None
        row_count: int | None = None

        should_execute = execute or self._settings.agent.enable_validation
        if should_execute:
            try:
                query_result = await execute_sql_with_context(
                    db_context=db_context,
                    sql=sql,
                    max_rows=max_rows,
                    timeout_seconds=self._settings.agent.execution_timeout,
                    allow_mutations=self._settings.multi_database.allow_mutations,
                )

                if execute and query_result.success:
                    execution_results = query_result.rows
                    row_count = query_result.row_count

                if query_result.warnings:
                    warnings.extend(query_result.warnings)

                if self._settings.agent.enable_validation:
                    results_str = format_results_for_validation(query_result)
                    validation_str = result_validator(results_str, natural_query, sql)
                    validation_result = parse_validation_result(validation_str)
                    if validation_result.outcome != ValidationOutcome.VALID:
                        warnings.append(validation_result.message)

            except Exception as exec_error:
                warnings.append(f"Execution warning: {exec_error!s}")

        confidence = self._calculate_confidence(
            agent_model.last_confidence,
            validation_result,
            total_steps,
        )

        validator = QueryValidator(
            allow_mutations=self._settings.multi_database.allow_mutations
        )
        validation_errors = validator.validate(sql)
        valid_syntax = len(validation_errors) == 0
        if validation_errors:
            warnings.extend(validation_errors)

        execution_time_ms = (time.perf_counter() - start_time) * 1000

        self._instrumentor.record_reasoning_complete(
            total_steps=total_steps,
            success=validation_result is None
            or validation_result.outcome == ValidationOutcome.VALID,
        )

        return AgentResult(
            sql=sql,
            confidence=confidence,
            execution_time_ms=execution_time_ms,
            reasoning_trace=reasoning_trace if show_reasoning else [],
            validation_result=validation_result,
            execution_results=execution_results if execute else None,
            row_count=row_count if execute else None,
            total_steps=total_steps,
            warnings=warnings,
            metadata={
                "database_id": database_id,
                "dialect": db_context.dialect,
                "model_confidence": agent_model.last_confidence,
                "valid_syntax": valid_syntax,
                "validation_status": (
                    validation_result.outcome.value
                    if validation_result
                    else "not_validated"
                ),
            },
        )

    async def _get_schema_description(self, db_context: DatabaseContext) -> str:
        if db_context.database_id in self._schema_cache:
            return self._schema_cache[db_context.database_id]

        introspector = SchemaIntrospector(db_context.engine)
        schema = await introspector.get_schema(db_context.database_id)
        description = introspector.serialize_for_prompt(schema)

        self._schema_cache[db_context.database_id] = description
        return description

    def _build_instructions(self, db_context: DatabaseContext, execute: bool) -> str:
        execution_note = (
            "You may execute SQL to validate results."
            if execute
            else "Only execute SQL when validation is needed."
        )
        return (
            "You are a Text2SQL ReAct agent. Use the tools to inspect schema, "
            "generate SQL, and validate results. "
            "Always return only the final SQL string via final_answer without extra formatting. "
            f"Database id: {db_context.database_id}. Dialect: {db_context.dialect}. "
            f"{execution_note}"
        )

    def _map_verbosity(self, verbosity: int) -> LogLevel:
        mapping = {
            0: LogLevel.OFF,
            1: LogLevel.INFO,
            2: LogLevel.DEBUG,
        }
        return mapping.get(verbosity, LogLevel.INFO)

    def _extract_sql(self, output: Any) -> str:
        if isinstance(output, str):
            extracted = extract_sql_from_text(output)
            return extracted or output.strip()
        if isinstance(output, dict) and "sql" in output:
            return str(output["sql"]).strip()
        return str(output).strip()

    def _build_reasoning_trace(
        self,
        steps: list[dict[str, Any]],
        sql: str,
    ) -> list[AgentStep]:
        trace: list[AgentStep] = []
        step_number = 0

        for step in steps:
            if "step_number" not in step:
                continue

            model_output = step.get("model_output") or ""
            thought = self._extract_thought(model_output)
            if thought:
                step_number += 1
                trace.append(
                    AgentStep(
                        step_number=step_number,
                        step_type=AgentStepType.THOUGHT,
                        content=thought,
                    )
                )

            code_action = step.get("code_action")
            if code_action:
                step_number += 1
                trace.append(
                    AgentStep(
                        step_number=step_number,
                        step_type=AgentStepType.ACTION,
                        content="Executing tool calls via python_interpreter.",
                        tool_name="python_interpreter",
                        tool_input={"code": code_action},
                    )
                )

            observations = step.get("observations") or step.get("action_output")
            if observations:
                step_number += 1
                trace.append(
                    AgentStep(
                        step_number=step_number,
                        step_type=AgentStepType.OBSERVATION,
                        content=str(observations),
                        tool_output=str(observations),
                    )
                )

            if step.get("error"):
                step_number += 1
                trace.append(
                    AgentStep(
                        step_number=step_number,
                        step_type=AgentStepType.ERROR,
                        content=str(step["error"]),
                    )
                )

        step_number += 1
        trace.append(
            AgentStep(
                step_number=step_number,
                step_type=AgentStepType.FINAL_ANSWER,
                content=f"Final SQL: {sql}",
            )
        )

        return trace

    def _extract_thought(self, model_output: str) -> str:
        for line in model_output.splitlines():
            if line.strip().lower().startswith("thought:"):
                return line.split(":", 1)[1].strip()
        return model_output.strip()

    def _calculate_confidence(
        self,
        model_confidence: float,
        validation_result: ValidationResult | None,
        steps_taken: int,
    ) -> float:
        confidence = model_confidence

        if validation_result:
            if validation_result.outcome == ValidationOutcome.VALID:
                confidence = min(1.0, confidence * 1.1)
            elif validation_result.outcome == ValidationOutcome.NEEDS_CORRECTION:
                confidence *= 0.8
            elif validation_result.outcome == ValidationOutcome.INVALID:
                confidence *= 0.6

        step_penalty = max(0, steps_taken - 3) * 0.02
        confidence = max(0.0, confidence - step_penalty)

        return round(min(1.0, max(0.0, confidence)), 3)


class AgentText2SQL:
    """
    Agent-based Text2SQL engine with self-correction capabilities.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        max_steps: int | None = None,
        min_confidence: float | None = None,
        verbosity: int = 1,
    ) -> None:
        settings = get_settings()

        self._db_manager = db_manager
        self._max_steps = max_steps or settings.agent.max_steps
        self._min_confidence = min_confidence or settings.agent.min_confidence
        self._verbosity = verbosity
        self._settings = settings

        self._query_history: dict[str, QueryHistoryEntry] = {}
        self._schema_cache: dict[str, str] = {}

        logger.info(
            "agent_text2sql_initialized",
            max_steps=self._max_steps,
            min_confidence=self._min_confidence,
            verbosity=self._verbosity,
        )

    async def generate_sql(
        self,
        natural_query: str,
        database_id: str,
        execute: bool = False,
        show_reasoning: bool = True,
        max_rows: int = 100,
        correction_hint: str | None = None,
        previous_sql: str | None = None,
    ) -> AgentResult:
        start_time = time.perf_counter()
        query_id = str(uuid.uuid4())

        logger.info(
            "agent_sql_generation_started",
            query_id=query_id,
            database_id=database_id,
            query_length=len(natural_query),
        )

        try:
            runner = AgentRunner(
                db_manager=self._db_manager,
                schema_cache=self._schema_cache,
                settings=self._settings,
            )
            result = await runner.run(
                natural_query=natural_query,
                database_id=database_id,
                execute=execute,
                show_reasoning=show_reasoning,
                max_rows=max_rows,
                correction_hint=correction_hint,
                previous_sql=previous_sql,
            )

            result.execution_time_ms = (time.perf_counter() - start_time) * 1000
            result.metadata.update(
                {
                    "query_id": query_id,
                    "database_id": database_id,
                }
            )

            success = result.validation_result is None or (
                result.validation_result.outcome == ValidationOutcome.VALID
            )
            history_entry = QueryHistoryEntry(
                query_id=query_id,
                natural_query=natural_query,
                database_id=database_id,
                sql=result.sql,
                confidence=result.confidence,
                success=success,
                error_message=(
                    result.validation_result.message
                    if result.validation_result
                    and result.validation_result.outcome != ValidationOutcome.VALID
                    else None
                ),
                reasoning_trace=result.reasoning_trace if show_reasoning else [],
            )
            self._query_history[query_id] = history_entry

            self._trim_query_history()

            logger.info(
                "agent_sql_generation_complete",
                query_id=query_id,
                sql_length=len(result.sql),
                confidence=result.confidence,
                total_steps=result.total_steps,
                execution_time_ms=round(result.execution_time_ms, 2),
            )

            return result

        except AgentMaxStepsExceededException:
            raise
        except Exception as e:
            logger.error(
                "agent_sql_generation_failed",
                error=str(e),
                query_id=query_id,
            )
            raise AgentExecutionException(
                message=f"Agent execution failed: {e!s}",
                details={"query_id": query_id, "error": str(e)},
            ) from e

    async def execute_sql(
        self,
        sql: str,
        database_id: str,
        max_rows: int = 100,
    ) -> QueryResult:
        db_context = await resolve_database_context(self._db_manager, database_id)
        return await execute_sql_with_context(
            db_context=db_context,
            sql=sql,
            max_rows=max_rows,
            timeout_seconds=self._settings.agent.execution_timeout,
            allow_mutations=self._settings.multi_database.allow_mutations,
        )

    async def retry_query(
        self,
        query_id: str,
        correction_hint: str | None = None,
    ) -> AgentResult:
        if query_id not in self._query_history:
            raise QueryNotFoundException(query_id=query_id)

        history = self._query_history[query_id]

        logger.info(
            "agent_retry_started",
            query_id=query_id,
            has_hint=correction_hint is not None,
        )

        if correction_hint:
            history.correction_hint = correction_hint

        result = await self.generate_sql(
            natural_query=history.natural_query,
            database_id=history.database_id,
            execute=True,
            show_reasoning=True,
            correction_hint=correction_hint,
            previous_sql=history.sql,
        )

        result.retries = (
            self._query_history.get(query_id, history).reasoning_trace.__len__() // 3
            + 1
        )
        result.metadata["retry_of"] = query_id
        result.metadata["correction_hint"] = correction_hint

        return result

    def get_query_history(self, query_id: str) -> QueryHistoryEntry | None:
        return self._query_history.get(query_id)

    def invalidate_schema_cache(self, database_id: str | None = None) -> None:
        if database_id:
            self._schema_cache.pop(database_id, None)
        else:
            self._schema_cache.clear()

    def _calculate_confidence(
        self,
        model_confidence: float,
        validation_result: ValidationResult | None,
        steps_taken: int,
    ) -> float:
        confidence = model_confidence

        if validation_result:
            if validation_result.outcome == ValidationOutcome.VALID:
                confidence = min(1.0, confidence * 1.1)
            elif validation_result.outcome == ValidationOutcome.NEEDS_CORRECTION:
                confidence *= 0.8
            elif validation_result.outcome == ValidationOutcome.INVALID:
                confidence *= 0.6

        step_penalty = max(0, steps_taken - 3) * 0.02
        confidence = max(0.0, confidence - step_penalty)

        return round(min(1.0, max(0.0, confidence)), 3)

    def _trim_query_history(self) -> None:
        limit = self._settings.agent.query_history_size
        if limit <= 0:
            self._query_history.clear()
            return
        if len(self._query_history) <= limit:
            return

        sorted_entries = sorted(
            self._query_history.items(),
            key=lambda item: item[1].created_at,
        )
        for query_id, _entry in sorted_entries[:-limit]:
            self._query_history.pop(query_id, None)


# =============================================================================
# Global Engine Management
# =============================================================================


_agent_engine: AgentText2SQL | None = None


async def get_agent_engine() -> AgentText2SQL:
    """
    Get or create the global AgentText2SQL engine instance.

    Returns:
        AgentText2SQL: Global agent engine instance
    """
    global _agent_engine

    if _agent_engine is None:
        from db.connection import get_database

        db_manager = await get_database()
        _agent_engine = AgentText2SQL(db_manager)

    return _agent_engine


def reset_agent_engine() -> None:
    """Reset the global agent engine instance."""
    global _agent_engine
    _agent_engine = None
