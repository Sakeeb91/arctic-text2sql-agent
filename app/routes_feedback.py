"""
Feedback collection API routes (Issue #16).
"""

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.config import get_settings
from app.exceptions import ValidationException
from app.logging_config import get_logger
from app.security import (
    limiter,
    validate_database_id,
    validate_natural_language_query,
)
from app.security.input_validation import validate_sql_query
from db.examples import get_example_store
from db.feedback import FeedbackRecord, FeedbackStatus, get_feedback_store

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/feedback", tags=["Feedback"])


class FeedbackCreateRequest(BaseModel):
    """Request model for submitting feedback."""

    natural_query: str = Field(..., min_length=3, max_length=1000)
    database_id: str = Field(..., min_length=1, max_length=100)
    generated_sql: str | None = Field(default=None, max_length=10000)
    corrected_sql: str | None = Field(default=None, max_length=10000)
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    promote_to_examples: bool = Field(default=False)


class FeedbackStatusUpdateRequest(BaseModel):
    """Request model for updating feedback status."""

    status: FeedbackStatus


class FeedbackResponse(BaseModel):
    """Response model for feedback entries."""

    feedback_id: str
    database_id: str
    natural_query: str
    generated_sql: str | None
    corrected_sql: str | None
    rating: int | None
    status: str
    comment: str | None
    metadata: dict[str, Any]
    created_at: str | None
    updated_at: str | None

    @classmethod
    def from_record(cls, record: FeedbackRecord) -> "FeedbackResponse":
        data = record.to_dict()
        return cls(**data)


@router.post("", response_model=FeedbackResponse)
@limiter.limit("10/minute")
async def submit_feedback(
    request: Request, feedback_request: FeedbackCreateRequest
) -> FeedbackResponse:
    """Submit feedback for a generated query."""
    is_valid_query, query_errors = validate_natural_language_query(
        feedback_request.natural_query
    )
    if not is_valid_query:
        raise ValidationException(
            message="Invalid natural language query",
            validation_errors=[
                {"field": "natural_query", "error": e} for e in query_errors
            ],
        )

    is_valid_db, db_error = validate_database_id(feedback_request.database_id)
    if not is_valid_db:
        raise ValidationException(
            message=db_error or "Invalid database ID",
            validation_errors=[{"field": "database_id", "error": db_error}],
        )

    if feedback_request.generated_sql:
        is_valid_sql, sql_errors = validate_sql_query(feedback_request.generated_sql)
        if not is_valid_sql:
            raise ValidationException(
                message="Invalid generated SQL",
                validation_errors=[
                    {"field": "generated_sql", "error": e} for e in sql_errors
                ],
            )

    if feedback_request.corrected_sql:
        is_valid_sql, sql_errors = validate_sql_query(feedback_request.corrected_sql)
        if not is_valid_sql:
            raise ValidationException(
                message="Invalid corrected SQL",
                validation_errors=[
                    {"field": "corrected_sql", "error": e} for e in sql_errors
                ],
            )

    store = await get_feedback_store()
    record = await store.submit_feedback(
        database_id=feedback_request.database_id,
        natural_query=feedback_request.natural_query,
        generated_sql=feedback_request.generated_sql,
        corrected_sql=feedback_request.corrected_sql,
        rating=feedback_request.rating,
        comment=feedback_request.comment,
        metadata=feedback_request.metadata,
    )

    await _maybe_promote_feedback(
        feedback_request=feedback_request,
        database_id=feedback_request.database_id,
    )

    return FeedbackResponse.from_record(record)


@router.get("/{feedback_id}", response_model=FeedbackResponse)
@limiter.limit("30/minute")
async def get_feedback(request: Request, feedback_id: str) -> FeedbackResponse:
    """Retrieve a feedback entry."""
    store = await get_feedback_store()
    record = await store.get_feedback(feedback_id)
    return FeedbackResponse.from_record(record)


@router.get("", response_model=list[FeedbackResponse])
@limiter.limit("20/minute")
async def list_feedback(
    request: Request,
    database_id: str | None = None,
    status: FeedbackStatus | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[FeedbackResponse]:
    """List feedback entries."""
    store = await get_feedback_store()
    records = await store.list_feedback(
        database_id=database_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return [FeedbackResponse.from_record(record) for record in records]


@router.patch("/{feedback_id}/status", response_model=FeedbackResponse)
@limiter.limit("10/minute")
async def update_feedback_status(
    request: Request,
    feedback_id: str,
    update_request: FeedbackStatusUpdateRequest,
) -> FeedbackResponse:
    """Update feedback status."""
    store = await get_feedback_store()
    record = await store.update_feedback_status(
        feedback_id=feedback_id,
        status=update_request.status,
    )

    if update_request.status == FeedbackStatus.VERIFIED:
        await _maybe_promote_verified_feedback(record)

    return FeedbackResponse.from_record(record)


async def _maybe_promote_feedback(
    feedback_request: FeedbackCreateRequest,
    database_id: str,
) -> None:
    settings = get_settings()
    if (
        not settings.feedback.auto_promote_to_examples
        and not feedback_request.promote_to_examples
    ):
        return
    if not feedback_request.corrected_sql:
        return
    if (
        feedback_request.rating is not None
        and feedback_request.rating < settings.feedback.min_rating_for_promotion
    ):
        return

    store = await get_example_store()
    await store.add_example(
        natural_query=feedback_request.natural_query,
        sql_query=feedback_request.corrected_sql,
        database_id=database_id,
        verified=True,
        tags=["feedback"],
        metadata={"source": "feedback"},
    )

    logger.info("feedback_promoted_to_example", database_id=database_id)


async def _maybe_promote_verified_feedback(record: FeedbackRecord) -> None:
    settings = get_settings()
    if not settings.feedback.auto_promote_to_examples:
        return
    if not record.corrected_sql:
        return

    store = await get_example_store()
    await store.add_example(
        natural_query=record.natural_query,
        sql_query=record.corrected_sql,
        database_id=record.database_id,
        verified=True,
        tags=["feedback"],
        metadata={"source": "feedback", "feedback_id": record.feedback_id},
    )
