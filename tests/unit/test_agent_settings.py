"""Unit tests for agent settings defaults."""

import pytest

from app.config import AgentSettings


def test_agent_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_MODEL_BACKEND", raising=False)
    monkeypatch.delenv("AGENT_USE_LEGACY_FALLBACK", raising=False)
    monkeypatch.delenv("AGENT_INFERENCE_PROVIDER", raising=False)
    monkeypatch.delenv("AGENT_INFERENCE_TIMEOUT", raising=False)

    settings = AgentSettings()

    assert settings.model_backend == "local"
    assert settings.inference_timeout == 120
    assert settings.inference_provider is None
