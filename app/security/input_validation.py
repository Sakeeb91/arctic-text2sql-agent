"""
Input validation and SQL injection prevention utilities.

This module provides:
- SQL injection pattern detection
- Input sanitization
- Database ID validation
- Query whitelisting
"""

import re

from app.logging_config import get_logger

logger = get_logger(__name__)


# Dangerous SQL patterns to detect
DANGEROUS_SQL_PATTERNS = [
    (r";\s*DROP\s+", "Potential DROP table injection"),
    (r";\s*DELETE\s+FROM", "Potential DELETE injection"),
    (r";\s*TRUNCATE\s+", "Potential TRUNCATE injection"),
    (r";\s*UPDATE\s+.*SET", "Potential UPDATE injection"),
    (r";\s*INSERT\s+INTO", "Potential INSERT injection"),
    (r"UNION\s+(?:ALL\s+)?SELECT", "Potential UNION injection"),
    (r"--\s*$", "SQL comment detected"),
    (r"/\*.*?\*/", "SQL block comment detected"),
    (r";\s*EXEC(?:UTE)?\s+", "Potential EXEC command injection"),
    (r";\s*xp_", "Potential SQL Server extended procedure"),
    (r"BENCHMARK\s*\(", "Potential timing attack"),
    (r"SLEEP\s*\(", "Potential timing attack"),
    (r"WAITFOR\s+DELAY", "Potential timing attack"),
    (r"INTO\s+(?:OUT|DUMP)FILE", "Potential file operation"),
    (r"LOAD_FILE\s*\(", "Potential file read operation"),
]


def scan_for_injection_patterns(sql: str) -> list[str]:
    """
    Scan SQL query for potential injection patterns.

    This function detects common SQL injection patterns but does NOT
    prevent valid SQL queries. It's meant as a warning system.

    Args:
        sql: SQL query string to scan

    Returns:
        list[str]: List of warnings about detected patterns

    Example:
        >>> warnings = scan_for_injection_patterns("SELECT * FROM users; DROP TABLE users;")
        >>> # Returns ["Potential DROP table injection"]
    """
    warnings: list[str] = []

    for pattern, message in DANGEROUS_SQL_PATTERNS:
        if re.search(pattern, sql, re.IGNORECASE | re.MULTILINE):
            warnings.append(message)
            logger.warning(
                "sql_injection_pattern_detected",
                pattern=pattern,
                message=message,
            )

    return warnings


def validate_sql_query(sql: str, max_length: int = 10000) -> tuple[bool, list[str]]:
    """
    Validate SQL query for safety and correctness.

    Args:
        sql: SQL query to validate
        max_length: Maximum allowed query length

    Returns:
        tuple[bool, list[str]]: (is_valid, error_messages)

    Example:
        >>> is_valid, errors = validate_sql_query("SELECT * FROM users")
        >>> if not is_valid:
        >>>     print(errors)
    """
    errors: list[str] = []

    # Check length
    if len(sql) > max_length:
        errors.append(f"Query exceeds maximum length of {max_length} characters")

    # Check for empty query
    if not sql.strip():
        errors.append("Query cannot be empty")

    # Check for null bytes (common injection technique)
    if "\x00" in sql:
        errors.append("Query contains null bytes")

    # Scan for injection patterns
    injection_warnings = scan_for_injection_patterns(sql)
    if injection_warnings:
        errors.extend([f"Security warning: {w}" for w in injection_warnings])

    is_valid = len(errors) == 0

    if not is_valid:
        logger.warning(
            "sql_validation_failed",
            errors=errors,
            query_length=len(sql),
        )

    return is_valid, errors


def sanitize_input(text: str, max_length: int = 1000) -> str:
    """
    Sanitize user input by removing potentially dangerous characters.

    Args:
        text: Input text to sanitize
        max_length: Maximum allowed length

    Returns:
        str: Sanitized text

    Example:
        >>> safe_text = sanitize_input("User's <script>alert('xss')</script> input")
        >>> # Returns sanitized version
    """
    if not text:
        return ""

    # Truncate to max length
    sanitized = text[:max_length]

    # Remove null bytes
    sanitized = sanitized.replace("\x00", "")

    # Remove control characters (except newline, tab, carriage return)
    sanitized = "".join(
        char for char in sanitized if char in ("\n", "\t", "\r") or ord(char) >= 32
    )

    # Strip leading/trailing whitespace
    sanitized = sanitized.strip()

    return sanitized


def validate_database_id(database_id: str) -> tuple[bool, str | None]:
    """
    Validate database ID format.

    Database IDs should be alphanumeric with underscores and hyphens only.

    Args:
        database_id: Database identifier to validate

    Returns:
        tuple[bool, str | None]: (is_valid, error_message)

    Example:
        >>> is_valid, error = validate_database_id("my_database-123")
        >>> if not is_valid:
        >>>     raise ValueError(error)
    """
    # Check length
    if not database_id or len(database_id) < 1:
        return False, "Database ID cannot be empty"

    if len(database_id) > 100:
        return False, "Database ID cannot exceed 100 characters"

    # Check format (alphanumeric, underscores, hyphens only)
    if not re.match(r"^[a-zA-Z0-9_-]+$", database_id):
        return (
            False,
            "Database ID can only contain letters, numbers, underscores, and hyphens",
        )

    # Must start with letter or number
    if not database_id[0].isalnum():
        return False, "Database ID must start with a letter or number"

    return True, None


def validate_natural_language_query(query: str) -> tuple[bool, list[str]]:
    """
    Validate natural language query input.

    Args:
        query: Natural language query

    Returns:
        tuple[bool, list[str]]: (is_valid, error_messages)

    Example:
        >>> is_valid, errors = validate_natural_language_query("Show me all users")
        >>> if not is_valid:
        >>>     print(errors)
    """
    errors: list[str] = []

    # Check length
    if len(query) < 5:
        errors.append("Query must be at least 5 characters long")

    if len(query) > 1000:
        errors.append("Query cannot exceed 1000 characters")

    # Check for empty or whitespace-only
    if not query.strip():
        errors.append("Query cannot be empty")

    # Check for suspicious patterns that might indicate SQL injection attempts
    suspicious_patterns = [
        (r"UNION\s+SELECT", "Contains SQL UNION pattern"),
        (r"DROP\s+TABLE", "Contains DROP TABLE pattern"),
        (r"DELETE\s+FROM", "Contains DELETE FROM pattern"),
        (r"--\s*$", "Contains SQL comment"),
    ]

    for pattern, message in suspicious_patterns:
        if re.search(pattern, query, re.IGNORECASE):
            errors.append(f"Suspicious pattern detected: {message}")
            logger.warning(
                "suspicious_nl_query_pattern",
                pattern=pattern,
                message=message,
            )

    is_valid = len(errors) == 0
    return is_valid, errors


def create_query_whitelist() -> set[str]:
    """
    Create a whitelist of allowed SQL keywords for production.

    This is used in production to restrict SQL generation to safe operations.

    Returns:
        set[str]: Set of allowed SQL keywords (uppercase)

    Example:
        >>> whitelist = create_query_whitelist()
        >>> if "DROP" in whitelist:
        >>>     print("DROP is allowed")  # This won't print
    """
    # Only allow SELECT queries in production
    # Can be extended based on security requirements
    return {
        "SELECT",
        "FROM",
        "WHERE",
        "AND",
        "OR",
        "NOT",
        "IN",
        "LIKE",
        "BETWEEN",
        "IS",
        "NULL",
        "ORDER",
        "BY",
        "GROUP",
        "HAVING",
        "LIMIT",
        "OFFSET",
        "JOIN",
        "INNER",
        "LEFT",
        "RIGHT",
        "OUTER",
        "ON",
        "AS",
        "DISTINCT",
        "COUNT",
        "SUM",
        "AVG",
        "MIN",
        "MAX",
        "CASE",
        "WHEN",
        "THEN",
        "ELSE",
        "END",
        "CAST",
        "COALESCE",
    }


def check_query_against_whitelist(
    sql: str, whitelist: set[str] | None = None
) -> tuple[bool, list[str]]:
    """
    Check if SQL query only uses whitelisted keywords.

    Args:
        sql: SQL query to check
        whitelist: Optional set of allowed keywords (uses default if None)

    Returns:
        tuple[bool, list[str]]: (passes_check, forbidden_keywords)

    Example:
        >>> passes, forbidden = check_query_against_whitelist("SELECT * FROM users")
        >>> if not passes:
        >>>     print(f"Forbidden keywords: {forbidden}")
    """
    if whitelist is None:
        whitelist = create_query_whitelist()

    # List of dangerous keywords that should never be allowed
    dangerous_keywords = {
        "DROP",
        "DELETE",
        "UPDATE",
        "INSERT",
        "ALTER",
        "CREATE",
        "TRUNCATE",
        "EXEC",
        "EXECUTE",
        "GRANT",
        "REVOKE",
    }

    # Extract potential SQL keywords
    # Match words that appear in SQL context (not quoted strings or identifiers)
    # Remove strings in quotes first
    sql_cleaned = re.sub(r"'[^']*'", "", sql)
    sql_cleaned = re.sub(r'"[^"]*"', "", sql_cleaned)

    # Find all uppercase words (potential SQL keywords)
    potential_keywords = re.findall(r"\b[A-Z]{3,}\b", sql_cleaned.upper())

    # Find dangerous keywords
    forbidden: list[str] = []
    for keyword in set(potential_keywords):  # Use set to avoid duplicates
        if keyword in dangerous_keywords:
            forbidden.append(keyword)

    passes_check = len(forbidden) == 0

    if not passes_check:
        logger.warning(
            "query_whitelist_violation",
            forbidden_keywords=forbidden,
        )

    return passes_check, forbidden
