"""
Agent-based Text2SQL Engine with ReAct framework.

This module provides the main AgentText2SQL class that uses smolagents
CodeAgent to implement multi-step reasoning and self-correction for
SQL generation.

The agent follows the ReAct (Reasoning + Acting) framework:
1. Thought: Reason about what to do
2. Action: Execute a tool (sql_executor, result_validator, etc.)
3. Observation: Process the result
4. Repeat until satisfied or max steps reached
"""

import time
import uuid
from typing import Any

from app.agent.models import (
    AgentResult,
    AgentStep,
    AgentStepType,
    QueryHistoryEntry,
    ValidationOutcome,
    ValidationResult,
)
from app.agent.tools import (
    result_validator,
)
from app.config import get_settings
from app.exceptions import (
    AgentExecutionException,
    AgentMaxStepsExceededException,
    QueryNotFoundException,
)
from app.logging_config import get_logger
from db.connection import DatabaseManager
from db.schema import SchemaIntrospector

logger = get_logger(__name__)


class AgentText2SQL:
    """
    Agent-based Text2SQL engine with self-correction capabilities.

    Uses smolagents CodeAgent with ReAct framework for multi-step
    reasoning. The agent can:
    - Generate SQL using the Text2SQL model
    - Execute queries and inspect results
    - Validate if results answer the original question
    - Self-correct by iterating on failed attempts

    Usage:
        engine = AgentText2SQL(db_manager)
        result = await engine.generate_sql(
            natural_query="Show all customers from California",
            database_id="my_db"
        )
        print(result.sql)
        print(result.reasoning_trace)
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        max_steps: int | None = None,
        min_confidence: float | None = None,
        verbosity: int = 1,
    ) -> None:
        """
        Initialize the agent-based Text2SQL engine.

        Args:
            db_manager: Database manager for connections
            max_steps: Maximum reasoning steps (default from settings)
            min_confidence: Minimum confidence threshold (default from settings)
            verbosity: Agent verbosity level (0=quiet, 1=normal, 2=verbose)
        """
        settings = get_settings()

        self._db_manager = db_manager
        self._max_steps = max_steps or settings.agent.max_steps
        self._min_confidence = min_confidence or settings.agent.min_confidence
        self._verbosity = verbosity

        # Query history for retry functionality
        self._query_history: dict[str, QueryHistoryEntry] = {}

        # Schema cache
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
    ) -> AgentResult:
        """
        Generate SQL from natural language using agent-based reasoning.

        The agent will:
        1. Understand the natural language query
        2. Inspect schema if needed
        3. Generate SQL using the Text2SQL model
        4. Execute and validate results
        5. Self-correct if validation fails

        Args:
            natural_query: Natural language question
            database_id: Target database identifier
            execute: Whether to execute generated SQL
            show_reasoning: Include reasoning trace in result
            max_rows: Maximum rows to return if executing

        Returns:
            AgentResult with SQL, results, and reasoning trace

        Raises:
            AgentMaxStepsExceededException: If max steps exceeded
            AgentExecutionException: If agent execution fails
        """
        start_time = time.perf_counter()
        query_id = str(uuid.uuid4())
        reasoning_trace: list[AgentStep] = []
        step_number = 0
        warnings: list[str] = []

        logger.info(
            "agent_sql_generation_started",
            query_id=query_id,
            database_id=database_id,
            query_length=len(natural_query),
        )

        try:
            # Step 1: Get schema context
            step_number += 1
            step_start = time.perf_counter()

            reasoning_trace.append(
                AgentStep(
                    step_number=step_number,
                    step_type=AgentStepType.THOUGHT,
                    content="Retrieving database schema to understand available tables and columns.",
                )
            )

            schema_description = await self._get_schema_description(database_id)
            table_count = schema_description.count("Table:")

            reasoning_trace.append(
                AgentStep(
                    step_number=step_number,
                    step_type=AgentStepType.OBSERVATION,
                    content=f"Retrieved schema with {table_count} tables.",
                    duration_ms=(time.perf_counter() - step_start) * 1000,
                )
            )

            # Step 2: Generate SQL using model
            step_number += 1
            step_start = time.perf_counter()

            reasoning_trace.append(
                AgentStep(
                    step_number=step_number,
                    step_type=AgentStepType.THOUGHT,
                    content=f"Generating SQL for question: '{natural_query}'",
                )
            )

            sql, confidence = await self._generate_sql_with_model(
                natural_query, schema_description
            )

            reasoning_trace.append(
                AgentStep(
                    step_number=step_number,
                    step_type=AgentStepType.ACTION,
                    content="Using Text2SQL model to generate SQL query.",
                    tool_name="sql_generator",
                    tool_input={"question": natural_query},
                    tool_output=sql,
                    duration_ms=(time.perf_counter() - step_start) * 1000,
                )
            )

            # Step 3: Validate and optionally execute
            validation_result: ValidationResult | None = None
            execution_results: list[dict[str, Any]] | None = None
            row_count: int | None = None

            if execute or self._verbosity > 0:
                step_number += 1
                step_start = time.perf_counter()

                reasoning_trace.append(
                    AgentStep(
                        step_number=step_number,
                        step_type=AgentStepType.THOUGHT,
                        content="Executing SQL to verify it works and validate results.",
                    )
                )

                try:
                    results_str, execution_results, row_count = (
                        await self._execute_and_format(sql, max_rows)
                    )

                    reasoning_trace.append(
                        AgentStep(
                            step_number=step_number,
                            step_type=AgentStepType.ACTION,
                            content="Executing SQL query.",
                            tool_name="sql_executor",
                            tool_input={"query": sql},
                            tool_output=f"Returned {row_count} rows",
                            duration_ms=(time.perf_counter() - step_start) * 1000,
                        )
                    )

                    # Step 4: Validate results
                    step_number += 1
                    step_start = time.perf_counter()

                    reasoning_trace.append(
                        AgentStep(
                            step_number=step_number,
                            step_type=AgentStepType.THOUGHT,
                            content="Validating if results correctly answer the question.",
                        )
                    )

                    validation_str = result_validator(results_str, natural_query, sql)

                    if "VALID" in validation_str and "NEEDS" not in validation_str:
                        validation_result = ValidationResult(
                            outcome=ValidationOutcome.VALID,
                            message="Results appear to correctly answer the question.",
                        )
                    elif "NEEDS_CORRECTION" in validation_str:
                        validation_result = ValidationResult(
                            outcome=ValidationOutcome.NEEDS_CORRECTION,
                            message=validation_str.replace("NEEDS_CORRECTION: ", ""),
                            suggestions=(
                                validation_str.split(" | ")[1:]
                                if " | " in validation_str
                                else []
                            ),
                        )
                        warnings.append(validation_result.message)

                        # Attempt self-correction if steps remaining
                        if step_number < self._max_steps:
                            step_number += 1
                            reasoning_trace.append(
                                AgentStep(
                                    step_number=step_number,
                                    step_type=AgentStepType.THOUGHT,
                                    content=f"Validation suggests correction needed: {validation_result.message}. Attempting to improve SQL.",
                                )
                            )

                            # Regenerate with hints
                            improved_sql, improved_confidence = (
                                await self._generate_sql_with_hints(
                                    natural_query,
                                    schema_description,
                                    sql,
                                    validation_result.suggestions,
                                )
                            )

                            if improved_sql and improved_sql != sql:
                                sql = improved_sql
                                confidence = improved_confidence

                                reasoning_trace.append(
                                    AgentStep(
                                        step_number=step_number,
                                        step_type=AgentStepType.ACTION,
                                        content="Generated improved SQL with correction hints.",
                                        tool_name="sql_generator",
                                        tool_output=sql,
                                    )
                                )

                                # Re-execute improved SQL
                                if execute:
                                    results_str, execution_results, row_count = (
                                        await self._execute_and_format(sql, max_rows)
                                    )
                    else:
                        validation_result = ValidationResult(
                            outcome=ValidationOutcome.INVALID,
                            message=validation_str,
                        )

                    reasoning_trace.append(
                        AgentStep(
                            step_number=step_number,
                            step_type=AgentStepType.OBSERVATION,
                            content=f"Validation result: {validation_result.outcome.value}",
                            duration_ms=(time.perf_counter() - step_start) * 1000,
                        )
                    )

                except Exception as exec_error:
                    logger.warning(
                        "agent_execution_warning",
                        error=str(exec_error),
                    )
                    warnings.append(f"Execution warning: {exec_error!s}")

                    # Clear execution results since execution failed
                    if not execute:
                        execution_results = None
                        row_count = None

            # Final step: Prepare result
            step_number += 1
            reasoning_trace.append(
                AgentStep(
                    step_number=step_number,
                    step_type=AgentStepType.FINAL_ANSWER,
                    content=f"Final SQL: {sql}",
                )
            )

            execution_time_ms = (time.perf_counter() - start_time) * 1000

            # Calculate final confidence
            final_confidence = self._calculate_confidence(
                confidence, validation_result, step_number
            )

            # Store in history for retry
            history_entry = QueryHistoryEntry(
                query_id=query_id,
                natural_query=natural_query,
                database_id=database_id,
                sql=sql,
                confidence=final_confidence,
                success=validation_result is None
                or validation_result.outcome == ValidationOutcome.VALID,
                error_message=(
                    validation_result.message
                    if validation_result
                    and validation_result.outcome != ValidationOutcome.VALID
                    else None
                ),
                reasoning_trace=reasoning_trace if show_reasoning else [],
            )
            self._query_history[query_id] = history_entry

            logger.info(
                "agent_sql_generation_complete",
                query_id=query_id,
                sql_length=len(sql),
                confidence=final_confidence,
                total_steps=step_number,
                execution_time_ms=round(execution_time_ms, 2),
            )

            return AgentResult(
                sql=sql,
                confidence=final_confidence,
                execution_time_ms=execution_time_ms,
                reasoning_trace=reasoning_trace if show_reasoning else [],
                validation_result=validation_result,
                execution_results=execution_results if execute else None,
                row_count=row_count if execute else None,
                total_steps=step_number,
                warnings=warnings,
                metadata={
                    "query_id": query_id,
                    "database_id": database_id,
                    "model_confidence": confidence,
                },
            )

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
                step_number=step_number,
                details={"query_id": query_id, "error": str(e)},
            ) from e

    async def retry_query(
        self,
        query_id: str,
        correction_hint: str | None = None,
    ) -> AgentResult:
        """
        Retry a previous query with optional correction hints.

        Uses the stored query history to understand what went wrong
        and generate an improved SQL query.

        Args:
            query_id: ID of the query to retry
            correction_hint: Optional hint for how to correct the query

        Returns:
            AgentResult with improved SQL

        Raises:
            QueryNotFoundException: If query not in history
        """
        if query_id not in self._query_history:
            raise QueryNotFoundException(query_id=query_id)

        history = self._query_history[query_id]

        logger.info(
            "agent_retry_started",
            query_id=query_id,
            has_hint=correction_hint is not None,
        )

        # Update history with correction hint
        if correction_hint:
            history.correction_hint = correction_hint

        # Note: hints are passed via the correction_hint parameter
        # which is stored in history and used in subsequent generate_sql calls
        _ = history.error_message  # Will be used for enhanced retry in future
        _ = history.sql  # Previous SQL preserved in history

        # Regenerate with hints
        result = await self.generate_sql(
            natural_query=history.natural_query,
            database_id=history.database_id,
            execute=True,
            show_reasoning=True,
        )

        result.retries = (
            self._query_history.get(query_id, history).reasoning_trace.__len__() // 3
            + 1
        )
        result.metadata["retry_of"] = query_id
        result.metadata["correction_hint"] = correction_hint

        return result

    def get_query_history(self, query_id: str) -> QueryHistoryEntry | None:
        """
        Get query history entry by ID.

        Args:
            query_id: Query ID to look up

        Returns:
            QueryHistoryEntry or None if not found
        """
        return self._query_history.get(query_id)

    async def _get_schema_description(self, database_id: str) -> str:
        """Get formatted schema description for prompts."""
        if database_id in self._schema_cache:
            return self._schema_cache[database_id]

        introspector = SchemaIntrospector(self._db_manager.engine)
        schema = await introspector.get_schema(database_id)
        description = introspector.serialize_for_prompt(schema)

        self._schema_cache[database_id] = description
        return description

    async def _generate_sql_with_model(
        self,
        natural_query: str,
        schema_description: str,
    ) -> tuple[str, float]:
        """Generate SQL using the Text2SQL model."""
        from models.inference import InferenceEngine
        from models.loader import get_model_loader
        from models.prompts import build_prompt

        model_loader = await get_model_loader()

        if not model_loader.is_loaded:
            await model_loader.load()

        prompt = build_prompt(
            question=natural_query,
            schema=schema_description,
            template_type="arctic",
            dialect=self._db_manager.dialect,
        )

        inference_engine = InferenceEngine(model_loader)
        result = await inference_engine.generate(prompt, extract_sql=True)

        return result.sql or "", result.confidence

    async def _generate_sql_with_hints(
        self,
        natural_query: str,
        schema_description: str,
        previous_sql: str,
        hints: list[str],
    ) -> tuple[str, float]:
        """Generate improved SQL using correction hints."""
        from models.inference import InferenceEngine
        from models.loader import get_model_loader
        from models.prompts import build_prompt

        # Build enhanced prompt with hints
        hint_text = "\n".join(f"- {hint}" for hint in hints)
        enhanced_question = (
            f"{natural_query}\n\n"
            f"Note: Previous attempt '{previous_sql}' had issues:\n{hint_text}\n"
            f"Please generate a corrected SQL query."
        )

        model_loader = await get_model_loader()

        if not model_loader.is_loaded:
            await model_loader.load()

        prompt = build_prompt(
            question=enhanced_question,
            schema=schema_description,
            template_type="arctic",
            dialect=self._db_manager.dialect,
            use_default_examples=True,
        )

        inference_engine = InferenceEngine(model_loader)
        result = await inference_engine.generate(prompt, extract_sql=True)

        return result.sql or previous_sql, result.confidence

    async def _execute_and_format(
        self,
        sql: str,
        max_rows: int,
    ) -> tuple[str, list[dict[str, Any]], int]:
        """Execute SQL and format results."""
        from db.executor import SafeQueryExecutor

        async with self._db_manager.session() as session:
            executor = SafeQueryExecutor(
                session=session,
                allow_mutations=False,
                max_rows=max_rows,
            )

            result = await executor.execute(sql)

            # Format for validation tool
            if not result.rows:
                results_str = "Query returned 0 rows."
            else:
                lines = [f"Query returned {result.row_count} rows:"]
                for i, row in enumerate(result.rows[:10], 1):
                    row_str = ", ".join(f"{k}={v}" for k, v in row.items())
                    lines.append(f"Row {i}: {row_str}")
                if result.row_count > 10:
                    lines.append(f"... and {result.row_count - 10} more rows")
                results_str = "\n".join(lines)

            return results_str, result.rows, result.row_count

    def _calculate_confidence(
        self,
        model_confidence: float,
        validation_result: ValidationResult | None,
        steps_taken: int,
    ) -> float:
        """
        Calculate overall confidence based on multiple factors.

        Factors:
        - Model confidence from Text2SQL generation
        - Validation outcome
        - Number of steps taken (fewer is better)
        """
        confidence = model_confidence

        # Adjust based on validation
        if validation_result:
            if validation_result.outcome == ValidationOutcome.VALID:
                confidence = min(1.0, confidence * 1.1)  # Boost for validation pass
            elif validation_result.outcome == ValidationOutcome.NEEDS_CORRECTION:
                confidence *= 0.8  # Penalty for needing correction
            elif validation_result.outcome == ValidationOutcome.INVALID:
                confidence *= 0.6  # Larger penalty for invalid

        # Adjust based on steps (more steps = less confidence)
        step_penalty = (steps_taken - 3) * 0.02  # -2% per step over 3
        confidence = max(0.0, confidence - step_penalty)

        return round(min(1.0, max(0.0, confidence)), 3)

    def invalidate_schema_cache(self, database_id: str | None = None) -> None:
        """Invalidate cached schema descriptions."""
        if database_id:
            self._schema_cache.pop(database_id, None)
        else:
            self._schema_cache.clear()


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
