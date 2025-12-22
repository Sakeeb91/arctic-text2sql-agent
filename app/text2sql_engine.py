"""
Core Text2SQL Engine - Central orchestration layer.

This module provides the main orchestrator that coordinates:
- Schema extraction and context building
- Model inference for SQL generation
- SQL validation and schema alignment
- Confidence-based filtering and retry logic
- Query intent classification
- Result formatting and execution

The Text2SQLEngine is the primary entry point for converting
natural language questions into SQL queries.
"""

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from app.config import FewShotSettings, get_settings
from app.cache import (
    cache_prompt,
    cache_schema,
    generate_prompt_hash,
    get_cached_prompt,
    get_cached_schema,
)
from app.exceptions import (
    AgentMaxStepsExceededException,
    CircuitBreakerOpenException,
    ModelInferenceException,
    SchemaNotFoundException,
)
from app.logging_config import get_logger
from app.monitoring.metrics import get_metrics_registry
from app.monitoring.model_instrumentation import ModelInstrumentor
from app.monitoring.tracing import get_tracing_manager
from app.resilience import CircuitBreaker, CircuitBreakerConfig, compute_backoff_seconds
from db.connection import DatabaseManager
from db.executor import QueryResult
from db.registry import get_database_registry
from db.schema import SchemaInfo, SchemaIntrospector

logger = get_logger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


class QueryIntent(str, Enum):
    """Classification of query intent types."""

    SELECT = "select"
    AGGREGATE = "aggregate"
    JOIN = "join"
    SUBQUERY = "subquery"
    UNKNOWN = "unknown"


class ValidationStatus(str, Enum):
    """SQL validation status."""

    VALID = "valid"
    INVALID_SYNTAX = "invalid_syntax"
    SCHEMA_MISMATCH = "schema_mismatch"
    DANGEROUS_QUERY = "dangerous_query"
    NOT_VALIDATED = "not_validated"


@dataclass
class SchemaContext:
    """
    Context containing database schema information for SQL generation.

    Attributes:
        database_id: Unique identifier for the database
        dialect: SQL dialect (postgresql, mysql, sqlite)
        schema_info: Full schema information object
        serialized_schema: Schema formatted for model prompt
        table_names: List of available table names
    """

    database_id: str
    dialect: str
    schema_info: SchemaInfo
    serialized_schema: str
    table_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "database_id": self.database_id,
            "dialect": self.dialect,
            "table_names": self.table_names,
            "table_count": len(self.table_names),
        }


@dataclass(frozen=True)
class DatabaseContext:
    """Resolved database resources for a database id."""

    database_id: str
    engine: Any
    dialect: str
    session_provider: Callable[[], Any]


@dataclass
class ReasoningStep:
    """
    A single step in the agent's reasoning process.

    Attributes:
        step: Step number (1-indexed)
        thought: Agent's reasoning at this step
        action: Action taken (e.g., "generate_sql", "validate", "execute")
        observation: Result or observation from the action
        timestamp: When this step occurred
    """

    step: int
    thought: str
    action: str | None = None
    observation: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "step": self.step,
            "thought": self.thought,
            "action": self.action,
            "observation": self.observation,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class SQLResult:
    """
    Result of SQL generation from natural language.

    Attributes:
        sql: Generated SQL query
        confidence: Model confidence score (0.0-1.0)
        execution_time_ms: Total processing time in milliseconds
        valid_syntax: Whether SQL passed syntax validation
        validation_status: Detailed validation status
        dialect: SQL dialect used
        intent: Classified query intent
        warnings: List of warnings during generation
        reasoning_trace: Agent reasoning steps (if enabled)
        execution_results: Query results (if executed)
        row_count: Number of rows returned (if executed)
        metadata: Additional metadata
    """

    sql: str
    confidence: float
    execution_time_ms: float
    valid_syntax: bool
    validation_status: ValidationStatus
    dialect: str
    intent: QueryIntent = QueryIntent.UNKNOWN
    warnings: list[str] = field(default_factory=list)
    reasoning_trace: list[ReasoningStep] = field(default_factory=list)
    execution_results: list[dict[str, Any]] | None = None
    row_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "sql": self.sql,
            "confidence": self.confidence,
            "execution_time_ms": self.execution_time_ms,
            "valid_syntax": self.valid_syntax,
            "validation_status": self.validation_status.value,
            "dialect": self.dialect,
            "intent": self.intent.value,
            "warnings": self.warnings,
            "reasoning_trace": [step.to_dict() for step in self.reasoning_trace],
            "execution_results": self.execution_results,
            "row_count": self.row_count,
            "metadata": self.metadata,
        }


# =============================================================================
# Query Intent Classification
# =============================================================================


def classify_query_intent(natural_query: str) -> QueryIntent:
    """
    Classify the intent of a natural language query.

    Analyzes the query to determine what type of SQL operation
    is likely needed (simple select, aggregation, join, etc.).

    Args:
        natural_query: Natural language question

    Returns:
        QueryIntent: Classified intent type
    """
    query_lower = natural_query.lower()

    # Check for aggregation keywords
    aggregate_patterns = [
        r"\bhow many\b",
        r"\bcount\b",
        r"\btotal\b",
        r"\bsum\b",
        r"\baverage\b",
        r"\bavg\b",
        r"\bmaximum\b",
        r"\bmax\b",
        r"\bminimum\b",
        r"\bmin\b",
        r"\bgroup\b",
    ]
    for pattern in aggregate_patterns:
        if re.search(pattern, query_lower):
            return QueryIntent.AGGREGATE

    # Check for join indicators
    join_patterns = [
        r"\bwith\s+their\b",
        r"\balong\s+with\b",
        r"\band\s+their\b",
        r"\bfor\s+each\b",
        r"\bper\b",
        r"\brelationship\b",
        r"\bcombined?\b",
    ]
    for pattern in join_patterns:
        if re.search(pattern, query_lower):
            return QueryIntent.JOIN

    # Check for subquery indicators
    subquery_patterns = [
        r"\bwho\s+has\s+the\s+most\b",
        r"\bwhich\s+.+\s+has\s+the\b",
        r"\btop\s+\d+\b",
        r"\bhighest\b",
        r"\blowest\b",
        r"\bmore\s+than\b",
        r"\bless\s+than\b",
    ]
    for pattern in subquery_patterns:
        if re.search(pattern, query_lower):
            return QueryIntent.SUBQUERY

    # Check for simple select
    select_patterns = [
        r"\bshow\b",
        r"\blist\b",
        r"\bfind\b",
        r"\bget\b",
        r"\bdisplay\b",
        r"\bwhat\s+are\b",
        r"\bwhat\s+is\b",
    ]
    for pattern in select_patterns:
        if re.search(pattern, query_lower):
            return QueryIntent.SELECT

    return QueryIntent.UNKNOWN


# =============================================================================
# SQL Validation
# =============================================================================


@dataclass
class SemanticValidationFeedback:
    """Semantic validation warnings and suggestions."""

    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "warnings": self.warnings,
            "suggestions": self.suggestions,
        }


class SQLValidator:
    """
    Validates SQL queries for syntax and schema alignment.

    Provides multiple levels of validation:
    - Basic syntax checks (balanced parentheses, valid commands)
    - Security checks (injection patterns, dangerous keywords)
    - Schema alignment (table/column existence)
    """

    # Dangerous keywords that suggest mutation or injection
    DANGEROUS_KEYWORDS = {
        "DROP",
        "DELETE",
        "TRUNCATE",
        "ALTER",
        "CREATE",
        "INSERT",
        "UPDATE",
        "GRANT",
        "REVOKE",
        "EXEC",
        "EXECUTE",
    }

    # SQL injection patterns
    INJECTION_PATTERNS = [
        r";\s*--",
        r";\s*DROP",
        r";\s*DELETE",
        r";\s*UPDATE.*SET",
        r";\s*INSERT",
        r"UNION\s+SELECT",
        r"OR\s+1\s*=\s*1",
        r"OR\s+'\w*'\s*=\s*'\w*'",
        r"--.*DROP",
        r"/\*.*DROP.*\*/",
    ]

    def __init__(self, allow_mutations: bool = False) -> None:
        """
        Initialize SQL validator.

        Args:
            allow_mutations: Whether to allow mutation queries (INSERT/UPDATE/DELETE)
        """
        self._allow_mutations = allow_mutations

    def validate(
        self,
        sql: str,
        schema_context: SchemaContext | None = None,
    ) -> tuple[ValidationStatus, list[str]]:
        """
        Validate SQL query comprehensively.

        Args:
            sql: SQL query to validate
            schema_context: Optional schema context for alignment check

        Returns:
            Tuple of (validation status, list of error messages)
        """
        errors: list[str] = []

        database_id = schema_context.database_id if schema_context else "unknown"

        # Basic syntax check
        syntax_valid, syntax_errors = self._check_syntax(sql)
        if not syntax_valid:
            errors.extend(syntax_errors)
            self._record_validation_metrics(
                database_id, ValidationStatus.INVALID_SYNTAX
            )
            return ValidationStatus.INVALID_SYNTAX, errors

        # Security check
        is_safe, security_errors = self._check_security(sql)
        if not is_safe:
            errors.extend(security_errors)
            self._record_validation_metrics(
                database_id, ValidationStatus.DANGEROUS_QUERY
            )
            return ValidationStatus.DANGEROUS_QUERY, errors

        # Schema alignment check
        if schema_context:
            aligned, alignment_errors = self._check_schema_alignment(
                sql, schema_context
            )
            if not aligned:
                errors.extend(alignment_errors)
                self._record_validation_metrics(
                    database_id, ValidationStatus.SCHEMA_MISMATCH
                )
                return ValidationStatus.SCHEMA_MISMATCH, errors

        self._record_validation_metrics(database_id, ValidationStatus.VALID)
        return ValidationStatus.VALID, []

    def _record_validation_metrics(
        self, database_id: str, status: ValidationStatus
    ) -> None:
        metrics = get_metrics_registry()
        metrics.record_sql_validation(
            database_id=database_id,
            valid=status == ValidationStatus.VALID,
        )
        if status == ValidationStatus.INVALID_SYNTAX:
            metrics.record_sql_syntax_error(
                database_id=database_id, error_type="syntax"
            )

    def _check_syntax(self, sql: str) -> tuple[bool, list[str]]:
        """Check basic SQL syntax."""
        errors: list[str] = []
        sql_stripped = sql.strip()
        sql_upper = sql_stripped.upper()

        # Check for empty query
        if not sql_stripped:
            errors.append("SQL query is empty")
            return False, errors

        # Must start with valid SQL command
        valid_starts = ["SELECT", "WITH", "EXPLAIN"]
        if not any(sql_upper.startswith(cmd) for cmd in valid_starts):
            errors.append(f"Query must start with: {', '.join(valid_starts)}")
            return False, errors

        # Check balanced parentheses
        if sql.count("(") != sql.count(")"):
            errors.append("Unbalanced parentheses")
            return False, errors

        # Check balanced quotes (basic check)
        single_quotes = sql.count("'") - sql.count("\\'")
        if single_quotes % 2 != 0:
            errors.append("Unbalanced single quotes")
            return False, errors

        return True, []

    def _check_security(self, sql: str) -> tuple[bool, list[str]]:
        """Check for dangerous patterns."""
        errors: list[str] = []
        sql_upper = sql.upper()

        # Check for dangerous keywords
        if not self._allow_mutations:
            for keyword in self.DANGEROUS_KEYWORDS:
                if re.search(rf"\b{keyword}\b", sql_upper):
                    errors.append(f"Dangerous keyword detected: {keyword}")

        # Check for injection patterns
        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, sql_upper):
                errors.append("Potential SQL injection pattern detected")
                break

        return len(errors) == 0, errors

    def _check_schema_alignment(
        self,
        sql: str,
        schema_context: SchemaContext,
    ) -> tuple[bool, list[str]]:
        """Check if referenced tables exist in schema."""
        errors: list[str] = []

        # Extract table names from SQL
        tables_in_sql = self._extract_table_names(sql)
        tables_in_schema = {t.lower() for t in schema_context.table_names}

        # Check all tables exist
        for table in tables_in_sql:
            if table.lower() not in tables_in_schema:
                errors.append(f"Table not found in schema: {table}")

        return len(errors) == 0, errors

    def check_semantics(
        self,
        natural_query: str,
        sql: str,
        intent: QueryIntent,
    ) -> SemanticValidationFeedback:
        """
        Perform semantic checks between natural query intent and SQL structure.

        Returns warnings and suggestions without failing validation.
        """
        feedback = SemanticValidationFeedback()
        sql_upper = sql.upper()
        query_lower = natural_query.lower()

        if intent == QueryIntent.AGGREGATE and not self._has_aggregation(sql_upper):
            feedback.warnings.append(
                "Query intent suggests aggregation, but SQL lacks aggregate functions."
            )
            feedback.suggestions.append(
                "Consider using COUNT, SUM, AVG, MIN, MAX, or GROUP BY."
            )

        if intent == QueryIntent.JOIN and not self._has_join(sql_upper):
            feedback.warnings.append(
                "Query intent suggests a join, but SQL does not include JOINs."
            )
            feedback.suggestions.append(
                "Add JOIN clauses between related tables to match the request."
            )

        if intent == QueryIntent.SUBQUERY and not self._has_order_by(sql_upper):
            feedback.warnings.append(
                "Superlative query may require ordering to find top/bottom results."
            )
            feedback.suggestions.append(
                "Add ORDER BY with DESC/ASC and LIMIT for top/bottom queries."
            )

        top_match = re.search(r"\btop\s+(\d+)\b", query_lower)
        if top_match and not self._has_limit(sql_upper):
            feedback.warnings.append(
                "Natural language request includes a top-N filter without LIMIT."
            )
            feedback.suggestions.append(
                f"Add LIMIT {top_match.group(1)} to restrict results."
            )

        if re.search(
            r"\b(most|highest|lowest|least)\b", query_lower
        ) and not self._has_order_by(sql_upper):
            feedback.warnings.append("Ranking intent detected without ORDER BY in SQL.")
            feedback.suggestions.append(
                "Use ORDER BY to rank results and LIMIT 1 for the best match."
            )

        return feedback

    def _extract_table_names(self, sql: str) -> list[str]:
        """Extract table names from SQL query."""
        tables: list[str] = []

        # FROM clause
        from_matches = re.findall(
            r"FROM\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            sql,
            re.IGNORECASE,
        )
        tables.extend(from_matches)

        # JOIN clause
        join_matches = re.findall(
            r"JOIN\s+([a-zA-Z_][a-zA-Z0-9_]*)",
            sql,
            re.IGNORECASE,
        )
        tables.extend(join_matches)

        return list(set(tables))

    @staticmethod
    def _has_aggregation(sql_upper: str) -> bool:
        aggregate_tokens = ["COUNT(", "SUM(", "AVG(", "MIN(", "MAX("]
        return any(token in sql_upper for token in aggregate_tokens) or (
            "GROUP BY" in sql_upper
        )

    @staticmethod
    def _has_join(sql_upper: str) -> bool:
        return " JOIN " in sql_upper or " JOIN\n" in sql_upper

    @staticmethod
    def _has_order_by(sql_upper: str) -> bool:
        return "ORDER BY" in sql_upper

    @staticmethod
    def _has_limit(sql_upper: str) -> bool:
        return "LIMIT" in sql_upper or "FETCH FIRST" in sql_upper


# =============================================================================
# Text2SQL Engine
# =============================================================================


class Text2SQLEngine:
    """
    Main orchestrator for Natural Language to SQL translation.

    Coordinates the full pipeline:
    1. Schema extraction and context building
    2. Query intent classification
    3. Prompt construction with schema context
    4. Model inference for SQL generation
    5. SQL validation (syntax + schema alignment)
    6. Confidence-based retry logic
    7. Optional SQL execution

    Usage:
        engine = Text2SQLEngine(db_manager)
        result = await engine.generate_sql(
            "Show all customers from California",
            database_id="my_db"
        )
        print(result.sql)
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        min_confidence: float | None = None,
        max_retries: int | None = None,
        enable_validation: bool | None = None,
    ) -> None:
        """
        Initialize Text2SQL engine.

        Args:
            db_manager: Database manager for connections
            min_confidence: Minimum confidence threshold (default from settings)
            max_retries: Maximum retry attempts (default from settings)
            enable_validation: Enable SQL validation (default from settings)
        """
        settings = get_settings()

        self._db_manager = db_manager
        self._min_confidence = min_confidence or settings.agent.min_confidence
        self._max_retries = max_retries or settings.agent.max_steps
        self._enable_validation = (
            enable_validation
            if enable_validation is not None
            else settings.agent.enable_validation
        )
        self._resilience_settings = settings.resilience
        self._few_shot_settings = (
            settings.few_shot
            if isinstance(settings.few_shot, FewShotSettings)
            else FewShotSettings(enabled=False)
        )
        self._circuit_breaker = CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=self._resilience_settings.failure_threshold,
                recovery_timeout_seconds=self._resilience_settings.recovery_timeout_seconds,
                half_open_max_attempts=self._resilience_settings.half_open_max_attempts,
            )
        )
        self._backoff_base = self._resilience_settings.backoff_base_seconds
        self._backoff_max = self._resilience_settings.backoff_max_seconds
        self._fallback_enabled = self._resilience_settings.fallback_enabled

        self._validator = SQLValidator(allow_mutations=False)
        self._schema_cache: dict[str, SchemaContext] = {}
        self._cache_enabled = settings.cache.enabled
        model_name = getattr(getattr(settings, "huggingface", None), "model_name", None)
        self._instrumentor = ModelInstrumentor(
            model_name=model_name or "arctic-text2sql"
        )
        self._metrics = get_metrics_registry()
        self._tracing = get_tracing_manager()

        logger.info(
            "text2sql_engine_initialized",
            min_confidence=self._min_confidence,
            max_retries=self._max_retries,
            enable_validation=self._enable_validation,
            resilience={
                "failure_threshold": self._resilience_settings.failure_threshold,
                "recovery_timeout_seconds": self._resilience_settings.recovery_timeout_seconds,
                "half_open_max_attempts": self._resilience_settings.half_open_max_attempts,
            },
        )

    async def generate_sql(
        self,
        natural_query: str,
        database_id: str,
        execute: bool = False,
        show_reasoning: bool = False,
        max_rows: int = 100,
    ) -> SQLResult:
        """
        Generate SQL from natural language query.

        This is the main entry point for SQL generation. It orchestrates:
        1. Schema context extraction
        2. Query intent classification
        3. Prompt building with schema
        4. Model inference
        5. Validation and retry logic
        6. Optional execution

        Args:
            natural_query: Natural language question
            database_id: Database identifier
            execute: Whether to execute generated SQL
            show_reasoning: Include reasoning trace in result
            max_rows: Maximum rows to return if executing

        Returns:
            SQLResult with generated SQL and metadata

        Raises:
            SchemaNotFoundException: If database schema not found
            ModelInferenceException: If model inference fails
            AgentMaxStepsExceededException: If max retries exceeded
        """
        start_time = time.perf_counter()
        warnings: list[str] = []
        reasoning_trace: list[ReasoningStep] = []
        step_num = 0

        logger.info(
            "sql_generation_started",
            database_id=database_id,
            query_length=len(natural_query),
            execute=execute,
        )

        # Step 1: Get schema context
        step_num += 1
        if show_reasoning:
            reasoning_trace.append(
                ReasoningStep(
                    step=step_num,
                    thought="Retrieving database schema context",
                    action="get_schema",
                )
            )

        try:
            schema_context = await self._get_schema_context(database_id)
        except Exception as e:
            logger.error(
                "schema_retrieval_failed",
                database_id=database_id,
                error=str(e),
            )
            raise SchemaNotFoundException(
                database_id=database_id,
                details={"error": str(e)},
            ) from e

        if show_reasoning:
            reasoning_trace[-1].observation = (
                f"Found {len(schema_context.table_names)} tables: "
                f"{', '.join(schema_context.table_names[:5])}"
                f"{'...' if len(schema_context.table_names) > 5 else ''}"
            )

        # Step 2: Classify query intent
        step_num += 1
        intent = classify_query_intent(natural_query)

        if show_reasoning:
            reasoning_trace.append(
                ReasoningStep(
                    step=step_num,
                    thought="Classifying query intent",
                    action="classify_intent",
                    observation=f"Intent classified as: {intent.value}",
                )
            )

        # Step 3: Generate SQL with retry logic
        step_num += 1
        if show_reasoning:
            reasoning_trace.append(
                ReasoningStep(
                    step=step_num,
                    thought="Generating SQL query from natural language",
                    action="generate_sql",
                )
            )

        inference_result, generation_warnings = await self._generate_with_retry(
            natural_query=natural_query,
            schema_context=schema_context,
            intent=intent,
        )
        warnings.extend(generation_warnings)

        if show_reasoning:
            reasoning_trace[-1].observation = (
                f"Generated SQL with confidence {inference_result.confidence:.2f}"
            )

        # Step 4: Validate SQL
        step_num += 1
        validation_status = ValidationStatus.NOT_VALIDATED
        valid_syntax = True
        semantic_feedback: SemanticValidationFeedback | None = None

        if self._enable_validation:
            if show_reasoning:
                reasoning_trace.append(
                    ReasoningStep(
                        step=step_num,
                        thought="Validating generated SQL",
                        action="validate_sql",
                    )
                )

            validation_status, validation_errors = self._validator.validate(
                inference_result.sql or "",
                schema_context,
            )
            valid_syntax = validation_status == ValidationStatus.VALID

            if not valid_syntax:
                warnings.extend(validation_errors)
                if show_reasoning:
                    reasoning_trace[-1].observation = (
                        f"Validation failed: {', '.join(validation_errors)}"
                    )
            else:
                if show_reasoning:
                    reasoning_trace[-1].observation = "SQL validation passed"

        if self._enable_validation and valid_syntax and inference_result.sql:
            semantic_feedback = self._validator.check_semantics(
                natural_query=natural_query,
                sql=inference_result.sql,
                intent=intent,
            )
            if semantic_feedback.warnings:
                warnings.extend(semantic_feedback.warnings)
            if semantic_feedback.suggestions:
                warnings.extend(
                    [f"Suggestion: {item}" for item in semantic_feedback.suggestions]
                )

        # Step 5: Check confidence threshold
        if inference_result.confidence < self._min_confidence:
            warnings.append(
                f"Low confidence: {inference_result.confidence:.2f} "
                f"(threshold: {self._min_confidence:.2f})"
            )

        # Step 6: Execute if requested
        execution_results: list[dict[str, Any]] | None = None
        row_count: int | None = None

        if execute and valid_syntax and inference_result.sql:
            step_num += 1
            if show_reasoning:
                reasoning_trace.append(
                    ReasoningStep(
                        step=step_num,
                        thought="Executing generated SQL",
                        action="execute_sql",
                    )
                )

            try:
                execution_results, row_count = await self._execute_sql(
                    inference_result.sql,
                    max_rows,
                    database_id=database_id,
                )
                if show_reasoning:
                    reasoning_trace[-1].observation = f"Query returned {row_count} rows"
            except Exception as e:
                warnings.append(f"Execution failed: {str(e)}")
                if show_reasoning:
                    reasoning_trace[-1].observation = f"Execution failed: {str(e)}"

        # Calculate execution time
        execution_time_ms = (time.perf_counter() - start_time) * 1000

        logger.info(
            "sql_generation_complete",
            database_id=database_id,
            confidence=inference_result.confidence,
            valid_syntax=valid_syntax,
            execution_time_ms=round(execution_time_ms, 2),
            executed=execute,
            row_count=row_count,
        )

        return SQLResult(
            sql=inference_result.sql or "",
            confidence=inference_result.confidence,
            execution_time_ms=execution_time_ms,
            valid_syntax=valid_syntax,
            validation_status=validation_status,
            dialect=schema_context.dialect,
            intent=intent,
            warnings=warnings,
            reasoning_trace=reasoning_trace if show_reasoning else [],
            execution_results=execution_results,
            row_count=row_count,
            metadata={
                "database_id": database_id,
                "table_count": len(schema_context.table_names),
                "input_tokens": inference_result.input_tokens,
                "output_tokens": inference_result.output_tokens,
                "retries": inference_result.metadata.get("retries", 0),
                "semantic_feedback": (
                    semantic_feedback.to_dict() if semantic_feedback else None
                ),
            },
        )

    async def validate_sql(
        self,
        sql: str,
        database_id: str,
    ) -> tuple[bool, list[str], list[str]]:
        """
        Validate SQL syntax and schema alignment.

        Args:
            sql: SQL query to validate
            database_id: Database to validate against

        Returns:
            Tuple of (is_valid, errors, warnings)
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Get schema context
        try:
            schema_context = await self._get_schema_context(database_id)
        except Exception as e:
            errors.append(f"Could not retrieve schema: {str(e)}")
            return False, errors, warnings

        # Validate
        status, validation_errors = self._validator.validate(sql, schema_context)

        if status == ValidationStatus.VALID:
            return True, [], []
        else:
            return False, validation_errors, warnings

    async def _get_schema_context(self, database_id: str) -> SchemaContext:
        """Get or create schema context for database."""
        start_time = time.perf_counter()
        db_context = await self._resolve_database_context(database_id)
        # Check cache
        if database_id in self._schema_cache:
            return self._schema_cache[database_id]

        if self._cache_enabled:
            cached_payload = await get_cached_schema(database_id)
            if isinstance(cached_payload, dict):
                schema_payload = cached_payload.get("schema_info", cached_payload)
                schema_info = SchemaInfo.from_dict(
                    schema_payload, database_id=database_id
                )
                serialized = cached_payload.get("serialized_schema")
                if not serialized:
                    introspector = SchemaIntrospector(db_context.engine)
                    serialized = introspector.serialize_for_prompt(schema_info)
                table_names = cached_payload.get("table_names") or [
                    table.name for table in schema_info.tables
                ]
                context = SchemaContext(
                    database_id=database_id,
                    dialect=schema_info.dialect,
                    schema_info=schema_info,
                    serialized_schema=serialized,
                    table_names=table_names,
                )
                self._schema_cache[database_id] = context
                duration = time.perf_counter() - start_time
                self._metrics.record_schema_introspection(
                    database_id=database_id,
                    status="cached",
                    duration_seconds=duration,
                )
                return context

        # Create introspector and get schema
        introspector = SchemaIntrospector(db_context.engine)
        with self._tracing.create_span(
            "schema.introspect",
            attributes={"db.database_id": database_id},
            kind="client",
        ):
            schema_info = await introspector.get_schema(database_id)

        # Serialize for prompt
        serialized = introspector.serialize_for_prompt(schema_info)

        # Build context
        context = SchemaContext(
            database_id=database_id,
            dialect=schema_info.dialect,
            schema_info=schema_info,
            serialized_schema=serialized,
            table_names=[table.name for table in schema_info.tables],
        )

        if self._cache_enabled:
            await cache_schema(
                database_id,
                {
                    "schema_info": schema_info.to_dict(),
                    "serialized_schema": serialized,
                    "table_names": context.table_names,
                    "dialect": schema_info.dialect,
                },
            )

        duration = time.perf_counter() - start_time
        self._metrics.record_schema_introspection(
            database_id=database_id,
            status="success",
            duration_seconds=duration,
        )

        # Cache and return
        self._schema_cache[database_id] = context
        return context

    async def _resolve_database_context(
        self,
        database_id: str | None,
    ) -> DatabaseContext:
        resolved_id = database_id or "default"
        settings = get_settings()

        if settings.multi_database.enabled:
            registry = await get_database_registry()
            registered = registry.get_database(resolved_id)
            dialect = (
                registered.config.dialect.value
                if registered.config.dialect is not None
                else registered.engine.dialect.name
            )
            return DatabaseContext(
                database_id=resolved_id,
                engine=registered.engine,
                dialect=dialect,
                session_provider=lambda: registry.session(resolved_id),
            )

        return DatabaseContext(
            database_id=resolved_id,
            engine=self._db_manager.engine,
            dialect=self._db_manager.dialect,
            session_provider=self._db_manager.session,
        )

    async def _get_few_shot_examples(
        self,
        natural_query: str,
        database_id: str,
        attempt: int,
    ) -> list[Any]:
        """Retrieve few-shot examples for the given attempt."""
        if not self._few_shot_settings.enabled:
            return []

        if attempt == 0 and not self._few_shot_settings.use_on_first_attempt:
            return []
        if attempt > 0 and not self._few_shot_settings.use_on_retry:
            return []

        try:
            from app.few_shot.service import get_few_shot_service

            service = await get_few_shot_service()
            return await service.get_prompt_examples(
                natural_query=natural_query,
                database_id=database_id,
            )
        except Exception as e:
            logger.warning("few_shot_retrieval_failed", error=str(e))
            return []

    def _build_prompt_cache_key(
        self,
        natural_query: str,
        schema_context: SchemaContext,
        intent: QueryIntent,
        attempt: int,
        use_default_examples: bool,
        few_shot_examples: list[Any],
    ) -> str:
        examples_payload = []
        for example in few_shot_examples:
            examples_payload.append(
                {
                    "question": getattr(example, "question", ""),
                    "sql": getattr(example, "sql", ""),
                    "explanation": getattr(example, "explanation", None),
                }
            )

        examples_hash = "none"
        if examples_payload:
            examples_hash = hashlib.sha256(
                json.dumps(examples_payload, sort_keys=True).encode()
            ).hexdigest()[:16]

        key_data = {
            "query": natural_query.lower().strip(),
            "database_id": schema_context.database_id,
            "dialect": schema_context.dialect,
            "intent": intent.value,
            "attempt": attempt,
            "schema_hash": generate_prompt_hash(schema_context.serialized_schema),
            "examples_hash": examples_hash,
            "use_default_examples": use_default_examples,
        }

        return hashlib.sha256(
            json.dumps(key_data, sort_keys=True).encode()
        ).hexdigest()[:32]

    async def _generate_with_retry(
        self,
        natural_query: str,
        schema_context: SchemaContext,
        intent: QueryIntent,
    ) -> tuple[Any, list[str]]:  # Returns InferenceResult but avoiding import
        """
        Generate SQL with retry logic for low confidence.

        Attempts generation up to max_retries times, with different
        prompt strategies on each retry.

        Args:
            natural_query: Natural language question
            schema_context: Database schema context
            intent: Classified query intent

        Returns:
            Tuple of (inference result, warnings list)
        """
        from models.inference import InferenceEngine, InferenceResult
        from models.loader import get_model_loader
        from models.prompts import build_prompt

        warnings: list[str] = []
        best_result: InferenceResult | None = None

        async def _run_inference(use_examples: bool, attempt: int) -> InferenceResult:
            model_loader = await get_model_loader()
            if not model_loader.is_loaded:
                await model_loader.load()

            inference_engine = InferenceEngine(
                model_loader,
                instrumentor=self._instrumentor,
            )
            few_shot_examples = await self._get_few_shot_examples(
                natural_query=natural_query,
                database_id=schema_context.database_id,
                attempt=attempt,
            )
            use_default = (
                use_examples or self._few_shot_settings.include_default_examples
            )
            prompt_cache_key = self._build_prompt_cache_key(
                natural_query=natural_query,
                schema_context=schema_context,
                intent=intent,
                attempt=attempt,
                use_default_examples=use_default,
                few_shot_examples=few_shot_examples,
            )
            prompt_cached = False
            prompt = None

            if self._cache_enabled:
                prompt = await get_cached_prompt(prompt_cache_key)
                prompt_cached = prompt is not None

            if not prompt:
                prompt = build_prompt(
                    question=natural_query,
                    schema=schema_context.serialized_schema,
                    template_type="arctic",
                    dialect=schema_context.dialect,
                    few_shot_examples=few_shot_examples,
                    use_default_examples=use_default,
                    context=(
                        f"Query intent: {intent.value}"
                        if intent != QueryIntent.UNKNOWN
                        else None
                    ),
                )
                if self._cache_enabled:
                    await cache_prompt(prompt_cache_key, prompt)

            trace_attributes = {
                "db.database_id": schema_context.database_id,
                "query.intent": intent.value,
                "query.attempt": attempt,
                "prompt.cached": prompt_cached,
                "prompt.examples_count": len(few_shot_examples),
            }

            return await inference_engine.generate(
                prompt,
                extract_sql=True,
                trace_attributes=trace_attributes,
            )

        if not self._circuit_breaker.can_attempt():
            warnings.append("Model inference temporarily unavailable (circuit open)")
            circuit_error = CircuitBreakerOpenException(
                details={
                    "failure_count": self._circuit_breaker.state.failure_count,
                    "last_error": self._circuit_breaker.state.last_error,
                },
                retry_after_seconds=self._resilience_settings.recovery_timeout_seconds,
            )
            if self._fallback_enabled:
                return self._build_fallback_inference_result("circuit_open"), warnings
            raise circuit_error

        for attempt in range(self._max_retries):
            try:
                use_examples = attempt > 0  # Add examples on retry
                current_use_examples = use_examples

                async def _task(
                    use_examples: bool = current_use_examples,
                    current_attempt: int = attempt,
                ) -> InferenceResult:
                    return await _run_inference(use_examples, current_attempt)

                result = await self._circuit_breaker.run(_task)

                if best_result is None or result.confidence > best_result.confidence:
                    best_result = result

                if result.confidence >= self._min_confidence:
                    if attempt > 0:
                        result.metadata["retries"] = attempt
                    return result, warnings

                logger.debug(
                    "low_confidence_retry",
                    attempt=attempt + 1,
                    confidence=result.confidence,
                    threshold=self._min_confidence,
                )

                if attempt < self._max_retries - 1:
                    warnings.append(
                        f"Retry {attempt + 1}: confidence {result.confidence:.2f} "
                        f"below threshold {self._min_confidence:.2f}"
                    )
                    delay = compute_backoff_seconds(
                        attempt, self._backoff_base, self._backoff_max
                    )
                    await asyncio.sleep(delay)

            except CircuitBreakerOpenException:
                warnings.append("Model inference circuit open")
                if self._fallback_enabled:
                    return (
                        self._build_fallback_inference_result("circuit_open"),
                        warnings,
                    )
                raise
            except Exception as e:
                logger.error(
                    "generation_attempt_failed",
                    attempt=attempt + 1,
                    error=str(e),
                )
                warnings.append(f"Generation attempt {attempt + 1} failed: {str(e)}")

                if attempt == self._max_retries - 1:
                    if self._fallback_enabled:
                        warnings.append("Returning fallback after repeated failures")
                        return (
                            self._build_fallback_inference_result("exhausted_retries"),
                            warnings,
                        )

                    raise ModelInferenceException(
                        message=f"All {self._max_retries} generation attempts failed",
                        details={"last_error": str(e)},
                    ) from e

                delay = compute_backoff_seconds(
                    attempt, self._backoff_base, self._backoff_max
                )
                await asyncio.sleep(delay)

        if best_result:
            best_result.metadata["retries"] = self._max_retries - 1
            return best_result, warnings

        raise AgentMaxStepsExceededException(
            max_steps=self._max_retries,
            details={"reason": "No successful generation"},
        )

    def _build_fallback_inference_result(self, reason: str) -> Any:
        """Construct a lightweight fallback inference result."""
        from models.inference import InferenceResult

        return InferenceResult(
            generated_text="",
            sql=None,
            confidence=0.0,
            metadata={"fallback": True, "reason": reason},
        )

    def get_resilience_state(self) -> dict[str, Any]:
        """Expose current circuit breaker state for health checks."""
        state = self._circuit_breaker.state
        return {
            "state": state.state,
            "failure_count": state.failure_count,
            "last_error": state.last_error,
            "half_open_attempts": state.half_open_attempts,
        }

    async def execute_sql(
        self,
        sql: str,
        database_id: str | None = None,
        max_rows: int = 1000,
    ) -> QueryResult:
        """
        Execute a SQL query using the safe executor.

        Args:
            sql: SQL query to execute
            database_id: Optional database identifier for logging
            max_rows: Maximum rows to return

        Returns:
            QueryResult with execution results
        """
        from db.executor import SafeQueryExecutor

        db_context = await self._resolve_database_context(database_id)
        async with db_context.session_provider() as session:
            executor = SafeQueryExecutor(
                session=session,
                allow_mutations=False,
                max_rows=max_rows,
                database_id=db_context.database_id,
                dialect=db_context.dialect,
            )

            result: QueryResult = await executor.execute(sql)

        logger.info(
            "text2sql_execute_sql",
            database_id=db_context.database_id,
            row_count=result.row_count,
        )

        return result

    async def _execute_sql(
        self,
        sql: str,
        max_rows: int,
        database_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Execute validated SQL query.

        Args:
            sql: SQL query to execute
            max_rows: Maximum rows to return

        Returns:
            Tuple of (results list, row count)
        """
        result = await self.execute_sql(
            sql=sql,
            database_id=database_id,
            max_rows=max_rows,
        )
        return result.rows, result.row_count

    def invalidate_schema_cache(self, database_id: str | None = None) -> None:
        """
        Invalidate cached schema context.

        Args:
            database_id: Specific database to invalidate, or None for all
        """
        if database_id:
            self._schema_cache.pop(database_id, None)
        else:
            self._schema_cache.clear()

        if self._cache_enabled:
            try:
                from app.cache import invalidate_schema_cache as invalidate_cache

                loop = asyncio.get_running_loop()
                loop.create_task(invalidate_cache(database_id))
            except RuntimeError:
                asyncio.run(invalidate_cache(database_id))

        logger.info(
            "schema_cache_invalidated",
            database_id=database_id or "all",
        )


# =============================================================================
# Global Engine Management
# =============================================================================


_text2sql_engine: Text2SQLEngine | None = None


async def get_text2sql_engine() -> Text2SQLEngine:
    """
    Get or create the global Text2SQL engine instance.

    Returns:
        Text2SQLEngine: Global engine instance
    """
    global _text2sql_engine

    if _text2sql_engine is None:
        from db.connection import get_database

        db_manager = await get_database()
        _text2sql_engine = Text2SQLEngine(db_manager)

    return _text2sql_engine


def reset_text2sql_engine() -> None:
    """Reset the global Text2SQL engine instance."""
    global _text2sql_engine
    _text2sql_engine = None
