"""
HuggingFace model loading and inference utilities.

This package provides ML model infrastructure:
- loader: Model loading with quantization support
- inference: SQL generation inference engine
- prompts: Prompt templates for Text2SQL
"""

from models.loader import ModelLoader, ModelInfo, get_model_loader, load_model
from models.inference import InferenceEngine, InferenceResult, GenerationConfig
from models.prompts import (
    PromptTemplate,
    ArcticPromptTemplate,
    FewShotExample,
    build_prompt,
    get_prompt_template,
)

__all__ = [
    "ModelLoader",
    "ModelInfo",
    "get_model_loader",
    "load_model",
    "InferenceEngine",
    "InferenceResult",
    "GenerationConfig",
    "PromptTemplate",
    "ArcticPromptTemplate",
    "FewShotExample",
    "build_prompt",
    "get_prompt_template",
]
