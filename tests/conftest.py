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
    
    Uses the new directory structure:
    - common/: Shared agents (Research)
    - author/: Author system agents (AuthorTraining)
    - reviewer/: Reviewer system agents (ReviewerQA)
    """
    config_dir = tmp_path / "agents"
    config_dir.mkdir()
    
    # Create subdirectories
    common_dir = config_dir / "common"
    author_dir = config_dir / "author"
    reviewer_dir = config_dir / "reviewer"
    
    common_dir.mkdir()
    author_dir.mkdir()
    reviewer_dir.mkdir()

    # Create Research agent in common/ (shared by both systems)
    # Note: routes_to is empty since the target depends on which system loads it
    (common_dir / "research.yaml").write_text("""
name: Research
instructions: |
  You gather PR context from various sources.
handoff_trigger: Research agent for gathering context
routes_to: []
tools:
  - query_rag
  - index_to_rag
mcp_servers: []
is_entry_point: false
""")

    # Create AuthorTraining agent in author/
    (author_dir / "author_training.yaml").write_text("""
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

    # Create ReviewerQA agent in reviewer/
    (reviewer_dir / "reviewer_qa.yaml").write_text("""
name: ReviewerQA
instructions: |
  You answer reviewer questions about the PR.
handoff_trigger: Reviewer Q&A agent
routes_to:
  - Research
tools:
  - query_rag
  - get_readiness_score
mcp_servers: []
is_entry_point: true
""")
    
    return config_dir


@pytest.fixture
def config_manager(config_dir: Path) -> FileSystemConfigManager:
    """Create a config manager for testing.
    
    Note: This creates a manager for the common directory.
    For session tests, use the patch_config_base fixture instead.
    """
    # Use the common directory for backward compatibility with some tests
    manager = FileSystemConfigManager(config_dir / "common")
    set_config_manager(manager)
    return manager


@pytest.fixture
def patch_config_base(config_dir: Path):
    """Patch the factory config base path for tests.
    
    This makes create_author_system and create_reviewer_system
    use the test config directories instead of the real ones.
    """
    with patch("src.agents.factory._get_config_base_path", return_value=config_dir):
        yield config_dir


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

