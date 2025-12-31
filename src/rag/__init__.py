"""RAG (Retrieval-Augmented Generation) module for PR Buddy.

Provides Weaviate-backed vector storage for PR-scoped knowledge bases.
"""

from .store import WeaviatePRRAGStore, RAGResult, set_rag_store, get_rag_store
from .schema import create_schema, SCHEMA_CLASS_NAME

__all__ = [
    "WeaviatePRRAGStore",
    "RAGResult",
    "set_rag_store",
    "get_rag_store",
    "create_schema",
    "SCHEMA_CLASS_NAME",
]

