"""
Tests for model versioning (Issue #16).
"""

import pytest

from models.versioning import ModelVersionManager, ModelVersionStatus


class TestModelVersionManager:
    """Tests for ModelVersionManager operations."""

    @pytest.mark.asyncio
    async def test_register_and_activate_version(self, db_manager) -> None:
        manager = ModelVersionManager(db_manager=db_manager)

        version = await manager.register_version(
            model_name="example/model",
            base_model="base/model",
            description="Test model",
            set_active=True,
        )

        active = await manager.get_active_version()

        assert active is not None
        assert active.version_id == version.version_id
        assert active.status == ModelVersionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_list_versions(self, db_manager) -> None:
        manager = ModelVersionManager(db_manager=db_manager)

        await manager.register_version(model_name="model/a")
        await manager.register_version(model_name="model/b")

        versions = await manager.list_versions()

        assert len(versions) >= 2
