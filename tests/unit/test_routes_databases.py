"""
Unit tests for database management API routes (Issue #14: Multi-Database Support).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes_databases import router
from db.registry import (
    DatabaseConfig,
    DatabaseHealth,
    DatabaseRegistry,
    DatabaseStatus,
    RegisteredDatabase,
)


@pytest.fixture
def mock_registry() -> MagicMock:
    """Create mock database registry."""
    registry = MagicMock(spec=DatabaseRegistry)
    registry.database_count = 0
    registry.database_ids = []
    registry._databases = {}
    return registry


@pytest.fixture
def mock_settings() -> MagicMock:
    """Create mock settings."""
    settings = MagicMock()
    settings.multi_database.max_databases = 50
    return settings


@pytest.fixture
def app(mock_registry: MagicMock, mock_settings: MagicMock) -> FastAPI:
    """Create test FastAPI app."""
    from app.error_handlers import setup_exception_handlers
    from app.security import limiter

    test_app = FastAPI()
    test_app.state.limiter = limiter
    setup_exception_handlers(test_app)
    test_app.include_router(router)

    return test_app


@pytest.fixture
def client(app: FastAPI, auth_headers: dict[str, str]) -> TestClient:
    """Create test client."""
    client = TestClient(app)
    client.headers.update(auth_headers)
    return client


class TestDatabaseRegisterRequest:
    """Tests for DatabaseRegisterRequest model validation."""

    def test_valid_request(self) -> None:
        """Test valid registration request."""
        from app.routes_databases import DatabaseRegisterRequest

        request = DatabaseRegisterRequest(
            database_id="test_db",
            connection_string="postgresql://localhost/db",
            display_name="Test Database",
        )

        assert request.database_id == "test_db"
        assert request.read_only is True

    def test_invalid_database_id(self) -> None:
        """Test invalid database ID is rejected."""
        from pydantic import ValidationError

        from app.routes_databases import DatabaseRegisterRequest

        with pytest.raises(ValidationError):
            DatabaseRegisterRequest(
                database_id="123-invalid",  # Must start with letter
                connection_string="postgresql://localhost/db",
            )

    def test_dialect_validation(self) -> None:
        """Test dialect validation."""
        from app.routes_databases import DatabaseRegisterRequest

        # Valid dialect
        request = DatabaseRegisterRequest(
            database_id="test",
            connection_string="postgresql://localhost/db",
            dialect="postgresql",
        )
        assert request.dialect == "postgresql"

    def test_invalid_dialect(self) -> None:
        """Test invalid dialect is rejected."""
        from pydantic import ValidationError

        from app.routes_databases import DatabaseRegisterRequest

        with pytest.raises(ValidationError):
            DatabaseRegisterRequest(
                database_id="test",
                connection_string="postgresql://localhost/db",
                dialect="invalid_dialect",
            )


class TestRegisterDatabaseEndpoint:
    """Tests for POST /api/v1/databases endpoint."""

    @pytest.mark.asyncio
    async def test_register_database_success(
        self, client: TestClient, mock_registry: MagicMock, mock_settings: MagicMock
    ) -> None:
        """Test successful database registration."""
        from datetime import datetime

        # Setup mock registered database
        mock_config = DatabaseConfig(
            database_id="test_db",
            connection_string="sqlite:///test.db",
        )
        mock_health = DatabaseHealth(
            database_id="test_db",
            status=DatabaseStatus.CONNECTED,
        )
        mock_registered = MagicMock(spec=RegisteredDatabase)
        mock_registered.config = mock_config
        mock_registered.health = mock_health
        mock_registered.registered_at = datetime.now()

        mock_registry.register_database = AsyncMock(return_value=mock_registered)

        with (
            patch(
                "app.routes_databases.get_database_registry", return_value=mock_registry
            ),
            patch("app.routes_databases.get_settings", return_value=mock_settings),
        ):
            response = client.post(
                "/api/v1/databases",
                json={
                    "database_id": "test_db",
                    "connection_string": "sqlite:///test.db",
                },
            )

        assert response.status_code == 201
        data = response.json()
        assert data["database_id"] == "test_db"

    @pytest.mark.asyncio
    async def test_register_duplicate_database(
        self, client: TestClient, mock_registry: MagicMock, mock_settings: MagicMock
    ) -> None:
        """Test registering duplicate database returns 409."""
        from app.exceptions import DatabaseAlreadyExistsException

        mock_registry.register_database = AsyncMock(
            side_effect=DatabaseAlreadyExistsException("test_db")
        )

        with (
            patch(
                "app.routes_databases.get_database_registry", return_value=mock_registry
            ),
            patch("app.routes_databases.get_settings", return_value=mock_settings),
        ):
            response = client.post(
                "/api/v1/databases",
                json={
                    "database_id": "test_db",
                    "connection_string": "sqlite:///test.db",
                },
            )

        assert response.status_code == 409


class TestListDatabasesEndpoint:
    """Tests for GET /api/v1/databases endpoint."""

    @pytest.mark.asyncio
    async def test_list_databases_empty(
        self, client: TestClient, mock_registry: MagicMock
    ) -> None:
        """Test listing databases when empty."""
        mock_registry.list_databases = MagicMock(return_value=[])

        with patch(
            "app.routes_databases.get_database_registry", return_value=mock_registry
        ):
            response = client.get("/api/v1/databases")

        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 0
        assert data["databases"] == []

    @pytest.mark.asyncio
    async def test_list_databases_with_filter(
        self, client: TestClient, mock_registry: MagicMock
    ) -> None:
        """Test listing databases with dialect filter."""
        mock_registry.list_databases = MagicMock(return_value=[])

        with patch(
            "app.routes_databases.get_database_registry", return_value=mock_registry
        ):
            response = client.get("/api/v1/databases?dialect=postgresql")

        assert response.status_code == 200
        mock_registry.list_databases.assert_called_once()


class TestGetDatabaseEndpoint:
    """Tests for GET /api/v1/databases/{database_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_database_success(
        self, client: TestClient, mock_registry: MagicMock
    ) -> None:
        """Test getting database details."""
        from datetime import datetime

        mock_config = DatabaseConfig(
            database_id="my_db",
            connection_string="sqlite:///test.db",
        )
        mock_health = DatabaseHealth(
            database_id="my_db",
            status=DatabaseStatus.CONNECTED,
        )
        mock_registered = MagicMock(spec=RegisteredDatabase)
        mock_registered.config = mock_config
        mock_registered.health = mock_health
        mock_registered.registered_at = datetime.now()

        mock_registry.get_database = MagicMock(return_value=mock_registered)

        with patch(
            "app.routes_databases.get_database_registry", return_value=mock_registry
        ):
            response = client.get("/api/v1/databases/my_db")

        assert response.status_code == 200
        data = response.json()
        assert data["database_id"] == "my_db"

    @pytest.mark.asyncio
    async def test_get_database_not_found(
        self, client: TestClient, mock_registry: MagicMock
    ) -> None:
        """Test getting non-existent database returns 404."""
        from app.exceptions import DatabaseNotRegisteredException

        mock_registry.get_database = MagicMock(
            side_effect=DatabaseNotRegisteredException("unknown")
        )

        with patch(
            "app.routes_databases.get_database_registry", return_value=mock_registry
        ):
            response = client.get("/api/v1/databases/unknown")

        assert response.status_code == 404


class TestDatabaseHealthEndpoint:
    """Tests for GET /api/v1/databases/{database_id}/health endpoint."""

    @pytest.mark.asyncio
    async def test_health_check_success(
        self, client: TestClient, mock_registry: MagicMock
    ) -> None:
        """Test health check returns health status."""
        from datetime import datetime

        mock_health = DatabaseHealth(
            database_id="test_db",
            status=DatabaseStatus.CONNECTED,
            last_check=datetime.now(),
            latency_ms=5.0,
        )

        mock_registry.health_check = AsyncMock(return_value=mock_health)

        with patch(
            "app.routes_databases.get_database_registry", return_value=mock_registry
        ):
            response = client.get("/api/v1/databases/test_db/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "connected"
        assert data["healthy"] is True


class TestUnregisterDatabaseEndpoint:
    """Tests for DELETE /api/v1/databases/{database_id} endpoint."""

    @pytest.mark.asyncio
    async def test_unregister_success(
        self, client: TestClient, mock_registry: MagicMock
    ) -> None:
        """Test successful database unregistration."""
        mock_registry.unregister_database = AsyncMock()

        with patch(
            "app.routes_databases.get_database_registry", return_value=mock_registry
        ):
            response = client.delete("/api/v1/databases/test_db")

        assert response.status_code == 200
        data = response.json()
        assert data["database_id"] == "test_db"

    @pytest.mark.asyncio
    async def test_unregister_default_protected(
        self, client: TestClient, mock_registry: MagicMock
    ) -> None:
        """Test that default database cannot be unregistered."""
        with patch(
            "app.routes_databases.get_database_registry", return_value=mock_registry
        ):
            response = client.delete("/api/v1/databases/default")

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_unregister_not_found(
        self, client: TestClient, mock_registry: MagicMock
    ) -> None:
        """Test unregistering non-existent database returns 404."""
        from app.exceptions import DatabaseNotRegisteredException

        mock_registry.unregister_database = AsyncMock(
            side_effect=DatabaseNotRegisteredException("unknown")
        )

        with patch(
            "app.routes_databases.get_database_registry", return_value=mock_registry
        ):
            response = client.delete("/api/v1/databases/unknown")

        assert response.status_code == 404


class TestHealthCheckAllEndpoint:
    """Tests for GET /api/v1/databases/health/all endpoint."""

    @pytest.mark.asyncio
    async def test_health_check_all(
        self, client: TestClient, mock_registry: MagicMock
    ) -> None:
        """Test health check all databases."""
        from datetime import datetime

        mock_health1 = DatabaseHealth(
            database_id="db1",
            status=DatabaseStatus.CONNECTED,
            last_check=datetime.now(),
        )
        mock_health2 = DatabaseHealth(
            database_id="db2",
            status=DatabaseStatus.ERROR,
            last_check=datetime.now(),
            error_message="Connection refused",
        )

        mock_registry.health_check_all = AsyncMock(
            return_value={"db1": mock_health1, "db2": mock_health2}
        )

        with patch(
            "app.routes_databases.get_database_registry", return_value=mock_registry
        ):
            response = client.get("/api/v1/databases/health/all")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["healthy"] == 1
        assert data["unhealthy"] == 1
