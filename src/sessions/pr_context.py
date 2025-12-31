"""PR context for session scoping.

Provides a data structure for identifying a specific pull request
and generating consistent tenant names for RAG storage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class PRContext:
    """Context for a specific pull request.
    
    Identifies a PR and provides utilities for URL parsing,
    tenant naming, and GitHub API paths.
    """
    
    owner: str
    repo: str
    number: int
    author: str | None = None
    title: str | None = None
    
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
            data: Dict with owner, repo, number keys.
        
        Returns:
            PRContext instance.
        """
        return cls(
            owner=data["owner"],
            repo=data["repo"],
            number=int(data["number"]),
            author=data.get("author"),
            title=data.get("title"),
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "owner": self.owner,
            "repo": self.repo,
            "number": self.number,
            "author": self.author,
            "title": self.title,
            "pr_id": self.pr_id,
            "github_url": self.github_url,
        }

