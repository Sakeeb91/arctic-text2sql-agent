"""
Application configuration management using Pydantic Settings.

This module provides centralized configuration with environment variable support,
validation, and type safety.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class HuggingFaceSettings(BaseSettings):
    """HuggingFace and model-related configuration."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    token: str = Field(
        default="",
        alias="HUGGINGFACE_TOKEN",
        description="HuggingFace API token for model access",
    )
    model_name: str = Field(
        default="Snowflake/Arctic-Text2SQL-R1-7B",
        alias="TEXT2SQL_MODEL",
        description="HuggingFace model identifier",
    )
    device: str = Field(
        default="auto",
        alias="MODEL_DEVICE",
        description="Device for model inference (auto, cuda, cpu, mps)",
    )
    enable_8bit_quantization: bool = Field(
        default=False,
        alias="ENABLE_8BIT_QUANTIZATION",
        description="Enable 8-bit quantization for memory efficiency",
    )
    enable_4bit_quantization: bool = Field(
        default=False,
        alias="ENABLE_4BIT_QUANTIZATION",
        description="Enable 4-bit quantization for maximum memory efficiency",
    )


class DatabaseSettings(BaseSettings):
    """Database connection configuration."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    url: str = Field(
        default="sqlite:///./data/text2sql.db",
        alias="DATABASE_URL",
        description="Database connection URL",
    )
    pool_size: int = Field(
        default=5,
        alias="DB_POOL_SIZE",
        ge=1,
        le=100,
        description="Connection pool size",
    )
    max_overflow: int = Field(
        default=10,
        alias="DB_MAX_OVERFLOW",
        ge=0,
        le=100,
        description="Maximum pool overflow connections",
    )
    pool_timeout: int = Field(
        default=30,
        alias="DB_POOL_TIMEOUT",
        ge=1,
        description="Connection pool timeout in seconds",
    )

    @field_validator("url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Validate database URL format."""
        valid_prefixes = ("postgresql://", "mysql://", "sqlite:///")
        if not any(v.startswith(prefix) for prefix in valid_prefixes):
            raise ValueError(
                f"Database URL must start with one of: {', '.join(valid_prefixes)}"
            )
        return v


class APISettings(BaseSettings):
    """API server configuration."""

    model_config = SettingsConfigDict(env_prefix="API_", extra="ignore")

    host: str = Field(default="0.0.0.0", description="API server host")
    port: int = Field(default=8000, ge=1, le=65535, description="API server port")
    debug: bool = Field(default=False, description="Enable debug mode")
    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:8080",
        alias="CORS_ORIGINS",
        description="Comma-separated allowed CORS origins",
    )
    rate_limit_per_minute: int = Field(
        default=60,
        alias="RATE_LIMIT_PER_MINUTE",
        ge=1,
        description="Rate limit requests per minute",
    )
    rate_limit_burst: int = Field(
        default=10,
        alias="RATE_LIMIT_BURST",
        ge=1,
        description="Rate limit burst allowance",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        """Return CORS origins as a list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


class AgentSettings(BaseSettings):
    """Agent-specific configuration."""

    model_config = SettingsConfigDict(env_prefix="AGENT_", extra="ignore")

    max_steps: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum reasoning steps for agent",
    )
    min_confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence score to return results",
    )
    enable_validation: bool = Field(
        default=True,
        description="Enable output validation",
    )


class SecuritySettings(BaseSettings):
    """Security-related configuration."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    secret_key: str = Field(
        default="your-secret-key-change-in-production",
        alias="SECRET_KEY",
        description="Secret key for JWT token signing",
    )
    jwt_algorithm: str = Field(
        default="HS256",
        alias="JWT_ALGORITHM",
        description="JWT signing algorithm",
    )
    jwt_access_token_expire_minutes: int = Field(
        default=30,
        alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
        ge=1,
        description="JWT access token expiration time in minutes",
    )


class LoggingSettings(BaseSettings):
    """Logging configuration."""

    model_config = SettingsConfigDict(env_prefix="LOG_", extra="ignore")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level",
    )
    format: Literal["json", "console"] = Field(
        default="json",
        description="Log output format",
    )
    requests: bool = Field(
        default=True,
        description="Enable request logging",
    )


class MonitoringSettings(BaseSettings):
    """Monitoring and metrics configuration."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    enable_metrics: bool = Field(
        default=True,
        alias="ENABLE_METRICS",
        description="Enable Prometheus metrics",
    )
    metrics_port: int = Field(
        default=9090,
        alias="METRICS_PORT",
        ge=1,
        le=65535,
        description="Prometheus metrics port",
    )


class CacheSettings(BaseSettings):
    """Cache configuration."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    redis_url: str | None = Field(
        default=None,
        alias="REDIS_URL",
        description="Redis connection URL for caching",
    )
    ttl: int = Field(
        default=3600,
        alias="CACHE_TTL",
        ge=0,
        description="Cache TTL in seconds",
    )


class Settings(BaseSettings):
    """
    Main application settings aggregating all configuration sections.

    Usage:
        from app.config import get_settings

        settings = get_settings()
        print(settings.api.host)
        print(settings.huggingface.model_name)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Nested configuration sections
    huggingface: HuggingFaceSettings = Field(default_factory=HuggingFaceSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    api: APISettings = Field(default_factory=APISettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    monitoring: MonitoringSettings = Field(default_factory=MonitoringSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)


@lru_cache
def get_settings() -> Settings:
    """
    Get cached application settings instance.

    Uses LRU cache to ensure settings are loaded only once.

    Returns:
        Settings: Application settings instance
    """
    return Settings()

