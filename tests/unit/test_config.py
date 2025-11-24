"""
Unit tests for configuration module.
"""

import pytest
from pydantic import ValidationError

from app.config import (
    APISettings,
    AgentSettings,
    DatabaseSettings,
    HuggingFaceSettings,
    Settings,
    get_settings,
)


class TestDatabaseSettings:
    """Tests for DatabaseSettings."""

    def test_default_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test default database settings."""
        # Clear any env vars that might interfere
        monkeypatch.delenv("DATABASE_URL", raising=False)
        settings = DatabaseSettings()
        assert settings.url == "sqlite:///./data/text2sql.db"
        assert settings.pool_size == 5
        assert settings.max_overflow == 10
        assert settings.pool_timeout == 30

    def test_valid_postgresql_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test valid PostgreSQL URL."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
        settings = DatabaseSettings()
        assert settings.url.startswith("postgresql://")

    def test_valid_mysql_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test valid MySQL URL."""
        monkeypatch.setenv("DATABASE_URL", "mysql://user:pass@localhost/db")
        settings = DatabaseSettings()
        assert settings.url.startswith("mysql://")

    def test_valid_sqlite_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test valid SQLite URL."""
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
        settings = DatabaseSettings()
        assert settings.url.startswith("sqlite:///")

    def test_invalid_url_raises_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that invalid URL raises ValidationError."""
        monkeypatch.setenv("DATABASE_URL", "invalid://url")
        with pytest.raises(ValidationError):
            DatabaseSettings()


class TestAgentSettings:
    """Tests for AgentSettings."""

    def test_default_values(self) -> None:
        """Test default agent settings."""
        settings = AgentSettings()
        assert settings.max_steps == 5
        assert settings.min_confidence == 0.7
        assert settings.enable_validation is True

    def test_max_steps_bounds(self) -> None:
        """Test max_steps boundary validation."""
        # Valid values
        AgentSettings(max_steps=1)
        AgentSettings(max_steps=20)

        # Invalid values
        with pytest.raises(ValidationError):
            AgentSettings(max_steps=0)

        with pytest.raises(ValidationError):
            AgentSettings(max_steps=21)

    def test_min_confidence_bounds(self) -> None:
        """Test min_confidence boundary validation."""
        # Valid values
        AgentSettings(min_confidence=0.0)
        AgentSettings(min_confidence=1.0)

        # Invalid values
        with pytest.raises(ValidationError):
            AgentSettings(min_confidence=-0.1)

        with pytest.raises(ValidationError):
            AgentSettings(min_confidence=1.1)


class TestAPISettings:
    """Tests for APISettings."""

    def test_cors_origins_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test CORS origins parsing."""
        monkeypatch.setenv("API_CORS_ORIGINS", "http://a.com, http://b.com")
        settings = APISettings()
        assert settings.cors_origins_list == ["http://a.com", "http://b.com"]

    def test_port_bounds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test port boundary validation."""
        # Valid values
        monkeypatch.setenv("API_PORT", "1")
        APISettings()
        monkeypatch.setenv("API_PORT", "65535")
        APISettings()

        # Invalid values - port 0
        monkeypatch.setenv("API_PORT", "0")
        with pytest.raises(ValidationError):
            APISettings()

        # Invalid values - port 65536
        monkeypatch.setenv("API_PORT", "65536")
        with pytest.raises(ValidationError):
            APISettings()


class TestGetSettings:
    """Tests for get_settings function."""

    def test_returns_settings_instance(self) -> None:
        """Test that get_settings returns Settings instance."""
        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_settings_cached(self) -> None:
        """Test that settings are cached (LRU cache)."""
        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2
