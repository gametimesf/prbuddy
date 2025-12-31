"""Tests for tool implementations."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from src.agents.registry import ToolRegistry
from src.tools.rag_tools import (
    query_rag_impl,
    index_to_rag_impl,
    get_readiness_score_impl,
    register_rag_tools,
)
from src.tools.github_tools import (
    fetch_pr_info_impl,
    fetch_pr_diff_impl,
    register_github_tools,
)


class TestRAGTools:
    """Tests for RAG tool implementations."""
    
    @pytest.mark.asyncio
    async def test_query_rag_no_store(self):
        """Test query_rag when store not initialized."""
        # Reset global store
        import src.rag.store as store_module
        store_module._rag_store = None
        
        result = await query_rag_impl("test question")
        
        assert result["success"] is False
        assert "not initialized" in result["error"]
    
    @pytest.mark.asyncio
    async def test_index_to_rag_no_store(self):
        """Test index_to_rag when store not initialized."""
        import src.rag.store as store_module
        store_module._rag_store = None
        
        result = await index_to_rag_impl(
            content="test",
            doc_type="test",
        )
        
        assert result["success"] is False
        assert "not initialized" in result["error"]
    
    @pytest.mark.asyncio
    async def test_index_to_rag_empty_content(self):
        """Test index_to_rag with empty content."""
        # Set up a mock store
        import src.rag.store as store_module
        mock_store = MagicMock()
        store_module._rag_store = mock_store
        
        result = await index_to_rag_impl(
            content="   ",  # Whitespace only
            doc_type="test",
        )
        
        assert result["success"] is False
        assert "empty" in result["error"].lower()
    
    @pytest.mark.asyncio
    async def test_get_readiness_score_no_store(self):
        """Test get_readiness_score when store not initialized."""
        import src.rag.store as store_module
        store_module._rag_store = None
        
        result = await get_readiness_score_impl()
        
        assert result["success"] is False
    
    def test_register_rag_tools(self, clear_registries):
        """Test that RAG tools are registered."""
        register_rag_tools()
        
        assert ToolRegistry.is_registered("query_rag")
        assert ToolRegistry.is_registered("index_to_rag")
        assert ToolRegistry.is_registered("get_readiness_score")


class TestGitHubTools:
    """Tests for GitHub tool implementations."""
    
    @pytest.mark.asyncio
    async def test_fetch_pr_info_success(self):
        """Test fetching PR info successfully."""
        mock_response = {
            "title": "Test PR",
            "body": "Description",
            "user": {"login": "author"},
            "state": "open",
            "draft": False,
            "base": {"ref": "main"},
            "head": {"ref": "feature"},
            "html_url": "https://github.com/owner/repo/pull/1",
            "additions": 10,
            "deletions": 5,
            "changed_files": 2,
        }
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_response_obj.raise_for_status = MagicMock()
            
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock()
            mock_client.return_value.get = AsyncMock(return_value=mock_response_obj)
            
            result = await fetch_pr_info_impl("owner", "repo", 1)
        
        assert result["success"] is True
        assert result["title"] == "Test PR"
        assert result["author"] == "author"
    
    @pytest.mark.asyncio
    async def test_fetch_pr_diff_success(self):
        """Test fetching PR diff successfully."""
        diff_text = """diff --git a/file.py b/file.py
--- a/file.py
+++ b/file.py
@@ -1 +1 @@
-old
+new"""
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_response_obj = MagicMock()
            mock_response_obj.text = diff_text
            mock_response_obj.raise_for_status = MagicMock()
            
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock()
            mock_client.return_value.get = AsyncMock(return_value=mock_response_obj)
            
            result = await fetch_pr_diff_impl("owner", "repo", 1)
        
        assert result["success"] is True
        assert "diff --git" in result["diff"]
    
    def test_register_github_tools(self, clear_registries):
        """Test that GitHub tools are registered."""
        register_github_tools()
        
        assert ToolRegistry.is_registered("fetch_pr_diff")
        assert ToolRegistry.is_registered("fetch_pr_info")
        assert ToolRegistry.is_registered("fetch_pr_comments")
        assert ToolRegistry.is_registered("fetch_pr_files")
        assert ToolRegistry.is_registered("fetch_file_content")


class TestToolRegistry:
    """Tests for ToolRegistry."""
    
    def test_register_and_get(self, clear_registries):
        """Test registering and getting a tool."""
        async def my_tool(arg: str) -> str:
            return arg
        
        ToolRegistry.register("my_tool", my_tool)
        
        tool = ToolRegistry.get("my_tool")
        assert tool is not None
    
    def test_get_not_registered(self, clear_registries):
        """Test getting unregistered tool raises KeyError."""
        with pytest.raises(KeyError):
            ToolRegistry.get("nonexistent")
    
    def test_list_tools(self, clear_registries):
        """Test listing registered tools."""
        async def tool1(x: str) -> str:
            return x
        
        async def tool2(y: int) -> int:
            return y
        
        ToolRegistry.register("tool1", tool1)
        ToolRegistry.register("tool2", tool2)
        
        tools = ToolRegistry.list_tools()
        
        assert "tool1" in tools
        assert "tool2" in tools
    
    def test_is_registered(self, clear_registries):
        """Test checking if tool is registered."""
        async def my_tool() -> None:
            pass
        
        assert ToolRegistry.is_registered("my_tool") is False
        
        ToolRegistry.register("my_tool", my_tool)
        
        assert ToolRegistry.is_registered("my_tool") is True

