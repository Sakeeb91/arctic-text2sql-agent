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

    def test_default_values(self) -> None:
        """Test default database settings."""
        settings = DatabaseSettings()
        assert settings.url == "sqlite:///./data/text2sql.db"
        assert settings.pool_size == 5
        assert settings.max_overflow == 10
        assert settings.pool_timeout == 30

    def test_valid_postgresql_url(self) -> None:
        """Test valid PostgreSQL URL."""
        settings = DatabaseSettings(url="postgresql://user:pass@localhost/db")
        assert settings.url.startswith("postgresql://")

    def test_valid_mysql_url(self) -> None:
        """Test valid MySQL URL."""
        settings = DatabaseSettings(url="mysql://user:pass@localhost/db")
        assert settings.url.startswith("mysql://")

    def test_valid_sqlite_url(self) -> None:
        """Test valid SQLite URL."""
        settings = DatabaseSettings(url="sqlite:///./test.db")
        assert settings.url.startswith("sqlite:///")

    def test_invalid_url_raises_error(self) -> None:
        """Test that invalid URL raises ValidationError."""
        with pytest.raises(ValidationError):
            DatabaseSettings(url="invalid://url")


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

    def test_cors_origins_list(self) -> None:
        """Test CORS origins parsing."""
        settings = APISettings(cors_origins="http://a.com, http://b.com")
        assert settings.cors_origins_list == ["http://a.com", "http://b.com"]

    def test_port_bounds(self) -> None:
        """Test port boundary validation."""
        APISettings(port=1)
        APISettings(port=65535)

        with pytest.raises(ValidationError):
            APISettings(port=0)

        with pytest.raises(ValidationError):
            APISettings(port=65536)


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

