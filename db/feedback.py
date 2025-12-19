"""
Feedback collection store for Text2SQL corrections (Issue #16).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from collections.abc import Mapping
from typing import Any, cast

from sqlalchemy import text

from app.exceptions import FeedbackNotFoundException, FeedbackException
from app.logging_config import get_logger
from db.connection import DatabaseManager, get_database

logger = get_logger(__name__)


class FeedbackStatus(str, Enum):
    """Status for feedback entries."""

    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


@dataclass
class FeedbackRecord:
    """Stored feedback entry."""

    feedback_id: str
    database_id: str
    natural_query: str
    generated_sql: str | None = None
    corrected_sql: str | None = None
    rating: int | None = None
    status: FeedbackStatus = FeedbackStatus.PENDING
    comment: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "feedback_id": self.feedback_id,
            "database_id": self.database_id,
            "natural_query": self.natural_query,
            "generated_sql": self.generated_sql,
            "corrected_sql": self.corrected_sql,
            "rating": self.rating,
            "status": self.status.value,
            "comment": self.comment,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class FeedbackStore:
    """Store and manage feedback entries."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db_manager = db_manager
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        """Ensure feedback tables exist."""
        async with self._lock:
            if self._initialized:
                return
            await self._ensure_tables()
            self._initialized = True

    async def submit_feedback(
        self,
        database_id: str,
        natural_query: str,
        generated_sql: str | None = None,
        corrected_sql: str | None = None,
        rating: int | None = None,
        comment: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> FeedbackRecord:
        """Submit a feedback entry."""
        await self._ensure_initialized()

        feedback_id = str(uuid.uuid4())
        metadata = metadata or {}

        query = text(
            """
            INSERT INTO query_feedback (
                feedback_id,
                database_id,
                natural_query,
                generated_sql,
                corrected_sql,
                rating,
                status,
                comment,
                metadata,
                created_at,
                updated_at
            ) VALUES (
                :feedback_id,
                :database_id,
                :natural_query,
                :generated_sql,
                :corrected_sql,
                :rating,
                :status,
                :comment,
                :metadata,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            """
        )

        try:
            async with self._db_manager.session() as session:
                await session.execute(
                    query,
                    {
                        "feedback_id": feedback_id,
                        "database_id": database_id,
                        "natural_query": natural_query,
                        "generated_sql": generated_sql,
                        "corrected_sql": corrected_sql,
                        "rating": rating,
                        "status": FeedbackStatus.PENDING.value,
                        "comment": comment,
                        "metadata": json.dumps(metadata),
                    },
                )

            logger.info("feedback_submitted", feedback_id=feedback_id)
            return await self.get_feedback(feedback_id)

        except Exception as e:
            logger.error("feedback_submit_failed", error=str(e))
            raise FeedbackException(
                message=f"Failed to submit feedback: {e}",
                details={"database_id": database_id},
            ) from e

    async def get_feedback(self, feedback_id: str) -> FeedbackRecord:
        """Retrieve a feedback entry by ID."""
        await self._ensure_initialized()

        query = text(
            """
            SELECT
                feedback_id,
                database_id,
                natural_query,
                generated_sql,
                corrected_sql,
                rating,
                status,
                comment,
                metadata,
                created_at,
                updated_at
            FROM query_feedback
            WHERE feedback_id = :feedback_id
            """
        )

        async with self._db_manager.session() as session:
            result = await session.execute(query, {"feedback_id": feedback_id})
            row = result.mappings().first()

        if not row:
            raise FeedbackNotFoundException(feedback_id=feedback_id)

        return self._row_to_feedback(cast(Mapping[str, Any], row))

    async def list_feedback(
        self,
        database_id: str | None = None,
        status: FeedbackStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[FeedbackRecord]:
        """List feedback entries with optional filtering."""
        await self._ensure_initialized()

        conditions = []
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if database_id:
            conditions.append("database_id = :database_id")
            params["database_id"] = database_id
        if status:
            conditions.append("status = :status")
            params["status"] = status.value

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query = text(
            f"""
            SELECT
                feedback_id,
                database_id,
                natural_query,
                generated_sql,
                corrected_sql,
                rating,
                status,
                comment,
                metadata,
                created_at,
                updated_at
            FROM query_feedback
            {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """
        )

        async with self._db_manager.session() as session:
            result = await session.execute(query, params)
            rows = result.mappings().all()

        return [self._row_to_feedback(cast(Mapping[str, Any], row)) for row in rows]

    async def update_feedback_status(
        self,
        feedback_id: str,
        status: FeedbackStatus,
    ) -> FeedbackRecord:
        """Update feedback status."""
        await self._ensure_initialized()

        query = text(
            """
            UPDATE query_feedback
            SET status = :status,
                updated_at = CURRENT_TIMESTAMP
            WHERE feedback_id = :feedback_id
            """
        )

        async with self._db_manager.session() as session:
            result = await session.execute(
                query,
                {"feedback_id": feedback_id, "status": status.value},
            )

        rowcount = getattr(result, "rowcount", 0)
        if rowcount == 0:
            raise FeedbackNotFoundException(feedback_id=feedback_id)

        logger.info(
            "feedback_status_updated", feedback_id=feedback_id, status=status.value
        )
        return await self.get_feedback(feedback_id)

    async def delete_feedback(self, feedback_id: str) -> None:
        """Delete a feedback entry."""
        await self._ensure_initialized()

        query = text("DELETE FROM query_feedback WHERE feedback_id = :feedback_id")

        async with self._db_manager.session() as session:
            result = await session.execute(query, {"feedback_id": feedback_id})

        rowcount = getattr(result, "rowcount", 0)
        if rowcount == 0:
            raise FeedbackNotFoundException(feedback_id=feedback_id)

        logger.info("feedback_deleted", feedback_id=feedback_id)

    def _row_to_feedback(self, row: Mapping[str, Any]) -> FeedbackRecord:
        return FeedbackRecord(
            feedback_id=row["feedback_id"],
            database_id=row["database_id"],
            natural_query=row["natural_query"],
            generated_sql=row.get("generated_sql"),
            corrected_sql=row.get("corrected_sql"),
            rating=row.get("rating"),
            status=FeedbackStatus(row.get("status", FeedbackStatus.PENDING.value)),
            comment=row.get("comment"),
            metadata=self._parse_json(row.get("metadata")),
            created_at=self._parse_datetime(row.get("created_at")),
            updated_at=self._parse_datetime(row.get("updated_at")),
        )

    @staticmethod
    def _parse_json(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self.initialize()

    async def _ensure_tables(self) -> None:
        create_table = text(
            """
            CREATE TABLE IF NOT EXISTS query_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feedback_id TEXT NOT NULL UNIQUE,
                database_id TEXT NOT NULL,
                natural_query TEXT NOT NULL,
                generated_sql TEXT,
                corrected_sql TEXT,
                rating INTEGER,
                status TEXT NOT NULL,
                comment TEXT,
                metadata TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        create_db_index = text(
            "CREATE INDEX IF NOT EXISTS ix_query_feedback_database_id "
            "ON query_feedback (database_id)"
        )
        create_status_index = text(
            "CREATE INDEX IF NOT EXISTS ix_query_feedback_status "
            "ON query_feedback (status)"
        )
        create_created_index = text(
            "CREATE INDEX IF NOT EXISTS ix_query_feedback_created_at "
            "ON query_feedback (created_at)"
        )

        async with self._db_manager.session() as session:
            await session.execute(create_table)
            await session.execute(create_db_index)
            await session.execute(create_status_index)
            await session.execute(create_created_index)


_feedback_store: FeedbackStore | None = None


async def get_feedback_store() -> FeedbackStore:
    """Get or create the global feedback store."""
    global _feedback_store

    if _feedback_store is None:
        db_manager = await get_database()
        _feedback_store = FeedbackStore(db_manager=db_manager)

    return _feedback_store


def reset_feedback_store() -> None:
    """Reset the global feedback store instance."""
    global _feedback_store
    _feedback_store = None
