"""
Authentication utilities for JWT and API key authentication.

This module provides:
- JWT token creation and validation
- API key authentication
- User authentication dependencies for FastAPI routes
"""

from datetime import datetime, timedelta
from typing import Any

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)
security = HTTPBearer()


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
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> dict[str, Any]:
    """
    Verify JWT token from Authorization header.

    Args:
        credentials: HTTP authorization credentials from request

    Returns:
        dict: Decoded token payload

    Raises:
        HTTPException: If token is invalid or expired

    Example:
        >>> @app.get("/protected")
        >>> async def protected_route(token_data: dict = Depends(verify_token)):
        >>>     return {"user": token_data["sub"]}
    """
    settings = get_settings()

    try:
        payload: dict[str, Any] = jwt.decode(
            credentials.credentials,
            settings.security.secret_key,
            algorithms=[settings.security.jwt_algorithm],
        )

        # Validate expiration
        exp = payload.get("exp")
        if exp is None:
            logger.warning("jwt_verification_failed", reason="missing_expiration")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if datetime.utcnow().timestamp() > exp:
            logger.warning("jwt_verification_failed", reason="token_expired")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )

        logger.debug("jwt_verified", subject=payload.get("sub"))
        return payload

    except JWTError as e:
        logger.warning("jwt_verification_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


async def verify_api_key(api_key: str) -> bool:
    """
    Verify API key authentication.

    Args:
        api_key: API key to validate

    Returns:
        bool: True if API key is valid

    Note:
        In production, this should validate against a database of API keys.
        For now, it validates against the SECRET_KEY from settings.

    Example:
        >>> from fastapi import Header
        >>> @app.get("/api/endpoint")
        >>> async def endpoint(x_api_key: str = Header(...)):
        >>>     if not await verify_api_key(x_api_key):
        >>>         raise HTTPException(401, "Invalid API key")
    """
    settings = get_settings()

    # Simple validation against secret key for now
    # In production, check against database of valid API keys
    is_valid = api_key == settings.security.secret_key

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
        HTTPException: If user data is invalid

    Example:
        >>> @app.get("/me")
        >>> async def get_me(user: dict = Depends(get_current_user)):
        >>>     return user
    """
    user_id = token_data.get("sub")
    if user_id is None:
        logger.warning("get_current_user_failed", reason="missing_subject")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )

    # In production, fetch user from database
    # For now, return token data
    return {
        "user_id": user_id,
        "token_data": token_data,
    }
