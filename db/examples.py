"""
Few-shot example repository with semantic search (Issue #16).

Provides storage and retrieval of domain-specific examples for
in-context learning using lightweight embeddings.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text

from app.config import get_settings
from app.exceptions import ExampleNotFoundException, ExampleStoreException
from app.few_shot.embeddings import EmbeddingProvider, cosine_similarity
from app.logging_config import get_logger
from db.connection import DatabaseManager, get_database

logger = get_logger(__name__)


@dataclass
class ExampleRecord:
    """Stored few-shot example."""

    example_id: str
    natural_query: str
    sql_query: str
    database_id: str
    verified: bool = False
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] = field(default_factory=list)
    usage_count: int = 0
    last_used_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self, include_embedding: bool = False) -> dict[str, Any]:
        """Convert to dictionary."""
        data = {
            "example_id": self.example_id,
            "natural_query": self.natural_query,
            "sql_query": self.sql_query,
            "database_id": self.database_id,
            "verified": self.verified,
            "tags": self.tags,
            "metadata": self.metadata,
            "usage_count": self.usage_count,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_embedding:
            data["embedding"] = self.embedding
        return data


@dataclass
class ExampleSearchResult:
    """Result of a semantic search for examples."""

    example: ExampleRecord
    similarity: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "example": self.example.to_dict(),
            "similarity": round(self.similarity, 4),
        }


class ExampleStore:
    """
    Store and retrieve few-shot examples.

    Uses embeddings to retrieve the most relevant examples for a query.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self._db_manager = db_manager
        self._embedding_provider = embedding_provider
        self._settings = get_settings()
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        """Ensure example tables exist."""
        async with self._lock:
            if self._initialized:
                return
            await self._ensure_tables()
            self._initialized = True

    async def add_example(
        self,
        natural_query: str,
        sql_query: str,
        database_id: str,
        verified: bool = False,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExampleRecord:
        """Add a new example to the store."""
        await self._ensure_initialized()

        tags = tags or []
        metadata = metadata or {}
        embedding = await self._get_embedding(natural_query)
        example_id = str(uuid.uuid4())

        query = text(
            """
            INSERT INTO few_shot_examples (
                example_id,
                natural_query,
                sql_query,
                database_id,
                verified,
                tags,
                metadata,
                embedding,
                usage_count,
                created_at,
                updated_at
            ) VALUES (
                :example_id,
                :natural_query,
                :sql_query,
                :database_id,
                :verified,
                :tags,
                :metadata,
                :embedding,
                :usage_count,
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
                        "example_id": example_id,
                        "natural_query": natural_query,
                        "sql_query": sql_query,
                        "database_id": database_id,
                        "verified": verified,
                        "tags": json.dumps(tags),
                        "metadata": json.dumps(metadata),
                        "embedding": json.dumps(embedding),
                        "usage_count": 0,
                    },
                )

            logger.info(
                "example_added",
                example_id=example_id,
                database_id=database_id,
                verified=verified,
            )

            return await self.get_example(example_id)
        except Exception as e:
            logger.error("example_add_failed", error=str(e))
            raise ExampleStoreException(
                message=f"Failed to add example: {e}",
                details={"database_id": database_id},
            ) from e

    async def get_example(self, example_id: str) -> ExampleRecord:
        """Retrieve a single example by ID."""
        await self._ensure_initialized()

        query = text(
            """
            SELECT
                example_id,
                natural_query,
                sql_query,
                database_id,
                verified,
                tags,
                metadata,
                embedding,
                usage_count,
                last_used_at,
                created_at,
                updated_at
            FROM few_shot_examples
            WHERE example_id = :example_id
            """
        )

        async with self._db_manager.session() as session:
            result = await session.execute(query, {"example_id": example_id})
            row = result.mappings().first()

        if not row:
            raise ExampleNotFoundException(example_id=example_id)

        return self._row_to_example(row)

    async def list_examples(
        self,
        database_id: str | None = None,
        verified_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ExampleRecord]:
        """List examples with optional filtering."""
        await self._ensure_initialized()

        conditions = []
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if database_id:
            conditions.append("database_id = :database_id")
            params["database_id"] = database_id
        if verified_only:
            conditions.append("verified = 1")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query = text(
            f"""
            SELECT
                example_id,
                natural_query,
                sql_query,
                database_id,
                verified,
                tags,
                metadata,
                embedding,
                usage_count,
                last_used_at,
                created_at,
                updated_at
            FROM few_shot_examples
            {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """
        )

        async with self._db_manager.session() as session:
            result = await session.execute(query, params)
            rows = result.mappings().all()

        return [self._row_to_example(row) for row in rows]

    async def update_example(
        self,
        example_id: str,
        verified: bool | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExampleRecord:
        """Update example metadata."""
        await self._ensure_initialized()

        updates = []
        params: dict[str, Any] = {"example_id": example_id}

        if verified is not None:
            updates.append("verified = :verified")
            params["verified"] = verified
        if tags is not None:
            updates.append("tags = :tags")
            params["tags"] = json.dumps(tags)
        if metadata is not None:
            updates.append("metadata = :metadata")
            params["metadata"] = json.dumps(metadata)

        if not updates:
            return await self.get_example(example_id)

        updates.append("updated_at = CURRENT_TIMESTAMP")

        query = text(
            f"""
            UPDATE few_shot_examples
            SET {', '.join(updates)}
            WHERE example_id = :example_id
            """
        )

        async with self._db_manager.session() as session:
            result = await session.execute(query, params)

        if result.rowcount == 0:
            raise ExampleNotFoundException(example_id=example_id)

        logger.info("example_updated", example_id=example_id)
        return await self.get_example(example_id)

    async def delete_example(self, example_id: str) -> None:
        """Delete an example from the store."""
        await self._ensure_initialized()

        query = text(
            "DELETE FROM few_shot_examples WHERE example_id = :example_id"
        )

        async with self._db_manager.session() as session:
            result = await session.execute(query, {"example_id": example_id})

        if result.rowcount == 0:
            raise ExampleNotFoundException(example_id=example_id)

        logger.info("example_deleted", example_id=example_id)

    async def get_relevant_examples(
        self,
        query: str,
        database_id: str | None = None,
        k: int | None = None,
        verified_only: bool | None = None,
    ) -> list[ExampleSearchResult]:
        """
        Retrieve the most similar examples for a query.

        Uses cosine similarity on stored embeddings.
        """
        await self._ensure_initialized()

        max_results = k if k is not None else self._settings.few_shot.max_examples
        verified_only = (
            verified_only
            if verified_only is not None
            else self._settings.few_shot.verified_only
        )
        if max_results <= 0:
            return []

        query_embedding = await self._get_embedding(query)
        if not query_embedding:
            return []

        conditions = []
        params: dict[str, Any] = {"limit": max(max_results * 20, 50)}

        if database_id:
            conditions.append("database_id = :database_id")
            params["database_id"] = database_id
        if verified_only:
            conditions.append("verified = 1")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query_stmt = text(
            f"""
            SELECT
                example_id,
                natural_query,
                sql_query,
                database_id,
                verified,
                tags,
                metadata,
                embedding,
                usage_count,
                last_used_at,
                created_at,
                updated_at
            FROM few_shot_examples
            {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit
            """
        )

        async with self._db_manager.session() as session:
            result = await session.execute(query_stmt, params)
            rows = result.mappings().all()

        scored: list[ExampleSearchResult] = []
        min_similarity = self._settings.few_shot.min_similarity

        for row in rows:
            example = self._row_to_example(row)
            if not example.embedding:
                continue
            similarity = cosine_similarity(query_embedding, example.embedding)
            if similarity >= min_similarity:
                scored.append(
                    ExampleSearchResult(example=example, similarity=similarity)
                )

        scored.sort(key=lambda item: item.similarity, reverse=True)

        results = scored[:max_results]
        await self._record_usage([r.example.example_id for r in results])

        return results

    async def _record_usage(self, example_ids: list[str]) -> None:
        if not example_ids:
            return

        query = text(
            """
            UPDATE few_shot_examples
            SET usage_count = usage_count + 1,
                last_used_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE example_id = :example_id
            """
        )

        async with self._db_manager.session() as session:
            for example_id in example_ids:
                await session.execute(query, {"example_id": example_id})

    async def _get_embedding(self, text_value: str) -> list[float]:
        try:
            embeddings = await self._embedding_provider.embed_texts([text_value])
            if embeddings:
                return embeddings[0]
        except Exception as e:
            logger.warning("embedding_failed", error=str(e))
        return []

    def _row_to_example(self, row: dict[str, Any]) -> ExampleRecord:
        return ExampleRecord(
            example_id=row["example_id"],
            natural_query=row["natural_query"],
            sql_query=row["sql_query"],
            database_id=row["database_id"],
            verified=bool(row["verified"]),
            tags=self._parse_json(row.get("tags"), default=list),
            metadata=self._parse_json(row.get("metadata"), default=dict),
            embedding=self._parse_json(row.get("embedding"), default=list),
            usage_count=row.get("usage_count") or 0,
            last_used_at=self._parse_datetime(row.get("last_used_at")),
            created_at=self._parse_datetime(row.get("created_at")),
            updated_at=self._parse_datetime(row.get("updated_at")),
        )

    @staticmethod
    def _parse_json(value: Any, default: type) -> Any:
        if value is None:
            return default()
        if isinstance(value, (list, dict)):
            return value
        try:
            return json.loads(value)
        except Exception:
            return default()

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
            CREATE TABLE IF NOT EXISTS few_shot_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                example_id TEXT NOT NULL UNIQUE,
                natural_query TEXT NOT NULL,
                sql_query TEXT NOT NULL,
                database_id TEXT NOT NULL,
                verified BOOLEAN NOT NULL DEFAULT 0,
                tags TEXT,
                metadata TEXT,
                embedding TEXT,
                usage_count INTEGER NOT NULL DEFAULT 0,
                last_used_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        create_db_index = text(
            "CREATE INDEX IF NOT EXISTS ix_few_shot_examples_database_id "
            "ON few_shot_examples (database_id)"
        )
        create_verified_index = text(
            "CREATE INDEX IF NOT EXISTS ix_few_shot_examples_verified "
            "ON few_shot_examples (verified)"
        )
        create_created_index = text(
            "CREATE INDEX IF NOT EXISTS ix_few_shot_examples_created_at "
            "ON few_shot_examples (created_at)"
        )

        async with self._db_manager.session() as session:
            await session.execute(create_table)
            await session.execute(create_db_index)
            await session.execute(create_verified_index)
            await session.execute(create_created_index)


_example_store: ExampleStore | None = None


async def get_example_store() -> ExampleStore:
    """Get or create the global example store."""
    global _example_store

    if _example_store is None:
        from app.few_shot.embeddings import get_embedding_provider

        db_manager = await get_database()
        _example_store = ExampleStore(
            db_manager=db_manager,
            embedding_provider=get_embedding_provider(),
        )

    return _example_store


def reset_example_store() -> None:
    """Reset the global example store instance."""
    global _example_store
    _example_store = None
