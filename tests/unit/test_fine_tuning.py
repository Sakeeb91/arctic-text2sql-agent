"""
Tests for fine-tuning pipeline (Issue #16).
"""

import json

import pytest

from app.few_shot.embeddings import HashingEmbeddingProvider
from db.examples import ExampleStore
from db.feedback import FeedbackStatus, FeedbackStore
from models.fine_tuning import FineTuningPipeline


class TestFineTuningPipeline:
    """Tests for FineTuningPipeline."""

    @pytest.mark.asyncio
    async def test_export_dataset(self, db_manager, tmp_path) -> None:
        example_store = ExampleStore(
            db_manager=db_manager,
            embedding_provider=HashingEmbeddingProvider(dimension=64),
        )
        feedback_store = FeedbackStore(db_manager=db_manager)

        await example_store.add_example(
            natural_query="Count users",
            sql_query="SELECT COUNT(*) FROM users",
            database_id="test_db",
            verified=True,
        )

        feedback = await feedback_store.submit_feedback(
            database_id="test_db",
            natural_query="List orders",
            generated_sql="SELECT * FROM orders",
            corrected_sql="SELECT * FROM orders",
        )
        await feedback_store.update_feedback_status(
            feedback_id=feedback.feedback_id,
            status=FeedbackStatus.VERIFIED,
        )

        pipeline = FineTuningPipeline(
            example_store=example_store,
            feedback_store=feedback_store,
        )

        output_path = await pipeline.export_dataset(output_path=tmp_path)

        lines = output_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 2

        parsed = json.loads(lines[0])
        assert "prompt" in parsed
        assert "response" in parsed
