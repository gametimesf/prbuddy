"""Tests for the RAG store."""

import pytest
from unittest.mock import MagicMock, patch

from src.rag.store import WeaviatePRRAGStore, RAGResult, set_rag_store, get_rag_store
from src.sessions.pr_context import PRContext


class TestWeaviatePRRAGStore:
    """Tests for WeaviatePRRAGStore."""
    
    @pytest.fixture
    def store(self, mock_weaviate_client, pr_context):
        """Create a store with mock client."""
        with patch("src.rag.store.ensure_tenant"):
            return WeaviatePRRAGStore(mock_weaviate_client, pr_context)
    
    @pytest.mark.asyncio
    async def test_add_document(self, store):
        """Test adding a document."""
        doc_id = await store.add_document(
            doc_type="author_explanation",
            content="This change was made because...",
            source_url="https://example.com",
        )
        
        assert doc_id is not None
    
    @pytest.mark.asyncio
    async def test_add_document_with_file_path(self, store):
        """Test adding a document with file path."""
        doc_id = await store.add_document(
            doc_type="diff",
            content="+ new line\n- old line",
            file_path="src/main.py",
        )
        
        assert doc_id is not None
    
    @pytest.mark.asyncio
    async def test_query(self, store, mock_weaviate_client):
        """Test querying documents."""
        # Set up mock response
        mock_obj = MagicMock()
        mock_obj.properties = {
            "content": "Test content",
            "doc_type": "author_explanation",
            "source_url": None,
            "file_path": None,
            "chunk_index": None,
        }
        mock_obj.metadata = MagicMock(score=0.85)
        
        collection = mock_weaviate_client.collections.get.return_value
        collection.query.hybrid.return_value.objects = [mock_obj]
        
        results = await store.query("Why was this changed?")
        
        assert len(results) == 1
        assert results[0].content == "Test content"
        assert results[0].doc_type == "author_explanation"
        assert results[0].score == 0.85
    
    @pytest.mark.asyncio
    async def test_query_with_doc_types_filter(self, store, mock_weaviate_client):
        """Test querying with document type filter."""
        collection = mock_weaviate_client.collections.get.return_value
        collection.query.hybrid.return_value.objects = []
        
        results = await store.query(
            "test",
            doc_types=["author_explanation", "diff"],
        )
        
        # Verify filter was passed
        collection.query.hybrid.assert_called_once()
        call_kwargs = collection.query.hybrid.call_args.kwargs
        assert call_kwargs.get("filters") is not None
    
    @pytest.mark.asyncio
    async def test_count_documents(self, store, mock_weaviate_client):
        """Test counting documents."""
        collection = mock_weaviate_client.collections.get.return_value
        collection.aggregate.over_all.return_value.total_count = 10
        
        count = await store.count_documents()
        
        assert count == 10


class TestRAGStoreGlobal:
    """Tests for global RAG store functions."""
    
    def test_set_and_get_rag_store(self, mock_weaviate_client, pr_context):
        """Test setting and getting the global store."""
        with patch("src.rag.store.ensure_tenant"):
            store = WeaviatePRRAGStore(mock_weaviate_client, pr_context)
            set_rag_store(store)
            
            retrieved = get_rag_store()
            assert retrieved is store
    
    def test_get_rag_store_not_initialized(self):
        """Test that getting store before setting raises error."""
        # Reset the global store
        import src.rag.store as store_module
        store_module._rag_store = None
        
        with pytest.raises(RuntimeError):
            get_rag_store()


class TestRAGResult:
    """Tests for RAGResult dataclass."""
    
    def test_create_result(self):
        """Test creating a RAG result."""
        result = RAGResult(
            content="Test content",
            doc_type="diff",
            source_url="https://github.com/...",
            file_path="src/main.py",
            chunk_index=0,
            score=0.95,
        )
        
        assert result.content == "Test content"
        assert result.doc_type == "diff"
        assert result.score == 0.95
    
    def test_result_defaults(self):
        """Test RAGResult default values."""
        result = RAGResult(content="Test", doc_type="test")
        
        assert result.source_url is None
        assert result.file_path is None
        assert result.chunk_index is None
        assert result.score == 0.0

