"""Session management for PR Buddy.

Provides PR-scoped sessions supporting text, pipeline, and realtime modes.
"""

from .manager import PRSessionManager, PRSession, PRSessionConfig, PRSessionMode
from .pr_context import PRContext
from .pr_context_repository import PRContextRepository
from .pr_fetcher import fetch_and_populate_context, refresh_pr_context
from .system_message import generate_pr_context_message, inject_pr_context_message
from .text_session import TextSession, TextEventType, TextEvent
from .pipeline import PipelineSession, PipelineEventType, PipelineEvent

__all__ = [
    # Manager
    "PRSessionManager",
    "PRSession",
    "PRSessionConfig",
    "PRSessionMode",
    # Context
    "PRContext",
    "PRContextRepository",
    "fetch_and_populate_context",
    "refresh_pr_context",
    "generate_pr_context_message",
    "inject_pr_context_message",
    # Sessions
    "TextSession",
    "TextEventType",
    "TextEvent",
    "PipelineSession",
    "PipelineEventType",
    "PipelineEvent",
]

