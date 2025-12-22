"""
Few-shot example repository API routes (Issue #16).
"""

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.exceptions import ValidationException
from app.logging_config import get_logger
from app.security import (
    limiter,
    require_auth,
    require_mutation_scope,
    validate_database_id,
    validate_natural_language_query,
)
from app.security.input_validation import validate_sql_query
from db.examples import ExampleRecord, get_example_store

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/examples",
    tags=["Few-Shot Examples"],
    dependencies=[Depends(require_auth)],
)


class ExampleCreateRequest(BaseModel):
    """Request model for creating a few-shot example."""

    natural_query: str = Field(..., min_length=3, max_length=1000)
    sql_query: str = Field(..., min_length=3, max_length=10000)
    database_id: str = Field(..., min_length=1, max_length=100)
    verified: bool = Field(default=False)
    tags: list[str] = Field(default_factory=list, max_length=20)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExampleUpdateRequest(BaseModel):
    """Request model for updating a few-shot example."""

    verified: bool | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


class ExampleSearchRequest(BaseModel):
    """Request model for searching few-shot examples."""

    query: str = Field(..., min_length=3, max_length=1000)
    database_id: str | None = None
    k: int = Field(default=3, ge=1, le=10)
    verified_only: bool = Field(default=True)


class ExampleResponse(BaseModel):
    """Response model for a single example."""

    example_id: str
    natural_query: str
    sql_query: str
    database_id: str
    verified: bool
    tags: list[str]
    metadata: dict[str, Any]
    usage_count: int
    last_used_at: str | None
    created_at: str | None
    updated_at: str | None

    @classmethod
    def from_record(cls, record: ExampleRecord) -> "ExampleResponse":
        data = record.to_dict()
        return cls(**data)


class ExampleSearchResponse(BaseModel):
    """Response model for example search results."""

    results: list[dict[str, Any]]


@router.post(
    "",
    response_model=ExampleResponse,
    dependencies=[Depends(require_mutation_scope)],
)
@limiter.limit("10/minute")
async def create_example(
    request: Request,
    response: Response,
    example_request: ExampleCreateRequest,
) -> ExampleResponse:
    """Create a new few-shot example."""
    is_valid_query, query_errors = validate_natural_language_query(
        example_request.natural_query
    )
    if not is_valid_query:
        raise ValidationException(
            message="Invalid natural language query",
            validation_errors=[
                {"field": "natural_query", "error": e} for e in query_errors
            ],
        )

    is_valid_db, db_error = validate_database_id(example_request.database_id)
    if not is_valid_db:
        raise ValidationException(
            message=db_error or "Invalid database ID",
            validation_errors=[{"field": "database_id", "error": db_error}],
        )

    is_valid_sql, sql_errors = validate_sql_query(example_request.sql_query)
    if not is_valid_sql:
        raise ValidationException(
            message="Invalid SQL query",
            validation_errors=[{"field": "sql_query", "error": e} for e in sql_errors],
        )

    store = await get_example_store()
    record = await store.add_example(
        natural_query=example_request.natural_query,
        sql_query=example_request.sql_query,
        database_id=example_request.database_id,
        verified=example_request.verified,
        tags=example_request.tags,
        metadata=example_request.metadata,
    )

    logger.info(
        "example_created",
        example_id=record.example_id,
        database_id=record.database_id,
    )

    return ExampleResponse.from_record(record)


@router.get("/{example_id}", response_model=ExampleResponse)
@limiter.limit("30/minute")
async def get_example(
    request: Request,
    response: Response,
    example_id: str,
) -> ExampleResponse:
    """Retrieve a specific example."""
    store = await get_example_store()
    record = await store.get_example(example_id)
    return ExampleResponse.from_record(record)


@router.get("", response_model=list[ExampleResponse])
@limiter.limit("20/minute")
async def list_examples(
    request: Request,
    response: Response,
    database_id: str | None = None,
    verified_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[ExampleResponse]:
    """List stored examples."""
    store = await get_example_store()
    records = await store.list_examples(
        database_id=database_id,
        verified_only=verified_only,
        limit=limit,
        offset=offset,
    )
    return [ExampleResponse.from_record(record) for record in records]


@router.post("/search", response_model=ExampleSearchResponse)
@limiter.limit("20/minute")
async def search_examples(
    request: Request,
    response: Response,
    search_request: ExampleSearchRequest,
) -> ExampleSearchResponse:
    """Search for relevant examples."""
    store = await get_example_store()
    results = await store.get_relevant_examples(
        query=search_request.query,
        database_id=search_request.database_id,
        k=search_request.k,
        verified_only=search_request.verified_only,
    )

    return ExampleSearchResponse(results=[result.to_dict() for result in results])


@router.patch(
    "/{example_id}",
    response_model=ExampleResponse,
    dependencies=[Depends(require_mutation_scope)],
)
@limiter.limit("10/minute")
async def update_example(
    request: Request,
    response: Response,
    example_id: str,
    update_request: ExampleUpdateRequest,
) -> ExampleResponse:
    """Update example metadata."""
    store = await get_example_store()
    record = await store.update_example(
        example_id=example_id,
        verified=update_request.verified,
        tags=update_request.tags,
        metadata=update_request.metadata,
    )
    return ExampleResponse.from_record(record)


@router.delete(
    "/{example_id}",
    dependencies=[Depends(require_mutation_scope)],
)
@limiter.limit("10/minute")
async def delete_example(
    request: Request,
    response: Response,
    example_id: str,
) -> dict[str, Any]:
    """Delete a stored example."""
    store = await get_example_store()
    await store.delete_example(example_id)
    return {"status": "deleted", "example_id": example_id}
