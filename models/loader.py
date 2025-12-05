"""
HuggingFace model loading and management.

This module provides efficient model loading with:
- Lazy loading and caching
- Quantization support (8-bit, 4-bit)
- Device management (CPU/GPU/MPS)
- Model warmup
"""

import gc
from dataclasses import dataclass
from typing import Any, cast

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    PreTrainedModel,
    PreTrainedTokenizer,
)

from app.config import get_settings
from app.exceptions import ModelLoadException
from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ModelInfo:
    """Information about a loaded model."""

    model_name: str
    device: str
    quantization: str | None
    loaded: bool
    memory_usage_mb: float | None = None
    max_length: int = 4096

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "model_name": self.model_name,
            "device": self.device,
            "quantization": self.quantization,
            "loaded": self.loaded,
            "memory_usage_mb": self.memory_usage_mb,
            "max_length": self.max_length,
        }


def get_optimal_device() -> str:
    """
    Determine the optimal device for model inference.

    Returns:
        str: Device identifier (cuda, mps, or cpu)
    """
    if torch.cuda.is_available():
        return "cuda"
    elif torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def get_memory_usage() -> float | None:
    """
    Get current GPU memory usage in MB.

    Returns:
        Memory usage in MB or None if not available
    """
    if torch.cuda.is_available():
        return torch.cuda.memory_allocated() / 1024 / 1024
    return None


class ModelLoader:
    """
    Manages HuggingFace model loading with optimization.

    Usage:
        loader = ModelLoader()
        model, tokenizer = await loader.load()
        # Use model for inference
        loader.unload()
    """

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        enable_8bit: bool | None = None,
        enable_4bit: bool | None = None,
        hf_token: str | None = None,
    ) -> None:
        """
        Initialize model loader.

        Args:
            model_name: HuggingFace model identifier
            device: Device to load model on (auto, cuda, cpu, mps)
            enable_8bit: Enable 8-bit quantization
            enable_4bit: Enable 4-bit quantization
            hf_token: HuggingFace API token
        """
        settings = get_settings()

        self._model_name = model_name or settings.huggingface.model_name
        self._device = device or settings.huggingface.device
        self._enable_8bit = (
            enable_8bit
            if enable_8bit is not None
            else settings.huggingface.enable_8bit_quantization
        )
        self._enable_4bit = (
            enable_4bit
            if enable_4bit is not None
            else settings.huggingface.enable_4bit_quantization
        )
        self._hf_token = hf_token or settings.huggingface.token

        self._model: PreTrainedModel | None = None
        self._tokenizer: PreTrainedTokenizer | None = None
        self._is_loaded = False

    @property
    def is_loaded(self) -> bool:
        """Check if model is loaded."""
        return self._is_loaded

    @property
    def model(self) -> PreTrainedModel:
        """Get loaded model."""
        if not self._model:
            raise ModelLoadException(
                model_name=self._model_name,
                reason="Model not loaded. Call load() first.",
            )
        return self._model

    @property
    def tokenizer(self) -> PreTrainedTokenizer:
        """Get loaded tokenizer."""
        if not self._tokenizer:
            raise ModelLoadException(
                model_name=self._model_name,
                reason="Tokenizer not loaded. Call load() first.",
            )
        return self._tokenizer

    def get_info(self) -> ModelInfo:
        """Get model information."""
        device = self._get_actual_device()
        quantization = None
        if self._enable_4bit:
            quantization = "4-bit"
        elif self._enable_8bit:
            quantization = "8-bit"

        return ModelInfo(
            model_name=self._model_name,
            device=device,
            quantization=quantization,
            loaded=self._is_loaded,
            memory_usage_mb=get_memory_usage(),
        )

    def _get_actual_device(self) -> str:
        """Resolve 'auto' device to actual device."""
        if self._device == "auto":
            return get_optimal_device()
        return self._device

    async def load(self) -> tuple[PreTrainedModel, PreTrainedTokenizer]:
        """
        Load model and tokenizer.

        Returns:
            Tuple of (model, tokenizer)

        Raises:
            ModelLoadException: If loading fails
        """
        if self._is_loaded:
            return self._model, self._tokenizer  # type: ignore

        logger.info(
            "loading_model",
            model_name=self._model_name,
            device=self._device,
            enable_8bit=self._enable_8bit,
            enable_4bit=self._enable_4bit,
        )

        try:
            # Load tokenizer
            self._tokenizer = await self._load_tokenizer()

            # Load model with appropriate settings
            self._model = await self._load_model()

            self._is_loaded = True

            logger.info(
                "model_loaded",
                model_name=self._model_name,
                device=self._get_actual_device(),
                memory_mb=get_memory_usage(),
            )

            return self._model, self._tokenizer

        except Exception as e:
            logger.error(
                "model_load_failed",
                model_name=self._model_name,
                error=str(e),
            )
            raise ModelLoadException(
                model_name=self._model_name,
                reason=str(e),
            ) from e

    async def _load_tokenizer(self) -> PreTrainedTokenizer:
        """Load tokenizer from HuggingFace."""
        logger.debug("loading_tokenizer", model_name=self._model_name)

        tokenizer = AutoTokenizer.from_pretrained(
            self._model_name,
            token=self._hf_token if self._hf_token else None,
            trust_remote_code=True,
        )

        # Set padding token if not set
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        return tokenizer

    async def _load_model(self) -> PreTrainedModel:
        """Load model with optimization settings."""
        logger.debug(
            "loading_model_weights",
            model_name=self._model_name,
        )

        device = self._get_actual_device()
        load_kwargs: dict[str, Any] = {
            "token": self._hf_token if self._hf_token else None,
            "trust_remote_code": True,
        }

        # Configure quantization
        if self._enable_4bit and device == "cuda":
            from transformers import BitsAndBytesConfig

            load_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
            )
            load_kwargs["device_map"] = "auto"
            logger.info("using_4bit_quantization")

        elif self._enable_8bit and device == "cuda":
            from transformers import BitsAndBytesConfig

            load_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_8bit=True,
                bnb_8bit_compute_dtype=torch.float16,
            )
            load_kwargs["device_map"] = "auto"
            logger.info("using_8bit_quantization")

        else:
            # Standard loading
            if device == "cuda":
                load_kwargs["torch_dtype"] = torch.float16
                load_kwargs["device_map"] = "auto"
            elif device == "mps":
                load_kwargs["torch_dtype"] = torch.float16

        model = AutoModelForCausalLM.from_pretrained(
            self._model_name,
            **load_kwargs,
        )

        # Move to device if not using device_map
        if "device_map" not in load_kwargs:
            model = cast(
                PreTrainedModel, model.to(device)  # type: ignore[arg-type,assignment]
            )

        # Set to evaluation mode
        model.eval()

        return model

    async def warmup(self, sample_text: str = "SELECT * FROM users") -> None:
        """
        Warm up model with a sample inference.

        Args:
            sample_text: Sample text for warmup
        """
        if not self._is_loaded:
            raise ModelLoadException(
                model_name=self._model_name,
                reason="Cannot warmup: model not loaded",
            )

        logger.info("warming_up_model")

        try:
            # Assert model and tokenizer are loaded (checked above)
            assert self._tokenizer is not None
            assert self._model is not None

            inputs = self._tokenizer(
                sample_text,
                return_tensors="pt",
                truncation=True,
                max_length=100,
            )

            device = self._get_actual_device()
            inputs = {k: v.to(device) for k, v in inputs.items()}

            with torch.no_grad():
                _ = self._model.generate(  # type: ignore[operator]
                    **inputs,
                    max_new_tokens=10,
                    do_sample=False,
                )

            logger.info("model_warmup_complete")

        except Exception as e:
            logger.warning("model_warmup_failed", error=str(e))

    def unload(self) -> None:
        """Unload model and free memory."""
        if self._model:
            del self._model
            self._model = None

        if self._tokenizer:
            del self._tokenizer
            self._tokenizer = None

        self._is_loaded = False

        # Force garbage collection
        gc.collect()

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        logger.info("model_unloaded")


# Global model loader instance
_model_loader: ModelLoader | None = None


async def get_model_loader() -> ModelLoader:
    """
    Get the global model loader instance.

    Returns:
        ModelLoader: Global model loader
    """
    global _model_loader

    if _model_loader is None:
        _model_loader = ModelLoader()

    return _model_loader


async def load_model() -> tuple[PreTrainedModel, PreTrainedTokenizer]:
    """
    Load model using global loader.

    Returns:
        Tuple of (model, tokenizer)
    """
    loader = await get_model_loader()
    return await loader.load()


def unload_model() -> None:
    """Unload model using global loader."""
    global _model_loader

    if _model_loader:
        _model_loader.unload()
        _model_loader = None
