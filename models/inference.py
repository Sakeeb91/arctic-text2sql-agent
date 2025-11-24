"""
Model inference engine for SQL generation.

This module provides the core inference functionality for
generating SQL from natural language using the Text2SQL model.
"""

import time
from dataclasses import dataclass, field
from typing import Any

import torch
from transformers import PreTrainedModel, PreTrainedTokenizer

from app.config import get_settings
from app.exceptions import ModelInferenceException, TokenLimitExceededException
from app.logging_config import get_logger
from models.loader import ModelLoader

logger = get_logger(__name__)


@dataclass
class GenerationConfig:
    """Configuration for text generation."""

    max_new_tokens: int = 512
    temperature: float = 0.1
    top_p: float = 0.95
    top_k: int = 50
    do_sample: bool = False
    num_beams: int = 1
    repetition_penalty: float = 1.0
    length_penalty: float = 1.0
    early_stopping: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for model.generate()."""
        return {
            "max_new_tokens": self.max_new_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "do_sample": self.do_sample,
            "num_beams": self.num_beams,
            "repetition_penalty": self.repetition_penalty,
            "length_penalty": self.length_penalty,
            "early_stopping": self.early_stopping,
        }


@dataclass
class InferenceResult:
    """Result of model inference."""

    generated_text: str
    sql: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    inference_time_ms: float = 0.0
    confidence: float = 0.0
    raw_output: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "generated_text": self.generated_text,
            "sql": self.sql,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "inference_time_ms": self.inference_time_ms,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }


def extract_sql_from_output(text: str) -> str | None:
    """
    Extract SQL query from model output.

    The model may output SQL in various formats:
    - Plain SQL
    - ```sql ... ```
    - <sql>...</sql>
    - SQL: ...

    Args:
        text: Raw model output

    Returns:
        Extracted SQL or None if not found
    """
    import re

    text = text.strip()

    # Try to extract from code blocks
    sql_block_patterns = [
        r"```sql\s*(.*?)\s*```",  # Markdown SQL block
        r"```\s*(SELECT.*?)```",  # Generic code block with SELECT
        r"<sql>(.*?)</sql>",  # XML-style tags
        r"SQL:\s*(SELECT.*?)(?:\n\n|$)",  # SQL: prefix
    ]

    for pattern in sql_block_patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()

    # If the output starts with SELECT, WITH, or similar, return as-is
    if re.match(r"^\s*(SELECT|WITH|INSERT|UPDATE|DELETE)\s", text, re.IGNORECASE):
        # Take until we hit a double newline or end
        lines = []
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped and lines:
                break
            if stripped:
                lines.append(line)
        return "\n".join(lines).strip()

    # Return the whole text if it looks like SQL
    if "SELECT" in text.upper() or "FROM" in text.upper():
        return text.strip()

    return None


def calculate_confidence(
    output_ids: torch.Tensor,
    scores: tuple[torch.Tensor, ...] | None,
) -> float:
    """
    Calculate confidence score from generation scores.

    Args:
        output_ids: Generated token IDs
        scores: Tuple of score tensors from generation

    Returns:
        Confidence score between 0 and 1
    """
    if scores is None or len(scores) == 0:
        return 0.5  # Default confidence when scores unavailable

    try:
        # Calculate average probability of generated tokens
        total_log_prob = 0.0
        num_tokens = 0

        for i, score in enumerate(scores):
            if i >= len(output_ids[0]) - 1:
                break

            # Get probability of the generated token
            probs = torch.softmax(score[0], dim=-1)
            token_id = output_ids[0, i + 1] if i + 1 < len(output_ids[0]) else 0
            token_prob = probs[token_id].item()

            total_log_prob += token_prob
            num_tokens += 1

        if num_tokens > 0:
            avg_prob = total_log_prob / num_tokens
            return min(max(avg_prob, 0.0), 1.0)

        return 0.5

    except Exception as e:
        logger.warning("confidence_calculation_failed", error=str(e))
        return 0.5


class InferenceEngine:
    """
    Engine for running model inference.

    Usage:
        engine = InferenceEngine(model_loader)
        result = await engine.generate(prompt)
        print(result.sql)
    """

    def __init__(
        self,
        model_loader: ModelLoader,
        default_config: GenerationConfig | None = None,
    ) -> None:
        """
        Initialize inference engine.

        Args:
            model_loader: Loaded model loader instance
            default_config: Default generation configuration
        """
        self._loader = model_loader
        self._default_config = default_config or GenerationConfig()

        settings = get_settings()
        self._max_input_length = 4096
        self._min_confidence = settings.agent.min_confidence

    @property
    def model(self) -> PreTrainedModel:
        """Get the model."""
        return self._loader.model

    @property
    def tokenizer(self) -> PreTrainedTokenizer:
        """Get the tokenizer."""
        return self._loader.tokenizer

    async def generate(
        self,
        prompt: str,
        config: GenerationConfig | None = None,
        extract_sql: bool = True,
    ) -> InferenceResult:
        """
        Generate text from prompt.

        Args:
            prompt: Input prompt for generation
            config: Generation configuration (uses default if None)
            extract_sql: Whether to extract SQL from output

        Returns:
            InferenceResult with generated text and metadata

        Raises:
            TokenLimitExceededException: If input too long
            ModelInferenceException: If generation fails
        """
        config = config or self._default_config

        logger.debug(
            "starting_inference",
            prompt_length=len(prompt),
            config=config.to_dict(),
        )

        start_time = time.perf_counter()

        try:
            # Tokenize input
            inputs = self.tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=self._max_input_length,
            )

            input_tokens = inputs["input_ids"].shape[1]

            # Check token limit
            if input_tokens >= self._max_input_length:
                raise TokenLimitExceededException(
                    max_tokens=self._max_input_length,
                    actual_tokens=input_tokens,
                )

            # Move to model device
            device = next(self.model.parameters()).device
            inputs = {k: v.to(device) for k, v in inputs.items()}

            # Generate
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    **config.to_dict(),
                    return_dict_in_generate=True,
                    output_scores=True,
                    pad_token_id=self.tokenizer.pad_token_id,
                    eos_token_id=self.tokenizer.eos_token_id,
                )

            # Decode output
            generated_ids = outputs.sequences[0, input_tokens:]
            generated_text = self.tokenizer.decode(
                generated_ids,
                skip_special_tokens=True,
            )

            output_tokens = len(generated_ids)

            # Calculate confidence
            confidence = calculate_confidence(
                outputs.sequences,
                outputs.scores if hasattr(outputs, "scores") else None,
            )

            # Extract SQL if requested
            sql = None
            if extract_sql:
                sql = extract_sql_from_output(generated_text)

            inference_time_ms = (time.perf_counter() - start_time) * 1000

            logger.info(
                "inference_complete",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                inference_time_ms=round(inference_time_ms, 2),
                confidence=round(confidence, 3),
                sql_extracted=sql is not None,
            )

            return InferenceResult(
                generated_text=generated_text,
                sql=sql,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                inference_time_ms=inference_time_ms,
                confidence=confidence,
                raw_output=generated_text,
            )

        except TokenLimitExceededException:
            raise
        except Exception as e:
            logger.error(
                "inference_failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            raise ModelInferenceException(
                message=f"Generation failed: {e}",
                details={"error": str(e)},
            ) from e

    async def generate_sql(
        self,
        prompt: str,
        config: GenerationConfig | None = None,
    ) -> str | None:
        """
        Generate SQL from prompt (convenience method).

        Args:
            prompt: Full prompt with schema and question
            config: Generation configuration

        Returns:
            Generated SQL or None if extraction failed
        """
        result = await self.generate(prompt, config, extract_sql=True)
        return result.sql


# Global inference engine
_inference_engine: InferenceEngine | None = None


async def get_inference_engine(model_loader: ModelLoader) -> InferenceEngine:
    """
    Get or create inference engine.

    Args:
        model_loader: Model loader instance

    Returns:
        InferenceEngine instance
    """
    global _inference_engine

    if _inference_engine is None:
        _inference_engine = InferenceEngine(model_loader)

    return _inference_engine
