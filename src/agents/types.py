"""Type definitions for the PR Buddy agent system.

This module contains the core dataclasses used to run agents.
Agent configuration is handled by AgentConfigSchema in schema.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentContext:
    """Shared context passed between agents during a conversation.
    
    This context is available to all agents and persists across handoffs.
    Use this to share PR information, session state, and routing metadata.
    """
    
    # PR identification
    pr_owner: str | None = None
    pr_repo: str | None = None
    pr_number: int | None = None
    pr_author: str | None = None
    
    # Session tracking
    session_id: str | None = None
    session_type: str | None = None  # "author" or "reviewer"
    
    # Agent routing metadata
    previous_agents: list[str] = field(default_factory=list)
    handoff_reason: str | None = None
    
    # RAG readiness score (0-1)
    readiness_score: float = 0.0
    
    # Any additional data agents want to share
    extra: dict[str, Any] = field(default_factory=dict)
    
    def record_handoff(self, from_agent: str, reason: str | None = None) -> None:
        """Record a handoff from one agent to another."""
        self.previous_agents.append(from_agent)
        self.handoff_reason = reason
    
    @property
    def pr_id(self) -> str | None:
        """Get the full PR identifier."""
        if self.pr_owner and self.pr_repo and self.pr_number:
            return f"{self.pr_owner}/{self.pr_repo}#{self.pr_number}"
        return None
    
    @property
    def is_pr_identified(self) -> bool:
        """Check if the PR has been identified."""
        return all([self.pr_owner, self.pr_repo, self.pr_number])


