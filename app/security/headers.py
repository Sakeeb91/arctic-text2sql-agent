"""
Security headers middleware.

This module provides security headers to protect against common vulnerabilities:
- XSS (Cross-Site Scripting)
- Clickjacking
- MIME type sniffing
- Information disclosure
"""

from collections.abc import Callable
from typing import Any, cast

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.logging_config import get_logger

logger = get_logger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to all responses.

    Headers added:
    - X-Content-Type-Options: Prevent MIME type sniffing
    - X-Frame-Options: Prevent clickjacking
    - X-XSS-Protection: Enable XSS filter (legacy browsers)
    - Strict-Transport-Security: Enforce HTTPS
    - Content-Security-Policy: Prevent XSS and data injection
    - Referrer-Policy: Control referrer information
    - Permissions-Policy: Control browser features
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Any]
    ) -> Response:
        """Add security headers to response."""
        response = await call_next(request)

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # XSS protection (legacy, but doesn't hurt)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Enforce HTTPS (commented out for development, enable in production)
        # Uncomment the following line in production with HTTPS
        # response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Content Security Policy - restrictive for API
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; " "frame-ancestors 'none'; " "base-uri 'none';"
        )

        # Referrer policy - don't leak referrer to external sites
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions policy - disable unnecessary features
        response.headers["Permissions-Policy"] = (
            "geolocation=(), "
            "microphone=(), "
            "camera=(), "
            "payment=(), "
            "usb=(), "
            "magnetometer=(), "
            "gyroscope=(), "
            "accelerometer=()"
        )

        # Remove server header to avoid information disclosure
        if "Server" in response.headers:
            del response.headers["Server"]

        # Remove X-Powered-By if present
        if "X-Powered-By" in response.headers:
            del response.headers["X-Powered-By"]

        return cast(Response, response)
