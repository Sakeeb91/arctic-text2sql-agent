"""Model factory for selecting agent inference backends."""

from __future__ import annotations

from typing import Any

from app.agent.model_backends import HFInferenceModel, LocalInferenceModel
from app.config import Settings
from app.monitoring.model_instrumentation import ModelInstrumentor


def _build_inference_kwargs(settings: Settings) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if settings.agent.inference_max_tokens is not None:
        kwargs["max_tokens"] = settings.agent.inference_max_tokens
    if settings.agent.inference_temperature is not None:
        kwargs["temperature"] = settings.agent.inference_temperature
    if settings.agent.inference_top_p is not None:
        kwargs["top_p"] = settings.agent.inference_top_p
    return kwargs


def build_agent_model(
    settings: Settings,
    model_loader: Any,
    instrumentor: ModelInstrumentor,
) -> LocalInferenceModel | HFInferenceModel:
    """Return the configured agent model backend."""
    model_name = settings.huggingface.model_name
    backend = settings.agent.model_backend

    if backend == "hf_inference":
        return HFInferenceModel(
            model_id=model_name,
            instrumentor=instrumentor,
            provider=settings.agent.inference_provider,
            token=settings.huggingface.token or None,
            timeout=settings.agent.inference_timeout,
            base_url=settings.agent.inference_base_url,
            bill_to=settings.agent.inference_bill_to,
            **_build_inference_kwargs(settings),
        )

    return LocalInferenceModel(
        model_loader=model_loader,
        model_id=model_name,
        instrumentor=instrumentor,
    )
