"""
Model version registry and metadata tracking (Issue #16).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import text

from app.config import get_settings
from app.exceptions import ModelVersionNotFoundException, ModelVersioningException
from app.logging_config import get_logger
from db.connection import DatabaseManager, get_database

logger = get_logger(__name__)


class ModelVersionStatus(str, Enum):
    """Model version lifecycle status."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"


@dataclass
class ModelVersion:
    """Model version metadata."""

    version_id: str
    model_name: str
    base_model: str | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    status: ModelVersionStatus = ModelVersionStatus.INACTIVE
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "version_id": self.version_id,
            "model_name": self.model_name,
            "base_model": self.base_model,
            "description": self.description,
            "tags": self.tags,
            "metrics": self.metrics,
            "status": self.status.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ModelVersionManager:
    """Manage model versions and active selection."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db_manager = db_manager
        self._lock = asyncio.Lock()
        self._initialized = False
        self._settings = get_settings()

    async def initialize(self) -> None:
        """Ensure version tables exist."""
        async with self._lock:
            if self._initialized:
                return
            await self._ensure_tables()
            self._initialized = True

    async def register_version(
        self,
        model_name: str,
        base_model: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        metrics: dict[str, Any] | None = None,
        set_active: bool = False,
    ) -> ModelVersion:
        """Register a new model version."""
        await self._ensure_initialized()

        version_id = str(uuid.uuid4())
        tags = tags or []
        metrics = metrics or {}
        status = ModelVersionStatus.ACTIVE if set_active else ModelVersionStatus.INACTIVE

        query = text(
            """
            INSERT INTO model_versions (
                version_id,
                model_name,
                base_model,
                description,
                tags,
                metrics,
                status,
                created_at,
                updated_at
            ) VALUES (
                :version_id,
                :model_name,
                :base_model,
                :description,
                :tags,
                :metrics,
                :status,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            """
        )

        try:
            async with self._db_manager.session() as session:
                if set_active:
                    await session.execute(
                        text("UPDATE model_versions SET status = :status"),
                        {"status": ModelVersionStatus.INACTIVE.value},
                    )
                await session.execute(
                    query,
                    {
                        "version_id": version_id,
                        "model_name": model_name,
                        "base_model": base_model,
                        "description": description,
                        "tags": json.dumps(tags),
                        "metrics": json.dumps(metrics),
                        "status": status.value,
                    },
                )

            logger.info("model_version_registered", version_id=version_id)
            return await self.get_version(version_id)

        except Exception as e:
            logger.error("model_version_register_failed", error=str(e))
            raise ModelVersioningException(
                message=f"Failed to register model version: {e}",
                details={"model_name": model_name},
            ) from e

    async def get_version(self, version_id: str) -> ModelVersion:
        """Retrieve model version metadata."""
        await self._ensure_initialized()

        query = text(
            """
            SELECT
                version_id,
                model_name,
                base_model,
                description,
                tags,
                metrics,
                status,
                created_at,
                updated_at
            FROM model_versions
            WHERE version_id = :version_id
            """
        )

        async with self._db_manager.session() as session:
            result = await session.execute(query, {"version_id": version_id})
            row = result.mappings().first()

        if not row:
            raise ModelVersionNotFoundException(version_id=version_id)

        return self._row_to_version(row)

    async def list_versions(
        self,
        status: ModelVersionStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ModelVersion]:
        """List registered model versions."""
        await self._ensure_initialized()

        conditions = []
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if status:
            conditions.append("status = :status")
            params["status"] = status.value

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query = text(
            f"""
            SELECT
                version_id,
                model_name,
                base_model,
                description,
                tags,
                metrics,
                status,
                created_at,
                updated_at
            FROM model_versions
            {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """
        )

        async with self._db_manager.session() as session:
            result = await session.execute(query, params)
            rows = result.mappings().all()

        return [self._row_to_version(row) for row in rows]

    async def get_active_version(self) -> ModelVersion | None:
        """Return active model version if set."""
        await self._ensure_initialized()

        query = text(
            """
            SELECT
                version_id,
                model_name,
                base_model,
                description,
                tags,
                metrics,
                status,
                created_at,
                updated_at
            FROM model_versions
            WHERE status = :status
            ORDER BY updated_at DESC
            LIMIT 1
            """
        )

        async with self._db_manager.session() as session:
            result = await session.execute(
                query, {"status": ModelVersionStatus.ACTIVE.value}
            )
            row = result.mappings().first()

        return self._row_to_version(row) if row else None

    async def set_active_version(self, version_id: str) -> ModelVersion:
        """Set a model version as active."""
        await self._ensure_initialized()

        async with self._db_manager.session() as session:
            await session.execute(
                text("UPDATE model_versions SET status = :status"),
                {"status": ModelVersionStatus.INACTIVE.value},
            )
            result = await session.execute(
                text(
                    """
                    UPDATE model_versions
                    SET status = :status,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE version_id = :version_id
                    """
                ),
                {
                    "status": ModelVersionStatus.ACTIVE.value,
                    "version_id": version_id,
                },
            )

        if result.rowcount == 0:
            raise ModelVersionNotFoundException(version_id=version_id)

        logger.info("model_version_activated", version_id=version_id)
        return await self.get_version(version_id)

    async def resolve_model_name(self) -> str | None:
        """
        Resolve active model name based on settings.

        Returns None if no active version configured.
        """
        if not self._settings.model_versioning.enabled:
            return None

        configured_version = self._settings.model_versioning.active_version_id
        if not configured_version:
            return None

        version = await self.get_version(configured_version)
        return version.model_name

    def _row_to_version(self, row: dict[str, Any]) -> ModelVersion:
        return ModelVersion(
            version_id=row["version_id"],
            model_name=row["model_name"],
            base_model=row.get("base_model"),
            description=row.get("description"),
            tags=self._parse_json(row.get("tags"), default=list),
            metrics=self._parse_json(row.get("metrics"), default=dict),
            status=ModelVersionStatus(row.get("status", ModelVersionStatus.INACTIVE.value)),
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
            CREATE TABLE IF NOT EXISTS model_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id TEXT NOT NULL UNIQUE,
                model_name TEXT NOT NULL,
                base_model TEXT,
                description TEXT,
                tags TEXT,
                metrics TEXT,
                status TEXT NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        create_status_index = text(
            "CREATE INDEX IF NOT EXISTS ix_model_versions_status "
            "ON model_versions (status)"
        )
        create_created_index = text(
            "CREATE INDEX IF NOT EXISTS ix_model_versions_created_at "
            "ON model_versions (created_at)"
        )

        async with self._db_manager.session() as session:
            await session.execute(create_table)
            await session.execute(create_status_index)
            await session.execute(create_created_index)


_model_version_manager: ModelVersionManager | None = None


async def get_model_version_manager() -> ModelVersionManager:
    """Get or create the global model version manager."""
    global _model_version_manager

    if _model_version_manager is None:
        db_manager = await get_database()
        _model_version_manager = ModelVersionManager(db_manager=db_manager)

    return _model_version_manager


def reset_model_version_manager() -> None:
    """Reset the global model version manager instance."""
    global _model_version_manager
    _model_version_manager = None
