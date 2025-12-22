"""
Model versioning API routes (Issue #16).
"""

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.logging_config import get_logger
from app.security import limiter, require_auth, require_mutation_scope
from models.versioning import (
    ModelVersion,
    ModelVersionManager,
    ModelVersionStatus,
    get_model_version_manager,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/models",
    tags=["Model Versioning"],
    dependencies=[Depends(require_auth)],
)


class ModelVersionCreateRequest(BaseModel):
    """Request model for registering a model version."""

    model_name: str = Field(..., min_length=3, max_length=200)
    base_model: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    metrics: dict[str, Any] = Field(default_factory=dict)
    set_active: bool = Field(default=False)


class ModelVersionResponse(BaseModel):
    """Response model for model versions."""

    version_id: str
    model_name: str
    base_model: str | None
    description: str | None
    tags: list[str]
    metrics: dict[str, Any]
    status: str
    created_at: str | None
    updated_at: str | None

    @classmethod
    def from_record(cls, record: ModelVersion) -> "ModelVersionResponse":
        return cls(**record.to_dict())


@router.get("/versions", response_model=list[ModelVersionResponse])
@limiter.limit("20/minute")
async def list_model_versions(
    request: Request,
    status: ModelVersionStatus | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ModelVersionResponse]:
    """List model versions."""
    manager = await get_model_version_manager()
    versions = await manager.list_versions(status=status, limit=limit, offset=offset)
    return [ModelVersionResponse.from_record(version) for version in versions]


@router.get("/versions/active", response_model=ModelVersionResponse | None)
@limiter.limit("30/minute")
async def get_active_model_version(
    request: Request,
) -> ModelVersionResponse | None:
    """Get active model version."""
    manager = await get_model_version_manager()
    version = await manager.get_active_version()
    return ModelVersionResponse.from_record(version) if version else None


@router.get("/versions/{version_id}", response_model=ModelVersionResponse)
@limiter.limit("30/minute")
async def get_model_version(
    request: Request,
    version_id: str,
) -> ModelVersionResponse:
    """Retrieve model version details."""
    manager = await get_model_version_manager()
    version = await manager.get_version(version_id)
    return ModelVersionResponse.from_record(version)


@router.post(
    "/versions",
    response_model=ModelVersionResponse,
    dependencies=[Depends(require_mutation_scope)],
)
@limiter.limit("10/minute")
async def register_model_version(
    request: Request,
    version_request: ModelVersionCreateRequest,
) -> ModelVersionResponse:
    """Register a new model version."""
    manager = await get_model_version_manager()
    version = await manager.register_version(
        model_name=version_request.model_name,
        base_model=version_request.base_model,
        description=version_request.description,
        tags=version_request.tags,
        metrics=version_request.metrics,
        set_active=version_request.set_active,
    )

    logger.info("model_version_registered", version_id=version.version_id)
    return ModelVersionResponse.from_record(version)


@router.post(
    "/versions/{version_id}/activate",
    response_model=ModelVersionResponse,
    dependencies=[Depends(require_mutation_scope)],
)
@limiter.limit("10/minute")
async def activate_model_version(
    request: Request,
    version_id: str,
) -> ModelVersionResponse:
    """Activate a model version."""
    manager = await get_model_version_manager()
    version = await manager.set_active_version(version_id)

    logger.info("model_version_activated", version_id=version.version_id)
    return ModelVersionResponse.from_record(version)
