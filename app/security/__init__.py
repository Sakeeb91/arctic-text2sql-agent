"""
Security module for Arctic Text2SQL Agent.

This module provides:
- JWT authentication
- API key authentication
- Rate limiting
- SQL injection prevention
- Input validation and sanitization
- Security headers
"""

from app.security.auth import (
    create_access_token,
    get_current_user,
    verify_api_key,
    verify_token,
)
from app.security.headers import SecurityHeadersMiddleware
from app.security.input_validation import (
    check_query_against_whitelist,
    create_query_whitelist,
    sanitize_input,
    scan_for_injection_patterns,
    validate_database_id,
    validate_natural_language_query,
    validate_sql_query,
)
from app.security.rate_limiting import limiter, setup_rate_limiting

__all__ = [
    # Authentication
    "create_access_token",
    "verify_token",
    "verify_api_key",
    "get_current_user",
    # Rate limiting
    "limiter",
    "setup_rate_limiting",
    # Input validation
    "sanitize_input",
    "validate_sql_query",
    "validate_database_id",
    "validate_natural_language_query",
    "scan_for_injection_patterns",
    "create_query_whitelist",
    "check_query_against_whitelist",
    # Security headers
    "SecurityHeadersMiddleware",
]
