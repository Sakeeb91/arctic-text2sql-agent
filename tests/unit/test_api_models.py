"""
Unit tests for API models.
"""

from app.api_models import ErrorDetail, ErrorResponse


def test_error_detail_defaults() -> None:
    """Ensure ErrorDetail carries code/message/details."""
    detail = ErrorDetail(code="TEST", message="msg", details={"foo": "bar"})
    assert detail.code == "TEST"
    assert detail.message == "msg"
    assert detail.details == {"foo": "bar"}


def test_error_response_wrapper() -> None:
    """Ensure ErrorResponse wraps ErrorDetail."""
    detail = ErrorDetail(code="X", message="oops")
    resp = ErrorResponse(error=detail)
    assert resp.error.code == "X"
    assert resp.model_dump()["error"]["message"] == "oops"
