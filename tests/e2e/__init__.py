"""
End-to-end integration tests for Arctic Text2SQL Agent.

These tests run with real model inference and database execution
to verify the complete pipeline from natural language to SQL results.

Usage:
    # Run all E2E tests
    pytest tests/e2e/ -v

    # Run with specific markers
    pytest tests/e2e/ -m "e2e and not slow" -v

    # Skip E2E tests in regular test runs
    pytest tests/ -m "not e2e" -v
"""
