"""
Fine-tuning pipeline utilities (Issue #16).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorForLanguageModeling,
    Trainer,
    TrainingArguments,
)

from app.config import get_settings
from app.exceptions import FineTuningException
from app.logging_config import get_logger
from models.versioning import ModelVersion, get_model_version_manager

if TYPE_CHECKING:
    from db.examples import ExampleRecord, ExampleStore
    from db.feedback import FeedbackRecord, FeedbackStore

logger = get_logger(__name__)


@dataclass
class FineTuningExample:
    """Training example for fine-tuning."""

    prompt: str
    response: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "prompt": self.prompt,
            "response": self.response,
            "metadata": self.metadata,
        }


class _PromptDataset(torch.utils.data.Dataset):
    """Torch dataset for prompt + response training."""

    def __init__(
        self,
        texts: list[str],
        tokenizer: Any,
        max_length: int,
    ) -> None:
        self._encodings = tokenizer(
            texts,
            truncation=True,
            padding="max_length",
            max_length=max_length,
            return_tensors="pt",
        )

    def __len__(self) -> int:
        return int(self._encodings["input_ids"].shape[0])

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        item = {key: tensor[idx] for key, tensor in self._encodings.items()}
        item["labels"] = item["input_ids"].clone()
        return item


class FineTuningPipeline:
    """Pipeline for exporting and training fine-tuning datasets."""

    def __init__(
        self,
        example_store: ExampleStore | None = None,
        feedback_store: FeedbackStore | None = None,
    ) -> None:
        self._settings = get_settings()
        self._example_store = example_store
        self._feedback_store = feedback_store

    async def build_examples(
        self,
        include_feedback: bool | None = None,
        max_examples: int | None = None,
    ) -> list[FineTuningExample]:
        """Build fine-tuning examples from stores."""
        include_feedback = (
            include_feedback
            if include_feedback is not None
            else self._settings.fine_tuning.include_feedback
        )
        max_examples = max_examples or self._settings.fine_tuning.max_examples

        example_store = await self._get_example_store()
        feedback_store = await self._get_feedback_store()

        examples: list[FineTuningExample] = []

        stored_examples = await example_store.list_examples(
            verified_only=True,
            limit=max_examples,
        )
        examples.extend([self._from_example(record) for record in stored_examples])

        if include_feedback:
            from db.feedback import FeedbackStatus

            feedback_entries = await feedback_store.list_feedback(
                status=FeedbackStatus.VERIFIED,
                limit=max_examples,
            )
            examples.extend(
                [
                    self._from_feedback(entry)
                    for entry in feedback_entries
                    if entry.corrected_sql
                ]
            )

        return examples[:max_examples]

    async def export_dataset(
        self,
        output_path: str | Path | None = None,
        include_feedback: bool | None = None,
        max_examples: int | None = None,
    ) -> Path:
        """Export dataset to a JSONL file."""
        examples = await self.build_examples(
            include_feedback=include_feedback,
            max_examples=max_examples,
        )

        path = self._resolve_output_path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", encoding="utf-8") as handle:
            for example in examples:
                handle.write(json.dumps(example.to_dict()) + "\n")

        logger.info(
            "fine_tuning_dataset_exported",
            path=str(path),
            examples=len(examples),
        )

        return path

    async def train(
        self,
        model_name: str | None = None,
        output_dir: str | Path | None = None,
        register_version: bool = False,
    ) -> dict[str, Any]:
        """Run a fine-tuning job using exported examples."""
        if not self._settings.fine_tuning.enabled:
            raise FineTuningException(
                message="Fine-tuning pipeline is disabled. Set FINETUNE_ENABLED=true."
            )

        examples = await self.build_examples()
        if not examples:
            raise FineTuningException(message="No verified examples available")

        model_name = model_name or self._settings.huggingface.model_name
        output_dir = Path(
            output_dir or self._settings.fine_tuning.output_dir
        ).resolve()

        texts = [f"{example.prompt} {example.response}".strip() for example in examples]

        tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            token=self._settings.huggingface.token or None,
            trust_remote_code=True,
        )
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            token=self._settings.huggingface.token or None,
            trust_remote_code=True,
        )

        dataset = _PromptDataset(
            texts=texts,
            tokenizer=tokenizer,
            max_length=self._settings.fine_tuning.max_seq_length,
        )

        training_args = TrainingArguments(
            output_dir=str(output_dir),
            num_train_epochs=self._settings.fine_tuning.train_epochs,
            per_device_train_batch_size=self._settings.fine_tuning.batch_size,
            learning_rate=self._settings.fine_tuning.learning_rate,
            logging_steps=10,
            save_steps=500,
            save_total_limit=2,
            fp16=torch.cuda.is_available(),
        )

        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=dataset,
            data_collator=DataCollatorForLanguageModeling(
                tokenizer=tokenizer, mlm=False
            ),
        )

        trainer.train()
        trainer.save_model(str(output_dir))

        result = {
            "output_dir": str(output_dir),
            "examples": len(examples),
            "model_name": model_name,
        }

        if register_version:
            version = await self.register_model_version(
                model_name=str(output_dir),
                base_model=model_name,
                metrics={"training_examples": len(examples)},
                description="Fine-tuned Text2SQL model",
                tags=["fine-tuned"],
                set_active=True,
            )
            result["version_id"] = version.version_id

        logger.info("fine_tuning_complete", **result)
        return result

    async def register_model_version(
        self,
        model_name: str,
        base_model: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        metrics: dict[str, Any] | None = None,
        set_active: bool = False,
    ) -> ModelVersion:
        """Register a fine-tuned model version."""
        manager = await get_model_version_manager()
        return await manager.register_version(
            model_name=model_name,
            base_model=base_model,
            description=description,
            tags=tags,
            metrics=metrics,
            set_active=set_active,
        )

    def _format_prompt(self, question: str) -> str:
        return f"Question: {question}\nSQL:"

    def _from_example(self, example: ExampleRecord) -> FineTuningExample:
        return FineTuningExample(
            prompt=self._format_prompt(example.natural_query),
            response=example.sql_query,
            metadata={
                "source": "example_store",
                "database_id": example.database_id,
                "example_id": example.example_id,
            },
        )

    def _from_feedback(self, feedback: FeedbackRecord) -> FineTuningExample:
        return FineTuningExample(
            prompt=self._format_prompt(feedback.natural_query),
            response=feedback.corrected_sql or feedback.generated_sql or "",
            metadata={
                "source": "feedback",
                "database_id": feedback.database_id,
                "feedback_id": feedback.feedback_id,
                "rating": feedback.rating,
            },
        )

    def _resolve_output_path(self, output_path: str | Path | None) -> Path:
        if output_path is None:
            output_dir = Path(self._settings.fine_tuning.output_dir)
            return output_dir / f"{self._settings.fine_tuning.dataset_name}.jsonl"

        path = Path(output_path)
        if path.suffix == "":
            path.mkdir(parents=True, exist_ok=True)
            return path / f"{self._settings.fine_tuning.dataset_name}.jsonl"
        return path

    async def _get_example_store(self) -> ExampleStore:
        if self._example_store is None:
            from db.examples import get_example_store

            self._example_store = await get_example_store()
        return self._example_store

    async def _get_feedback_store(self) -> FeedbackStore:
        if self._feedback_store is None:
            from db.feedback import get_feedback_store

            self._feedback_store = await get_feedback_store()
        return self._feedback_store


_fine_tuning_pipeline: FineTuningPipeline | None = None


async def get_fine_tuning_pipeline() -> FineTuningPipeline:
    """Get or create the global fine-tuning pipeline."""
    global _fine_tuning_pipeline

    if _fine_tuning_pipeline is None:
        _fine_tuning_pipeline = FineTuningPipeline()

    return _fine_tuning_pipeline


def reset_fine_tuning_pipeline() -> None:
    """Reset the global fine-tuning pipeline instance."""
    global _fine_tuning_pipeline
    _fine_tuning_pipeline = None
