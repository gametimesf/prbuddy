"""Context tools for PR Buddy agents.

These tools allow agents to retrieve and enrich the current PR context.
"""

from __future__ import annotations

from typing import Any

from ..agents.registry import ToolRegistry
from ..rag.store import get_rag_store
from ..sessions.pr_context_repository import PRContextRepository


async def get_pr_context_impl() -> dict[str, Any]:
    """Retrieve full PR context from the knowledge base.

    Returns detailed information about the current PR including:
    - Title, description, author
    - State (open/closed/merged), draft status
    - Branch information (head -> base)
    - Statistics (additions, deletions, changed files)
    - Any enrichments added by agents

    Use this when you need detailed information about the PR
    beyond what's in the system message.

    Returns:
        Dict with PR context or error if not available.
    """
    try:
        store = get_rag_store()
    except RuntimeError:
        return {
            "success": False,
            "error": "RAG store not initialized. PR context may not be set.",
        }

    try:
        repo = PRContextRepository(store)
        context = await repo.load()

        if context:
            return {
                "success": True,
                "context": context.to_dict(),
            }
        return {
            "success": False,
            "error": "PR context not found. Has the PR been initialized?",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to load PR context: {str(e)}",
        }


async def enrich_pr_context_impl(
    key: str,
    value: str,
) -> dict[str, Any]:
    """Add enrichment data to the PR context.

    Use this to store agent-discovered insights or metadata
    that should persist across sessions. Good examples:

    - "breaking_changes": List of breaking changes discovered
    - "key_decisions": Important design decisions the author mentioned
    - "related_prs": Related PRs discovered during conversation
    - "testing_notes": Notes about testing approach
    - "architecture_impact": How this PR affects system architecture

    Args:
        key: Enrichment key (e.g., "breaking_changes", "related_prs").
        value: The value to store (string - use JSON for complex data).

    Returns:
        Success status.
    """
    try:
        store = get_rag_store()
    except RuntimeError:
        return {
            "success": False,
            "error": "RAG store not initialized.",
        }

    if not key.strip():
        return {
            "success": False,
            "error": "Enrichment key cannot be empty.",
        }

    try:
        repo = PRContextRepository(store)
        context = await repo.enrich(key, value)

        if context:
            return {
                "success": True,
                "message": f"Added enrichment '{key}' to PR context.",
                "enrichments": context.enrichments,
            }
        return {
            "success": False,
            "error": "PR context not found. Cannot add enrichment.",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to add enrichment: {str(e)}",
        }


async def refresh_pr_context_impl() -> dict[str, Any]:
    """Refresh PR context from GitHub API.

    Re-fetches the PR metadata from GitHub to get the latest
    state, comments, and statistics. Preserves existing enrichments.

    Use this if the PR has been updated since the session started.

    Returns:
        Updated PR context or error.
    """
    try:
        store = get_rag_store()
    except RuntimeError:
        return {
            "success": False,
            "error": "RAG store not initialized.",
        }

    try:
        # Import here to avoid circular imports
        from ..sessions.pr_fetcher import refresh_pr_context

        context = await refresh_pr_context(store)

        if context:
            return {
                "success": True,
                "message": "PR context refreshed from GitHub.",
                "context": context.to_dict(),
            }
        return {
            "success": False,
            "error": "PR context not found. Cannot refresh.",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to refresh PR context: {str(e)}",
        }


def register_context_tools() -> None:
    """Register context tools with the ToolRegistry."""
    ToolRegistry.register("get_pr_context", get_pr_context_impl)
    ToolRegistry.register("enrich_pr_context", enrich_pr_context_impl)
    ToolRegistry.register("refresh_pr_context", refresh_pr_context_impl)
