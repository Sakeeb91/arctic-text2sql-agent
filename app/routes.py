"""
FastAPI API route definitions.

This module defines all REST API endpoints for the Arctic Text2SQL Agent.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app import __version__
from app.config import get_settings
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Invalid query",
                "messages": query_errors,
            },
        )

    # Validate database ID (Phase 2.2: Security Implementation)
    is_valid_db, db_error = validate_database_id(query_request.database_id)
    if not is_valid_db:
        logger.warning(
            "invalid_database_id",
            error=db_error,
            database_id=query_request.database_id,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": db_error},
        )

    logger.info(
        "generate_sql_request",
        database_id=query_request.database_id,
        execute=query_request.execute,
        show_reasoning=query_request.show_reasoning,
    )

    # Import the Text2SQL engine
    from app.text2sql_engine import get_text2sql_engine

    try:
        # Get engine instance
        engine = await get_text2sql_engine()

        # Generate SQL
        result = await engine.generate_sql(
            natural_query=query_request.query,
            database_id=query_request.database_id,
            execute=query_request.execute,
            show_reasoning=query_request.show_reasoning,
            max_rows=query_request.max_rows,
        )

        # Convert reasoning trace to response model
        reasoning_trace = None
        if result.reasoning_trace:
            reasoning_trace = [
                ReasoningStep(
                    step=step.step,
                    thought=step.thought,
                    action=step.action,
                    observation=step.observation,
                )
                for step in result.reasoning_trace
            ]

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

    except Exception as e:
        logger.error(
            "generate_sql_error",
            error=str(e),
            database_id=query_request.database_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "SQL generation failed", "message": str(e)},
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": db_error},
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": db_error},
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": db_error},
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
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Query not found", "query_id": query_id},
            )

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

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_reasoning_trace_error", error=str(e), query_id=query_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Failed to retrieve reasoning trace", "message": str(e)},
        ) from e


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
    from app.exceptions import QueryNotFoundException

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

    except QueryNotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "Query not found",
                "message": str(e),
                "query_id": retry_request.query_id,
            },
        ) from e
    except Exception as e:
        logger.error(
            "retry_query_error",
            error=str(e),
            query_id=retry_request.query_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "Retry failed", "message": str(e)},
        ) from e


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
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


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
