"""
Database management API routes (Issue #14: Multi-Database Support).

This module provides REST API endpoints for managing multiple database
connections in the registry.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.exceptions import (
    DatabaseAlreadyExistsException,
    DatabaseNotRegisteredException,
    UnsupportedDialectException,
    ValidationException,
)
from app.logging_config import get_logger
from app.security import limiter, require_auth, require_mutation_scope
from db.dialects import SQLDialect
from db.registry import (
    DatabaseConfig,
    DatabaseHealth,
    DatabaseStatus,
    RegisteredDatabase,
    get_database_registry,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/databases",
    tags=["Database Management"],
    dependencies=[Depends(require_auth)],
)


# =============================================================================
# Request/Response Models
# =============================================================================


class DatabaseRegisterRequest(BaseModel):
    """Request model for registering a new database."""

    database_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$",
        description="Unique identifier for the database",
        examples=["analytics_db", "prod-warehouse"],
    )
    connection_string: str = Field(
        ...,
        min_length=10,
        description="Database connection URL",
        examples=["postgresql://user:pass@localhost:5432/mydb"],
    )
    dialect: str | None = Field(
        default=None,
        description="SQL dialect (auto-detected if not provided)",
        examples=["postgresql", "mysql", "sqlite"],
    )
    display_name: str | None = Field(
        default=None,
        max_length=200,
        description="Human-readable name for the database",
        examples=["Analytics Database"],
    )
    description: str | None = Field(
        default=None,
        max_length=500,
        description="Optional description of the database",
    )
    pool_size: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Connection pool size",
    )
    max_overflow: int = Field(
        default=10,
        ge=0,
        le=50,
        description="Maximum overflow connections",
    )
    pool_timeout: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Connection timeout in seconds",
    )
    read_only: bool = Field(
        default=True,
        description="Restrict to read-only queries",
    )
    tags: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Tags for categorization",
    )
    test_connection: bool = Field(
        default=True,
        description="Test connection before registering",
    )

    @field_validator("dialect")
    @classmethod
    def validate_dialect(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                SQLDialect(v.lower())
            except ValueError:
                raise ValueError(
                    f"Invalid dialect. Supported: {SQLDialect.supported_dialects()}"
                ) from None
        return v.lower() if v else None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "database_id": "analytics_db",
                    "connection_string": "postgresql://user:pass@localhost:5432/analytics",
                    "display_name": "Analytics Database",
                    "description": "Data warehouse for analytics queries",
                    "pool_size": 10,
                    "tags": ["analytics", "readonly"],
                }
            ]
        }
    }


class DatabaseResponse(BaseModel):
    """Response model for database information."""

    database_id: str = Field(..., description="Database identifier")
    dialect: str = Field(..., description="SQL dialect")
    display_name: str | None = Field(None, description="Human-readable name")
    description: str | None = Field(None, description="Database description")
    pool_size: int = Field(..., description="Connection pool size")
    max_overflow: int = Field(..., description="Max overflow connections")
    pool_timeout: int = Field(..., description="Connection timeout")
    read_only: bool = Field(..., description="Read-only restriction")
    tags: list[str] = Field(..., description="Database tags")
    registered_at: datetime = Field(..., description="Registration timestamp")
    health: "DatabaseHealthResponse" = Field(..., description="Current health status")


class DatabaseHealthResponse(BaseModel):
    """Response model for database health status."""

    database_id: str = Field(..., description="Database identifier")
    status: str = Field(..., description="Connection status")
    healthy: bool = Field(..., description="Whether database is healthy")
    last_check: datetime | None = Field(None, description="Last health check time")
    latency_ms: float | None = Field(None, description="Response latency")
    error_message: str | None = Field(None, description="Error message if unhealthy")
    pool_size: int = Field(..., description="Current pool size")
    connections_in_use: int = Field(..., description="Active connections")
    consecutive_failures: int = Field(..., description="Consecutive check failures")


class DatabaseListResponse(BaseModel):
    """Response model for listing databases."""

    databases: list[DatabaseResponse] = Field(..., description="List of databases")
    total_count: int = Field(..., description="Total number of databases")
    healthy_count: int = Field(..., description="Number of healthy databases")


class DatabaseDeleteResponse(BaseModel):
    """Response model for database deletion."""

    database_id: str = Field(..., description="Deleted database ID")
    message: str = Field(..., description="Success message")


class HealthCheckAllResponse(BaseModel):
    """Response model for checking all database health."""

    total: int = Field(..., description="Total databases checked")
    healthy: int = Field(..., description="Healthy databases")
    unhealthy: int = Field(..., description="Unhealthy databases")
    results: dict[str, DatabaseHealthResponse] = Field(
        ..., description="Health status per database"
    )


# =============================================================================
# Helper Functions
# =============================================================================


def _registered_to_response(registered: RegisteredDatabase) -> DatabaseResponse:
    """Convert RegisteredDatabase to response model."""
    health_response = DatabaseHealthResponse(
        database_id=registered.health.database_id,
        status=registered.health.status.value,
        healthy=registered.health.status == DatabaseStatus.CONNECTED,
        last_check=registered.health.last_check,
        latency_ms=registered.health.latency_ms,
        error_message=registered.health.error_message,
        pool_size=registered.health.pool_size,
        connections_in_use=registered.health.connections_in_use,
        consecutive_failures=registered.health.consecutive_failures,
    )

    return DatabaseResponse(
        database_id=registered.config.database_id,
        dialect=(
            registered.config.dialect.value if registered.config.dialect else "unknown"
        ),
        display_name=registered.config.display_name,
        description=registered.config.description,
        pool_size=registered.config.pool_size,
        max_overflow=registered.config.max_overflow,
        pool_timeout=registered.config.pool_timeout,
        read_only=registered.config.read_only,
        tags=registered.config.tags,
        registered_at=registered.registered_at,
        health=health_response,
    )


def _health_to_response(health: DatabaseHealth) -> DatabaseHealthResponse:
    """Convert DatabaseHealth to response model."""
    return DatabaseHealthResponse(
        database_id=health.database_id,
        status=health.status.value,
        healthy=health.status == DatabaseStatus.CONNECTED,
        last_check=health.last_check,
        latency_ms=health.latency_ms,
        error_message=health.error_message,
        pool_size=health.pool_size,
        connections_in_use=health.connections_in_use,
        consecutive_failures=health.consecutive_failures,
    )


# =============================================================================
# API Endpoints
# =============================================================================


@router.post(
    "",
    response_model=DatabaseResponse,
    status_code=201,
    dependencies=[Depends(require_mutation_scope)],
)
@limiter.limit("10/minute")
async def register_database(
    request: Request,
    response: Response,
    register_request: DatabaseRegisterRequest,
) -> DatabaseResponse:
    """
    Register a new database with the registry.

    Creates a connection pool and validates connectivity before registration.

    Rate limit: 10 requests per minute per client.
    """
    settings = get_settings()

    # Check max databases limit
    registry = await get_database_registry()
    if registry.database_count >= settings.multi_database.max_databases:
        raise ValidationException(
            message=f"Maximum database limit reached ({settings.multi_database.max_databases})",
            validation_errors=[{"field": "database_id", "error": "Registry is full"}],
        )

    logger.info(
        "register_database_request",
        database_id=register_request.database_id,
        dialect=register_request.dialect,
    )

    try:
        # Parse dialect if provided
        dialect: SQLDialect | None = None
        if register_request.dialect:
            dialect = SQLDialect(register_request.dialect)

        # Create config
        config = DatabaseConfig(
            database_id=register_request.database_id,
            connection_string=register_request.connection_string,
            dialect=dialect,
            display_name=register_request.display_name,
            description=register_request.description,
            pool_size=register_request.pool_size,
            max_overflow=register_request.max_overflow,
            pool_timeout=register_request.pool_timeout,
            read_only=register_request.read_only,
            tags=register_request.tags,
        )

        # Register database
        registered = await registry.register_database(
            config,
            test_connection=register_request.test_connection,
        )

        logger.info(
            "database_registered",
            database_id=register_request.database_id,
            dialect=config.dialect.value if config.dialect else "unknown",
        )

        return _registered_to_response(registered)

    except DatabaseAlreadyExistsException:
        raise
    except UnsupportedDialectException:
        raise
    except Exception as e:
        logger.error(
            "register_database_error",
            database_id=register_request.database_id,
            error=str(e),
        )
        raise


@router.get("", response_model=DatabaseListResponse)
@limiter.limit("30/minute")
async def list_databases(
    request: Request,
    response: Response,
    dialect: str | None = None,
    tag: str | None = None,
    healthy_only: bool = False,
) -> DatabaseListResponse:
    """
    List all registered databases.

    Supports filtering by dialect, tag, and health status.

    Rate limit: 30 requests per minute per client.
    """
    logger.info(
        "list_databases_request",
        dialect=dialect,
        tag=tag,
        healthy_only=healthy_only,
    )

    registry = await get_database_registry()

    # Parse dialect filter
    dialect_filter: SQLDialect | None = None
    if dialect:
        try:
            dialect_filter = SQLDialect(dialect.lower())
        except ValueError:
            raise ValidationException(
                message=f"Invalid dialect: {dialect}",
                validation_errors=[
                    {
                        "field": "dialect",
                        "error": f"Supported: {SQLDialect.supported_dialects()}",
                    }
                ],
            ) from None

    # Get filtered list
    tags = [tag] if tag else None
    databases = registry.list_databases(
        dialect=dialect_filter,
        tags=tags,
        healthy_only=healthy_only,
    )

    # Convert to response
    responses = [_registered_to_response(db) for db in databases]
    healthy_count = sum(
        1 for db in databases if db.health.status == DatabaseStatus.CONNECTED
    )

    return DatabaseListResponse(
        databases=responses,
        total_count=len(responses),
        healthy_count=healthy_count,
    )


@router.get("/{database_id}", response_model=DatabaseResponse)
@limiter.limit("30/minute")
async def get_database(
    request: Request,
    response: Response,
    database_id: str,
) -> DatabaseResponse:
    """
    Get details of a specific registered database.

    Rate limit: 30 requests per minute per client.
    """
    logger.info("get_database_request", database_id=database_id)

    registry = await get_database_registry()

    try:
        registered = registry.get_database(database_id)
        return _registered_to_response(registered)
    except DatabaseNotRegisteredException:
        raise


@router.get("/{database_id}/health", response_model=DatabaseHealthResponse)
@limiter.limit("60/minute")
async def check_database_health(
    request: Request,
    response: Response,
    database_id: str,
) -> DatabaseHealthResponse:
    """
    Perform health check on a specific database.

    Executes a simple query to verify connectivity and measure latency.

    Rate limit: 60 requests per minute per client.
    """
    logger.info("check_database_health_request", database_id=database_id)

    registry = await get_database_registry()

    try:
        health = await registry.health_check(database_id)
        return _health_to_response(health)
    except DatabaseNotRegisteredException:
        raise


@router.get("/health/all", response_model=HealthCheckAllResponse)
@limiter.limit("10/minute")
async def check_all_database_health(
    request: Request,
    response: Response,
) -> HealthCheckAllResponse:
    """
    Perform health check on all registered databases.

    Returns aggregated health status for all databases.

    Rate limit: 10 requests per minute per client.
    """
    logger.info("check_all_database_health_request")

    registry = await get_database_registry()
    results = await registry.health_check_all()

    # Convert to response
    health_responses: dict[str, DatabaseHealthResponse] = {}
    healthy_count = 0
    unhealthy_count = 0

    for db_id, health in results.items():
        health_responses[db_id] = _health_to_response(health)
        if health.status == DatabaseStatus.CONNECTED:
            healthy_count += 1
        else:
            unhealthy_count += 1

    return HealthCheckAllResponse(
        total=len(results),
        healthy=healthy_count,
        unhealthy=unhealthy_count,
        results=health_responses,
    )


@router.delete(
    "/{database_id}",
    response_model=DatabaseDeleteResponse,
    dependencies=[Depends(require_mutation_scope)],
)
@limiter.limit("10/minute")
async def unregister_database(
    request: Request,
    response: Response,
    database_id: str,
) -> DatabaseDeleteResponse:
    """
    Unregister and close a database connection.

    Closes the connection pool and removes the database from the registry.
    The 'default' database cannot be removed.

    Rate limit: 10 requests per minute per client.
    """
    # Prevent removal of default database
    if database_id == "default":
        raise ValidationException(
            message="Cannot remove the default database",
            validation_errors=[
                {"field": "database_id", "error": "Default database is protected"}
            ],
        )

    logger.info("unregister_database_request", database_id=database_id)

    registry = await get_database_registry()

    try:
        await registry.unregister_database(database_id)

        logger.info("database_unregistered", database_id=database_id)

        return DatabaseDeleteResponse(
            database_id=database_id,
            message=f"Database '{database_id}' successfully unregistered",
        )
    except DatabaseNotRegisteredException:
        raise


@router.post("/{database_id}/test", response_model=DatabaseHealthResponse)
@limiter.limit("20/minute")
async def test_database_connection(
    request: Request,
    response: Response,
    database_id: str,
) -> DatabaseHealthResponse:
    """
    Test connection to a registered database.

    Similar to health check but intended for manual testing.

    Rate limit: 20 requests per minute per client.
    """
    logger.info("test_database_connection_request", database_id=database_id)

    registry = await get_database_registry()

    try:
        health = await registry.health_check(database_id)
        return _health_to_response(health)
    except DatabaseNotRegisteredException:
        raise
