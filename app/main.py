"""
FastAPI application entry point.

This module initializes and configures the Arctic Text2SQL API application.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.config import get_settings
from app.error_handlers import setup_exception_handlers
from app.logging_config import configure_logging, get_logger
from app.middleware import setup_middleware

# Issue #9: Import monitoring module
from app.monitoring import (
    get_metrics_registry,
    get_tracing_manager,
    setup_monitoring_routes,
)
from app.monitoring.middleware import MetricsMiddleware
from app.monitoring.trace_middleware import TraceContextMiddleware
from app.routes import router
from app.routes_databases import router as databases_router
from app.routes_examples import router as examples_router
from app.routes_feedback import router as feedback_router
from app.routes_models import router as models_router
from app.security.rate_limiting import setup_rate_limiting
from db.connection import close_database, get_database
from db.registry import close_database_registry, get_database_registry
from models.loader import get_model_loader, unload_model

# Initialize settings
settings = get_settings()

# Configure logging based on settings
configure_logging(
    level=settings.logging.level,
    log_format=settings.logging.format,
    enable_request_logging=settings.logging.requests,
)

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Handles startup and shutdown events for initializing
    and cleaning up resources.
    """
    # Startup
    logger.info(
        "application_starting",
        version=__version__,
        host=settings.api.host,
        port=settings.api.port,
        debug=settings.api.debug,
    )

    # Initialize database connection
    logger.info("database_initializing")
    try:
        db_manager = await get_database()
        is_healthy = await db_manager.health_check()
        logger.info(
            "database_initialized",
            dialect=db_manager.dialect,
            healthy=is_healthy,
        )
    except Exception as e:
        logger.error("database_initialization_failed", error=str(e))
        # Continue startup even if database fails - allows health checks to report status
        pass

    # Issue #14: Initialize multi-database registry
    if settings.multi_database.enabled:
        logger.info("database_registry_initializing")
        try:
            registry = await get_database_registry()
            logger.info(
                "database_registry_initialized",
                database_count=registry.database_count,
            )
        except Exception as e:
            logger.warning(
                "database_registry_initialization_failed",
                error=str(e),
            )

    # Load model (Phase 1.3: HuggingFace Model Integration)
    model_loaded = False
    if settings.huggingface.token:
        logger.info(
            "model_loading",
            model_name=settings.huggingface.model_name,
            device=settings.huggingface.device,
            enable_8bit=settings.huggingface.enable_8bit_quantization,
            enable_4bit=settings.huggingface.enable_4bit_quantization,
        )
        try:
            model_loader = await get_model_loader()
            await model_loader.load()
            await model_loader.warmup()
            model_loaded = True
            model_info = model_loader.get_info()
            logger.info(
                "model_loaded",
                model_name=model_info.model_name,
                device=model_info.device,
                quantization=model_info.quantization,
                memory_mb=model_info.memory_usage_mb,
            )
        except Exception as e:
            logger.warning(
                "model_loading_skipped",
                error=str(e),
                message="Model loading failed, API will run without model inference",
            )
    else:
        logger.warning(
            "model_loading_skipped",
            message="No HUGGINGFACE_TOKEN provided, model will not be loaded",
        )

    # Issue #9: Initialize monitoring
    logger.info("monitoring_initializing")
    try:
        # Initialize tracing
        tracing = get_tracing_manager()
        tracing_enabled = tracing.initialize()

        # Set service info in metrics
        metrics = get_metrics_registry()
        metrics.set_service_info(
            version=__version__,
            model_name=settings.huggingface.model_name,
            environment="production" if not settings.api.debug else "development",
        )

        # Set model loaded status
        metrics.set_model_loaded_status(
            model_name=settings.huggingface.model_name,
            loaded=model_loaded,
        )

        logger.info(
            "monitoring_initialized",
            metrics_enabled=settings.monitoring.enable_metrics,
            tracing_enabled=tracing_enabled,
            service_name=settings.monitoring.service_name,
        )
    except Exception as e:
        logger.warning("monitoring_initialization_failed", error=str(e))

    logger.info("application_started", model_loaded=model_loaded)

    yield

    # Shutdown
    logger.info("application_shutting_down")

    # Issue #14: Close database registry
    if settings.multi_database.enabled:
        logger.info("database_registry_closing")
        await close_database_registry()
        logger.info("database_registry_closed")

    # Cleanup resources
    logger.info("database_closing")
    await close_database()
    logger.info("database_closed")

    # Unload model (Phase 1.3: HuggingFace Model Integration)
    logger.info("model_unloading")
    unload_model()
    logger.info("model_unloaded")

    # Issue #9: Shutdown tracing
    logger.info("tracing_shutting_down")
    try:
        tracing = get_tracing_manager()
        tracing.shutdown()
        logger.info("tracing_shutdown_complete")
    except Exception as e:
        logger.warning("tracing_shutdown_failed", error=str(e))

    logger.info("application_stopped")


# Create FastAPI application
app = FastAPI(
    title="Arctic Text2SQL API",
    description="""
    Self-Correcting AI Agent for Natural Language to SQL powered by
    Snowflake's Arctic-Text2SQL-R1 model and HuggingFace smolagents.

    ## Features

    - **Multi-Step Reasoning**: Agent breaks down complex queries into manageable steps
    - **Self-Correction**: Validates and fixes incorrect SQL automatically
    - **Output Inspection**: Checks if results actually answer the question
    - **Transparent Reasoning**: See agent's thought process for every query
    - **Tool-Based Architecture**: Modular, extensible design
    - **Multi-Database Support**: Connect to multiple databases simultaneously

    ## Quick Start

    1. Register a database: `POST /api/v1/databases`
    2. Generate SQL: `POST /api/v1/query`
    3. View reasoning: `GET /api/v1/agent/reasoning/{query_id}`
    """,
    version=__version__,
    contact={
        "name": "Arctic Text2SQL Agent",
        "url": "https://github.com/Sakeeb91/arctic-text2sql-agent",
        "email": "rahman.sakeeb@gmail.com",
    },
    license_info={
        "name": "MIT License",
        "url": "https://opensource.org/licenses/MIT",
    },
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Setup middleware
setup_middleware(app, cors_origins=settings.api.cors_origins_list)

# Issue #9: Setup monitoring middleware (before other middleware for accurate timing)
if settings.monitoring.enable_metrics:
    app.add_middleware(
        MetricsMiddleware,
        exclude_paths=[
            "/metrics",
            "/monitoring/metrics",
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
        ],
    )

# Issue #9: Setup trace context middleware
if settings.monitoring.enable_tracing:
    app.add_middleware(TraceContextMiddleware)

# Setup exception handlers (Phase 2.3: Error Handling & Resilience)
setup_exception_handlers(app)

# Setup rate limiting (Phase 2.2: Security Implementation)
setup_rate_limiting(app)

# Include API routes
app.include_router(router)

# Issue #16: Include few-shot example routes
if settings.few_shot.enabled:
    app.include_router(examples_router)

# Issue #16: Include feedback routes
if settings.feedback.enabled:
    app.include_router(feedback_router)

# Issue #16: Include model versioning routes
if settings.model_versioning.enabled:
    app.include_router(models_router)

# Issue #14: Include database management routes
if settings.multi_database.enabled:
    app.include_router(databases_router)

# Issue #9: Include monitoring routes
if settings.monitoring.enable_metrics:
    setup_monitoring_routes(app)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    """Root endpoint redirect to documentation."""
    return {
        "message": "Arctic Text2SQL API",
        "version": __version__,
        "docs": "/docs",
        "health": "/api/v1/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=settings.api.debug,
        log_level="info",
    )
