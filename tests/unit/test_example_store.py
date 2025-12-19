"""
Tests for ExampleStore (Issue #16).
"""

import pytest

from app.few_shot.embeddings import HashingEmbeddingProvider
from db.examples import ExampleStore


class TestExampleStore:
    """Tests for ExampleStore operations."""

    @pytest.mark.asyncio
    async def test_add_and_get_example(self, db_manager) -> None:
        store = ExampleStore(
            db_manager=db_manager,
            embedding_provider=HashingEmbeddingProvider(dimension=64),
        )

        example = await store.add_example(
            natural_query="Count users",
            sql_query="SELECT COUNT(*) FROM users",
            database_id="test_db",
            verified=True,
        )

        fetched = await store.get_example(example.example_id)

        assert fetched.example_id == example.example_id
        assert fetched.natural_query == "Count users"
        assert fetched.verified is True

    @pytest.mark.asyncio
    async def test_get_relevant_examples(self, db_manager) -> None:
        store = ExampleStore(
            db_manager=db_manager,
            embedding_provider=HashingEmbeddingProvider(dimension=64),
        )

        example = await store.add_example(
            natural_query="Count users",
            sql_query="SELECT COUNT(*) FROM users",
            database_id="test_db",
            verified=True,
        )

        results = await store.get_relevant_examples(
            query="Count users",
            database_id="test_db",
            verified_only=True,
        )

        assert results
        assert results[0].example.example_id == example.example_id

    @pytest.mark.asyncio
    async def test_verified_filtering(self, db_manager) -> None:
        store = ExampleStore(
            db_manager=db_manager,
            embedding_provider=HashingEmbeddingProvider(dimension=64),
        )

        await store.add_example(
            natural_query="List customers",
            sql_query="SELECT * FROM customers",
            database_id="test_db",
            verified=False,
        )

        results = await store.get_relevant_examples(
            query="List customers",
            database_id="test_db",
            verified_only=True,
        )

        assert results == []
