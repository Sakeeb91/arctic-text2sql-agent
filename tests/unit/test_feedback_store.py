"""
Tests for FeedbackStore (Issue #16).
"""

import pytest

from db.feedback import FeedbackStatus, FeedbackStore


class TestFeedbackStore:
    """Tests for feedback store operations."""

    @pytest.mark.asyncio
    async def test_submit_and_get_feedback(self, db_manager) -> None:
        store = FeedbackStore(db_manager=db_manager)

        feedback = await store.submit_feedback(
            database_id="test_db",
            natural_query="Count users",
            generated_sql="SELECT COUNT(*) FROM users",
            corrected_sql="SELECT COUNT(*) FROM users",
            rating=5,
            comment="Looks good",
        )

        fetched = await store.get_feedback(feedback.feedback_id)

        assert fetched.feedback_id == feedback.feedback_id
        assert fetched.rating == 5

    @pytest.mark.asyncio
    async def test_update_feedback_status(self, db_manager) -> None:
        store = FeedbackStore(db_manager=db_manager)

        feedback = await store.submit_feedback(
            database_id="test_db",
            natural_query="List orders",
            generated_sql="SELECT * FROM orders",
        )

        updated = await store.update_feedback_status(
            feedback_id=feedback.feedback_id,
            status=FeedbackStatus.VERIFIED,
        )

        assert updated.status == FeedbackStatus.VERIFIED
