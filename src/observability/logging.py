"""Structured logging configuration for PR Buddy."""

from __future__ import annotations

import os
import sys
import logging
import warnings
from typing import Any

import structlog


def configure_logging(verbose: int = 0) -> None:
    """Configure structured logging.
    
    Args:
        verbose: Verbosity level (0=info, 1=debug, 2=trace).
    """
    # Determine log level from verbose or env
    if verbose >= 2:
        level = logging.DEBUG
    elif verbose >= 1:
        level = logging.DEBUG
    else:
        level = logging.INFO
    
    # Override from environment
    env_level = os.environ.get("LOG_LEVEL", "").upper()
    if env_level:
        level = getattr(logging, env_level, level)
    
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )
    
    # Reduce noise from libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("weaviate").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    
    # Suppress deprecation warnings from websockets library (dependency issue)
    warnings.filterwarnings(
        "ignore",
        message="remove second argument of ws_handler",
        category=DeprecationWarning,
        module="websockets",
    )
    
    # Configure structlog
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    
    # Use dev renderer for local, JSON for production
    if os.environ.get("ENVIRONMENT") == "production":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None, **initial_context: Any) -> structlog.BoundLogger:
    """Get a structured logger.
    
    Args:
        name: Logger name (module path).
        **initial_context: Initial context to bind.
    
    Returns:
        Configured structlog logger.
    """
    logger = structlog.get_logger(name)
    if initial_context:
        logger = logger.bind(**initial_context)
    return logger

