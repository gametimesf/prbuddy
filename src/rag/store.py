"""Weaviate-backed RAG store for PR documents.

Provides a per-PR isolated knowledge base using Weaviate multi-tenancy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import weaviate
from weaviate.classes.query import MetadataQuery

from .schema import SCHEMA_CLASS_NAME, ensure_tenant

if TYPE_CHECKING:
    from ..sessions.pr_context import PRContext


@dataclass
class RAGResult:
    """Result from a RAG query."""
    
    content: str
    doc_type: str
    source_url: str | None = None
    file_path: str | None = None
    chunk_index: int | None = None
    score: float = 0.0


# Module-level store reference for tools
_rag_store: "WeaviatePRRAGStore | None" = None


def set_rag_store(store: "WeaviatePRRAGStore") -> None:
    """Set the module-level RAG store reference.
    
    Called when creating a PR session to make the store available to tools.
    """
    global _rag_store
    _rag_store = store


def get_rag_store() -> "WeaviatePRRAGStore":
    """Get the module-level RAG store.
    
    Returns:
        The current RAG store.
    
    Raises:
        RuntimeError: If store not initialized.
    """
    global _rag_store
    if _rag_store is None:
        raise RuntimeError("RAG store not initialized. Call set_rag_store() first.")
    return _rag_store


class WeaviatePRRAGStore:
    """PR-scoped RAG store using Weaviate.
    
    Uses multi-tenancy to isolate PR documents, enabling:
    - Per-PR knowledge bases
    - Clean deletion when PR is closed
    - No cross-PR data leakage
    
    Example:
        >>> store = WeaviatePRRAGStore(client, pr_context)
        >>> await store.add_document(doc_type="diff", content="...")
        >>> results = await store.query("Why was this function added?")
    """
    
    def __init__(
        self,
        client: weaviate.WeaviateClient,
        pr_context: "PRContext",
    ) -> None:
        """Initialize the RAG store for a specific PR.
        
        Args:
            client: Weaviate client.
            pr_context: PR context with owner, repo, number.
        """
        self.client = client
        self.pr_context = pr_context
        self.tenant_name = pr_context.tenant_name
        
        # Ensure tenant exists
        ensure_tenant(client, self.tenant_name)
    
    def _get_collection(self):
        """Get the tenant-scoped collection."""
        return self.client.collections.get(SCHEMA_CLASS_NAME).with_tenant(self.tenant_name)
    
    async def add_document(
        self,
        doc_type: str,
        content: str,
        *,
        file_path: str | None = None,
        source_url: str | None = None,
        chunk_index: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Add a document to the knowledge base.
        
        Args:
            doc_type: Document type (diff, description, author_explanation, etc.)
            content: The text content to index.
            file_path: Optional file path for code chunks.
            source_url: Optional URL to the source.
            chunk_index: Optional position in the source.
            metadata: Optional additional metadata.
        
        Returns:
            The document ID.
        """
        collection = self._get_collection()
        
        properties = {
            "content": content,
            "doc_type": doc_type,
        }
        
        if file_path:
            properties["file_path"] = file_path
        if source_url:
            properties["source_url"] = source_url
        if chunk_index is not None:
            properties["chunk_index"] = chunk_index
        
        # Add any additional metadata fields
        if metadata:
            for key, value in metadata.items():
                if key not in properties:
                    properties[key] = value
        
        # Use sync API (Weaviate v4 client is sync)
        result = collection.data.insert(properties)
        
        return str(result)
    
    async def add_documents(
        self,
        documents: list[dict[str, Any]],
    ) -> list[str]:
        """Add multiple documents in batch.
        
        Args:
            documents: List of dicts with doc_type, content, and optional fields.
        
        Returns:
            List of document IDs.
        """
        collection = self._get_collection()
        
        with collection.batch.dynamic() as batch:
            ids = []
            for doc in documents:
                properties = {
                    "content": doc["content"],
                    "doc_type": doc["doc_type"],
                }
                
                for key in ["file_path", "source_url", "chunk_index"]:
                    if key in doc and doc[key] is not None:
                        properties[key] = doc[key]
                
                uuid = str(uuid4())
                batch.add_object(properties=properties, uuid=uuid)
                ids.append(uuid)
        
        return ids
    
    async def query(
        self,
        question: str,
        *,
        top_k: int = 5,
        alpha: float = 0.5,
        doc_types: list[str] | None = None,
    ) -> list[RAGResult]:
        """Search the knowledge base using hybrid search.
        
        Combines BM25 keyword search with vector similarity.
        
        Args:
            question: The query/question to search for.
            top_k: Number of results to return.
            alpha: Balance between vector (1.0) and keyword (0.0) search.
            doc_types: Optional filter by document types.
        
        Returns:
            List of matching documents with scores.
        """
        collection = self._get_collection()
        
        # Build filters if doc_types specified
        filters = None
        if doc_types:
            from weaviate.classes.query import Filter
            filters = Filter.by_property("doc_type").contains_any(doc_types)
        
        # Execute hybrid search
        response = collection.query.hybrid(
            query=question,
            alpha=alpha,
            limit=top_k,
            filters=filters,
            return_metadata=MetadataQuery(score=True),
        )
        
        results = []
        for obj in response.objects:
            results.append(RAGResult(
                content=obj.properties.get("content", ""),
                doc_type=obj.properties.get("doc_type", "unknown"),
                source_url=obj.properties.get("source_url"),
                file_path=obj.properties.get("file_path"),
                chunk_index=obj.properties.get("chunk_index"),
                score=obj.metadata.score if obj.metadata else 0.0,
            ))
        
        return results
    
    async def search_vector(
        self,
        question: str,
        *,
        top_k: int = 5,
    ) -> list[RAGResult]:
        """Pure vector similarity search.
        
        Args:
            question: The query to embed and search.
            top_k: Number of results.
        
        Returns:
            Matching documents.
        """
        collection = self._get_collection()
        
        response = collection.query.near_text(
            query=question,
            limit=top_k,
            return_metadata=MetadataQuery(distance=True),
        )
        
        results = []
        for obj in response.objects:
            # Convert distance to similarity score (1 - distance)
            score = 1 - (obj.metadata.distance if obj.metadata else 0.0)
            results.append(RAGResult(
                content=obj.properties.get("content", ""),
                doc_type=obj.properties.get("doc_type", "unknown"),
                source_url=obj.properties.get("source_url"),
                file_path=obj.properties.get("file_path"),
                chunk_index=obj.properties.get("chunk_index"),
                score=score,
            ))
        
        return results
    
    async def search_keyword(
        self,
        keywords: str,
        *,
        top_k: int = 5,
    ) -> list[RAGResult]:
        """Pure BM25 keyword search.
        
        Args:
            keywords: Search terms.
            top_k: Number of results.
        
        Returns:
            Matching documents.
        """
        collection = self._get_collection()
        
        response = collection.query.bm25(
            query=keywords,
            limit=top_k,
            return_metadata=MetadataQuery(score=True),
        )
        
        results = []
        for obj in response.objects:
            results.append(RAGResult(
                content=obj.properties.get("content", ""),
                doc_type=obj.properties.get("doc_type", "unknown"),
                source_url=obj.properties.get("source_url"),
                file_path=obj.properties.get("file_path"),
                chunk_index=obj.properties.get("chunk_index"),
                score=obj.metadata.score if obj.metadata else 0.0,
            ))
        
        return results
    
    async def count_documents(self, doc_type: str | None = None) -> int:
        """Count documents in the knowledge base.
        
        Args:
            doc_type: Optional filter by document type.
        
        Returns:
            Number of documents.
        """
        collection = self._get_collection()
        
        if doc_type:
            from weaviate.classes.query import Filter
            result = collection.aggregate.over_all(
                filters=Filter.by_property("doc_type").equal(doc_type),
                total_count=True,
            )
        else:
            result = collection.aggregate.over_all(total_count=True)
        
        return result.total_count or 0
    
    async def delete_by_type(self, doc_type: str) -> int:
        """Delete all documents of a specific type.
        
        Args:
            doc_type: Document type to delete.
        
        Returns:
            Number of documents deleted.
        """
        collection = self._get_collection()
        
        from weaviate.classes.query import Filter
        result = collection.data.delete_many(
            where=Filter.by_property("doc_type").equal(doc_type),
        )
        
        return result.successful if result else 0
    
    async def clear(self) -> int:
        """Delete all documents in this PR's knowledge base.
        
        Returns:
            Number of documents deleted.
        """
        collection = self._get_collection()
        
        # Get count before deletion
        count = await self.count_documents()
        
        # Delete all objects in this tenant
        collection.data.delete_many(
            where=None,  # No filter = delete all
        )
        
        return count
    
    async def get_document_types(self) -> dict[str, int]:
        """Get counts by document type.
        
        Returns:
            Dict mapping doc_type to count.
        """
        collection = self._get_collection()
        
        result = collection.aggregate.over_all(
            group_by="doc_type",
            total_count=True,
        )
        
        counts = {}
        if result.groups:
            for group in result.groups:
                doc_type = group.grouped_by.value
                counts[doc_type] = group.total_count or 0
        
        return counts
    
    async def list_documents(
        self,
        doc_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List documents in the knowledge base.
        
        Args:
            doc_type: Optional filter by document type.
            limit: Maximum number of documents to return.
            offset: Number of documents to skip (for pagination).
        
        Returns:
            List of document dicts with id, doc_type, content, etc.
        """
        collection = self._get_collection()
        
        # Build query
        if doc_type:
            from weaviate.classes.query import Filter
            result = collection.query.fetch_objects(
                filters=Filter.by_property("doc_type").equal(doc_type),
                limit=limit,
                offset=offset,
                return_metadata=MetadataQuery(creation_time=True),
            )
        else:
            result = collection.query.fetch_objects(
                limit=limit,
                offset=offset,
                return_metadata=MetadataQuery(creation_time=True),
            )
        
        documents = []
        for obj in result.objects:
            props = obj.properties
            # Truncate content for listing
            content = props.get("content", "")
            doc = {
                "id": str(obj.uuid),
                "doc_type": props.get("doc_type"),
                "content_preview": content[:200] + "..." if len(content) > 200 else content,
                "content_length": len(content),
                "file_path": props.get("file_path"),
                "source_url": props.get("source_url"),
                "chunk_index": props.get("chunk_index"),
                "created_at": obj.metadata.creation_time.isoformat() if obj.metadata and obj.metadata.creation_time else None,
            }
            documents.append(doc)
        
        return documents
    
    async def get_document(self, doc_id: str) -> dict[str, Any] | None:
        """Get a single document by ID.
        
        Args:
            doc_id: Document UUID.
        
        Returns:
            Document dict or None if not found.
        """
        from uuid import UUID
        collection = self._get_collection()
        
        try:
            obj = collection.query.fetch_object_by_id(UUID(doc_id))
            if obj:
                props = obj.properties
                return {
                    "id": str(obj.uuid),
                    "doc_type": props.get("doc_type"),
                    "content": props.get("content"),
                    "file_path": props.get("file_path"),
                    "source_url": props.get("source_url"),
                    "chunk_index": props.get("chunk_index"),
                    "created_at": obj.metadata.creation_time.isoformat() if obj.metadata and obj.metadata.creation_time else None,
                }
        except Exception:
            pass
        
        return None
    
    async def save_conversation_history(
        self,
        session_type: str,
        history: list[dict[str, str]],
    ) -> str:
        """Save conversation history for session resumption.
        
        Args:
            session_type: 'author' or 'reviewer'.
            history: List of {role, content} messages.
        
        Returns:
            Document ID.
        """
        import json
        
        # Delete any existing history for this session type
        await self.delete_by_type(f"conversation_{session_type}")
        
        # Save as JSON in content field
        content = json.dumps(history)
        
        return await self.add_document(
            doc_type=f"conversation_{session_type}",
            content=content,
            metadata={"message_count": len(history)},
        )
    
    async def load_conversation_history(
        self,
        session_type: str,
    ) -> list[dict[str, str]]:
        """Load conversation history for session resumption.
        
        Args:
            session_type: 'author' or 'reviewer'.
        
        Returns:
            List of {role, content} messages, or empty list if none.
        """
        import json
        
        collection = self._get_collection()
        
        from weaviate.classes.query import Filter
        response = collection.query.fetch_objects(
            filters=Filter.by_property("doc_type").equal(f"conversation_{session_type}"),
            limit=1,
        )
        
        if not response.objects:
            return []
        
        try:
            content = response.objects[0].properties.get("content", "[]")
            return json.loads(content)
        except json.JSONDecodeError:
            return []
    
    async def has_been_researched(self) -> bool:
        """Check if this PR has been researched before.
        
        Returns:
            True if there's indexed content (diffs, descriptions, etc.)
        """
        counts = await self.get_document_types()
        
        # Check for research artifacts
        research_types = {"diff", "description", "comment", "issue"}
        for doc_type in research_types:
            if counts.get(doc_type, 0) > 0:
                return True
        
        return False
    
    async def get_research_summary(self) -> dict[str, Any]:
        """Get a summary of what's been researched.
        
        Returns:
            Dict with counts and timestamps.
        """
        counts = await self.get_document_types()
        total = sum(counts.values())
        
        return {
            "has_content": total > 0,
            "total_documents": total,
            "document_types": counts,
            "has_diff": counts.get("diff", 0) > 0,
            "has_author_explanations": counts.get("author_explanation", 0) > 0,
            "explanation_count": counts.get("author_explanation", 0),
        }

