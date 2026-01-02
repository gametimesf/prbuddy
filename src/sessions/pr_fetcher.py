"""PR fetcher for populating PRContext from GitHub API.

Handles fetching PR metadata from GitHub and persisting to Weaviate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .pr_context import PRContext
from .pr_context_repository import PRContextRepository

if TYPE_CHECKING:
    from ..rag.store import WeaviatePRRAGStore


async def fetch_and_populate_context(
    pr_url_or_context: str | PRContext,
    rag_store: "WeaviatePRRAGStore",
    *,
    force_refresh: bool = False,
) -> PRContext:
    """Parse URL, fetch from GitHub, and persist to Weaviate.

    If context already exists in Weaviate and force_refresh is False,
    returns the existing context. Otherwise fetches fresh data from GitHub.

    Args:
        pr_url_or_context: GitHub PR URL or existing PRContext with basic fields.
        rag_store: Weaviate RAG store (scoped to PR tenant).
        force_refresh: If True, always fetch from GitHub even if cached.

    Returns:
        Fully populated PRContext.
    """
    # Parse URL if string
    if isinstance(pr_url_or_context, str):
        context = PRContext.from_url(pr_url_or_context)
    else:
        context = pr_url_or_context

    repo = PRContextRepository(rag_store)

    # Check for existing context
    if not force_refresh:
        existing = await repo.load()
        if existing is not None:
            return existing

    # Fetch from GitHub API
    context = await _fetch_pr_metadata(context)

    # Persist to Weaviate
    await repo.save(context)

    return context


async def _fetch_pr_metadata(context: PRContext) -> PRContext:
    """Fetch PR metadata from GitHub API and update context.

    Args:
        context: PRContext with at least owner, repo, number set.

    Returns:
        Updated PRContext with GitHub metadata.
    """
    # Import here to avoid circular dependency
    from ..tools.github_tools import fetch_pr_info_impl

    pr_info = await fetch_pr_info_impl(
        owner=context.owner,
        repo=context.repo,
        pr_number=context.number,
    )

    if pr_info.get("success"):
        # Update context with fetched data
        context.title = pr_info.get("title")
        context.description = pr_info.get("description")
        context.author = pr_info.get("author")
        context.state = pr_info.get("state")
        context.draft = pr_info.get("draft", False)
        context.base_branch = pr_info.get("base_branch")
        context.head_branch = pr_info.get("head_branch")
        context.additions = pr_info.get("additions", 0)
        context.deletions = pr_info.get("deletions", 0)
        context.changed_files = pr_info.get("changed_files", 0)
        context.created_at = pr_info.get("created_at")
        context.updated_at = pr_info.get("updated_at")
        context.fetched_at = datetime.now(timezone.utc).isoformat()

    return context


async def refresh_pr_context(rag_store: "WeaviatePRRAGStore") -> PRContext | None:
    """Refresh an existing PRContext from GitHub API.

    Loads existing context, re-fetches from GitHub, preserves enrichments,
    and saves back.

    Args:
        rag_store: Weaviate RAG store (scoped to PR tenant).

    Returns:
        Updated PRContext or None if no existing context.
    """
    repo = PRContextRepository(rag_store)

    existing = await repo.load()
    if existing is None:
        return None

    # Preserve enrichments
    enrichments = existing.enrichments.copy()

    # Re-fetch from GitHub
    updated = await _fetch_pr_metadata(existing)

    # Restore enrichments
    updated.enrichments = enrichments

    # Save back
    await repo.save(updated)

    return updated
