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

    enabled: bool = Field(
        default=True,
        description="Enable the smolagents agent for query endpoints",
    )
    use_legacy_fallback: bool = Field(
        default=True,
        description="Fall back to the legacy Text2SQLEngine on agent failure",
    )
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
    model_backend: Literal["local", "hf_inference"] = Field(
        default="local",
        description="Agent model backend: local or Hugging Face Inference Providers",
    )
    inference_provider: str | None = Field(
        default=None,
        description="Inference Providers backend (e.g. hf-inference, together, fireworks)",
    )
    inference_timeout: int = Field(
        default=120,
        ge=1,
        le=600,
        description="Timeout for inference provider calls in seconds",
    )
    inference_base_url: str | None = Field(
        default=None,
        description="Override base URL for Hugging Face Inference Providers",
    )
    inference_bill_to: str | None = Field(
        default=None,
        description="Billing account/org for inference provider calls",
    )
    inference_max_tokens: int | None = Field(
        default=None,
        ge=1,
        description="Maximum tokens for inference provider completions",
    )
    inference_temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Sampling temperature for inference provider completions",
    )
    inference_top_p: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Nucleus sampling for inference provider completions",
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


class ExplanationSettings(BaseSettings):
    """Query explanation and visualization configuration (Issue #15)."""

    model_config = SettingsConfigDict(env_prefix="EXPLAIN_", extra="ignore")

    enabled: bool = Field(
        default=True,
        description="Enable query explanation feature",
    )
    cache_explanations: bool = Field(
        default=True,
        description="Cache generated explanations",
    )
    cache_ttl: int = Field(
        default=3600,
        ge=0,
        le=86400,
        description="Explanation cache TTL in seconds",
    )
    max_sql_length: int = Field(
        default=10000,
        ge=100,
        le=100000,
        description="Maximum SQL length to explain",
    )
    include_complexity: bool = Field(
        default=True,
        description="Include complexity analysis in explanations",
    )
    include_optimization_hints: bool = Field(
        default=True,
        description="Include optimization suggestions",
    )
    visualization_format: Literal["ascii", "json", "html"] = Field(
        default="ascii",
        description="Default visualization format",
    )
    max_depth: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum depth for query plan visualization",
    )
    enable_execution_plan: bool = Field(
        default=False,
        description="Enable EXPLAIN ANALYZE for execution plans (requires DB access)",
    )
    llm_explanation: bool = Field(
        default=True,
        description="Use LLM to generate natural language explanations",
    )


class FewShotSettings(BaseSettings):
    """Few-shot learning configuration (Issue #16)."""

    model_config = SettingsConfigDict(env_prefix="FEWSHOT_", extra="ignore")

    enabled: bool = Field(
        default=True,
        description="Enable few-shot example retrieval for in-context learning",
    )
    max_examples: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum number of examples to include in prompts",
    )
    min_similarity: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score for example inclusion",
    )
    embedding_strategy: Literal["hash", "model"] = Field(
        default="hash",
        description="Embedding strategy for semantic search (hash, model)",
    )
    embedding_dim: int = Field(
        default=256,
        ge=64,
        le=2048,
        description="Embedding dimensionality for hash strategy",
    )
    embedding_max_length: int = Field(
        default=256,
        ge=32,
        le=2048,
        description="Maximum token length for model-based embeddings",
    )
    include_default_examples: bool = Field(
        default=False,
        description="Include built-in few-shot examples alongside retrieved ones",
    )
    verified_only: bool = Field(
        default=True,
        description="Only use verified examples for retrieval",
    )
    use_on_first_attempt: bool = Field(
        default=True,
        description="Use few-shot examples on first generation attempt",
    )
    use_on_retry: bool = Field(
        default=True,
        description="Use few-shot examples on retry attempts",
    )


class FeedbackSettings(BaseSettings):
    """Feedback collection configuration (Issue #16)."""

    model_config = SettingsConfigDict(env_prefix="FEEDBACK_", extra="ignore")

    enabled: bool = Field(
        default=True,
        description="Enable feedback collection endpoints",
    )
    auto_promote_to_examples: bool = Field(
        default=False,
        description="Automatically promote verified feedback into few-shot examples",
    )
    min_rating_for_promotion: int = Field(
        default=4,
        ge=1,
        le=5,
        description="Minimum rating required for auto-promotion",
    )


class FineTuningSettings(BaseSettings):
    """Fine-tuning pipeline configuration (Issue #16)."""

    model_config = SettingsConfigDict(env_prefix="FINETUNE_", extra="ignore")

    enabled: bool = Field(
        default=False,
        description="Enable fine-tuning pipeline utilities",
    )
    output_dir: str = Field(
        default="data/fine_tuning",
        description="Directory for fine-tuning datasets and outputs",
    )
    dataset_name: str = Field(
        default="text2sql_finetune",
        description="Dataset name for exported fine-tuning data",
    )
    max_examples: int = Field(
        default=5000,
        ge=0,
        description="Maximum number of training examples to export",
    )
    include_feedback: bool = Field(
        default=True,
        description="Include verified feedback in fine-tuning data",
    )
    train_epochs: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Training epochs for fine-tuning runs",
    )
    batch_size: int = Field(
        default=2,
        ge=1,
        le=32,
        description="Batch size for fine-tuning runs",
    )
    learning_rate: float = Field(
        default=2e-5,
        gt=0.0,
        description="Learning rate for fine-tuning runs",
    )
    max_seq_length: int = Field(
        default=1024,
        ge=128,
        le=4096,
        description="Maximum sequence length for fine-tuning",
    )


class ModelVersioningSettings(BaseSettings):
    """Model versioning configuration (Issue #16)."""

    model_config = SettingsConfigDict(env_prefix="MODEL_VERSION_", extra="ignore")

    enabled: bool = Field(
        default=True,
        description="Enable model version registry",
    )
    active_version_id: str | None = Field(
        default=None,
        description="Active model version identifier to load",
    )


class MultiDatabaseSettings(BaseSettings):
    """Multi-database registry configuration (Issue #14)."""

    model_config = SettingsConfigDict(env_prefix="MULTIDB_", extra="ignore")

    enabled: bool = Field(
        default=True,
        description="Enable multi-database support",
    )
    max_databases: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum number of registered databases",
    )
    default_pool_size: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Default connection pool size for new databases",
    )
    default_max_overflow: int = Field(
        default=10,
        ge=0,
        le=50,
        description="Default max overflow connections for new databases",
    )
    default_pool_timeout: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Default connection timeout for new databases",
    )
    health_check_interval: int = Field(
        default=60,
        ge=10,
        le=3600,
        description="Interval between health checks in seconds",
    )
    health_check_timeout: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Health check query timeout in seconds",
    )
    require_connection_test: bool = Field(
        default=True,
        description="Test connection before registering a database",
    )
    allow_mutations: bool = Field(
        default=False,
        description="Allow INSERT/UPDATE/DELETE queries by default",
    )
    connection_string_encryption: bool = Field(
        default=False,
        description="Encrypt stored connection strings (requires SECRET_KEY)",
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
    few_shot: FewShotSettings = Field(default_factory=FewShotSettings)
    feedback: FeedbackSettings = Field(default_factory=FeedbackSettings)
    fine_tuning: FineTuningSettings = Field(default_factory=FineTuningSettings)
    model_versioning: ModelVersioningSettings = Field(
        default_factory=ModelVersioningSettings
    )
    multi_database: MultiDatabaseSettings = Field(default_factory=MultiDatabaseSettings)
    explanation: ExplanationSettings = Field(default_factory=ExplanationSettings)


@lru_cache
def get_settings() -> Settings:
    """
    Get cached application settings instance.

    Uses LRU cache to ensure settings are loaded only once.

    Returns:
        Settings: Application settings instance
    """
    return Settings()
