"""PR session manager.

Manages the lifecycle of PR-scoped sessions across voice and text modes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Literal
from uuid import uuid4

import weaviate

from agents import Agent
from agents.realtime import RealtimeAgent, RealtimeRunner

from ..agents.factory import (
    create_author_system,
    create_reviewer_system,
    create_author_realtime_system,
    create_reviewer_realtime_system,
)
from ..rag.store import WeaviatePRRAGStore, set_rag_store
from ..rag.schema import create_schema, delete_tenant, list_tenants
from ..voice.config import TTSVoiceConfig, STTVoiceConfig, WhisperSTTConfig, PollyVoiceConfig
from ..voice.factory import create_tts, create_stt
from .pr_context import PRContext
from .pr_context_repository import PRContextRepository
from .pr_fetcher import fetch_and_populate_context
from .text_session import TextSession
from .pipeline import PipelineSession

if TYPE_CHECKING:
    pass


class PRSessionMode(str, Enum):
    """Session mode for PR Buddy."""
    
    TEXT = "text"  # Text only, no audio
    PIPELINE = "pipeline"  # Whisper STT + Agent + TTS
    REALTIME = "realtime"  # OpenAI Realtime API


@dataclass
class PRSessionConfig:
    """Configuration for creating a PR session."""
    
    mode: PRSessionMode = PRSessionMode.TEXT
    session_type: Literal["author", "reviewer"] = "reviewer"
    tts_config: TTSVoiceConfig | None = None
    stt_config: STTVoiceConfig | None = None


@dataclass
class PRSession:
    """A PR-scoped session."""
    
    id: str
    pr_context: PRContext
    config: PRSessionConfig
    rag_store: WeaviatePRRAGStore
    runner: TextSession | PipelineSession | RealtimeRunner
    created_at: float = field(default_factory=lambda: __import__("time").time())
    
    @property
    def mode(self) -> PRSessionMode:
        return self.config.mode
    
    @property
    def session_type(self) -> str:
        return self.config.session_type


class PRSessionManager:
    """Manages PR-scoped sessions across voice and text modes.
    
    Handles session creation, caching of RAG stores, and cleanup.
    """
    
    def __init__(
        self,
        weaviate_client: weaviate.WeaviateClient,
    ) -> None:
        """Initialize the session manager.
        
        Args:
            weaviate_client: Weaviate client for RAG storage.
        """
        self._weaviate = weaviate_client
        self._sessions: dict[str, PRSession] = {}
        self._pr_rag_stores: dict[str, WeaviatePRRAGStore] = {}
        
        # Ensure schema exists
        create_schema(weaviate_client)
    
    def _get_or_create_rag_store(self, pr_context: PRContext) -> WeaviatePRRAGStore:
        """Get or create a RAG store for a PR.
        
        Args:
            pr_context: PR context.
        
        Returns:
            WeaviatePRRAGStore instance.
        """
        tenant_name = pr_context.tenant_name
        
        if tenant_name not in self._pr_rag_stores:
            self._pr_rag_stores[tenant_name] = WeaviatePRRAGStore(
                self._weaviate,
                pr_context,
            )
        
        return self._pr_rag_stores[tenant_name]
    
    async def create_session(
        self,
        pr_context: PRContext,
        config: PRSessionConfig | None = None,
        on_event: Callable[[Any], Coroutine[Any, Any, None]] | None = None,
    ) -> PRSession:
        """Create a new PR session.

        Args:
            pr_context: PR context with owner, repo, number.
            config: Session configuration.
            on_event: Optional event callback.

        Returns:
            Created PRSession.
        """
        config = config or PRSessionConfig()

        # Get or create RAG store for this PR
        rag_store = self._get_or_create_rag_store(pr_context)

        # Set as module-level for tools
        set_rag_store(rag_store)

        # Load existing PRContext or fetch from GitHub and persist
        pr_context = await fetch_and_populate_context(pr_context, rag_store)
        
        # Create session based on mode
        session_id = str(uuid4())
        
        if config.mode == PRSessionMode.REALTIME:
            runner = await self._create_realtime_runner(pr_context, config)
        elif config.mode == PRSessionMode.PIPELINE:
            runner = await self._create_pipeline_session(
                session_id, pr_context, config, rag_store, on_event
            )
        else:
            runner = await self._create_text_session(
                session_id, pr_context, config, rag_store, on_event
            )
        
        session = PRSession(
            id=session_id,
            pr_context=pr_context,
            config=config,
            rag_store=rag_store,
            runner=runner,
        )
        
        self._sessions[session_id] = session
        return session
    
    async def _create_realtime_runner(
        self,
        pr_context: PRContext,
        config: PRSessionConfig,
    ) -> RealtimeRunner:
        """Create a realtime runner for voice mode."""
        # Create realtime agent system based on session type
        if config.session_type == "author":
            system = await create_author_realtime_system()
        else:
            system = await create_reviewer_realtime_system()
        
        return RealtimeRunner(starting_agent=system.entry_point)
    
    async def _create_pipeline_session(
        self,
        session_id: str,
        pr_context: PRContext,
        config: PRSessionConfig,
        rag_store: WeaviatePRRAGStore,
        on_event: Callable[[Any], Coroutine[Any, Any, None]] | None = None,
    ) -> PipelineSession:
        """Create a pipeline session for voice mode."""
        # Create text agent system based on session type
        if config.session_type == "author":
            system = await create_author_system()
        else:
            system = await create_reviewer_system()

        # Create STT provider
        stt_config = config.stt_config or WhisperSTTConfig()
        stt = create_stt(stt_config)

        # Create TTS provider
        tts_config = config.tts_config or PollyVoiceConfig()
        tts, tts_synth_config = create_tts(tts_config)

        return PipelineSession(
            session_id=session_id,
            stt=stt,
            agent=system.entry_point,
            tts=tts,
            tts_config=tts_synth_config,
            pr_context=pr_context,
            session_type=config.session_type,
            on_event=on_event,
            rag_store=rag_store,
        )
    
    async def _create_text_session(
        self,
        session_id: str,
        pr_context: PRContext,
        config: PRSessionConfig,
        rag_store: WeaviatePRRAGStore,
        on_event: Callable[[Any], Coroutine[Any, Any, None]] | None = None,
    ) -> TextSession:
        """Create a text-only session."""
        # Create text agent system based on session type
        if config.session_type == "author":
            system = await create_author_system()
        else:
            system = await create_reviewer_system()
        
        return TextSession(
            session_id=session_id,
            agent=system.entry_point,
            pr_context=pr_context,
            session_type=config.session_type,
            on_event=on_event,
            rag_store=rag_store,
        )
    
    def get_session(self, session_id: str) -> PRSession | None:
        """Get a session by ID."""
        return self._sessions.get(session_id)
    
    def list_sessions(self) -> list[PRSession]:
        """List all active sessions."""
        return list(self._sessions.values())
    
    def list_sessions_for_pr(self, pr_context: PRContext) -> list[PRSession]:
        """List sessions for a specific PR."""
        return [
            s for s in self._sessions.values()
            if s.pr_context.tenant_name == pr_context.tenant_name
        ]
    
    async def delete_session(self, session_id: str) -> bool:
        """Delete a session.
        
        Args:
            session_id: Session ID.
        
        Returns:
            True if deleted, False if not found.
        """
        session = self._sessions.pop(session_id, None)
        if session:
            # End the session if it has an end_session method
            if hasattr(session.runner, "end_session"):
                await session.runner.end_session()
            return True
        return False
    
    async def delete_pr_data(self, pr_context: PRContext) -> bool:
        """Delete all data for a PR.
        
        Removes all sessions and the Weaviate tenant.
        
        Args:
            pr_context: PR context.
        
        Returns:
            True if deleted, False if not found.
        """
        tenant_name = pr_context.tenant_name
        
        # Delete all sessions for this PR
        to_delete = [
            sid for sid, s in self._sessions.items()
            if s.pr_context.tenant_name == tenant_name
        ]
        for sid in to_delete:
            await self.delete_session(sid)
        
        # Remove cached RAG store
        self._pr_rag_stores.pop(tenant_name, None)
        
        # Delete Weaviate tenant
        return delete_tenant(self._weaviate, tenant_name)
    
    def list_prs(self) -> list[str]:
        """List all PRs with data."""
        return list_tenants(self._weaviate)
    
    async def get_pr_status(self, pr_context: PRContext) -> dict[str, Any]:
        """Get status information for a PR.
        
        Args:
            pr_context: PR context.
        
        Returns:
            Status dict with document counts, sessions, etc.
        """
        rag_store = self._get_or_create_rag_store(pr_context)
        
        doc_counts = await rag_store.get_document_types()
        total_docs = sum(doc_counts.values())
        
        sessions = self.list_sessions_for_pr(pr_context)
        
        return {
            "pr_id": pr_context.pr_id,
            "tenant_name": pr_context.tenant_name,
            "document_count": total_docs,
            "document_types": doc_counts,
            "active_sessions": len(sessions),
            "session_types": {
                "author": len([s for s in sessions if s.session_type == "author"]),
                "reviewer": len([s for s in sessions if s.session_type == "reviewer"]),
            },
        }

