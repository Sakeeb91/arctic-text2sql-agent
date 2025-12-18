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
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]


class AgentSettings(BaseSettings):
    """Agent-specific configuration for smolagents integration."""

    model_config = SettingsConfigDict(env_prefix="AGENT_", extra="ignore")

    max_steps: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum reasoning steps for agent ReAct loop",
    )
    min_confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence score to return results",
    )
    enable_validation: bool = Field(
        default=True,
        description="Enable output validation after SQL generation",
    )
    enable_self_correction: bool = Field(
        default=True,
        description="Enable automatic self-correction on validation failure",
    )
    verbosity: int = Field(
        default=1,
        ge=0,
        le=2,
        description="Agent verbosity level (0=quiet, 1=normal, 2=verbose)",
    )
    query_history_size: int = Field(
        default=100,
        ge=0,
        le=1000,
        description="Maximum queries to keep in history for retry",
    )
    execution_timeout: int = Field(
        default=30,
        ge=1,
        le=300,
        description="SQL execution timeout in seconds",
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


class ResilienceSettings(BaseSettings):
    """Resilience and retry configuration."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    failure_threshold: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Number of consecutive failures before opening circuit",
    )
    recovery_timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Time to wait before attempting half-open trial",
    )
    half_open_max_attempts: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Allowed attempts while circuit is half-open",
    )
    backoff_base_seconds: float = Field(
        default=1.0,
        ge=0.1,
        description="Initial delay for exponential backoff",
    )
    backoff_max_seconds: float = Field(
        default=8.0,
        ge=1.0,
        description="Maximum delay for exponential backoff",
    )
    fallback_enabled: bool = Field(
        default=True,
        description="Return fallback responses when dependencies fail repeatedly",
    )
    max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        alias="RESILIENCE_MAX_RETRIES",
        description="Maximum number of retry attempts for transient failures",
    )


class MonitoringSettings(BaseSettings):
    """Monitoring, metrics, and tracing configuration (Issue #9)."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    # Prometheus Metrics
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
    metrics_path: str = Field(
        default="/metrics",
        alias="METRICS_PATH",
        description="Path for Prometheus metrics endpoint",
    )

    # Distributed Tracing (OpenTelemetry)
    enable_tracing: bool = Field(
        default=True,
        alias="ENABLE_TRACING",
        description="Enable distributed tracing with OpenTelemetry",
    )
    otlp_endpoint: str = Field(
        default="http://localhost:4317",
        alias="OTLP_ENDPOINT",
        description="OpenTelemetry collector OTLP endpoint",
    )
    trace_sample_rate: float = Field(
        default=1.0,
        alias="TRACE_SAMPLE_RATE",
        ge=0.0,
        le=1.0,
        description="Trace sampling rate (0.0-1.0)",
    )
    service_name: str = Field(
        default="arctic-text2sql",
        alias="SERVICE_NAME",
        description="Service name for tracing",
    )
    service_version: str = Field(
        default="1.0.0",
        alias="SERVICE_VERSION",
        description="Service version for tracing",
    )

    # Health Checks
    health_check_interval: int = Field(
        default=30,
        alias="HEALTH_CHECK_INTERVAL",
        ge=5,
        le=300,
        description="Health check interval in seconds",
    )
    health_check_timeout: int = Field(
        default=5,
        alias="HEALTH_CHECK_TIMEOUT",
        ge=1,
        le=30,
        description="Health check timeout in seconds",
    )

    # Alerting
    enable_alerting: bool = Field(
        default=True,
        alias="ENABLE_ALERTING",
        description="Enable alerting rules",
    )
    alertmanager_url: str | None = Field(
        default=None,
        alias="ALERTMANAGER_URL",
        description="Alertmanager URL for sending alerts",
    )


class CacheSettings(BaseSettings):
    """Cache configuration (Issue #8: Performance Optimization)."""

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
        description="Default cache TTL in seconds",
    )
    query_ttl: int = Field(
        default=3600,
        alias="CACHE_QUERY_TTL",
        ge=0,
        description="Cache TTL for query results in seconds",
    )
    model_ttl: int = Field(
        default=7200,
        alias="CACHE_MODEL_TTL",
        ge=0,
        description="Cache TTL for model outputs in seconds",
    )
    schema_ttl: int = Field(
        default=86400,
        alias="CACHE_SCHEMA_TTL",
        ge=0,
        description="Cache TTL for schema data in seconds",
    )
    enabled: bool = Field(
        default=True,
        alias="CACHE_ENABLED",
        description="Enable/disable caching globally",
    )
    max_memory_entries: int = Field(
        default=1000,
        alias="CACHE_MAX_MEMORY_ENTRIES",
        ge=100,
        le=10000,
        description="Maximum in-memory cache entries when Redis unavailable",
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
    resilience: ResilienceSettings = Field(default_factory=ResilienceSettings)
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
