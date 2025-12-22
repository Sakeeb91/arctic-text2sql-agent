"""
Unit tests for schema routes (Issue #31: Multi-DB registry wiring).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import router
from db.schema import SchemaInfo


@pytest.fixture
def app() -> FastAPI:
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


class TestSchemaRoutes:
    """Tests for schema registration endpoints."""

    def test_register_schema_registers_and_caches(
        self,
        client: TestClient,
    ) -> None:
        """Ensure schema registration wires registry and cache."""
        schema_info = SchemaInfo(
            database_id="analytics",
            dialect="postgresql",
            tables=[],
        )

        mock_introspector = MagicMock()
        mock_introspector.get_schema = AsyncMock(return_value=schema_info)
        mock_introspector.serialize_for_prompt.return_value = "schema"

        registry = MagicMock()
        registry.database_count = 0
        registry.register_database = AsyncMock()
        registered = MagicMock()
        registered.engine = MagicMock()
        registry.register_database.return_value = registered

        settings = MagicMock()
        settings.multi_database.enabled = True
        settings.multi_database.max_databases = 50
        settings.multi_database.default_pool_size = 5
        settings.multi_database.default_max_overflow = 10
        settings.multi_database.default_pool_timeout = 30
        settings.multi_database.allow_mutations = False
        settings.multi_database.require_connection_test = True
        settings.cache.enabled = True

        with (
            patch("app.routes.get_settings", return_value=settings),
            patch("db.registry.get_database_registry", return_value=registry),
            patch("db.schema.SchemaIntrospector", return_value=mock_introspector),
            patch("app.cache.cache_schema", new_callable=AsyncMock) as cache_schema,
        ):
            response = client.post(
                "/api/v1/schema/register",
                json={
                    "database_id": "analytics",
                    "connection_string": "sqlite:///test.db",
                    "dialect": "postgresql",
                },
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "registered"
        assert payload["database_id"] == "analytics"
        assert payload["dialect"] == "postgresql"

        registry.register_database.assert_awaited_once()
        args, kwargs = registry.register_database.call_args
        config = args[0]
        assert config.database_id == "analytics"
        assert config.connection_string == "sqlite:///test.db"
        assert config.pool_size == 5
        assert kwargs["test_connection"] is True

        mock_introspector.get_schema.assert_awaited_once_with("analytics")
        cache_schema.assert_awaited_once()
