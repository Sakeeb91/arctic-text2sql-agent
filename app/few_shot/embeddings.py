"""
Embedding utilities for few-shot example retrieval (Issue #16).

Provides lightweight hashing embeddings by default, with an optional
model-based embedding provider that reuses the loaded Text2SQL model.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Protocol

import torch

from app.config import get_settings
from app.logging_config import get_logger
from models.loader import ModelLoader, get_model_loader

logger = get_logger(__name__)


class EmbeddingProvider(Protocol):
    """Protocol for text embedding providers."""

    @property
    def dimension(self) -> int:
        """Return embedding dimensionality."""
        raise NotImplementedError

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for input texts."""
        raise NotImplementedError


def cosine_similarity(vector_a: list[float], vector_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not vector_a or not vector_b or len(vector_a) != len(vector_b):
        return 0.0
    dot_product = sum(a * b for a, b in zip(vector_a, vector_b, strict=False))
    return float(dot_product)


def _normalize(vector: list[float]) -> list[float]:
    """Normalize vector to unit length."""
    if not vector:
        return vector
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _stable_hash(token: str) -> int:
    """Generate a stable hash for token indexing."""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


@dataclass
class HashingEmbeddingProvider:
    """
    Lightweight hashing-based embedding provider.

    Uses token hashing to create a normalized bag-of-words vector.
    """

    dimension: int = 256
    lowercase: bool = True

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using hashed bag-of-words."""
        return [self._embed_single(text) for text in texts]

    def _embed_single(self, text: str) -> list[float]:
        if self.lowercase:
            text = text.lower()

        tokens = re.findall(r"[a-z0-9_]+", text)
        vector = [0.0] * self.dimension

        for token in tokens:
            index = _stable_hash(token) % self.dimension
            vector[index] += 1.0

        return _normalize(vector)


class ModelEmbeddingProvider:
    """
    Model-based embedding provider.

    Uses the Text2SQL model's input embeddings to compute mean-pooled vectors.
    """

    def __init__(
        self,
        model_loader: ModelLoader | None = None,
        max_length: int = 256,
    ) -> None:
        self._model_loader = model_loader
        self._max_length = max_length

    @property
    def dimension(self) -> int:
        """Return embedding dimensionality."""
        if not self._model_loader or not self._model_loader.is_loaded:
            return 0
        return int(self._model_loader.model.get_input_embeddings().weight.shape[1])

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using the loaded model's token embeddings."""
        loader = await self._ensure_loader()
        tokenizer = loader.tokenizer
        model = loader.model

        inputs = tokenizer(
            texts,
            return_tensors="pt",
            truncation=True,
            max_length=self._max_length,
            padding=True,
        )

        input_ids = inputs["input_ids"].to(model.device)
        embeddings = model.get_input_embeddings()(input_ids)

        if tokenizer.pad_token_id is None:
            mask = torch.ones_like(input_ids, dtype=torch.float32)
        else:
            mask = (input_ids != tokenizer.pad_token_id).float()

        masked_embeddings = embeddings * mask.unsqueeze(-1)
        lengths = mask.sum(dim=1).clamp(min=1)
        pooled = masked_embeddings.sum(dim=1) / lengths.unsqueeze(-1)

        vectors = pooled.detach().cpu().tolist()
        return [_normalize(vector) for vector in vectors]

    async def _ensure_loader(self) -> ModelLoader:
        if self._model_loader is None:
            self._model_loader = await get_model_loader()

        if not self._model_loader.is_loaded:
            await self._model_loader.load()

        return self._model_loader


def get_embedding_provider() -> EmbeddingProvider:
    """Create an embedding provider based on settings."""
    settings = get_settings()
    strategy = settings.few_shot.embedding_strategy

    if strategy == "model":
        logger.info("embedding_provider_selected", strategy="model")
        return ModelEmbeddingProvider(max_length=settings.few_shot.embedding_max_length)

    logger.info("embedding_provider_selected", strategy="hash")
    return HashingEmbeddingProvider(dimension=settings.few_shot.embedding_dim)
