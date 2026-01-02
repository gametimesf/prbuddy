"""PR context for session scoping.

Provides a data structure for identifying a specific pull request
and generating consistent tenant names for RAG storage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PRContext:
    """Context for a specific pull request.

    Identifies a PR and provides utilities for URL parsing,
    tenant naming, and GitHub API paths.

    Core fields (required):
        owner, repo, number - PR identification

    GitHub metadata (fetched from API):
        title, description, author, state, draft, etc.

    Enrichments (added by agents over time):
        enrichments dict - arbitrary key/value pairs
    """

    # Core identification (required)
    owner: str
    repo: str
    number: int

    # GitHub metadata (fetched from API)
    title: str | None = None
    description: str | None = None
    author: str | None = None
    state: str | None = None  # "open", "closed", "merged"
    draft: bool = False
    base_branch: str | None = None
    head_branch: str | None = None

    # Statistics
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0

    # Timestamps
    created_at: str | None = None
    updated_at: str | None = None
    fetched_at: str | None = None  # When we last fetched from GitHub

    # Agent enrichments (persisted across sessions)
    enrichments: dict[str, Any] = field(default_factory=dict)
    
    @property
    def tenant_name(self) -> str:
        """Get the Weaviate tenant name for this PR.
        
        Format: owner_repo_number (sanitized for Weaviate)
        """
        # Weaviate tenant names can only contain alphanumeric and underscore
        safe_owner = re.sub(r"[^a-zA-Z0-9]", "_", self.owner)
        safe_repo = re.sub(r"[^a-zA-Z0-9]", "_", self.repo)
        return f"{safe_owner}_{safe_repo}_{self.number}"
    
    @property
    def pr_id(self) -> str:
        """Get a human-readable PR identifier.
        
        Format: owner/repo#number
        """
        return f"{self.owner}/{self.repo}#{self.number}"
    
    @property
    def github_url(self) -> str:
        """Get the GitHub PR URL."""
        return f"https://github.com/{self.owner}/{self.repo}/pull/{self.number}"
    
    @property
    def api_path(self) -> str:
        """Get the GitHub API path for this PR.
        
        Format: /repos/owner/repo/pulls/number
        """
        return f"/repos/{self.owner}/{self.repo}/pulls/{self.number}"
    
    @classmethod
    def from_url(cls, url: str) -> "PRContext":
        """Parse a PR context from a GitHub URL.
        
        Supports formats:
        - https://github.com/owner/repo/pull/123
        - github.com/owner/repo/pull/123
        - owner/repo#123
        
        Args:
            url: GitHub PR URL or short reference.
        
        Returns:
            PRContext instance.
        
        Raises:
            ValueError: If URL cannot be parsed.
        """
        # Try full URL pattern
        match = re.match(
            r"(?:https?://)?(?:www\.)?github\.com/([^/]+)/([^/]+)/pull/(\d+)",
            url.strip(),
        )
        if match:
            return cls(
                owner=match.group(1),
                repo=match.group(2),
                number=int(match.group(3)),
            )
        
        # Try short reference pattern: owner/repo#number
        match = re.match(r"([^/]+)/([^#]+)#(\d+)", url.strip())
        if match:
            return cls(
                owner=match.group(1),
                repo=match.group(2),
                number=int(match.group(3)),
            )
        
        raise ValueError(
            f"Cannot parse PR URL: {url}. "
            "Expected format: https://github.com/owner/repo/pull/123 or owner/repo#123"
        )
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PRContext":
        """Create from a dictionary.

        Args:
            data: Dict with owner, repo, number keys and optional metadata.

        Returns:
            PRContext instance.
        """
        return cls(
            owner=data["owner"],
            repo=data["repo"],
            number=int(data["number"]),
            title=data.get("title"),
            description=data.get("description"),
            author=data.get("author"),
            state=data.get("state"),
            draft=data.get("draft", False),
            base_branch=data.get("base_branch"),
            head_branch=data.get("head_branch"),
            additions=data.get("additions", 0),
            deletions=data.get("deletions", 0),
            changed_files=data.get("changed_files", 0),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            fetched_at=data.get("fetched_at"),
            enrichments=data.get("enrichments", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for persistence."""
        return {
            # Core identification
            "owner": self.owner,
            "repo": self.repo,
            "number": self.number,
            # GitHub metadata
            "title": self.title,
            "description": self.description,
            "author": self.author,
            "state": self.state,
            "draft": self.draft,
            "base_branch": self.base_branch,
            "head_branch": self.head_branch,
            # Statistics
            "additions": self.additions,
            "deletions": self.deletions,
            "changed_files": self.changed_files,
            # Timestamps
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "fetched_at": self.fetched_at,
            # Enrichments
            "enrichments": self.enrichments,
            # Computed (for convenience)
            "pr_id": self.pr_id,
            "github_url": self.github_url,
        }

