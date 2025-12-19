"""
Tests for few-shot embedding utilities (Issue #16).
"""

import math

import pytest

from app.few_shot.embeddings import HashingEmbeddingProvider, cosine_similarity


class TestHashingEmbeddingProvider:
    """Tests for hashing-based embeddings."""

    @pytest.mark.asyncio
    async def test_embeddings_are_deterministic(self) -> None:
        provider = HashingEmbeddingProvider(dimension=64)

        embeddings_a = await provider.embed_texts(["Count users by status"])
        embeddings_b = await provider.embed_texts(["Count users by status"])

        assert embeddings_a == embeddings_b
        assert len(embeddings_a[0]) == 64

    @pytest.mark.asyncio
    async def test_embeddings_are_normalized(self) -> None:
        provider = HashingEmbeddingProvider(dimension=64)

        embedding = (await provider.embed_texts(["Count users"]))[0]
        norm = math.sqrt(sum(value * value for value in embedding))

        assert pytest.approx(norm, abs=1e-6) == 1.0


def test_cosine_similarity_identity() -> None:
    vector = [1.0, 0.0, 0.0]
    assert cosine_similarity(vector, vector) == pytest.approx(1.0)
