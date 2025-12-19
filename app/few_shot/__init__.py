"""
Few-shot learning utilities (Issue #16).
"""

from app.few_shot.embeddings import (
    EmbeddingProvider,
    HashingEmbeddingProvider,
    ModelEmbeddingProvider,
    cosine_similarity,
    get_embedding_provider,
)
from app.few_shot.service import (
    FewShotService,
    get_few_shot_service,
    reset_few_shot_service,
)

__all__ = [
    "EmbeddingProvider",
    "HashingEmbeddingProvider",
    "ModelEmbeddingProvider",
    "cosine_similarity",
    "get_embedding_provider",
    "FewShotService",
    "get_few_shot_service",
    "reset_few_shot_service",
]
