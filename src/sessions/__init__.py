"""Session management for PR Buddy.

Provides PR-scoped sessions supporting text, pipeline, and realtime modes.
"""

from .manager import PRSessionManager, PRSession, PRSessionConfig, PRSessionMode
from .pr_context import PRContext
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
    # Sessions
    "TextSession",
    "TextEventType",
    "TextEvent",
    "PipelineSession",
    "PipelineEventType",
    "PipelineEvent",
]

