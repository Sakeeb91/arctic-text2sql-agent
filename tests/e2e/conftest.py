"""
E2E test configuration and fixtures.

This module provides fixtures for end-to-end testing with real
model inference and database execution.
"""

import asyncio
import os
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.main import app
from db.dialects import SQLDialect
from db.registry import DatabaseConfig, DatabaseRegistry, reset_database_registry
from db.schema import ColumnInfo, SchemaInfo, TableInfo
from tests.e2e.seed_data import E2E_TEST_DATA, seed_database


# =============================================================================
# Event Loop Fixture for Module-Scoped Async Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def event_loop() -> asyncio.AbstractEventLoop:
    """
    Create an event loop for module-scoped async fixtures.

    pytest-asyncio requires an event_loop fixture with the same scope
    as any async fixtures that need it.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

# =============================================================================
# Environment Configuration
# =============================================================================


def is_e2e_enabled() -> bool:
    """Check if E2E tests should run."""
    return os.getenv("E2E_TESTS_ENABLED", "false").lower() == "true"


def get_e2e_database_url() -> str:
    """Get the E2E test database URL."""
    return os.getenv(
        "E2E_DATABASE_URL",
        "sqlite+aiosqlite:///:memory:",
    )


def use_real_model() -> bool:
    """Check if real model should be used."""
    return os.getenv("E2E_USE_REAL_MODEL", "false").lower() == "true"


# =============================================================================
# Pytest Configuration
# =============================================================================


def pytest_configure(config: Any) -> None:
    """Configure custom pytest markers for E2E tests."""
    config.addinivalue_line("markers", "e2e: End-to-end tests with real model/database")
    config.addinivalue_line("markers", "e2e_slow: Slow E2E tests (model loading)")
    config.addinivalue_line("markers", "e2e_multidb: Multi-database E2E tests")
    config.addinivalue_line("markers", "e2e_streaming: Streaming endpoint E2E tests")
    config.addinivalue_line(
        "markers", "e2e_performance: Performance benchmark E2E tests"
    )


# =============================================================================
# Database Fixtures
# =============================================================================


@pytest_asyncio.fixture(scope="module")
async def e2e_engine() -> AsyncGenerator[Any, None]:
    """
    Create a real database engine for E2E tests.

    Uses SQLite in-memory by default, can be configured via
    E2E_DATABASE_URL environment variable.
    """
    db_url = get_e2e_database_url()

    engine_kwargs: dict[str, Any] = {
        "echo": False,
    }

    if "sqlite" in db_url:
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        engine_kwargs["poolclass"] = StaticPool

    engine = create_async_engine(db_url, **engine_kwargs)

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture(scope="module")
async def e2e_session_factory(
    e2e_engine: Any,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Create a session factory for E2E tests."""
    factory = async_sessionmaker(
        bind=e2e_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    yield factory


@pytest_asyncio.fixture(scope="module")
async def e2e_seeded_database(
    e2e_engine: Any,
    e2e_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[SchemaInfo, None]:
    """
    Create and seed the E2E test database with known data.

    This fixture creates tables and populates them with deterministic
    test data for E2E verification.
    """
    # Create tables and seed data
    async with e2e_engine.begin() as conn:
        # Create customers table
        await conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(255),
                state VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
            )
        )

        # Create orders table
        await conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                amount DECIMAL(10,2) NOT NULL,
                status VARCHAR(20) NOT NULL,
                order_date DATE NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            )
        """
            )
        )

        # Create products table
        await conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                category VARCHAR(50),
                price DECIMAL(10,2) NOT NULL,
                stock INTEGER DEFAULT 0
            )
        """
            )
        )

        # Create order_items table
        await conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price DECIMAL(10,2) NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
        """
            )
        )

    # Seed with test data
    async with e2e_session_factory() as session:
        await seed_database(session, E2E_TEST_DATA)
        await session.commit()

    # Return schema info
    schema = SchemaInfo(
        database_id="e2e_test",
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
                    ColumnInfo(name="created_at", data_type="TIMESTAMP", nullable=True),
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
                    ColumnInfo(name="status", data_type="VARCHAR(20)", nullable=False),
                    ColumnInfo(name="order_date", data_type="DATE", nullable=False),
                ],
                primary_keys=["id"],
            ),
            TableInfo(
                name="products",
                columns=[
                    ColumnInfo(
                        name="id", data_type="INTEGER", nullable=False, primary_key=True
                    ),
                    ColumnInfo(name="name", data_type="VARCHAR(100)", nullable=False),
                    ColumnInfo(name="category", data_type="VARCHAR(50)", nullable=True),
                    ColumnInfo(name="price", data_type="DECIMAL(10,2)", nullable=False),
                    ColumnInfo(name="stock", data_type="INTEGER", nullable=True),
                ],
                primary_keys=["id"],
            ),
            TableInfo(
                name="order_items",
                columns=[
                    ColumnInfo(
                        name="id", data_type="INTEGER", nullable=False, primary_key=True
                    ),
                    ColumnInfo(
                        name="order_id",
                        data_type="INTEGER",
                        nullable=False,
                        foreign_key="orders.id",
                    ),
                    ColumnInfo(
                        name="product_id",
                        data_type="INTEGER",
                        nullable=False,
                        foreign_key="products.id",
                    ),
                    ColumnInfo(name="quantity", data_type="INTEGER", nullable=False),
                    ColumnInfo(
                        name="unit_price", data_type="DECIMAL(10,2)", nullable=False
                    ),
                ],
                primary_keys=["id"],
            ),
        ],
    )

    yield schema

    # Cleanup tables
    async with e2e_engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS order_items"))
        await conn.execute(text("DROP TABLE IF EXISTS orders"))
        await conn.execute(text("DROP TABLE IF EXISTS products"))
        await conn.execute(text("DROP TABLE IF EXISTS customers"))


# =============================================================================
# Registry Fixtures
# =============================================================================


@pytest_asyncio.fixture(scope="function")
async def e2e_registry(
    e2e_engine: Any,
    e2e_seeded_database: SchemaInfo,
) -> AsyncGenerator[DatabaseRegistry, None]:
    """
    Create a database registry with the E2E test database registered.

    This fixture provides a clean registry for each test function.
    """
    # Reset global registry
    reset_database_registry()

    # Create new registry
    registry = DatabaseRegistry()

    # Create config with in-memory SQLite
    config = DatabaseConfig(
        database_id="e2e_test",
        connection_string=get_e2e_database_url(),
        dialect=SQLDialect.SQLITE,
        display_name="E2E Test Database",
        description="Database for end-to-end testing",
    )

    # Register without connection test (we'll use the existing engine)
    await registry.register_database(config, test_connection=False)

    # Store schema
    registry.update_schema("e2e_test", e2e_seeded_database)

    yield registry

    # Cleanup
    await registry.close_all()
    reset_database_registry()


# =============================================================================
# API Client Fixtures
# =============================================================================


@pytest.fixture
def e2e_auth_headers() -> dict[str, str]:
    """Provide auth headers for E2E API tests."""
    return {"X-API-Key": "test-api-key"}


@pytest_asyncio.fixture(scope="function")
async def e2e_client(
    e2e_auth_headers: dict[str, str],
) -> AsyncGenerator[AsyncClient, None]:
    """Create an async HTTP client for E2E API tests."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://e2e-test",
        headers=e2e_auth_headers,
    ) as client:
        yield client


# =============================================================================
# Expected Results Fixtures
# =============================================================================


@pytest.fixture
def expected_customer_count() -> int:
    """Expected number of customers in seeded database."""
    return len(E2E_TEST_DATA["customers"])


@pytest.fixture
def expected_order_count() -> int:
    """Expected number of orders in seeded database."""
    return len(E2E_TEST_DATA["orders"])


@pytest.fixture
def expected_california_customers() -> int:
    """Expected number of California customers."""
    return sum(1 for c in E2E_TEST_DATA["customers"] if c["state"] == "California")


@pytest.fixture
def expected_pending_orders() -> int:
    """Expected number of pending orders."""
    return sum(1 for o in E2E_TEST_DATA["orders"] if o["status"] == "pending")


# =============================================================================
# Environment Setup Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def e2e_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure environment for E2E tests."""
    # Set test auth environment
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("JWT_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_KEY_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_KEYS", "test-api-key:read|write|admin")
    monkeypatch.setenv("SECRET_KEY", "e2e-test-secret-key-for-testing")

    # Set agent configuration
    monkeypatch.setenv("AGENT_ENABLED", "true")
    monkeypatch.setenv("AGENT_MAX_STEPS", "5")
    monkeypatch.setenv("AGENT_MIN_CONFIDENCE", "0.5")

    # Enable multi-database
    monkeypatch.setenv("MULTIDB_ENABLED", "true")

    # Disable cache for deterministic tests
    monkeypatch.setenv("CACHE_ENABLED", "false")

    # Clear settings cache
    get_settings.cache_clear()

    yield

    get_settings.cache_clear()


# =============================================================================
# Skip Conditions
# =============================================================================


@pytest.fixture
def skip_without_e2e() -> None:
    """Skip test if E2E tests are not enabled."""
    if not is_e2e_enabled():
        pytest.skip("E2E tests not enabled. Set E2E_TESTS_ENABLED=true")


@pytest.fixture
def skip_without_real_model() -> None:
    """Skip test if real model is not configured."""
    if not use_real_model():
        pytest.skip("Real model not configured. Set E2E_USE_REAL_MODEL=true")
