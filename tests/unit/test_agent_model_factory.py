"""Unit tests for agent model factory."""

import pytest

pytest.importorskip("smolagents")

from unittest.mock import MagicMock, patch

from app.agent.model_factory import build_agent_model
from app.config import AgentSettings, HuggingFaceSettings, Settings


def _settings_overrides(agent_overrides: dict, hf_overrides: dict | None = None) -> Settings:
    return Settings(
        agent=AgentSettings(**agent_overrides),
        huggingface=HuggingFaceSettings(**(hf_overrides or {})),
    )


def test_build_agent_model_local_backend() -> None:
    settings = _settings_overrides(
        {
            "model_backend": "local",
        },
        {"model_name": "local-model"},
    )

    model_loader = MagicMock()
    instrumentor = MagicMock()

    with patch("app.agent.model_factory.LocalInferenceModel") as local_model:
        local_model.return_value = "local"

        model = build_agent_model(
            settings=settings,
            model_loader=model_loader,
            instrumentor=instrumentor,
        )

        assert model == "local"
        local_model.assert_called_once_with(
            model_loader=model_loader,
            model_id="local-model",
            instrumentor=instrumentor,
        )


def test_build_agent_model_hf_inference_backend() -> None:
    settings = _settings_overrides(
        {
            "model_backend": "hf_inference",
            "inference_provider": "hf-inference",
            "inference_timeout": 90,
            "inference_base_url": "https://example.com",
            "inference_bill_to": "test-org",
            "inference_max_tokens": 256,
            "inference_temperature": 0.2,
            "inference_top_p": 0.9,
        },
        {"model_name": "remote-model", "token": "hf_token"},
    )

    model_loader = MagicMock()
    instrumentor = MagicMock()

    with patch("app.agent.model_factory.HFInferenceModel") as hf_model:
        hf_model.return_value = "remote"

        model = build_agent_model(
            settings=settings,
            model_loader=model_loader,
            instrumentor=instrumentor,
        )

        assert model == "remote"
        hf_model.assert_called_once_with(
            model_id="remote-model",
            instrumentor=instrumentor,
            provider="hf-inference",
            token="hf_token",
            timeout=90,
            base_url="https://example.com",
            bill_to="test-org",
            max_tokens=256,
            temperature=0.2,
            top_p=0.9,
        )
