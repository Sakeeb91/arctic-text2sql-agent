"""
Unit tests for feedback routes (Issue #16).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes_feedback import router
from db.feedback import FeedbackRecord, FeedbackStatus


@pytest.fixture
def mock_store() -> MagicMock:
    """Create mock feedback store."""
    store = MagicMock()
    store.submit_feedback = AsyncMock()
    store.get_feedback = AsyncMock()
    store.list_feedback = AsyncMock()
    store.update_feedback_status = AsyncMock()
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


class TestFeedbackRoutes:
    """Tests for feedback endpoints."""

    def test_submit_feedback(self, client: TestClient, mock_store: MagicMock) -> None:
        feedback = FeedbackRecord(
            feedback_id="fb-123",
            database_id="test_db",
            natural_query="Count users",
            generated_sql="SELECT COUNT(*) FROM users",
            corrected_sql="SELECT COUNT(*) FROM users",
            rating=5,
            status=FeedbackStatus.PENDING,
        )
        mock_store.submit_feedback.return_value = feedback

        with patch(
            "app.routes_feedback.get_feedback_store", return_value=mock_store
        ):
            response = client.post(
                "/api/v1/feedback",
                json={
                    "natural_query": "Count users",
                    "database_id": "test_db",
                    "generated_sql": "SELECT COUNT(*) FROM users",
                    "corrected_sql": "SELECT COUNT(*) FROM users",
                    "rating": 5,
                },
            )

        assert response.status_code == 200
        assert response.json()["feedback_id"] == "fb-123"

    def test_update_feedback_status(
        self, client: TestClient, mock_store: MagicMock
    ) -> None:
        feedback = FeedbackRecord(
            feedback_id="fb-456",
            database_id="test_db",
            natural_query="List orders",
            status=FeedbackStatus.VERIFIED,
        )
        mock_store.update_feedback_status.return_value = feedback

        with patch(
            "app.routes_feedback.get_feedback_store", return_value=mock_store
        ):
            response = client.patch(
                "/api/v1/feedback/fb-456/status",
                json={"status": "verified"},
            )

        assert response.status_code == 200
        assert response.json()["status"] == "verified"
