"""
Arctic Text2SQL - Production-grade Natural Language to SQL API

This package provides the core API components:
- config: Application configuration management
- logging_config: Structured logging setup
- exceptions: Custom exception hierarchy
- middleware: FastAPI middleware
- routes: API endpoint definitions
- main: FastAPI application entry point
"""

__version__ = "0.1.0"
__author__ = "Sakeeb91"
__email__ = "rahman.sakeeb@gmail.com"

from app.config import Settings, get_settings
from app.exceptions import Text2SQLException
from app.logging_config import configure_logging, get_logger

__all__ = [
    "__version__",
    "__author__",
    "__email__",
    "Settings",
    "get_settings",
    "Text2SQLException",
    "configure_logging",
    "get_logger",
]
