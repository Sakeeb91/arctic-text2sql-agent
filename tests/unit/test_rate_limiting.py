"""
Unit tests for rate limiting configuration helpers.
"""

import pytest

from app.config import get_settings
from app.security.rate_limiting import _resolve_storage_uri


def test_rate_limit_storage_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure storage falls back to memory when unset."""
    monkeypatch.delenv("RATE_LIMIT_STORAGE_URL", raising=False)
    get_settings.cache_clear()
    assert _resolve_storage_uri() == "memory://"


def test_rate_limit_storage_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure storage uses Redis URL when configured."""
    monkeypatch.setenv("RATE_LIMIT_STORAGE_URL", "redis://localhost:6379/1")
    get_settings.cache_clear()
    assert _resolve_storage_uri() == "redis://localhost:6379/1"
