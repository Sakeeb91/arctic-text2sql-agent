"""
FastAPI application entry point.

This module initializes and configures the Arctic Text2SQL API application.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app import __version__
from app.config import get_settings
from app.logging_config import configure_logging, get_logger
from app.middleware import setup_middleware
from app.routes import router

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
    # TODO: Initialize database manager
    logger.info("database_initializing")

    # Load model
    # TODO: Initialize model loader
    logger.info(
        "model_loading",
        model_name=settings.huggingface.model_name,
        device=settings.huggingface.device,
    )

    logger.info("application_started")

    yield

    # Shutdown
    logger.info("application_shutting_down")

    # Cleanup resources
    # TODO: Close database connections
    # TODO: Unload model

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

    ## Quick Start

    1. Register a database schema: `POST /api/v1/schema/register`
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

# Include API routes
app.include_router(router)


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
