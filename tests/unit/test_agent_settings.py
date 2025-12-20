"""Unit tests for agent settings defaults."""

from app.config import AgentSettings


def test_agent_settings_defaults() -> None:
    settings = AgentSettings()

    assert settings.model_backend == "local"
    assert settings.inference_timeout == 120
    assert settings.inference_provider is None
