"""
Pytest configuration and fixtures for Arctic Text2SQL tests.

This module provides reusable test fixtures for:
- Database connections
- Mock models
- API test clients
- Sample data
"""

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.main import app
from db.connection import DatabaseManager
from db.schema import ColumnInfo, SchemaInfo, TableInfo

# =============================================================================
# Configuration Fixtures
# =============================================================================


@pytest.fixture
def test_settings() -> Settings:
    """Provide test settings configuration."""
    return Settings(
        huggingface=MagicMock(
            token="test_token",
            model_name="test/model",
            device="cpu",
            enable_8bit_quantization=False,
            enable_4bit_quantization=False,
        ),
        database=MagicMock(
            url="sqlite:///./test_data/test.db",
            pool_size=1,
            max_overflow=0,
            pool_timeout=30,
        ),
        api=MagicMock(
            host="0.0.0.0",
            port=8000,
            debug=True,
            cors_origins="http://localhost:3000",
            rate_limit_per_minute=100,
            rate_limit_burst=20,
            cors_origins_list=["http://localhost:3000"],
        ),
        agent=MagicMock(
            max_steps=3,
            min_confidence=0.5,
            enable_validation=True,
        ),
        security=MagicMock(
            secret_key="test-secret-key",
            jwt_algorithm="HS256",
            jwt_access_token_expire_minutes=30,
        ),
        logging=MagicMock(
            level="DEBUG",
            format="console",
            requests=False,
        ),
        monitoring=MagicMock(
            enable_metrics=False,
            metrics_port=9090,
        ),
        cache=MagicMock(
            redis_url=None,
            ttl=60,
        ),
    )


# =============================================================================
# Database Fixtures
# =============================================================================


@pytest.fixture
async def async_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create an in-memory SQLite async engine for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    yield engine

    await engine.dispose()


@pytest.fixture
async def db_session(async_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Create a database session for testing."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session


@pytest.fixture
async def db_manager(
    async_engine: AsyncEngine,
) -> AsyncGenerator[DatabaseManager, None]:
    """Create a database manager for testing."""
    manager = DatabaseManager(url="sqlite:////:memory:")

    # Mock the engine
    manager._engine = async_engine
    manager._is_initialized = True

    from sqlalchemy.ext.asyncio import async_sessionmaker

    manager._session_factory = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    yield manager


# =============================================================================
# Schema Fixtures
# =============================================================================


@pytest.fixture
def sample_schema() -> SchemaInfo:
    """Provide sample schema information for testing."""
    return SchemaInfo(
        database_id="test_db",
        dialect="sqlite",
        tables=[
            TableInfo(
                name="customers",
                columns=[
                    ColumnInfo(
                        name="id", data_type="INTEGER", nullable=False, primary_key=True
                    ),
                    ColumnInfo(name="name", data_type="VARCHAR(100)", nullable=False),
                    ColumnInfo(name="email", data_type="VARCHAR(255)", nullable=True),
                    ColumnInfo(name="state", data_type="VARCHAR(50)", nullable=True),
                ],
                primary_keys=["id"],
            ),
            TableInfo(
                name="orders",
                columns=[
                    ColumnInfo(
                        name="id", data_type="INTEGER", nullable=False, primary_key=True
                    ),
                    ColumnInfo(
                        name="customer_id",
                        data_type="INTEGER",
                        nullable=False,
                        foreign_key="customers.id",
                    ),
                    ColumnInfo(
                        name="amount", data_type="DECIMAL(10,2)", nullable=False
                    ),
                    ColumnInfo(name="order_date", data_type="DATE", nullable=False),
                ],
                primary_keys=["id"],
            ),
        ],
    )


@pytest.fixture
def sample_schema_text() -> str:
    """Provide sample schema as formatted text."""
    return """Database Schema (sqlite):

Table: customers
  - id (INTEGER) [PK] [NOT NULL]
  - name (VARCHAR(100)) [NOT NULL]
  - email (VARCHAR(255))
  - state (VARCHAR(50))

Table: orders
  - id (INTEGER) [PK] [NOT NULL]
  - customer_id (INTEGER) [FK -> customers.id] [NOT NULL]
  - amount (DECIMAL(10,2)) [NOT NULL]
  - order_date (DATE) [NOT NULL]
"""


# =============================================================================
# Model Fixtures
# =============================================================================


@pytest.fixture
def mock_model() -> MagicMock:
    """Create a mock model for testing."""
    model = MagicMock()
    model.generate.return_value = MagicMock(
        sequences=MagicMock(),
        scores=None,
    )
    model.parameters.return_value = iter([MagicMock(device="cpu")])
    model.eval.return_value = model
    return model


@pytest.fixture
def mock_tokenizer() -> MagicMock:
    """Create a mock tokenizer for testing."""
    tokenizer = MagicMock()
    tokenizer.return_value = {
        "input_ids": MagicMock(shape=(1, 10)),
        "attention_mask": MagicMock(),
    }
    tokenizer.decode.return_value = "SELECT * FROM customers WHERE state = 'California'"
    tokenizer.pad_token = "[PAD]"
    tokenizer.eos_token = "[EOS]"
    tokenizer.pad_token_id = 0
    tokenizer.eos_token_id = 1
    return tokenizer


@pytest.fixture
def mock_model_loader(mock_model: MagicMock, mock_tokenizer: MagicMock) -> MagicMock:
    """Create a mock model loader for testing."""
    loader = MagicMock()
    loader.model = mock_model
    loader.tokenizer = mock_tokenizer
    loader.is_loaded = True
    loader.load = AsyncMock(return_value=(mock_model, mock_tokenizer))
    return loader


# =============================================================================
# API Client Fixtures
# =============================================================================


@pytest.fixture
def test_client() -> TestClient:
    """Create a synchronous test client."""
    return TestClient(app)


@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


# =============================================================================
# Sample Data Fixtures
# =============================================================================


@pytest.fixture
def sample_queries() -> list[dict[str, Any]]:
    """Provide sample natural language queries for testing."""
    return [
        {
            "question": "Show all customers from California",
            "expected_keywords": ["SELECT", "customers", "California"],
        },
        {
            "question": "How many orders were placed?",
            "expected_keywords": ["SELECT", "COUNT", "orders"],
        },
        {
            "question": "What is the total order amount by customer?",
            "expected_keywords": ["SELECT", "SUM", "GROUP BY"],
        },
        {
            "question": "Which customer has the most orders?",
            "expected_keywords": ["SELECT", "COUNT", "ORDER BY", "DESC", "LIMIT"],
        },
    ]


@pytest.fixture
def sample_sql_queries() -> list[str]:
    """Provide sample SQL queries for validation testing."""
    return [
        "SELECT * FROM customers WHERE state = 'California'",
        "SELECT COUNT(*) FROM orders",
        "SELECT customer_id, SUM(amount) FROM orders GROUP BY customer_id",
        "SELECT c.name, COUNT(o.id) FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.id ORDER BY COUNT(o.id) DESC LIMIT 1",
    ]


# =============================================================================
# Utility Fixtures
# =============================================================================


@pytest.fixture
def mock_settings(test_settings: Settings) -> Any:
    """Mock get_settings to return test settings."""
    with patch("app.config.get_settings", return_value=test_settings):
        yield test_settings


@pytest.fixture(autouse=True)
def reset_singletons() -> Any:
    """Reset singleton instances between tests."""
    # Reset database manager
    import db.connection

    db.connection._db_manager = None

    # Reset model loader (skip if torch not installed)
    try:
        import models.loader

        models.loader._model_loader = None
    except ImportError:
        pass  # torch not installed, skip model loader reset

    # Reset inference engine (skip if torch not installed)
    try:
        import models.inference

        models.inference._inference_engine = None
    except ImportError:
        pass  # torch not installed, skip inference engine reset

    yield
