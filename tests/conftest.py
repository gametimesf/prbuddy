"""Test fixtures for PR Buddy."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.config_manager import FileSystemConfigManager, set_config_manager
from src.agents.registry import ToolRegistry, MCPServerRegistry
from src.sessions.pr_context import PRContext


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def pr_context() -> PRContext:
    """Create a test PR context."""
    return PRContext(
        owner="testowner",
        repo="testrepo",
        number=123,
        author="testauthor",
        title="Test PR",
    )


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Create a temporary config directory with test agents.
    
    Note: The PR Buddy system uses entry_point_override to select the appropriate
    entry point (AuthorTraining for authors, ReviewerQA for reviewers), so we
    mark AuthorTraining as the default entry point here.
    """
    config_dir = tmp_path / "agents"
    config_dir.mkdir()

    # Create AuthorTraining agent for author session tests
    # This is the default entry point for the system
    (config_dir / "author_training.yaml").write_text("""
name: AuthorTraining
instructions: |
  You help authors train the PR knowledge base.
handoff_trigger: Author training agent
routes_to:
  - Research
tools:
  - query_rag
  - index_to_rag
  - get_readiness_score
mcp_servers: []
is_entry_point: true
""")

    # Create ReviewerQA agent for reviewer session tests
    # Selected via entry_point_override when creating reviewer sessions
    (config_dir / "reviewer_qa.yaml").write_text("""
name: ReviewerQA
instructions: |
  You answer reviewer questions about the PR.
handoff_trigger: Reviewer Q&A agent
routes_to: []
tools:
  - query_rag
  - get_readiness_score
mcp_servers: []
is_entry_point: false
""")

    # Create Research agent (for handoffs)
    (config_dir / "research.yaml").write_text("""
name: Research
instructions: |
  You gather PR context from various sources.
handoff_trigger: Research agent for gathering context
routes_to:
  - AuthorTraining
tools:
  - query_rag
  - index_to_rag
mcp_servers: []
is_entry_point: false
""")
    
    return config_dir


@pytest.fixture
def config_manager(config_dir: Path) -> FileSystemConfigManager:
    """Create a config manager for testing."""
    manager = FileSystemConfigManager(config_dir)
    set_config_manager(manager)
    return manager


@pytest.fixture(autouse=True)
def clear_registries():
    """Clear registries before each test."""
    ToolRegistry.clear()
    MCPServerRegistry.clear()
    yield
    ToolRegistry.clear()
    MCPServerRegistry.clear()


@pytest.fixture
def mock_weaviate_client():
    """Create a mock Weaviate client."""
    client = MagicMock()
    
    # Mock is_ready
    client.is_ready.return_value = True
    
    # Create the tenant-scoped collection (returned by with_tenant())
    tenant_collection = MagicMock()
    tenant_collection.data.insert.return_value = "test-doc-id"
    
    # Mock query
    mock_result = MagicMock()
    mock_result.objects = []
    tenant_collection.query.hybrid.return_value = mock_result
    tenant_collection.query.near_text.return_value = mock_result
    tenant_collection.query.bm25.return_value = mock_result
    
    # Mock aggregate
    mock_aggregate = MagicMock()
    mock_aggregate.total_count = 0
    mock_aggregate.groups = []
    tenant_collection.aggregate.over_all.return_value = mock_aggregate
    
    # Create the base collection (returned by collections.get())
    collection = MagicMock()
    collection.tenants.get.return_value = {}
    collection.tenants.create = MagicMock()
    collection.with_tenant.return_value = tenant_collection
    
    # Also set up query on base collection for compatibility
    collection.query = tenant_collection.query
    collection.aggregate = tenant_collection.aggregate
    collection.data = tenant_collection.data
    
    client.collections.get.return_value = collection
    client.collections.list_all.return_value = []
    client.collections.create = MagicMock()
    
    return client


@pytest.fixture
def mock_openai():
    """Mock OpenAI client."""
    with patch("openai.AsyncOpenAI") as mock:
        client = MagicMock()
        mock.return_value = client
        
        # Mock chat completions
        completion = MagicMock()
        completion.choices = [MagicMock(message=MagicMock(content="Test response"))]
        client.chat.completions.create = AsyncMock(return_value=completion)
        
        yield mock


@pytest.fixture
def mock_agent():
    """Create a mock agent."""
    agent = MagicMock()
    agent.name = "TestAgent"
    agent.instructions = "Test instructions"
    agent.handoffs = []
    agent.tools = []
    return agent


# Tool mock implementations
async def mock_query_rag_impl(
    question: str,
    top_k: int = 5,
    doc_types: list[str] | None = None,
) -> dict[str, Any]:
    """Mock query_rag implementation."""
    return {
        "success": True,
        "results": [
            {
                "content": "Mock content about the PR",
                "doc_type": "author_explanation",
                "source": None,
                "file_path": None,
                "score": 0.95,
            }
        ],
        "count": 1,
    }


async def mock_index_to_rag_impl(
    content: str,
    doc_type: str,
    source_url: str | None = None,
    file_path: str | None = None,
) -> dict[str, Any]:
    """Mock index_to_rag implementation."""
    return {
        "success": True,
        "doc_id": "mock-doc-id",
        "message": f"Indexed document of type '{doc_type}'",
    }


async def mock_get_readiness_score_impl() -> dict[str, Any]:
    """Mock get_readiness_score implementation."""
    return {
        "success": True,
        "score": 0.75,
        "level": "medium",
        "message": "The knowledge base has good coverage.",
        "breakdown": {"author_explanation": {"count": 2, "contribution": 0.35}},
        "total_documents": 5,
    }


@pytest.fixture
def register_mock_tools():
    """Register mock tools for testing."""
    ToolRegistry.register("query_rag", mock_query_rag_impl)
    ToolRegistry.register("index_to_rag", mock_index_to_rag_impl)
    ToolRegistry.register("get_readiness_score", mock_get_readiness_score_impl)
    return {
        "query_rag": mock_query_rag_impl,
        "index_to_rag": mock_index_to_rag_impl,
        "get_readiness_score": mock_get_readiness_score_impl,
    }

