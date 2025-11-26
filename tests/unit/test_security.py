"""
Unit tests for security module.

Tests cover:
- JWT authentication
- API key validation
- Input validation
- SQL injection detection
- Rate limiting utilities
"""

import pytest
from datetime import timedelta
from jose import jwt

from app.config import get_settings
from app.security import (
    create_access_token,
    sanitize_input,
    scan_for_injection_patterns,
    validate_database_id,
    validate_natural_language_query,
    validate_sql_query,
    check_query_against_whitelist,
    verify_api_key,
)


class TestJWTAuthentication:
    """Tests for JWT token creation and validation."""

    def test_create_access_token(self):
        """Test JWT token creation."""
        token = create_access_token(data={"sub": "test_user"})
        assert token is not None
        assert isinstance(token, str)

        # Decode and verify
        settings = get_settings()
        payload = jwt.decode(
            token, settings.security.secret_key, algorithms=[settings.security.jwt_algorithm]
        )
        assert payload["sub"] == "test_user"
        assert "exp" in payload
        assert "iat" in payload

    def test_create_access_token_with_expiration(self):
        """Test JWT token creation with custom expiration."""
        token = create_access_token(
            data={"sub": "test_user"}, expires_delta=timedelta(minutes=5)
        )
        assert token is not None

        settings = get_settings()
        payload = jwt.decode(
            token, settings.security.secret_key, algorithms=[settings.security.jwt_algorithm]
        )
        assert payload["sub"] == "test_user"

    @pytest.mark.asyncio
    async def test_verify_api_key_valid(self):
        """Test API key verification with valid key."""
        settings = get_settings()
        is_valid = await verify_api_key(settings.security.secret_key)
        assert is_valid is True

    @pytest.mark.asyncio
    async def test_verify_api_key_invalid(self):
        """Test API key verification with invalid key."""
        is_valid = await verify_api_key("invalid_key")
        assert is_valid is False


class TestInputValidation:
    """Tests for input validation and sanitization."""

    def test_sanitize_input_normal(self):
        """Test sanitization of normal input."""
        result = sanitize_input("Hello World")
        assert result == "Hello World"

    def test_sanitize_input_with_null_bytes(self):
        """Test sanitization removes null bytes."""
        result = sanitize_input("Hello\x00World")
        assert result == "HelloWorld"
        assert "\x00" not in result

    def test_sanitize_input_max_length(self):
        """Test sanitization truncates to max length."""
        long_text = "a" * 2000
        result = sanitize_input(long_text, max_length=100)
        assert len(result) == 100

    def test_sanitize_input_control_characters(self):
        """Test sanitization removes control characters."""
        result = sanitize_input("Hello\x01\x02World\n\tTest")
        assert "Hello" in result
        assert "World" in result
        assert "\x01" not in result
        assert "\x02" not in result

    def test_validate_database_id_valid(self):
        """Test database ID validation with valid IDs."""
        test_cases = [
            "my_database",
            "test-db-123",
            "database1",
            "DB_name",
        ]
        for db_id in test_cases:
            is_valid, error = validate_database_id(db_id)
            assert is_valid is True, f"Failed for {db_id}: {error}"
            assert error is None

    def test_validate_database_id_invalid(self):
        """Test database ID validation with invalid IDs."""
        test_cases = [
            "",  # Empty
            "a" * 101,  # Too long
            "my database",  # Contains space
            "db@name",  # Special character
            "drop;table",  # Semicolon
            "-starts-with-dash",  # Starts with dash
        ]
        for db_id in test_cases:
            is_valid, error = validate_database_id(db_id)
            assert is_valid is False, f"Should fail for {db_id}"
            assert error is not None

    def test_validate_natural_language_query_valid(self):
        """Test natural language query validation with valid queries."""
        test_cases = [
            "Show me all users from California",
            "What is the total revenue for 2023?",
            "List top 10 customers by purchase amount",
        ]
        for query in test_cases:
            is_valid, errors = validate_natural_language_query(query)
            assert is_valid is True, f"Failed for: {query}, errors: {errors}"
            assert len(errors) == 0

    def test_validate_natural_language_query_invalid(self):
        """Test natural language query validation with invalid queries."""
        test_cases = [
            "Show",  # Too short
            "a" * 1001,  # Too long
            "",  # Empty
            "   ",  # Whitespace only
        ]
        for query in test_cases:
            is_valid, errors = validate_natural_language_query(query)
            assert is_valid is False, f"Should fail for: {query}"
            assert len(errors) > 0

    def test_validate_natural_language_query_suspicious(self):
        """Test detection of suspicious patterns in natural language queries."""
        test_cases = [
            "Show users UNION SELECT password FROM admin",
            "List customers; DROP TABLE users",
            "Get data DELETE FROM important_table",
        ]
        for query in test_cases:
            is_valid, errors = validate_natural_language_query(query)
            assert is_valid is False, f"Should detect suspicious pattern in: {query}"
            assert len(errors) > 0


class TestSQLInjectionDetection:
    """Tests for SQL injection pattern detection."""

    def test_scan_safe_query(self):
        """Test scanning a safe SQL query."""
        sql = "SELECT * FROM users WHERE id = 1"
        warnings = scan_for_injection_patterns(sql)
        assert len(warnings) == 0

    def test_scan_drop_table_injection(self):
        """Test detection of DROP TABLE injection."""
        sql = "SELECT * FROM users; DROP TABLE users;"
        warnings = scan_for_injection_patterns(sql)
        assert len(warnings) > 0
        assert any("DROP" in w for w in warnings)

    def test_scan_union_injection(self):
        """Test detection of UNION injection."""
        sql = "SELECT id FROM users UNION SELECT password FROM admin"
        warnings = scan_for_injection_patterns(sql)
        assert len(warnings) > 0
        assert any("UNION" in w for w in warnings)

    def test_scan_delete_injection(self):
        """Test detection of DELETE injection."""
        sql = "SELECT * FROM users; DELETE FROM users WHERE 1=1"
        warnings = scan_for_injection_patterns(sql)
        assert len(warnings) > 0
        assert any("DELETE" in w for w in warnings)

    def test_scan_comment_injection(self):
        """Test detection of SQL comments."""
        sql = "SELECT * FROM users WHERE id = 1 --"
        warnings = scan_for_injection_patterns(sql)
        assert len(warnings) > 0
        assert any("comment" in w.lower() for w in warnings)

    def test_scan_timing_attack(self):
        """Test detection of timing attack patterns."""
        test_cases = [
            "SELECT * FROM users WHERE SLEEP(5)",
            "SELECT BENCHMARK(1000000, MD5('test'))",
            "SELECT * FROM users; WAITFOR DELAY '00:00:05'",
        ]
        for sql in test_cases:
            warnings = scan_for_injection_patterns(sql)
            assert len(warnings) > 0, f"Should detect timing attack in: {sql}"
            assert any("timing" in w.lower() for w in warnings)

    def test_validate_sql_query_safe(self):
        """Test SQL validation with safe query."""
        sql = "SELECT name, email FROM users WHERE active = true"
        is_valid, errors = validate_sql_query(sql)
        assert is_valid is True
        assert len(errors) == 0

    def test_validate_sql_query_too_long(self):
        """Test SQL validation rejects overly long queries."""
        sql = "SELECT * FROM users WHERE " + " AND ".join([f"col{i} = 1" for i in range(1000)])
        is_valid, errors = validate_sql_query(sql, max_length=1000)
        assert is_valid is False
        assert any("maximum length" in e.lower() for e in errors)

    def test_validate_sql_query_empty(self):
        """Test SQL validation rejects empty queries."""
        is_valid, errors = validate_sql_query("")
        assert is_valid is False
        assert any("empty" in e.lower() for e in errors)

    def test_validate_sql_query_null_bytes(self):
        """Test SQL validation rejects queries with null bytes."""
        sql = "SELECT * FROM users\x00WHERE id = 1"
        is_valid, errors = validate_sql_query(sql)
        assert is_valid is False
        assert any("null bytes" in e.lower() for e in errors)


class TestQueryWhitelisting:
    """Tests for SQL query whitelisting."""

    def test_check_query_whitelist_safe(self):
        """Test whitelisting allows safe queries."""
        sql = "SELECT name, COUNT(*) FROM users GROUP BY name ORDER BY COUNT(*) DESC LIMIT 10"
        passes, forbidden = check_query_against_whitelist(sql)
        assert passes is True
        assert len(forbidden) == 0

    def test_check_query_whitelist_drop(self):
        """Test whitelisting blocks DROP statements."""
        sql = "DROP TABLE users"
        passes, forbidden = check_query_against_whitelist(sql)
        assert passes is False
        assert "DROP" in forbidden

    def test_check_query_whitelist_delete(self):
        """Test whitelisting blocks DELETE statements."""
        sql = "DELETE FROM users WHERE id = 1"
        passes, forbidden = check_query_against_whitelist(sql)
        assert passes is False
        assert "DELETE" in forbidden

    def test_check_query_whitelist_update(self):
        """Test whitelisting blocks UPDATE statements."""
        sql = "UPDATE users SET active = false"
        passes, forbidden = check_query_against_whitelist(sql)
        assert passes is False
        assert "UPDATE" in forbidden

    def test_check_query_whitelist_insert(self):
        """Test whitelisting blocks INSERT statements."""
        sql = "INSERT INTO users (name) VALUES ('test')"
        passes, forbidden = check_query_against_whitelist(sql)
        assert passes is False
        assert "INSERT" in forbidden

    def test_check_query_whitelist_complex_safe(self):
        """Test whitelisting with complex but safe query."""
        sql = """
        SELECT
            u.name,
            COUNT(o.id) as order_count,
            SUM(o.total) as total_revenue
        FROM users u
        LEFT JOIN orders o ON u.id = o.user_id
        WHERE u.active = true
        AND o.created_at BETWEEN '2023-01-01' AND '2023-12-31'
        GROUP BY u.name
        HAVING COUNT(o.id) > 5
        ORDER BY total_revenue DESC
        LIMIT 100
        """
        passes, forbidden = check_query_against_whitelist(sql)
        assert passes is True
        assert len(forbidden) == 0
