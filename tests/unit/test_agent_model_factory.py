"""Unit tests for agent model factory."""

import pytest

pytest.importorskip("smolagents")

from unittest.mock import MagicMock, patch

from app.agent.model_factory import build_agent_model
from app.config import Settings


def test_build_agent_model_local_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_MODEL_BACKEND", "local")
    monkeypatch.setenv("TEXT2SQL_MODEL", "local-model")
    settings = Settings()

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


def test_build_agent_model_hf_inference_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_MODEL_BACKEND", "hf_inference")
    monkeypatch.setenv("AGENT_INFERENCE_PROVIDER", "hf-inference")
    monkeypatch.setenv("AGENT_INFERENCE_TIMEOUT", "90")
    monkeypatch.setenv("AGENT_INFERENCE_BASE_URL", "https://example.com")
    monkeypatch.setenv("AGENT_INFERENCE_BILL_TO", "test-org")
    monkeypatch.setenv("AGENT_INFERENCE_MAX_TOKENS", "256")
    monkeypatch.setenv("AGENT_INFERENCE_TEMPERATURE", "0.2")
    monkeypatch.setenv("AGENT_INFERENCE_TOP_P", "0.9")
    monkeypatch.setenv("TEXT2SQL_MODEL", "remote-model")
    monkeypatch.setenv("HUGGINGFACE_TOKEN", "hf_token")
    settings = Settings()

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
