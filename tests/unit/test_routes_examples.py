"""
Unit tests for few-shot example routes (Issue #16).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes_examples import router
from db.examples import ExampleRecord, ExampleSearchResult


@pytest.fixture
def mock_store() -> MagicMock:
    """Create mock example store."""
    store = MagicMock()
    store.add_example = AsyncMock()
    store.get_example = AsyncMock()
    store.list_examples = AsyncMock()
    store.get_relevant_examples = AsyncMock()
    store.update_example = AsyncMock()
    store.delete_example = AsyncMock()
    return store


@pytest.fixture
def app(mock_store: MagicMock) -> FastAPI:
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


class TestExampleRoutes:
    """Tests for example repository endpoints."""

    def test_create_example(self, client: TestClient, mock_store: MagicMock) -> None:
        example = ExampleRecord(
            example_id="ex-123",
            natural_query="Count users",
            sql_query="SELECT COUNT(*) FROM users",
            database_id="test_db",
            verified=True,
        )
        mock_store.add_example.return_value = example

        with patch("app.routes_examples.get_example_store", return_value=mock_store):
            response = client.post(
                "/api/v1/examples",
                json={
                    "natural_query": "Count users",
                    "sql_query": "SELECT COUNT(*) FROM users",
                    "database_id": "test_db",
                    "verified": True,
                },
            )

        assert response.status_code == 200
        assert response.json()["example_id"] == "ex-123"

    def test_search_examples(self, client: TestClient, mock_store: MagicMock) -> None:
        example = ExampleRecord(
            example_id="ex-456",
            natural_query="List orders",
            sql_query="SELECT * FROM orders",
            database_id="test_db",
            verified=True,
        )
        mock_store.get_relevant_examples.return_value = [
            ExampleSearchResult(example=example, similarity=0.9)
        ]

        with patch("app.routes_examples.get_example_store", return_value=mock_store):
            response = client.post(
                "/api/v1/examples/search",
                json={
                    "query": "List orders",
                    "database_id": "test_db",
                    "k": 1,
                    "verified_only": True,
                },
            )

        assert response.status_code == 200
        assert response.json()["results"][0]["example"]["example_id"] == "ex-456"
