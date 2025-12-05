"""
Rate limiting utilities using slowapi.

This module provides:
- Request rate limiting
- Configurable limits per endpoint
- Rate limit exceeded handling
"""

from typing import Any

from fastapi import FastAPI, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)


def get_rate_limit_key(request: Request) -> str:
    """
    Get rate limit key from request.

    Uses remote address by default. Can be extended to use
    API keys or user IDs for authenticated requests.

    Args:
        request: FastAPI request object

    Returns:
        str: Rate limit key (client IP address)
    """
    # Check for API key in headers
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"api_key:{api_key}"

    # Check for JWT token
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        token = auth.split(" ")[1]
        # Use a hash of the token to avoid storing full tokens
        import hashlib

        token_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
        return f"token:{token_hash}"

    # Fallback to IP address
    ip_address: str = get_remote_address(request)
    return ip_address


# Initialize limiter with configuration
settings = get_settings()
limiter = Limiter(
    key_func=get_rate_limit_key,
    default_limits=[
        f"{settings.api.rate_limit_per_minute}/minute",
    ],
    storage_uri="memory://",  # Use in-memory storage (upgrade to Redis in production)
)


def setup_rate_limiting(app: FastAPI) -> None:
    """
    Configure rate limiting for FastAPI application.

    Args:
        app: FastAPI application instance

    Example:
        >>> from fastapi import FastAPI
        >>> from app.security.rate_limiting import setup_rate_limiting
        >>>
        >>> app = FastAPI()
        >>> setup_rate_limiting(app)
    """
    app.state.limiter = limiter
    app.add_exception_handler(
        RateLimitExceeded, _rate_limit_exceeded_handler  # type: ignore[arg-type]
    )

    logger.info(
        "rate_limiting_configured",
        rate_limit_per_minute=settings.api.rate_limit_per_minute,
        rate_limit_burst=settings.api.rate_limit_burst,
    )


# Custom rate limit exceeded handler with logging
async def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> dict[str, Any]:
    """
    Custom handler for rate limit exceeded errors.

    Args:
        request: FastAPI request object
        exc: RateLimitExceeded exception

    Returns:
        dict: Error response
    """
    logger.warning(
        "rate_limit_exceeded",
        path=request.url.path,
        client=get_rate_limit_key(request),
    )

    retry_after: str | None = exc.retry_after if hasattr(exc, "retry_after") else None
    return {
        "error": {
            "code": "RATE_LIMIT_EXCEEDED",
            "message": "Too many requests. Please try again later.",
            "details": {
                "retry_after": retry_after,
            },
        }
    }
