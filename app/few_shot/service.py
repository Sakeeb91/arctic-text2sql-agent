"""
Few-shot example service for prompt integration (Issue #16).
"""

from __future__ import annotations

from app.config import get_settings
from app.logging_config import get_logger
from db.examples import ExampleRecord, ExampleStore, get_example_store
from models.prompts import FewShotExample

logger = get_logger(__name__)


class FewShotService:
    """Service for retrieving few-shot examples for prompts."""

    def __init__(self, example_store: ExampleStore) -> None:
        self._store = example_store
        self._settings = get_settings()

    def should_use_examples(self, attempt: int) -> bool:
        """Return True if examples should be used for this attempt."""
        if not self._settings.few_shot.enabled:
            return False
        if attempt == 0:
            return self._settings.few_shot.use_on_first_attempt
        return self._settings.few_shot.use_on_retry

    async def get_prompt_examples(
        self,
        natural_query: str,
        database_id: str | None,
        max_examples: int | None = None,
        verified_only: bool | None = None,
    ) -> list[FewShotExample]:
        """Retrieve relevant examples as prompt-friendly objects."""
        if not self._settings.few_shot.enabled:
            return []

        max_examples = max_examples or self._settings.few_shot.max_examples
        verified_only = (
            verified_only
            if verified_only is not None
            else self._settings.few_shot.verified_only
        )

        results = await self._store.get_relevant_examples(
            query=natural_query,
            database_id=database_id,
            k=max_examples,
            verified_only=verified_only,
        )

        examples = [self._to_few_shot_example(item.example) for item in results]

        logger.debug(
            "few_shot_examples_retrieved",
            query_length=len(natural_query),
            database_id=database_id,
            count=len(examples),
        )

        return examples

    @staticmethod
    def _to_few_shot_example(example: ExampleRecord) -> FewShotExample:
        explanation = None
        if example.metadata:
            explanation = example.metadata.get("explanation")

        return FewShotExample(
            question=example.natural_query,
            sql=example.sql_query,
            explanation=explanation,
        )


_few_shot_service: FewShotService | None = None


async def get_few_shot_service() -> FewShotService:
    """Get or create the global few-shot service."""
    global _few_shot_service

    if _few_shot_service is None:
        example_store = await get_example_store()
        _few_shot_service = FewShotService(example_store)

    return _few_shot_service


def reset_few_shot_service() -> None:
    """Reset the global few-shot service instance."""
    global _few_shot_service
    _few_shot_service = None
