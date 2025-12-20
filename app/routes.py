"""
FastAPI API route definitions.

This module defines all REST API endpoints for the Arctic Text2SQL Agent.

Issue #8: Added caching and streaming support for performance optimization.
"""

from datetime import datetime
from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import __version__
from app.config import get_settings
from app.exceptions import (
    AuthenticationException,
    ModelInferenceException,
    QueryNotFoundException,
    SchemaNotFoundException,
    ValidationException,
)
from app.logging_config import get_logger
from app.security import limiter, validate_database_id, validate_natural_language_query
from db.connection import get_database
from models.loader import get_model_loader

logger = get_logger(__name__)

# Create API router with prefix
router = APIRouter(prefix="/api/v1", tags=["Text2SQL"])


# =============================================================================
# Request/Response Models
# =============================================================================


class QueryRequest(BaseModel):
    """Request model for SQL generation."""

    query: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        description="Natural language question to convert to SQL",
        examples=["Show me all customers from California"],
    )
    database_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Registered database identifier",
        examples=["my_database"],
    )
    execute: bool = Field(
        default=False,
        description="Execute SQL after generation and return results",
    )
    show_reasoning: bool = Field(
        default=False,
        description="Include agent reasoning trace in response",
    )
    max_rows: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum rows to return when executing",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query": "Show me all customers from California who made purchases over $1000",
                    "database_id": "my_database",
                    "execute": True,
                    "show_reasoning": True,
                    "max_rows": 100,
                }
            ]
        }
    }


class ReasoningStep(BaseModel):
    """Model for agent reasoning step."""

    step: int = Field(..., description="Step number")
    thought: str = Field(..., description="Agent's thought process")
    action: str | None = Field(None, description="Action taken")
    observation: str | None = Field(None, description="Result of action")


class QueryResponse(BaseModel):
    """Response model for SQL generation."""

    sql: str = Field(..., description="Generated SQL query")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score")
    execution_time_ms: float = Field(
        ..., description="Total execution time in milliseconds"
    )
    dialect: str = Field(..., description="SQL dialect used")
    valid_syntax: bool = Field(..., description="Whether SQL syntax is valid")
    validation_status: str = Field(..., description="Validation status")
    results: list[dict[str, Any]] | None = Field(
        None, description="Query results if executed"
    )
    row_count: int | None = Field(None, description="Number of rows returned")
    reasoning_trace: list[ReasoningStep] | None = Field(
        None, description="Agent reasoning steps"
    )
    warnings: list[str] = Field(default_factory=list, description="Any warnings")


class ValidationRequest(BaseModel):
    """Request model for SQL validation."""

    sql: str = Field(..., min_length=1, description="SQL query to validate")
    database_id: str = Field(..., description="Database to validate against")


class ValidationResponse(BaseModel):
    """Response model for SQL validation."""

    valid: bool = Field(..., description="Whether SQL is valid")
    errors: list[str] = Field(default_factory=list, description="Validation errors")
    warnings: list[str] = Field(default_factory=list, description="Validation warnings")
    suggested_fixes: list[str] | None = Field(
        None, description="Suggested fixes for errors"
    )


class SchemaRequest(BaseModel):
    """Request model for schema registration."""

    database_id: str = Field(..., description="Unique database identifier")
    connection_string: str = Field(..., description="Database connection string")
    dialect: str = Field(
        default="postgresql",
        description="SQL dialect (postgresql, mysql, sqlite)",
    )


class SchemaResponse(BaseModel):
    """Response model for schema information."""

    database_id: str = Field(..., description="Database identifier")
    dialect: str = Field(..., description="SQL dialect")
    tables: list[dict[str, Any]] = Field(..., description="Table information")
    table_count: int = Field(..., description="Number of tables")
    last_updated: datetime = Field(..., description="Schema last updated time")


class HealthResponse(BaseModel):
    """Response model for health check."""

    status: str = Field(..., description="Health status")
    version: str = Field(..., description="API version")
    timestamp: datetime = Field(..., description="Current timestamp")
    components: dict[str, str] = Field(..., description="Component health status")


class ModelInfoResponse(BaseModel):
    """Response model for model information."""

    model_name: str = Field(..., description="Model name")
    model_loaded: bool = Field(..., description="Whether model is loaded")
    device: str = Field(..., description="Device model is running on")
    quantization: str | None = Field(None, description="Quantization type if enabled")


# =============================================================================
# Core Endpoints
# =============================================================================


@router.post("/query", response_model=QueryResponse)
@limiter.limit("10/minute")
async def generate_sql(request: Request, query_request: QueryRequest) -> QueryResponse:
    """
    Generate SQL from natural language query.

    Uses the agent-based approach with multi-step reasoning and self-correction
    to generate accurate SQL queries from natural language questions.

    Rate limit: 10 requests per minute per client.
    """
    # Validate natural language query (Phase 2.2: Security Implementation)
    is_valid_query, query_errors = validate_natural_language_query(query_request.query)
    if not is_valid_query:
        logger.warning(
            "invalid_nl_query",
            errors=query_errors,
            database_id=query_request.database_id,
        )
        raise ValidationException(
            message="Invalid natural language query",
            validation_errors=[{"field": "query", "error": e} for e in query_errors],
        )

    # Validate database ID (Phase 2.2: Security Implementation)
    is_valid_db, db_error = validate_database_id(query_request.database_id)
    if not is_valid_db:
        logger.warning(
            "invalid_database_id",
            error=db_error,
            database_id=query_request.database_id,
        )
        raise ValidationException(
            message=db_error or "Invalid database ID",
            validation_errors=[{"field": "database_id", "error": db_error}],
        )

    logger.info(
        "generate_sql_request",
        database_id=query_request.database_id,
        execute=query_request.execute,
        show_reasoning=query_request.show_reasoning,
    )
    settings = get_settings()

    def build_reasoning_trace(steps: list[Any] | None) -> list[ReasoningStep] | None:
        if not steps:
            return None

        reasoning: list[ReasoningStep] = []
        for step in steps:
            if hasattr(step, "step_number"):
                reasoning.append(
                    ReasoningStep(
                        step=step.step_number,
                        thought=step.content,
                        action=step.tool_name,
                        observation=step.tool_output,
                    )
                )
            else:
                reasoning.append(
                    ReasoningStep(
                        step=step.step,
                        thought=step.thought,
                        action=step.action,
                        observation=step.observation,
                    )
                )
        return reasoning

    if settings.agent.enabled:
        from app.agent import get_agent_engine

        try:
            agent_engine = await get_agent_engine()
            agent_result = await agent_engine.generate_sql(
                natural_query=query_request.query,
                database_id=query_request.database_id,
                execute=query_request.execute,
                show_reasoning=query_request.show_reasoning,
                max_rows=query_request.max_rows,
            )

            reasoning_trace = build_reasoning_trace(agent_result.reasoning_trace)
            metadata = agent_result.metadata or {}

            return QueryResponse(
                sql=agent_result.sql,
                confidence=agent_result.confidence,
                execution_time_ms=agent_result.execution_time_ms,
                dialect=metadata.get("dialect", "unknown"),
                valid_syntax=metadata.get("valid_syntax", True),
                validation_status=metadata.get("validation_status", "not_validated"),
                results=agent_result.execution_results,
                row_count=agent_result.row_count,
                reasoning_trace=reasoning_trace,
                warnings=agent_result.warnings,
            )
        except Exception as agent_error:
            if not settings.agent.use_legacy_fallback:
                raise
            if settings.agent.model_backend == "hf_inference":
                logger.warning(
                    "legacy_fallback_local_backend",
                    message="Legacy fallback uses local inference backend",
                )
            logger.warning(
                "agent_generation_failed_fallback",
                error=str(agent_error),
                database_id=query_request.database_id,
            )

    # Fallback to legacy Text2SQL engine
    from app.text2sql_engine import get_text2sql_engine

    try:
        engine = await get_text2sql_engine()

        result = await engine.generate_sql(
            natural_query=query_request.query,
            database_id=query_request.database_id,
            execute=query_request.execute,
            show_reasoning=query_request.show_reasoning,
            max_rows=query_request.max_rows,
        )

        reasoning_trace = build_reasoning_trace(result.reasoning_trace)

        return QueryResponse(
            sql=result.sql,
            confidence=result.confidence,
            execution_time_ms=result.execution_time_ms,
            dialect=result.dialect,
            valid_syntax=result.valid_syntax,
            validation_status=result.validation_status.value,
            results=result.execution_results,
            row_count=result.row_count,
            reasoning_trace=reasoning_trace,
            warnings=result.warnings,
        )

    except ModelInferenceException:
        raise
    except SchemaNotFoundException:
        raise
    except Exception as e:
        logger.error(
            "generate_sql_error",
            error=str(e),
            database_id=query_request.database_id,
        )
        raise ModelInferenceException(
            message=f"SQL generation failed: {str(e)}",
            details={"database_id": query_request.database_id},
        ) from e


@router.post("/validate", response_model=ValidationResponse)
@limiter.limit("20/minute")
async def validate_sql(
    request: Request, validation_request: ValidationRequest
) -> ValidationResponse:
    """
    Validate SQL syntax and semantics.

    Checks if the provided SQL is syntactically correct and matches
    the database schema.

    Rate limit: 20 requests per minute per client.
    """
    # Import validation utilities (Phase 2.2: Security Implementation)
    from app.security import validate_sql_query

    # Validate database ID
    is_valid_db, db_error = validate_database_id(validation_request.database_id)
    if not is_valid_db:
        logger.warning(
            "invalid_database_id",
            error=db_error,
            database_id=validation_request.database_id,
        )
        raise ValidationException(
            message=db_error or "Invalid database ID",
            validation_errors=[{"field": "database_id", "error": db_error}],
        )

    logger.info(
        "validate_sql_request",
        database_id=validation_request.database_id,
    )

    # Validate SQL query for injection patterns first
    is_safe, security_errors = validate_sql_query(validation_request.sql)

    if not is_safe:
        return ValidationResponse(
            valid=False,
            errors=security_errors,
            warnings=[],
            suggested_fixes=["Remove dangerous SQL patterns from query"],
        )

    # Use Text2SQL engine for comprehensive validation
    from app.text2sql_engine import get_text2sql_engine

    try:
        engine = await get_text2sql_engine()
        is_valid, errors, warnings = await engine.validate_sql(
            sql=validation_request.sql,
            database_id=validation_request.database_id,
        )

        return ValidationResponse(
            valid=is_valid,
            errors=errors,
            warnings=warnings,
            suggested_fixes=None,
        )

    except Exception as e:
        logger.error(
            "validate_sql_error",
            error=str(e),
            database_id=validation_request.database_id,
        )
        # Fall back to basic validation on error
        return ValidationResponse(
            valid=is_safe,
            errors=[],
            warnings=[f"Schema validation unavailable: {str(e)}"],
            suggested_fixes=None,
        )


@router.get("/schema/{database_id}", response_model=SchemaResponse)
@limiter.limit("30/minute")
async def get_schema(request: Request, database_id: str) -> SchemaResponse:
    """
    Get database schema information.

    Returns table names, column definitions, and relationships
    for the specified database.

    Rate limit: 30 requests per minute per client.
    """
    # Validate database ID (Phase 2.2: Security Implementation)
    is_valid_db, db_error = validate_database_id(database_id)
    if not is_valid_db:
        logger.warning(
            "invalid_database_id",
            error=db_error,
            database_id=database_id,
        )
        raise ValidationException(
            message=db_error or "Invalid database ID",
            validation_errors=[{"field": "database_id", "error": db_error}],
        )

    logger.info("get_schema_request", database_id=database_id)

    try:
        from db.schema import SchemaIntrospector

        db_manager = await get_database()
        introspector = SchemaIntrospector(db_manager.engine)
        schema = await introspector.get_schema(database_id)

        return SchemaResponse(
            database_id=schema.database_id,
            dialect=schema.dialect,
            tables=[table.to_dict() for table in schema.tables],
            table_count=len(schema.tables),
            last_updated=schema.last_updated,
        )
    except Exception as e:
        logger.error("get_schema_error", database_id=database_id, error=str(e))
        # Return empty schema on error for now
        return SchemaResponse(
            database_id=database_id,
            dialect="unknown",
            tables=[],
            table_count=0,
            last_updated=datetime.now(),
        )


@router.post("/schema/register")
@limiter.limit("10/minute")
async def register_schema(
    request: Request, schema_request: SchemaRequest
) -> dict[str, str]:
    """
    Register a new database schema.

    Connects to the database, extracts schema information,
    and stores it for future query generation.

    Rate limit: 10 requests per minute per client.
    """
    # Validate database ID
    is_valid_db, db_error = validate_database_id(schema_request.database_id)
    if not is_valid_db:
        logger.warning(
            "invalid_database_id",
            error=db_error,
            database_id=schema_request.database_id,
        )
        raise ValidationException(
            message=db_error or "Invalid database ID",
            validation_errors=[{"field": "database_id", "error": db_error}],
        )

    logger.info(
        "register_schema_request",
        database_id=schema_request.database_id,
        dialect=schema_request.dialect,
    )

    # TODO: Implement actual registration
    return {"status": "registered", "database_id": schema_request.database_id}


# =============================================================================
# Agent-Specific Endpoints
# =============================================================================


class AgentReasoningResponse(BaseModel):
    """Response model for agent reasoning trace."""

    query_id: str = Field(..., description="Query identifier")
    natural_query: str = Field(..., description="Original natural language question")
    database_id: str = Field(..., description="Database identifier")
    sql: str = Field(..., description="Generated SQL query")
    confidence: float = Field(..., description="Confidence score")
    success: bool = Field(..., description="Whether query succeeded")
    reasoning_trace: list[ReasoningStep] = Field(
        ..., description="Full agent reasoning trace"
    )
    total_steps: int = Field(..., description="Total reasoning steps taken")
    created_at: datetime = Field(..., description="When query was created")


class RetryRequest(BaseModel):
    """Request model for retry with correction hints."""

    query_id: str = Field(..., description="Query ID to retry")
    correction_hint: str | None = Field(
        None, description="Optional hint for how to correct the query"
    )


@router.get("/agent/reasoning/{query_id}", response_model=AgentReasoningResponse)
@limiter.limit("30/minute")
async def get_reasoning_trace(
    request: Request, query_id: str
) -> AgentReasoningResponse:
    """
    Get detailed reasoning trace for a query.

    Returns the full agent reasoning history including
    thoughts, actions, and observations from the ReAct loop.

    Rate limit: 30 requests per minute per client.
    """
    logger.info("get_reasoning_trace", query_id=query_id)

    from app.agent import get_agent_engine

    try:
        engine = await get_agent_engine()
        history = engine.get_query_history(query_id)

        if history is None:
            raise QueryNotFoundException(query_id=query_id)

        # Convert reasoning trace to response model
        reasoning_trace = [
            ReasoningStep(
                step=step.step_number,
                thought=step.content,
                action=step.tool_name,
                observation=step.tool_output,
            )
            for step in history.reasoning_trace
        ]

        return AgentReasoningResponse(
            query_id=history.query_id,
            natural_query=history.natural_query,
            database_id=history.database_id,
            sql=history.sql,
            confidence=history.confidence,
            success=history.success,
            reasoning_trace=reasoning_trace,
            total_steps=len(history.reasoning_trace),
            created_at=history.created_at,
        )

    except QueryNotFoundException:
        raise
    except Exception as e:
        logger.error("get_reasoning_trace_error", error=str(e), query_id=query_id)
        # Let global exception handler deal with unhandled exceptions
        raise


@router.post("/agent/retry", response_model=QueryResponse)
@limiter.limit("10/minute")
async def retry_query(request: Request, retry_request: RetryRequest) -> QueryResponse:
    """
    Retry a failed query with optional correction hints.

    The agent will use the previous attempt and any provided hints
    to generate a corrected SQL query using the ReAct framework.

    Rate limit: 10 requests per minute per client.
    """
    logger.info(
        "retry_query_request",
        query_id=retry_request.query_id,
        has_hint=retry_request.correction_hint is not None,
    )

    from app.agent import get_agent_engine

    try:
        engine = await get_agent_engine()
        result = await engine.retry_query(
            query_id=retry_request.query_id,
            correction_hint=retry_request.correction_hint,
        )

        # Convert reasoning trace to response model
        reasoning_trace = None
        if result.reasoning_trace:
            reasoning_trace = [
                ReasoningStep(
                    step=step.step_number,
                    thought=step.content,
                    action=step.tool_name,
                    observation=step.tool_output,
                )
                for step in result.reasoning_trace
            ]

        return QueryResponse(
            sql=result.sql,
            confidence=result.confidence,
            execution_time_ms=result.execution_time_ms,
            dialect="postgresql",  # TODO: Get from engine
            valid_syntax=True,
            validation_status=(
                result.validation_result.outcome.value
                if result.validation_result
                else "not_validated"
            ),
            results=result.execution_results,
            row_count=result.row_count,
            reasoning_trace=reasoning_trace,
            warnings=result.warnings,
        )

    except QueryNotFoundException:
        # Let custom exception handler deal with this
        raise
    except Exception as e:
        logger.error(
            "retry_query_error",
            error=str(e),
            query_id=retry_request.query_id,
        )
        # Let global exception handler deal with unhandled exceptions
        raise


# =============================================================================
# Authentication Endpoints (Phase 2.2: Security Implementation)
# =============================================================================


class LoginRequest(BaseModel):
    """Request model for authentication."""

    username: str = Field(..., min_length=3, description="Username")
    password: str = Field(..., min_length=8, description="Password")


class TokenResponse(BaseModel):
    """Response model for token generation."""

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Token expiration time in seconds")


@router.post("/auth/token", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, credentials: LoginRequest) -> TokenResponse:
    """
    Generate JWT access token.

    This endpoint authenticates users and returns a JWT token for API access.

    Rate limit: 5 requests per minute per client.

    Note: In production, this should validate against a user database.
    Currently uses placeholder authentication for development.
    """
    # Import auth utilities
    from app.security import create_access_token

    # TODO: Implement actual user authentication against database
    # For now, simple placeholder authentication
    if (
        credentials.username == "demo"
        and credentials.password == "demo_password"  # nosec B105
    ):
        token = create_access_token(data={"sub": credentials.username})

        settings = get_settings()

        logger.info("user_authenticated", username=credentials.username)

        return TokenResponse(
            access_token=token,
            token_type="bearer",  # nosec B106 - Standard OAuth2 token type
            expires_in=settings.security.jwt_access_token_expire_minutes * 60,
        )

    logger.warning("authentication_failed", username=credentials.username)
    raise AuthenticationException(message="Incorrect username or password")


# =============================================================================
# Management Endpoints
# =============================================================================


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Check API health status.

    Returns health status of the API and its components.
    """
    # Check database health
    db_status = "unhealthy"
    try:
        db_manager = await get_database()
        if await db_manager.health_check():
            db_status = "healthy"
    except Exception as e:
        logger.warning("health_check_database_error", error=str(e))
        db_status = "unhealthy"

    # Check model health (Phase 1.3: HuggingFace Model Integration)
    model_status = "not_loaded"
    try:
        model_loader = await get_model_loader()
        if model_loader.is_loaded:
            model_status = "healthy"
    except Exception as e:
        logger.debug("health_check_model_status", error=str(e))
        model_status = "not_loaded"

    # Check circuit breaker state for inference
    circuit_status = "unknown"
    try:
        from app.text2sql_engine import get_text2sql_engine

        engine = await get_text2sql_engine()
        resilience_state = engine.get_resilience_state()
        circuit_status = resilience_state.get("state", "unknown")
    except Exception as e:
        logger.debug("health_check_circuit_status", error=str(e))

    # Determine overall status
    components = {
        "api": "healthy",
        "database": db_status,
        "model": model_status,
        "inference_circuit": circuit_status,
    }

    # API is healthy if database works; degraded if only model missing
    if db_status == "healthy" and model_status == "healthy":
        overall_status = "healthy"
    elif db_status == "healthy":
        overall_status = "degraded"
    else:
        overall_status = "unhealthy"

    return HealthResponse(
        status=overall_status,
        version=__version__,
        timestamp=datetime.now(),
        components=components,
    )


@router.get("/models/info", response_model=ModelInfoResponse)
async def get_model_info() -> ModelInfoResponse:
    """
    Get information about the loaded model.

    Returns model name, status, and configuration.
    """
    settings = get_settings()

    try:
        model_loader = await get_model_loader()
        model_info = model_loader.get_info()

        return ModelInfoResponse(
            model_name=model_info.model_name,
            model_loaded=model_info.loaded,
            device=model_info.device,
            quantization=model_info.quantization,
        )
    except Exception as e:
        logger.debug("get_model_info_error", error=str(e))
        # Return default info if model loader not initialized
        return ModelInfoResponse(
            model_name=settings.huggingface.model_name,
            model_loaded=False,
            device=settings.huggingface.device,
            quantization=None,
        )


# =============================================================================
# Streaming Endpoints (Issue #8: Performance Optimization)
# =============================================================================


class StreamQueryRequest(BaseModel):
    """Request model for streaming SQL generation."""

    query: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        description="Natural language question to convert to SQL",
    )
    database_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Registered database identifier",
    )
    execute: bool = Field(
        default=False,
        description="Execute SQL after generation and stream results",
    )
    show_reasoning: bool = Field(
        default=False,
        description="Stream agent reasoning steps",
    )
    max_rows: int = Field(
        default=1000,
        ge=1,
        le=10000,
        description="Maximum rows to stream when executing",
    )


@router.post("/query/stream")
@limiter.limit("10/minute")
async def stream_sql_generation(
    request: Request, query_request: StreamQueryRequest
) -> StreamingResponse:
    """
    Stream SQL generation with Server-Sent Events.

    Provides real-time progress updates during:
    - Model inference
    - SQL validation
    - Query execution (if requested)
    - Result streaming (batched)

    Rate limit: 10 requests per minute per client.

    Issue #8: Performance Optimization - Streaming responses.
    """
    # Validate inputs
    is_valid_query, query_errors = validate_natural_language_query(query_request.query)
    if not is_valid_query:
        raise ValidationException(
            message="Invalid natural language query",
            validation_errors=[{"field": "query", "error": e} for e in query_errors],
        )

    is_valid_db, db_error = validate_database_id(query_request.database_id)
    if not is_valid_db:
        raise ValidationException(
            message=db_error or "Invalid database ID",
            validation_errors=[{"field": "database_id", "error": db_error}],
        )

    logger.info(
        "stream_sql_generation_request",
        database_id=query_request.database_id,
        execute=query_request.execute,
        show_reasoning=query_request.show_reasoning,
    )

    from app.streaming import QueryStreamer, create_sse_response

    streamer = QueryStreamer()
    event_generator = streamer.stream_query(
        natural_query=query_request.query,
        database_id=query_request.database_id,
        execute=query_request.execute,
        show_reasoning=query_request.show_reasoning,
        max_rows=query_request.max_rows,
    )

    return cast(StreamingResponse, create_sse_response(event_generator))


# =============================================================================
# Cache Management Endpoints (Issue #8: Performance Optimization)
# =============================================================================


class CacheStatsResponse(BaseModel):
    """Response model for cache statistics."""

    redis_connected: bool = Field(..., description="Redis connection status")
    redis_url: str | None = Field(None, description="Redis URL (masked)")
    in_memory_entries: int = Field(..., description="In-memory cache entries")
    hits: int = Field(..., description="Cache hits")
    misses: int = Field(..., description="Cache misses")
    errors: int = Field(..., description="Cache errors")
    hit_rate: float = Field(..., description="Cache hit rate")


@router.get("/cache/stats", response_model=CacheStatsResponse)
@limiter.limit("30/minute")
async def get_cache_stats(request: Request) -> CacheStatsResponse:
    """
    Get cache statistics.

    Returns current cache health and performance metrics.

    Rate limit: 30 requests per minute per client.

    Issue #8: Performance Optimization - Cache monitoring.
    """
    from app.cache import get_cache_manager

    cache = await get_cache_manager()
    health = await cache.health_check()
    stats = cache.get_stats()

    return CacheStatsResponse(
        redis_connected=health["redis_connected"],
        redis_url=health.get("redis_url"),
        in_memory_entries=health["in_memory_entries"],
        hits=stats.hits,
        misses=stats.misses,
        errors=stats.errors,
        hit_rate=stats.hit_rate,
    )


class CacheInvalidateRequest(BaseModel):
    """Request model for cache invalidation."""

    namespace: str | None = Field(
        None,
        description="Cache namespace to invalidate (query, model, schema). None for all.",
    )
    key: str | None = Field(
        None, description="Specific key to invalidate. None for entire namespace."
    )


class CacheInvalidateResponse(BaseModel):
    """Response model for cache invalidation."""

    success: bool = Field(..., description="Whether invalidation succeeded")
    invalidated_count: int = Field(..., description="Number of entries invalidated")
    message: str = Field(..., description="Result message")


@router.post("/cache/invalidate", response_model=CacheInvalidateResponse)
@limiter.limit("10/minute")
async def invalidate_cache(
    request: Request, invalidate_request: CacheInvalidateRequest
) -> CacheInvalidateResponse:
    """
    Invalidate cache entries.

    Allows selective or full cache invalidation for maintenance.

    Rate limit: 10 requests per minute per client.

    Issue #8: Performance Optimization - Cache management.
    """
    from app.cache import CacheNamespace, get_cache_manager

    cache = await get_cache_manager()

    try:
        if invalidate_request.namespace:
            # Validate namespace
            try:
                namespace = CacheNamespace(invalidate_request.namespace)
            except ValueError as e:
                raise ValidationException(
                    message=f"Invalid namespace: {invalidate_request.namespace}",
                    validation_errors=[
                        {
                            "field": "namespace",
                            "error": f"Must be one of: {[n.value for n in CacheNamespace]}",
                        }
                    ],
                ) from e

            if invalidate_request.key:
                # Invalidate specific key
                deleted = await cache.delete(invalidate_request.key, namespace)
                count = 1 if deleted else 0
                message = (
                    f"Invalidated key '{invalidate_request.key}' from {namespace.value}"
                )
            else:
                # Invalidate entire namespace
                count = await cache.invalidate_namespace(namespace)
                message = f"Invalidated {count} entries from {namespace.value}"
        else:
            # Clear all cache
            await cache.clear()
            count = -1  # Unknown count for full clear
            message = "Cleared all cache entries"

        logger.info(
            "cache_invalidated",
            namespace=invalidate_request.namespace,
            key=invalidate_request.key,
            count=count,
        )

        return CacheInvalidateResponse(
            success=True,
            invalidated_count=max(0, count),
            message=message,
        )

    except ValidationException:
        raise
    except Exception as e:
        logger.error("cache_invalidate_error", error=str(e))
        return CacheInvalidateResponse(
            success=False,
            invalidated_count=0,
            message=f"Invalidation failed: {str(e)}",
        )


# =============================================================================
# Performance Monitoring Endpoints (Issue #8: Performance Optimization)
# =============================================================================


class PerformanceResponse(BaseModel):
    """Response model for performance metrics."""

    timestamp: float = Field(..., description="Snapshot timestamp")
    memory_rss_mb: float = Field(..., description="Resident memory in MB")
    memory_vms_mb: float = Field(..., description="Virtual memory in MB")
    gpu_memory_mb: float = Field(..., description="GPU memory in MB")
    pool_size: int = Field(..., description="Database pool size")
    pool_checked_out: int = Field(..., description="Connections checked out")
    pool_overflow: int = Field(..., description="Overflow connections")
    cache_hit_rate: float = Field(..., description="Cache hit rate")
    active_requests: int = Field(..., description="Active requests")


@router.get("/performance", response_model=PerformanceResponse)
@limiter.limit("30/minute")
async def get_performance_metrics(request: Request) -> PerformanceResponse:
    """
    Get current performance metrics.

    Returns memory usage, connection pool status, and cache performance.

    Rate limit: 30 requests per minute per client.

    Issue #8: Performance Optimization - Monitoring.
    """
    from app.performance import get_performance_snapshot

    snapshot = await get_performance_snapshot()

    return PerformanceResponse(
        timestamp=snapshot.timestamp,
        memory_rss_mb=snapshot.memory_rss_mb,
        memory_vms_mb=snapshot.memory_vms_mb,
        gpu_memory_mb=snapshot.gpu_memory_mb,
        pool_size=snapshot.pool_metrics.pool_size,
        pool_checked_out=snapshot.pool_metrics.checked_out,
        pool_overflow=snapshot.pool_metrics.overflow,
        cache_hit_rate=snapshot.cache_hit_rate,
        active_requests=snapshot.active_requests,
    )


# =============================================================================
# Batch Processing Endpoints (Issue #8: Performance Optimization)
# =============================================================================


class BatchQueryRequest(BaseModel):
    """Request model for batch SQL generation."""

    queries: list[str] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="List of natural language queries (max 10)",
    )
    database_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Registered database identifier",
    )
    parallel: bool = Field(
        default=True,
        description="Process queries in parallel for faster execution",
    )
    max_concurrent: int = Field(
        default=4,
        ge=1,
        le=10,
        description="Maximum concurrent queries when parallel=True",
    )


class BatchQueryResult(BaseModel):
    """Result for a single query in batch."""

    query: str = Field(..., description="Original query")
    sql: str | None = Field(None, description="Generated SQL")
    confidence: float = Field(..., description="Confidence score")
    error: str | None = Field(None, description="Error if failed")


class BatchQueryResponse(BaseModel):
    """Response model for batch SQL generation."""

    results: list[BatchQueryResult] = Field(..., description="Results for each query")
    total_time_ms: float = Field(..., description="Total processing time")
    successful: int = Field(..., description="Number of successful queries")
    failed: int = Field(..., description="Number of failed queries")


@router.post("/query/batch", response_model=BatchQueryResponse)
@limiter.limit("5/minute")
async def generate_sql_batch(
    request: Request, batch_request: BatchQueryRequest
) -> BatchQueryResponse:
    """
    Generate SQL for multiple queries in batch.

    Supports parallel processing for improved throughput.

    Rate limit: 5 requests per minute per client.

    Issue #8: Performance Optimization - Batch processing.
    """
    import time

    # Validate database ID
    is_valid_db, db_error = validate_database_id(batch_request.database_id)
    if not is_valid_db:
        raise ValidationException(
            message=db_error or "Invalid database ID",
            validation_errors=[{"field": "database_id", "error": db_error}],
        )

    # Validate all queries
    for i, query in enumerate(batch_request.queries):
        is_valid, errors = validate_natural_language_query(query)
        if not is_valid:
            raise ValidationException(
                message=f"Invalid query at index {i}",
                validation_errors=[
                    {"field": f"queries[{i}]", "error": e} for e in errors
                ],
            )

    logger.info(
        "batch_query_request",
        database_id=batch_request.database_id,
        query_count=len(batch_request.queries),
        parallel=batch_request.parallel,
    )

    start_time = time.perf_counter()
    results: list[BatchQueryResult] = []

    try:
        from app.text2sql_engine import get_text2sql_engine

        engine = await get_text2sql_engine()

        # Generate SQL for each query
        # Note: True batch processing in the engine would be more efficient
        # This is a simplified version for the API layer
        import asyncio

        if batch_request.parallel:
            # Parallel processing
            async def process_query(query: str) -> BatchQueryResult:
                try:
                    result = await engine.generate_sql(
                        natural_query=query,
                        database_id=batch_request.database_id,
                        execute=False,
                        show_reasoning=False,
                    )
                    return BatchQueryResult(
                        query=query,
                        sql=result.sql,
                        confidence=result.confidence,
                        error=None,
                    )
                except Exception as e:
                    return BatchQueryResult(
                        query=query,
                        sql=None,
                        confidence=0.0,
                        error=str(e),
                    )

            # Use semaphore for concurrency control
            semaphore = asyncio.Semaphore(batch_request.max_concurrent)

            async def process_with_semaphore(query: str) -> BatchQueryResult:
                async with semaphore:
                    return await process_query(query)

            tasks = [process_with_semaphore(q) for q in batch_request.queries]
            results = await asyncio.gather(*tasks)
        else:
            # Sequential processing
            for query in batch_request.queries:
                try:
                    result = await engine.generate_sql(
                        natural_query=query,
                        database_id=batch_request.database_id,
                        execute=False,
                        show_reasoning=False,
                    )
                    results.append(
                        BatchQueryResult(
                            query=query,
                            sql=result.sql,
                            confidence=result.confidence,
                            error=None,
                        )
                    )
                except Exception as e:
                    results.append(
                        BatchQueryResult(
                            query=query,
                            sql=None,
                            confidence=0.0,
                            error=str(e),
                        )
                    )

        total_time_ms = (time.perf_counter() - start_time) * 1000
        successful = sum(1 for r in results if r.sql is not None)

        logger.info(
            "batch_query_complete",
            query_count=len(batch_request.queries),
            successful=successful,
            total_time_ms=round(total_time_ms, 2),
        )

        return BatchQueryResponse(
            results=list(results),
            total_time_ms=total_time_ms,
            successful=successful,
            failed=len(results) - successful,
        )

    except Exception as e:
        logger.error(
            "batch_query_error",
            error=str(e),
            database_id=batch_request.database_id,
        )
        raise ModelInferenceException(
            message=f"Batch query failed: {str(e)}",
            details={"database_id": batch_request.database_id},
        ) from e


# =============================================================================
# Query Explanation Endpoints (Issue #15)
# =============================================================================


class ExplainRequest(BaseModel):
    """Request model for SQL explanation."""

    sql: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="SQL query to explain",
    )
    database_id: str | None = Field(
        None,
        max_length=100,
        description="Optional database ID for context",
    )
    include_visualization: bool = Field(
        default=True,
        description="Include query structure visualization",
    )
    include_optimization_hints: bool = Field(
        default=True,
        description="Include optimization suggestions",
    )
    visualization_format: str = Field(
        default="ascii",
        description="Visualization format (ascii, json, html, mermaid)",
    )


class ExplainResponse(BaseModel):
    """Response model for SQL explanation."""

    query_id: str = Field(..., description="Unique identifier for this explanation")
    sql: str = Field(..., description="Original SQL query")
    summary: str = Field(..., description="Brief summary of the query")
    detailed_explanation: str = Field(..., description="Detailed explanation")
    data_retrieval: str = Field(..., description="What data is retrieved")
    tables_used: list[str] = Field(default_factory=list, description="Tables used")
    filters_applied: list[str] = Field(
        default_factory=list, description="Filters applied"
    )
    aggregations: list[str] = Field(
        default_factory=list, description="Aggregations performed"
    )
    sorting: str | None = Field(None, description="Sorting applied")
    limitations: str | None = Field(None, description="Row limits")
    complexity_level: str = Field(..., description="Complexity level")
    complexity_score: float = Field(..., description="Complexity score (0-1)")
    complexity_factors: list[str] = Field(
        default_factory=list, description="Factors affecting complexity"
    )
    optimization_hints: list[dict[str, Any]] = Field(
        default_factory=list, description="Optimization suggestions"
    )
    breakdown_steps: list[dict[str, Any]] = Field(
        default_factory=list, description="Step-by-step breakdown"
    )
    visualization: str | None = Field(None, description="Query visualization")
    created_at: datetime = Field(..., description="When explanation was generated")


class VisualizeRequest(BaseModel):
    """Request model for query visualization."""

    sql: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="SQL query to visualize",
    )
    format: str = Field(
        default="ascii",
        description="Output format (ascii, json, html, mermaid)",
    )


class VisualizeResponse(BaseModel):
    """Response model for query visualization."""

    format: str = Field(..., description="Visualization format")
    content: str = Field(..., description="Visualization content")
    width: int | None = Field(None, description="Width hint")
    height: int | None = Field(None, description="Height hint")


class BatchExplainRequest(BaseModel):
    """Request model for batch SQL explanation."""

    queries: list[str] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="SQL queries to explain (max 10)",
    )
    database_id: str | None = Field(
        None,
        description="Optional database ID for context",
    )


class BatchExplainResponse(BaseModel):
    """Response model for batch SQL explanation."""

    results: list[ExplainResponse] = Field(..., description="Explanation results")
    total: int = Field(..., description="Total queries processed")
    successful: int = Field(..., description="Successful explanations")
    failed: int = Field(..., description="Failed explanations")
    total_time_ms: float = Field(..., description="Total processing time")


@router.post("/explain", response_model=ExplainResponse)
@limiter.limit("20/minute")
async def explain_sql(
    request: Request, explain_request: ExplainRequest
) -> ExplainResponse:
    """
    Generate natural language explanation of a SQL query.

    Provides comprehensive explanation including:
    - Summary of what the query does
    - Step-by-step breakdown
    - Complexity analysis
    - Optimization suggestions
    - Query visualization

    Rate limit: 20 requests per minute per client.

    Issue #15: Query Explanation & Visualization.
    """
    from app.explanations import VisualizationFormat, get_explanation_engine

    logger.info(
        "explain_sql_request",
        sql_length=len(explain_request.sql),
        database_id=explain_request.database_id,
    )

    try:
        # Parse visualization format
        try:
            viz_format = VisualizationFormat(
                explain_request.visualization_format.lower()
            )
        except ValueError:
            viz_format = VisualizationFormat.ASCII

        engine = await get_explanation_engine()
        result = await engine.explain(
            sql=explain_request.sql,
            database_id=explain_request.database_id,
            include_visualization=explain_request.include_visualization,
            include_optimization_hints=explain_request.include_optimization_hints,
            visualization_format=viz_format,
        )

        return ExplainResponse(
            query_id=result.query_id,
            sql=result.sql,
            summary=result.explanation.summary,
            detailed_explanation=result.explanation.detailed_explanation,
            data_retrieval=result.explanation.data_retrieval,
            tables_used=result.explanation.tables_used,
            filters_applied=result.explanation.filters_applied,
            aggregations=result.explanation.aggregations,
            sorting=result.explanation.sorting,
            limitations=result.explanation.limitations,
            complexity_level=result.complexity.level,
            complexity_score=result.complexity.score,
            complexity_factors=result.complexity.factors,
            optimization_hints=[
                {
                    "category": h.category,
                    "title": h.title,
                    "description": h.description,
                    "severity": h.severity,
                    "affected_tables": h.affected_tables,
                }
                for h in result.optimization_hints
            ],
            breakdown_steps=[
                {
                    "step_number": step.step_number,
                    "clause_type": step.clause_type,
                    "description": step.description,
                    "sql_fragment": step.sql_fragment,
                }
                for step in result.breakdown.steps
            ],
            visualization=(
                result.visualization.content if result.visualization else None
            ),
            created_at=result.created_at,
        )

    except Exception as e:
        logger.error("explain_sql_error", error=str(e))
        raise


@router.post("/visualize", response_model=VisualizeResponse)
@limiter.limit("30/minute")
async def visualize_sql(
    request: Request, visualize_request: VisualizeRequest
) -> VisualizeResponse:
    """
    Generate visualization of SQL query structure.

    Supported formats:
    - ascii: ASCII tree diagram
    - json: JSON structure
    - html: HTML visualization
    - mermaid: Mermaid diagram syntax

    Rate limit: 30 requests per minute per client.

    Issue #15: Query Explanation & Visualization.
    """
    from app.explanations import VisualizationFormat, get_explanation_engine

    logger.info(
        "visualize_sql_request",
        sql_length=len(visualize_request.sql),
        format=visualize_request.format,
    )

    try:
        # Parse visualization format
        try:
            viz_format = VisualizationFormat(visualize_request.format.lower())
        except ValueError:
            viz_format = VisualizationFormat.ASCII

        engine = await get_explanation_engine()
        visualization = await engine.visualize(
            sql=visualize_request.sql,
            format_type=viz_format,
        )

        return VisualizeResponse(
            format=visualization.format,
            content=visualization.content,
            width=visualization.width,
            height=visualization.height,
        )

    except Exception as e:
        logger.error("visualize_sql_error", error=str(e))
        raise


@router.get("/explain/{query_id}", response_model=ExplainResponse)
@limiter.limit("30/minute")
async def get_cached_explanation(request: Request, query_id: str) -> ExplainResponse:
    """
    Retrieve a cached explanation by query ID.

    Returns a previously generated explanation if it exists in cache.

    Rate limit: 30 requests per minute per client.

    Issue #15: Query Explanation & Visualization.
    """
    from app.explanations import get_explanation_engine

    logger.info("get_cached_explanation", query_id=query_id)

    engine = await get_explanation_engine()
    result = await engine.get_cached_explanation(query_id)

    return ExplainResponse(
        query_id=result.query_id,
        sql=result.sql,
        summary=result.explanation.summary,
        detailed_explanation=result.explanation.detailed_explanation,
        data_retrieval=result.explanation.data_retrieval,
        tables_used=result.explanation.tables_used,
        filters_applied=result.explanation.filters_applied,
        aggregations=result.explanation.aggregations,
        sorting=result.explanation.sorting,
        limitations=result.explanation.limitations,
        complexity_level=result.complexity.level,
        complexity_score=result.complexity.score,
        complexity_factors=result.complexity.factors,
        optimization_hints=[
            {
                "category": h.category,
                "title": h.title,
                "description": h.description,
                "severity": h.severity,
                "affected_tables": h.affected_tables,
            }
            for h in result.optimization_hints
        ],
        breakdown_steps=[
            {
                "step_number": step.step_number,
                "clause_type": step.clause_type,
                "description": step.description,
                "sql_fragment": step.sql_fragment,
            }
            for step in result.breakdown.steps
        ],
        visualization=result.visualization.content if result.visualization else None,
        created_at=result.created_at,
    )


@router.post("/explain/batch", response_model=BatchExplainResponse)
@limiter.limit("5/minute")
async def explain_sql_batch(
    request: Request, batch_request: BatchExplainRequest
) -> BatchExplainResponse:
    """
    Generate explanations for multiple SQL queries.

    Processes up to 10 queries and returns explanations for each.

    Rate limit: 5 requests per minute per client.

    Issue #15: Query Explanation & Visualization.
    """
    import time

    from app.explanations import get_explanation_engine

    logger.info(
        "explain_sql_batch_request",
        query_count=len(batch_request.queries),
        database_id=batch_request.database_id,
    )

    start_time = time.perf_counter()

    engine = await get_explanation_engine()
    results = await engine.explain_batch(
        queries=batch_request.queries,
        database_id=batch_request.database_id,
    )

    total_time_ms = (time.perf_counter() - start_time) * 1000

    # Convert results to response format
    response_results = []
    successful = 0
    for result in results:
        if "error" not in result.metadata:
            successful += 1

        response_results.append(
            ExplainResponse(
                query_id=result.query_id,
                sql=result.sql,
                summary=result.explanation.summary,
                detailed_explanation=result.explanation.detailed_explanation,
                data_retrieval=result.explanation.data_retrieval,
                tables_used=result.explanation.tables_used,
                filters_applied=result.explanation.filters_applied,
                aggregations=result.explanation.aggregations,
                sorting=result.explanation.sorting,
                limitations=result.explanation.limitations,
                complexity_level=result.complexity.level,
                complexity_score=result.complexity.score,
                complexity_factors=result.complexity.factors,
                optimization_hints=[
                    {
                        "category": h.category,
                        "title": h.title,
                        "description": h.description,
                        "severity": h.severity,
                        "affected_tables": h.affected_tables,
                    }
                    for h in result.optimization_hints
                ],
                breakdown_steps=[
                    {
                        "step_number": step.step_number,
                        "clause_type": step.clause_type,
                        "description": step.description,
                        "sql_fragment": step.sql_fragment,
                    }
                    for step in result.breakdown.steps
                ],
                visualization=(
                    result.visualization.content if result.visualization else None
                ),
                created_at=result.created_at,
            )
        )

    logger.info(
        "explain_sql_batch_complete",
        total=len(results),
        successful=successful,
        total_time_ms=round(total_time_ms, 2),
    )

    return BatchExplainResponse(
        results=response_results,
        total=len(results),
        successful=successful,
        failed=len(results) - successful,
        total_time_ms=total_time_ms,
    )
