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

