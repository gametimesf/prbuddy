"""Eval fixtures — real Weaviate + real OpenAI agents.

These evals hit external services (Weaviate, OpenAI API) and are
excluded from normal test runs. Run with: make eval
"""

from __future__ import annotations

import os
import asyncio

import pytest
import weaviate
from dotenv import load_dotenv

load_dotenv()

from src.agents.factory import create_author_system, create_reviewer_system
from src.agents.tools import init_registries
from src.rag.schema import create_schema, delete_tenant
from src.rag.store import WeaviatePRRAGStore, set_rag_store
from src.sessions.pr_context import PRContext
from src.sessions.text_session import TextSession
from src.sessions.system_message import generate_pr_context_message


EVAL_TENANT = "eval_test_pr"


@pytest.fixture(scope="session")
def check_env():
    """Ensure required environment variables are set."""
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set — skipping evals")


@pytest.fixture(scope="session")
def weaviate_client(check_env):
    """Connect to a real local Weaviate instance."""
    try:
        client = weaviate.connect_to_local(
            host="localhost",
            port=8085,
            grpc_port=50052,
        )
    except Exception:
        pytest.skip("Weaviate not available on localhost:8085 — skipping evals")

    create_schema(client)
    yield client
    client.close()


@pytest.fixture(scope="session")
def _init_registries():
    """Initialize tool and MCP registries once per session."""
    init_registries()


@pytest.fixture
def pr_context():
    """Standard eval PR context."""
    return PRContext(
        owner="evalowner",
        repo="evalrepo",
        number=999,
        author="evalauthor",
        title="Eval Test PR: allow fan-ops-voice to reach private ALB",
        description="Adds a security group rule for fan-ops-voice to access the private ALB for internal MCP access.",
    )


@pytest.fixture
def rag_store(weaviate_client, pr_context):
    """Create a clean RAG store for each eval test."""
    # Clean up any leftover data
    try:
        delete_tenant(weaviate_client, pr_context.tenant_name)
    except Exception:
        pass

    store = WeaviatePRRAGStore(weaviate_client, pr_context)
    set_rag_store(store)
    yield store

    # Cleanup after test
    try:
        delete_tenant(weaviate_client, pr_context.tenant_name)
    except Exception:
        pass


@pytest.fixture
async def author_session(rag_store, pr_context, _init_registries):
    """Create a real author session with real agents."""
    system = await create_author_system()
    session = TextSession(
        session_id="eval-author",
        agent=system.entry_point,
        pr_context=pr_context,
        session_type="author",
        rag_store=rag_store,
    )
    return session


@pytest.fixture
async def reviewer_session(rag_store, pr_context, _init_registries):
    """Create a real reviewer session sharing the same RAG store."""
    system = await create_reviewer_system()
    session = TextSession(
        session_id="eval-reviewer",
        agent=system.entry_point,
        pr_context=pr_context,
        session_type="reviewer",
        rag_store=rag_store,
    )
    return session
