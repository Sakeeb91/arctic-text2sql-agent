"""
FastAPI API route definitions.

This module defines all REST API endpoints for the Arctic Text2SQL Agent.
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app import __version__
from app.config import get_settings
from app.logging_config import get_logger
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
async def generate_sql(request: QueryRequest) -> QueryResponse:
    """
    Generate SQL from natural language query.

    Uses the agent-based approach with multi-step reasoning and self-correction
    to generate accurate SQL queries from natural language questions.
    """
    logger.info(
        "generate_sql_request",
        database_id=request.database_id,
        execute=request.execute,
        show_reasoning=request.show_reasoning,
    )

    # TODO: Implement actual SQL generation
    # This is a placeholder response
    return QueryResponse(
        sql="SELECT * FROM customers WHERE state = 'California'",
        confidence=0.95,
        execution_time_ms=150.5,
        dialect="postgresql",
        valid_syntax=True,
        validation_status="validated",
        results=None,
        row_count=None,
        reasoning_trace=None,
        warnings=[],
    )


@router.post("/validate", response_model=ValidationResponse)
async def validate_sql(request: ValidationRequest) -> ValidationResponse:
    """
    Validate SQL syntax and semantics.

    Checks if the provided SQL is syntactically correct and matches
    the database schema.
    """
    logger.info(
        "validate_sql_request",
        database_id=request.database_id,
    )

    # TODO: Implement actual validation
    return ValidationResponse(
        valid=True,
        errors=[],
        warnings=[],
        suggested_fixes=None,
    )


@router.get("/schema/{database_id}", response_model=SchemaResponse)
async def get_schema(database_id: str) -> SchemaResponse:
    """
    Get database schema information.

    Returns table names, column definitions, and relationships
    for the specified database.
    """
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
async def register_schema(request: SchemaRequest) -> dict[str, str]:
    """
    Register a new database schema.

    Connects to the database, extracts schema information,
    and stores it for future query generation.
    """
    logger.info(
        "register_schema_request",
        database_id=request.database_id,
        dialect=request.dialect,
    )

    # TODO: Implement actual registration
    return {"status": "registered", "database_id": request.database_id}


# =============================================================================
# Agent-Specific Endpoints
# =============================================================================


@router.get("/agent/reasoning/{query_id}")
async def get_reasoning_trace(query_id: str) -> dict[str, Any]:
    """
    Get detailed reasoning trace for a query.

    Returns the full agent reasoning history including
    thoughts, actions, and observations.
    """
    logger.info("get_reasoning_trace", query_id=query_id)

    # TODO: Implement actual reasoning retrieval
    return {
        "query_id": query_id,
        "reasoning_trace": [],
        "total_steps": 0,
    }


@router.post("/agent/retry")
async def retry_query(
    query_id: str = Query(..., description="Query ID to retry"),
    correction_hint: str | None = Query(
        None, description="Optional hint for correction"
    ),
) -> QueryResponse:
    """
    Retry a failed query with optional correction hints.

    The agent will use the previous attempt and any provided hints
    to generate a corrected SQL query.
    """
    logger.info(
        "retry_query_request",
        query_id=query_id,
        has_hint=correction_hint is not None,
    )

    # TODO: Implement actual retry logic
    return QueryResponse(
        sql="SELECT * FROM customers",
        confidence=0.85,
        execution_time_ms=200.0,
        dialect="postgresql",
        valid_syntax=True,
        validation_status="validated",
        results=None,
        row_count=None,
        reasoning_trace=None,
        warnings=[],
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

    # Determine overall status
    components = {
        "api": "healthy",
        "database": db_status,
        "model": model_status,
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
