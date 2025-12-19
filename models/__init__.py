"""
HuggingFace model loading and inference utilities.

This package provides ML model infrastructure:
- loader: Model loading with quantization support
- inference: SQL generation inference engine
- prompts: Prompt templates for Text2SQL

Phase 1.3: HuggingFace Model Integration
- Efficient model loading with caching and quantization
- Inference engine with batch support and confidence scoring
- Prompt engineering for Text2SQL generation
- Device management (CPU/GPU/MPS)
"""

from models.inference import (
    GenerationConfig,
    InferenceEngine,
    InferenceResult,
    calculate_confidence,
    extract_sql_from_output,
    get_inference_engine,
)
from models.loader import (
    ModelInfo,
    ModelLoader,
    get_memory_usage,
    get_model_loader,
    get_optimal_device,
    load_model,
    unload_model,
)
from models.prompts import (
    AgentPromptTemplate,
    ArcticPromptTemplate,
    ChainOfThoughtPromptTemplate,
    FewShotExample,
    PromptTemplate,
    build_prompt,
    format_schema_for_prompt,
    get_prompt_template,
)
from models.fine_tuning import (
    FineTuningExample,
    FineTuningPipeline,
    get_fine_tuning_pipeline,
    reset_fine_tuning_pipeline,
)
from models.versioning import (
    ModelVersion,
    ModelVersionManager,
    ModelVersionStatus,
    get_model_version_manager,
    reset_model_version_manager,
)

__all__ = [
    # Loader
    "ModelLoader",
    "ModelInfo",
    "get_model_loader",
    "load_model",
    "unload_model",
    "get_optimal_device",
    "get_memory_usage",
    # Inference
    "InferenceEngine",
    "InferenceResult",
    "GenerationConfig",
    "get_inference_engine",
    "extract_sql_from_output",
    "calculate_confidence",
    # Prompts
    "PromptTemplate",
    "ArcticPromptTemplate",
    "ChainOfThoughtPromptTemplate",
    "AgentPromptTemplate",
    "FewShotExample",
    "build_prompt",
    "get_prompt_template",
    "format_schema_for_prompt",
    # Fine-tuning (Issue #16)
    "FineTuningExample",
    "FineTuningPipeline",
    "get_fine_tuning_pipeline",
    "reset_fine_tuning_pipeline",
    # Model versioning (Issue #16)
    "ModelVersion",
    "ModelVersionStatus",
    "ModelVersionManager",
    "get_model_version_manager",
    "reset_model_version_manager",
]
