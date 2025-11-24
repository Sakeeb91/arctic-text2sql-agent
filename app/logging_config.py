"""
Structured logging configuration using structlog.

This module provides production-grade logging with:
- JSON and console output formats
- Request correlation IDs
- Performance timing
- Consistent log structure
"""

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

# Context variable for request correlation ID
request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


def add_request_id(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Add request ID to log event if available."""
    request_id = request_id_context.get()
    if request_id:
        event_dict["request_id"] = request_id
    return event_dict


def configure_logging(
    level: str = "INFO",
    log_format: str = "json",
    enable_request_logging: bool = True,
) -> None:
    """
    Configure structured logging for the application.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: Output format - 'json' for production, 'console' for development
        enable_request_logging: Whether to enable request logging middleware

    Usage:
        from app.logging_config import configure_logging, get_logger

        configure_logging(level="INFO", log_format="json")
        logger = get_logger(__name__)
        logger.info("Application started", version="1.0.0")
    """
    # Shared processors for all log entries
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        add_request_id,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if log_format == "json":
        # JSON format for production - machine readable
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        # Console format for development - human readable
        renderer = structlog.dev.ConsoleRenderer(
            colors=True,
            exception_formatter=structlog.dev.rich_traceback,
        )

    # Configure structlog
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Create formatter for stdlib logging
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )

    # Configure root handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, level.upper()))

    # Quiet down noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("transformers").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger instance.

    Args:
        name: Logger name, typically __name__ of the calling module

    Returns:
        BoundLogger: Configured structlog logger

    Usage:
        logger = get_logger(__name__)
        logger.info("Processing query", query="SELECT * FROM users")
        logger.error("Query failed", error="Connection timeout", retry_count=3)
    """
    return structlog.get_logger(name)


class LogContext:
    """
    Context manager for adding temporary context to log entries.

    Usage:
        with LogContext(user_id="123", operation="sql_generation"):
            logger.info("Starting operation")
            # All logs within this block will have user_id and operation
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialize with context key-value pairs."""
        self.context = kwargs
        self._token: Any = None

    def __enter__(self) -> "LogContext":
        """Bind context variables."""
        structlog.contextvars.bind_contextvars(**self.context)
        return self

    def __exit__(self, *args: Any) -> None:
        """Unbind context variables."""
        structlog.contextvars.unbind_contextvars(*self.context.keys())


def log_function_call(
    logger: structlog.stdlib.BoundLogger,
) -> Any:
    """
    Decorator to log function entry, exit, and timing.

    Usage:
        @log_function_call(logger)
        async def process_query(query: str) -> str:
            ...
    """
    import functools
    import time

    def decorator(func: Any) -> Any:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            func_name = func.__qualname__
            logger.debug("function_enter", function=func_name)
            start_time = time.perf_counter()

            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start_time) * 1000
                logger.debug(
                    "function_exit",
                    function=func_name,
                    duration_ms=round(duration_ms, 2),
                    status="success",
                )
                return result
            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000
                logger.error(
                    "function_error",
                    function=func_name,
                    duration_ms=round(duration_ms, 2),
                    error=str(e),
                    error_type=type(e).__name__,
                )
                raise

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            func_name = func.__qualname__
            logger.debug("function_enter", function=func_name)
            start_time = time.perf_counter()

            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start_time) * 1000
                logger.debug(
                    "function_exit",
                    function=func_name,
                    duration_ms=round(duration_ms, 2),
                    status="success",
                )
                return result
            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000
                logger.error(
                    "function_error",
                    function=func_name,
                    duration_ms=round(duration_ms, 2),
                    error=str(e),
                    error_type=type(e).__name__,
                )
                raise

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator

