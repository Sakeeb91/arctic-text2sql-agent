"""
Unit tests for model versioning routes (Issue #16).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes_models import router
from models.versioning import ModelVersion, ModelVersionStatus


@pytest.fixture
def mock_manager() -> MagicMock:
    """Create mock model version manager."""
    manager = MagicMock()
    manager.list_versions = AsyncMock()
    manager.get_active_version = AsyncMock()
    manager.get_version = AsyncMock()
    manager.register_version = AsyncMock()
    manager.set_active_version = AsyncMock()
    return manager


@pytest.fixture
def app(mock_manager: MagicMock) -> FastAPI:
    """Create test FastAPI app."""
    from app.error_handlers import setup_exception_handlers
    from app.security import limiter

    test_app = FastAPI()
    test_app.state.limiter = limiter
    setup_exception_handlers(test_app)
    test_app.include_router(router)

    return test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create test client."""
    return TestClient(app)


class TestModelVersionRoutes:
    """Tests for model versioning endpoints."""

    def test_list_versions(self, client: TestClient, mock_manager: MagicMock) -> None:
        mock_manager.list_versions.return_value = [
            ModelVersion(
                version_id="ver-1",
                model_name="model/a",
                status=ModelVersionStatus.INACTIVE,
            )
        ]

        with patch(
            "app.routes_models.get_model_version_manager", return_value=mock_manager
        ):
            response = client.get("/api/v1/models/versions")

        assert response.status_code == 200
        assert response.json()[0]["version_id"] == "ver-1"

    def test_register_version(
        self, client: TestClient, mock_manager: MagicMock
    ) -> None:
        mock_manager.register_version.return_value = ModelVersion(
            version_id="ver-2",
            model_name="model/b",
            status=ModelVersionStatus.ACTIVE,
        )

        with patch(
            "app.routes_models.get_model_version_manager", return_value=mock_manager
        ):
            response = client.post(
                "/api/v1/models/versions",
                json={"model_name": "model/b", "set_active": True},
            )

        assert response.status_code == 200
        assert response.json()["version_id"] == "ver-2"
