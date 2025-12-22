"""
Test data seeding utilities for E2E tests.

This module provides deterministic test data and utilities for
seeding the test database with known values.
"""

from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# =============================================================================
# Test Data Definitions
# =============================================================================


E2E_TEST_DATA: dict[str, list[dict[str, Any]]] = {
    "customers": [
        {
            "id": 1,
            "name": "Alice Johnson",
            "email": "alice@example.com",
            "state": "California",
        },
        {
            "id": 2,
            "name": "Bob Smith",
            "email": "bob@example.com",
            "state": "New York",
        },
        {
            "id": 3,
            "name": "Charlie Brown",
            "email": "charlie@example.com",
            "state": "California",
        },
        {
            "id": 4,
            "name": "Diana Ross",
            "email": "diana@example.com",
            "state": "Texas",
        },
        {
            "id": 5,
            "name": "Edward Chen",
            "email": "edward@example.com",
            "state": "Washington",
        },
        {
            "id": 6,
            "name": "Fiona Williams",
            "email": "fiona@example.com",
            "state": "California",
        },
        {
            "id": 7,
            "name": "George Miller",
            "email": "george@example.com",
            "state": "Florida",
        },
        {
            "id": 8,
            "name": "Hannah Davis",
            "email": "hannah@example.com",
            "state": "New York",
        },
        {
            "id": 9,
            "name": "Ivan Petrov",
            "email": "ivan@example.com",
            "state": "Illinois",
        },
        {
            "id": 10,
            "name": "Julia Martinez",
            "email": "julia@example.com",
            "state": "Texas",
        },
    ],
    "products": [
        {
            "id": 1,
            "name": "Laptop",
            "category": "Electronics",
            "price": 999.99,
            "stock": 50,
        },
        {
            "id": 2,
            "name": "Mouse",
            "category": "Electronics",
            "price": 29.99,
            "stock": 200,
        },
        {
            "id": 3,
            "name": "Keyboard",
            "category": "Electronics",
            "price": 79.99,
            "stock": 150,
        },
        {
            "id": 4,
            "name": "Monitor",
            "category": "Electronics",
            "price": 349.99,
            "stock": 75,
        },
        {
            "id": 5,
            "name": "Desk Chair",
            "category": "Furniture",
            "price": 199.99,
            "stock": 30,
        },
        {
            "id": 6,
            "name": "Standing Desk",
            "category": "Furniture",
            "price": 449.99,
            "stock": 25,
        },
        {
            "id": 7,
            "name": "Notebook",
            "category": "Office",
            "price": 4.99,
            "stock": 500,
        },
        {
            "id": 8,
            "name": "Pen Set",
            "category": "Office",
            "price": 12.99,
            "stock": 300,
        },
        {
            "id": 9,
            "name": "Headphones",
            "category": "Electronics",
            "price": 149.99,
            "stock": 100,
        },
        {
            "id": 10,
            "name": "Webcam",
            "category": "Electronics",
            "price": 89.99,
            "stock": 80,
        },
    ],
    "orders": [
        {
            "id": 1,
            "customer_id": 1,
            "amount": 1029.98,
            "status": "completed",
            "order_date": "2024-01-15",
        },
        {
            "id": 2,
            "customer_id": 2,
            "amount": 379.98,
            "status": "completed",
            "order_date": "2024-01-16",
        },
        {
            "id": 3,
            "customer_id": 1,
            "amount": 149.99,
            "status": "pending",
            "order_date": "2024-01-20",
        },
        {
            "id": 4,
            "customer_id": 3,
            "amount": 999.99,
            "status": "completed",
            "order_date": "2024-01-22",
        },
        {
            "id": 5,
            "customer_id": 4,
            "amount": 449.99,
            "status": "shipped",
            "order_date": "2024-01-25",
        },
        {
            "id": 6,
            "customer_id": 5,
            "amount": 109.98,
            "status": "completed",
            "order_date": "2024-02-01",
        },
        {
            "id": 7,
            "customer_id": 2,
            "amount": 1349.97,
            "status": "pending",
            "order_date": "2024-02-05",
        },
        {
            "id": 8,
            "customer_id": 6,
            "amount": 79.99,
            "status": "completed",
            "order_date": "2024-02-10",
        },
        {
            "id": 9,
            "customer_id": 7,
            "amount": 199.99,
            "status": "shipped",
            "order_date": "2024-02-15",
        },
        {
            "id": 10,
            "customer_id": 1,
            "amount": 89.99,
            "status": "pending",
            "order_date": "2024-02-20",
        },
        {
            "id": 11,
            "customer_id": 8,
            "amount": 259.98,
            "status": "completed",
            "order_date": "2024-02-22",
        },
        {
            "id": 12,
            "customer_id": 3,
            "amount": 649.98,
            "status": "pending",
            "order_date": "2024-02-25",
        },
        {
            "id": 13,
            "customer_id": 9,
            "amount": 17.98,
            "status": "completed",
            "order_date": "2024-03-01",
        },
        {
            "id": 14,
            "customer_id": 10,
            "amount": 449.99,
            "status": "shipped",
            "order_date": "2024-03-05",
        },
        {
            "id": 15,
            "customer_id": 4,
            "amount": 239.98,
            "status": "completed",
            "order_date": "2024-03-10",
        },
    ],
    "order_items": [
        {"id": 1, "order_id": 1, "product_id": 1, "quantity": 1, "unit_price": 999.99},
        {"id": 2, "order_id": 1, "product_id": 2, "quantity": 1, "unit_price": 29.99},
        {"id": 3, "order_id": 2, "product_id": 3, "quantity": 1, "unit_price": 79.99},
        {"id": 4, "order_id": 2, "product_id": 4, "quantity": 1, "unit_price": 299.99},
        {"id": 5, "order_id": 3, "product_id": 9, "quantity": 1, "unit_price": 149.99},
        {"id": 6, "order_id": 4, "product_id": 1, "quantity": 1, "unit_price": 999.99},
        {"id": 7, "order_id": 5, "product_id": 6, "quantity": 1, "unit_price": 449.99},
        {"id": 8, "order_id": 6, "product_id": 2, "quantity": 1, "unit_price": 29.99},
        {"id": 9, "order_id": 6, "product_id": 3, "quantity": 1, "unit_price": 79.99},
        {"id": 10, "order_id": 7, "product_id": 1, "quantity": 1, "unit_price": 999.99},
        {"id": 11, "order_id": 7, "product_id": 4, "quantity": 1, "unit_price": 349.99},
        {"id": 12, "order_id": 8, "product_id": 3, "quantity": 1, "unit_price": 79.99},
        {"id": 13, "order_id": 9, "product_id": 5, "quantity": 1, "unit_price": 199.99},
        {
            "id": 14,
            "order_id": 10,
            "product_id": 10,
            "quantity": 1,
            "unit_price": 89.99,
        },
        {
            "id": 15,
            "order_id": 11,
            "product_id": 9,
            "quantity": 1,
            "unit_price": 149.99,
        },
        {"id": 16, "order_id": 11, "product_id": 2, "quantity": 2, "unit_price": 29.99},
        {"id": 17, "order_id": 11, "product_id": 7, "quantity": 10, "unit_price": 4.99},
        {
            "id": 18,
            "order_id": 12,
            "product_id": 6,
            "quantity": 1,
            "unit_price": 449.99,
        },
        {
            "id": 19,
            "order_id": 12,
            "product_id": 5,
            "quantity": 1,
            "unit_price": 199.99,
        },
        {"id": 20, "order_id": 13, "product_id": 7, "quantity": 2, "unit_price": 4.99},
        {"id": 21, "order_id": 13, "product_id": 8, "quantity": 1, "unit_price": 12.99},
        {
            "id": 22,
            "order_id": 14,
            "product_id": 6,
            "quantity": 1,
            "unit_price": 449.99,
        },
        {
            "id": 23,
            "order_id": 15,
            "product_id": 9,
            "quantity": 1,
            "unit_price": 149.99,
        },
        {
            "id": 24,
            "order_id": 15,
            "product_id": 10,
            "quantity": 1,
            "unit_price": 89.99,
        },
    ],
}


# =============================================================================
# Expected Values for Verification
# =============================================================================


class ExpectedValues:
    """Pre-calculated expected values for E2E test assertions."""

    # Customer counts
    TOTAL_CUSTOMERS = 10
    CALIFORNIA_CUSTOMERS = 3  # Alice, Charlie, Fiona
    NEW_YORK_CUSTOMERS = 2  # Bob, Hannah
    TEXAS_CUSTOMERS = 2  # Diana, Julia

    # Order counts
    TOTAL_ORDERS = 15
    COMPLETED_ORDERS = 8
    PENDING_ORDERS = 4
    SHIPPED_ORDERS = 3

    # Product counts
    TOTAL_PRODUCTS = 10
    ELECTRONICS_PRODUCTS = 6
    FURNITURE_PRODUCTS = 2
    OFFICE_PRODUCTS = 2

    # Order amounts
    TOTAL_ORDER_AMOUNT = Decimal("6454.73")
    MAX_ORDER_AMOUNT = Decimal("1349.97")
    MIN_ORDER_AMOUNT = Decimal("17.98")

    # Customers with most orders
    TOP_CUSTOMER_ID = 1  # Alice has 3 orders
    TOP_CUSTOMER_ORDER_COUNT = 3


# =============================================================================
# Seeding Utilities
# =============================================================================


async def seed_database(
    session: AsyncSession,
    data: dict[str, list[dict[str, Any]]],
) -> None:
    """
    Seed the database with test data.

    Args:
        session: Database session
        data: Dictionary of table data to insert
    """
    # Insert customers
    for customer in data.get("customers", []):
        await session.execute(
            text(
                """
                INSERT OR REPLACE INTO customers (id, name, email, state)
                VALUES (:id, :name, :email, :state)
            """
            ),
            customer,
        )

    # Insert products
    for product in data.get("products", []):
        await session.execute(
            text(
                """
                INSERT OR REPLACE INTO products (id, name, category, price, stock)
                VALUES (:id, :name, :category, :price, :stock)
            """
            ),
            product,
        )

    # Insert orders
    for order in data.get("orders", []):
        await session.execute(
            text(
                """
                INSERT OR REPLACE INTO orders (id, customer_id, amount, status, order_date)
                VALUES (:id, :customer_id, :amount, :status, :order_date)
            """
            ),
            order,
        )

    # Insert order items
    for item in data.get("order_items", []):
        await session.execute(
            text(
                """
                INSERT OR REPLACE INTO order_items (id, order_id, product_id, quantity, unit_price)
                VALUES (:id, :order_id, :product_id, :quantity, :unit_price)
            """
            ),
            item,
        )


async def clear_database(session: AsyncSession) -> None:
    """Clear all test data from the database."""
    await session.execute(text("DELETE FROM order_items"))
    await session.execute(text("DELETE FROM orders"))
    await session.execute(text("DELETE FROM products"))
    await session.execute(text("DELETE FROM customers"))


async def reset_database(
    session: AsyncSession,
    data: dict[str, list[dict[str, Any]]] | None = None,
) -> None:
    """Clear and re-seed the database."""
    await clear_database(session)
    await seed_database(session, data or E2E_TEST_DATA)
    await session.commit()


# =============================================================================
# Query Expectations
# =============================================================================


# Natural language queries and their expected SQL patterns/results
E2E_QUERY_EXPECTATIONS: list[dict[str, Any]] = [
    # Simple SELECT
    {
        "query": "Show all customers",
        "expected_keywords": ["SELECT", "customers"],
        "expected_row_count": ExpectedValues.TOTAL_CUSTOMERS,
        "complexity": "simple",
    },
    # Filtering
    {
        "query": "Show customers from California",
        "expected_keywords": ["SELECT", "customers", "California"],
        "expected_row_count": ExpectedValues.CALIFORNIA_CUSTOMERS,
        "complexity": "simple",
    },
    # Aggregation
    {
        "query": "How many orders are there?",
        "expected_keywords": ["SELECT", "COUNT", "orders"],
        "expected_value": ExpectedValues.TOTAL_ORDERS,
        "complexity": "moderate",
    },
    # Grouping
    {
        "query": "Count orders by status",
        "expected_keywords": ["SELECT", "COUNT", "GROUP BY", "status"],
        "complexity": "moderate",
    },
    # JOIN
    {
        "query": "Show customer names with their order amounts",
        "expected_keywords": ["SELECT", "customers", "orders", "JOIN"],
        "complexity": "moderate",
    },
    # Ordering
    {
        "query": "Show all products ordered by price descending",
        "expected_keywords": ["SELECT", "products", "ORDER BY", "DESC"],
        "expected_row_count": ExpectedValues.TOTAL_PRODUCTS,
        "complexity": "simple",
    },
    # Pagination
    {
        "query": "Show the top 5 most expensive products",
        "expected_keywords": ["SELECT", "products", "ORDER BY", "LIMIT"],
        "expected_row_count": 5,
        "complexity": "simple",
    },
    # Aggregation with filtering
    {
        "query": "What is the total amount of completed orders?",
        "expected_keywords": ["SELECT", "SUM", "orders", "completed"],
        "complexity": "moderate",
    },
    # Complex JOIN with aggregation
    {
        "query": "Which customer has the most orders?",
        "expected_keywords": ["SELECT", "COUNT", "GROUP BY", "ORDER BY", "LIMIT"],
        "complexity": "complex",
    },
    # Subquery or HAVING
    {
        "query": "Show customers who have more than 2 orders",
        "expected_keywords": ["SELECT", "COUNT", "HAVING"],
        "complexity": "complex",
    },
]


def get_test_queries_by_complexity(
    complexity: str,
) -> list[dict[str, Any]]:
    """Get test queries filtered by complexity level."""
    return [q for q in E2E_QUERY_EXPECTATIONS if q.get("complexity") == complexity]


def get_all_test_queries() -> list[dict[str, Any]]:
    """Get all test queries."""
    return E2E_QUERY_EXPECTATIONS
