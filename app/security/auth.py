"""
Authentication utilities for JWT and API key authentication.

This module provides:
- JWT token creation and validation
- API key authentication
- User authentication dependencies for FastAPI routes
"""

import secrets
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import Depends, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import get_settings
from app.exceptions import AuthenticationException, AuthorizationException
from app.logging_config import get_logger

logger = get_logger(__name__)
security = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    """Authenticated principal context."""

    subject: str
    scopes: set[str]
    auth_type: Literal["jwt", "api_key", "disabled"]
    token_data: dict[str, Any] | None = None


def _split_scopes(raw_scopes: str) -> list[str]:
    normalized = raw_scopes.replace("|", ",").replace(" ", ",")
    return [scope.strip().lower() for scope in normalized.split(",") if scope.strip()]


def _normalize_scopes(scopes: Iterable[str]) -> set[str]:
    return {scope.strip().lower() for scope in scopes if scope.strip()}


def _mask_secret(secret: str) -> str:
    if len(secret) <= 6:
        return "***"
    return f"{secret[:3]}***{secret[-3:]}"


def _parse_api_keys() -> dict[str, set[str]]:
    settings = get_settings()
    default_scopes = _normalize_scopes(settings.security.api_key_scopes_list)
    if not settings.security.api_keys:
        return {}

    keys: dict[str, set[str]] = {}
    for entry in settings.security.api_keys.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            key, scopes_raw = entry.split(":", 1)
            key = key.strip()
            scopes = _normalize_scopes(_split_scopes(scopes_raw))
            if not scopes:
                scopes = default_scopes
        else:
            key = entry.strip()
            scopes = default_scopes
        if key:
            keys[key] = scopes
    return keys


def _parse_auth_users() -> dict[str, tuple[str, set[str]]]:
    settings = get_settings()
    if not settings.security.auth_users:
        return {}

    default_scopes = _normalize_scopes(settings.security.api_key_scopes_list)
    users: dict[str, tuple[str, set[str]]] = {}
    raw_entries = [
        entry.strip()
        for entry in settings.security.auth_users.split(";")
        if entry.strip()
    ]
    if not raw_entries and settings.security.auth_users.strip():
        raw_entries = [settings.security.auth_users.strip()]

    for entry in raw_entries:
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":", 2)
        if len(parts) < 2:
            continue
        username = parts[0].strip()
        password = parts[1]
        scopes = default_scopes
        if len(parts) == 3:
            scopes = _normalize_scopes(_split_scopes(parts[2])) or default_scopes
        if username:
            users[username] = (password, scopes)
    return users


def _role_scopes(role: str | None) -> set[str]:
    if not role:
        return set()
    role_value = role.strip().lower()
    if role_value == "admin":
        return {"admin", "write", "read"}
    if role_value in {"writer", "write"}:
        return {"write", "read"}
    if role_value in {"reader", "read"}:
        return {"read"}
    return {role_value}


def _extract_scopes(payload: dict[str, Any]) -> set[str]:
    settings = get_settings()
    scopes: set[str] = set()
    claim_value = payload.get(settings.security.jwt_scopes_claim)
    if isinstance(claim_value, str):
        scopes |= _normalize_scopes(_split_scopes(claim_value))
    elif isinstance(claim_value, (list, tuple, set)):
        scopes |= _normalize_scopes([str(scope) for scope in claim_value])

    role_value = payload.get(settings.security.jwt_role_claim)
    if isinstance(role_value, str):
        scopes |= _role_scopes(role_value)

    if not scopes:
        scopes = _normalize_scopes(settings.security.api_key_scopes_list)
    return scopes


def create_access_token(
    data: dict[str, Any], expires_delta: timedelta | None = None
) -> str:
    """
    Create a JWT access token.

    Args:
        data: Payload data to encode in the token
        expires_delta: Optional expiration time delta (defaults to config value)

    Returns:
        str: Encoded JWT token

    Example:
        >>> token = create_access_token({"sub": "user123"})
        >>> # Returns JWT token string
    """
    settings = get_settings()
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.security.jwt_access_token_expire_minutes
        )

    to_encode.update({"exp": expire, "iat": datetime.utcnow()})

    encoded_jwt: str = jwt.encode(
        to_encode,
        settings.security.secret_key,
        algorithm=settings.security.jwt_algorithm,
    )

    logger.info("jwt_token_created", subject=data.get("sub"), expires_at=expire)
    return encoded_jwt


async def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
) -> dict[str, Any]:
    """
    Verify JWT token from Authorization header.

    Args:
        credentials: HTTP authorization credentials from request

    Returns:
        dict: Decoded token payload

    Raises:
        AuthenticationException: If token is invalid or expired

    Example:
        >>> @app.get("/protected")
        >>> async def protected_route(token_data: dict = Depends(verify_token)):
        >>>     return {"user": token_data["sub"]}
    """
    settings = get_settings()

    if not settings.security.jwt_enabled:
        raise AuthenticationException(message="JWT authentication is disabled")

    if credentials is None:
        raise AuthenticationException(message="Missing authentication credentials")

    try:
        payload: dict[str, Any] = jwt.decode(
            credentials.credentials,
            settings.security.secret_key,
            algorithms=[settings.security.jwt_algorithm],
        )
    except JWTError as e:
        logger.warning("jwt_verification_failed", error=str(e))
        raise AuthenticationException(
            message="Invalid authentication credentials"
        ) from e

    exp = payload.get("exp")
    if exp is None:
        logger.warning("jwt_verification_failed", reason="missing_expiration")
        raise AuthenticationException(message="Invalid authentication credentials")

    if datetime.utcnow().timestamp() > exp:
        logger.warning("jwt_verification_failed", reason="token_expired")
        raise AuthenticationException(message="Token has expired")

    logger.debug("jwt_verified", subject=payload.get("sub"))
    return payload


async def verify_api_key(api_key: str) -> bool:
    """
    Verify API key authentication.

    Args:
        api_key: API key to validate

    Returns:
        bool: True if API key is valid

    Note:
        In production, this should validate against a database of API keys.
        For now, it validates against configured API keys.

    Example:
        >>> from fastapi import Header
        >>> @app.get("/api/endpoint")
        >>> async def endpoint(x_api_key: str = Header(...)):
        >>>     if not await verify_api_key(x_api_key):
        >>>         raise HTTPException(401, "Invalid API key")
    """
    settings = get_settings()
    if not settings.security.api_key_enabled:
        return False

    api_keys = _parse_api_keys()
    is_valid = api_key in api_keys

    if is_valid:
        logger.debug("api_key_verified")
    else:
        logger.warning("api_key_verification_failed")

    return is_valid


async def get_current_user(
    token_data: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    """
    Get current authenticated user from JWT token.

    Args:
        token_data: Decoded JWT token data

    Returns:
        dict: User information from token

    Raises:
        AuthenticationException: If user data is invalid

    Example:
        >>> @app.get("/me")
        >>> async def get_me(user: dict = Depends(get_current_user)):
        >>>     return user
    """
    user_id = token_data.get("sub")
    if user_id is None:
        logger.warning("get_current_user_failed", reason="missing_subject")
        raise AuthenticationException(message="Invalid authentication credentials")

    # In production, fetch user from database
    # For now, return token data
    return {
        "user_id": user_id,
        "token_data": token_data,
    }


def authenticate_user(username: str, password: str) -> set[str] | None:
    """
    Authenticate user credentials against configured users.

    Returns:
        set[str] | None: scopes for user if credentials are valid
    """
    users = _parse_auth_users()
    if not users:
        logger.warning("auth_users_not_configured")
        return None

    entry = users.get(username)
    if not entry:
        logger.warning("auth_user_not_found", username=username)
        return None

    stored_password, scopes = entry
    if not secrets.compare_digest(stored_password, password):
        logger.warning("auth_user_password_mismatch", username=username)
        return None

    return scopes


async def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
    api_key: str | None = Security(api_key_header),
) -> AuthContext:
    """
    Resolve authentication context from JWT or API key.

    Returns:
        AuthContext: Authenticated principal data
    """
    settings = get_settings()
    if not settings.security.auth_enabled:
        return AuthContext(
            subject="anonymous",
            scopes={"read", "write", "admin"},
            auth_type="disabled",
        )

    if api_key and settings.security.api_key_enabled:
        api_keys = _parse_api_keys()
        scopes = api_keys.get(api_key)
        if scopes:
            logger.debug("api_key_authenticated", api_key=_mask_secret(api_key))
            return AuthContext(
                subject=f"api_key:{_mask_secret(api_key)}",
                scopes=scopes,
                auth_type="api_key",
            )
        logger.warning("api_key_authentication_failed", api_key=_mask_secret(api_key))
        raise AuthenticationException(message="Invalid API key")

    if credentials and settings.security.jwt_enabled:
        payload = await verify_token(credentials)
        subject = payload.get("sub")
        if not subject:
            raise AuthenticationException(message="Token missing subject")
        scopes = _extract_scopes(payload)
        return AuthContext(
            subject=str(subject),
            scopes=scopes,
            auth_type="jwt",
            token_data=payload,
        )

    raise AuthenticationException(message="Missing authentication credentials")


def ensure_scopes(
    auth: AuthContext, required_scopes: set[str], resource: str | None = None
) -> None:
    """Ensure the authenticated principal has required scopes."""
    if not required_scopes:
        return
    if auth.scopes.intersection(required_scopes):
        return
    details = {"required_scopes": sorted(required_scopes)}
    raise AuthorizationException(
        message="Insufficient permissions",
        resource=resource,
        details=details,
    )


async def require_auth(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
    """Require any authenticated principal."""
    return auth


def require_scopes(
    required_scopes: set[str],
) -> Callable[..., Awaitable[AuthContext]]:
    """Factory for scope-enforcing dependencies."""

    async def _require(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        ensure_scopes(auth, required_scopes)
        return auth

    return _require


async def require_mutation_scope(
    auth: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    """Require mutation scopes for write/management operations."""
    settings = get_settings()
    required_scopes = _normalize_scopes(settings.security.mutation_scopes_list)
    ensure_scopes(auth, required_scopes, resource="mutation")
    return auth
