"""Repository for PRContext persistence in Weaviate.

Provides CRUD operations for PRContext using the existing RAG store.
PRContext is stored as a document with doc_type="pr_context".
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..rag.store import WeaviatePRRAGStore
    from .pr_context import PRContext


class PRContextRepository:
    """Persistence layer for PRContext using Weaviate.

    Uses the existing WeaviatePRRAGStore to store PRContext as a
    document with doc_type="pr_context". Only one pr_context document
    exists per PR tenant (upsert semantics).

    Example:
        >>> repo = PRContextRepository(rag_store)
        >>> await repo.save(context)
        >>> loaded = await repo.load()
        >>> await repo.enrich("breaking_changes", ["API signature changed"])
    """

    DOC_TYPE = "pr_context"

    def __init__(self, store: "WeaviatePRRAGStore") -> None:
        """Initialize repository with a RAG store.

        Args:
            store: Weaviate RAG store (already scoped to a PR tenant).
        """
        self.store = store

    async def save(self, context: "PRContext") -> str:
        """Save or update PRContext in Weaviate.

        Uses upsert semantics: deletes existing pr_context document
        then inserts the new version.

        Args:
            context: PRContext to persist.

        Returns:
            Document ID.
        """
        # Delete existing context document (upsert)
        await self.store.delete_by_type(self.DOC_TYPE)

        # Serialize and save
        content = json.dumps(context.to_dict())

        return await self.store.add_document(
            doc_type=self.DOC_TYPE,
            content=content,
            source_url=context.github_url,
        )

    async def load(self) -> "PRContext | None":
        """Load PRContext from Weaviate if it exists.

        Returns:
            PRContext instance or None if not found.
        """
        from .pr_context import PRContext

        docs = await self.store.list_documents(doc_type=self.DOC_TYPE, limit=1)

        if not docs:
            return None

        try:
            # Get full content (list_documents truncates)
            doc_id = docs[0]["id"]
            full_doc = await self.store.get_document(doc_id)

            if full_doc and full_doc.get("content"):
                data = json.loads(full_doc["content"])
                return PRContext.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            pass

        return None

    async def exists(self) -> bool:
        """Check if PRContext exists for this PR.

        Returns:
            True if pr_context document exists.
        """
        count = await self.store.count_documents(doc_type=self.DOC_TYPE)
        return count > 0

    async def enrich(self, key: str, value: Any) -> "PRContext | None":
        """Add enrichment data to the PR context.

        Loads existing context, adds the enrichment, and saves back.

        Args:
            key: Enrichment key (e.g., "breaking_changes", "related_prs").
            value: The value to store (should be JSON-serializable).

        Returns:
            Updated PRContext or None if context doesn't exist.
        """
        context = await self.load()

        if context is None:
            return None

        # Add enrichment
        context.enrichments[key] = value
        context.fetched_at = datetime.now(timezone.utc).isoformat()

        # Save back
        await self.save(context)

        return context

    async def delete(self) -> int:
        """Delete the PRContext document.

        Returns:
            Number of documents deleted (0 or 1).
        """
        return await self.store.delete_by_type(self.DOC_TYPE)
