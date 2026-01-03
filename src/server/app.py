"""FastAPI server for PR Buddy.

Provides REST API and WebSocket endpoints for PR sessions.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import weaviate
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

# Config managers are created in factory functions, no global initialization needed
from ..agents.tools import init_registries
from ..observability.logging import configure_logging, get_logger
from ..rag.schema import create_schema
from ..sessions.manager import PRSessionManager, PRSessionConfig, PRSessionMode
from ..sessions.pr_context import PRContext
from ..sessions.text_session import TextEvent, TextEventType
from ..sessions.pipeline import PipelineEvent, PipelineEventType
from ..voice.config import PollyVoiceConfig, OpenAITTSConfig, WhisperSTTConfig
from .admin import router as admin_router


# Load environment variables
load_dotenv()


# Global state
_session_manager: PRSessionManager | None = None
_weaviate_client: weaviate.WeaviateClient | None = None
logger = get_logger(__name__)


def get_session_manager() -> PRSessionManager:
    """Get the session manager."""
    global _session_manager
    if _session_manager is None:
        raise RuntimeError("Session manager not initialized")
    return _session_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global _session_manager, _weaviate_client
    
    # Configure logging
    verbose = int(os.environ.get("VERBOSE", "0"))
    configure_logging(verbose)
    
    logger.info("Starting PR Buddy server")
    
    # Initialize tool registries
    # Note: Agent systems are created with MultiDirConfigManager in factory functions
    init_registries()
    
    # Connect to Weaviate
    weaviate_url = os.environ.get("WEAVIATE_URL", "http://localhost:8080")
    logger.info("Connecting to Weaviate", url=weaviate_url)
    
    try:
        _weaviate_client = weaviate.connect_to_local(
            host=weaviate_url.replace("http://", "").replace("https://", "").split(":")[0],
            port=int(weaviate_url.split(":")[-1]) if ":" in weaviate_url.split("//")[-1] else 8080,
        )
        
        # Create schema
        create_schema(_weaviate_client)
        
        # Initialize session manager
        _session_manager = PRSessionManager(_weaviate_client)
        
        logger.info("PR Buddy server started")
        
    except Exception as e:
        logger.error("Failed to connect to Weaviate", error=str(e))
        raise
    
    yield
    
    # Cleanup
    logger.info("Shutting down PR Buddy server")
    if _weaviate_client:
        _weaviate_client.close()


# Create FastAPI app
app = FastAPI(
    title="PR Buddy",
    description="AI-powered PR review companion",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include admin router
app.include_router(admin_router)


# Request/Response models
class CreateSessionRequest(BaseModel):
    """Request to create a new PR session."""
    
    pr_url: str = Field(..., description="GitHub PR URL or owner/repo#number")
    mode: Literal["text", "pipeline"] = Field(
        default="text",
        description="Session mode: text or pipeline (voice)"
    )
    session_type: Literal["author", "reviewer"] = Field(
        default="author",
        description="Session type: author (training) or reviewer (Q&A)"
    )
    tts_provider: Literal["openai", "polly"] | None = Field(
        default=None,
        description="TTS provider for voice modes (openai is default)"
    )
    voice_id: str | None = Field(
        default=None,
        description="Voice ID for TTS"
    )


class CreateSessionResponse(BaseModel):
    """Response from session creation."""
    
    session_id: str
    pr_id: str
    mode: str
    session_type: str
    websocket_url: str


class PRStatusResponse(BaseModel):
    """Response with PR status information."""

    pr_id: str
    title: str | None = None
    description: str | None = None
    author: str | None = None
    state: str | None = None
    document_count: int
    document_types: dict[str, int]
    active_sessions: int
    session_types: dict[str, int]


class SendMessageRequest(BaseModel):
    """Request to send a text message."""
    
    text: str


class SendMessageResponse(BaseModel):
    """Response from sending a message."""
    
    response: str


class HealthResponse(BaseModel):
    """Health check response."""
    
    status: str
    weaviate: str


# REST API Endpoints
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    weaviate_status = "connected" if _weaviate_client and _weaviate_client.is_ready() else "disconnected"
    return HealthResponse(status="ok", weaviate=weaviate_status)


@app.post("/api/sessions", response_model=CreateSessionResponse)
async def create_session(request: CreateSessionRequest):
    """Create a new PR session."""
    manager = get_session_manager()
    
    # Parse PR context
    try:
        pr_context = PRContext.from_url(request.pr_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Build session config
    mode = PRSessionMode(request.mode)
    
    tts_config = None
    if mode == PRSessionMode.PIPELINE:
        # Use OpenAI TTS by default for voice mode, or Polly if explicitly requested
        if request.tts_provider == "polly":
            tts_config = PollyVoiceConfig(voice_id=request.voice_id or "Joanna")
        else:
            # Default to OpenAI TTS - works with existing OpenAI credentials
            tts_config = OpenAITTSConfig(voice_id=request.voice_id or "alloy")
    
    config = PRSessionConfig(
        mode=mode,
        session_type=request.session_type,
        tts_config=tts_config,
        stt_config=WhisperSTTConfig() if mode != PRSessionMode.TEXT else None,
    )
    
    # Create session
    session = await manager.create_session(pr_context, config)
    
    return CreateSessionResponse(
        session_id=session.id,
        pr_id=pr_context.pr_id,
        mode=request.mode,
        session_type=request.session_type,
        websocket_url=f"/ws/{session.id}",
    )


@app.get("/api/pr/{owner}/{repo}/{pr_number}/status", response_model=PRStatusResponse)
async def get_pr_status(owner: str, repo: str, pr_number: int):
    """Get status information for a PR."""
    manager = get_session_manager()
    
    pr_context = PRContext(owner=owner, repo=repo, number=pr_number)
    status = await manager.get_pr_status(pr_context)
    
    return PRStatusResponse(**status)


@app.get("/api/pr/{owner}/{repo}/{pr_number}/documents")
async def list_pr_documents(
    owner: str,
    repo: str,
    pr_number: int,
    doc_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """List documents in the PR knowledge base."""
    manager = get_session_manager()
    
    pr_context = PRContext(owner=owner, repo=repo, number=pr_number)
    rag_store = manager._get_or_create_rag_store(pr_context)
    
    documents = await rag_store.list_documents(
        doc_type=doc_type,
        limit=limit,
        offset=offset,
    )
    
    return {"documents": documents, "count": len(documents)}


@app.get("/api/pr/{owner}/{repo}/{pr_number}/documents/{doc_id}")
async def get_pr_document(owner: str, repo: str, pr_number: int, doc_id: str):
    """Get a single document from the PR knowledge base."""
    manager = get_session_manager()
    
    pr_context = PRContext(owner=owner, repo=repo, number=pr_number)
    rag_store = manager._get_or_create_rag_store(pr_context)
    
    document = await rag_store.get_document(doc_id)
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return document


@app.delete("/api/pr/{owner}/{repo}/{pr_number}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pr(owner: str, repo: str, pr_number: int):
    """Delete all data for a PR."""
    manager = get_session_manager()
    
    pr_context = PRContext(owner=owner, repo=repo, number=pr_number)
    deleted = await manager.delete_pr_data(pr_context)
    
    if not deleted:
        raise HTTPException(status_code=404, detail="PR not found")


@app.get("/api/prs")
async def list_prs():
    """List all PRs with data."""
    manager = get_session_manager()
    return {"prs": manager.list_prs()}


@app.get("/api/sessions")
async def list_sessions():
    """List all active sessions."""
    manager = get_session_manager()
    sessions = manager.list_sessions()
    
    return {
        "sessions": [
            {
                "id": s.id,
                "pr_id": s.pr_context.pr_id,
                "mode": s.mode.value,
                "session_type": s.session_type,
                "created_at": s.created_at,
            }
            for s in sessions
        ]
    }


@app.delete("/api/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str):
    """Delete a session."""
    manager = get_session_manager()
    deleted = await manager.delete_session(session_id)
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")


@app.post("/api/sessions/{session_id}/message", response_model=SendMessageResponse)
async def send_message(session_id: str, request: SendMessageRequest):
    """Send a text message to a session (text mode only)."""
    manager = get_session_manager()
    session = manager.get_session(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if session.mode != PRSessionMode.TEXT:
        raise HTTPException(
            status_code=400,
            detail="Use WebSocket for voice mode sessions"
        )
    
    response = await session.runner.send_text(request.text)
    return SendMessageResponse(response=response)


# WebSocket endpoint
@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time sessions."""
    manager = get_session_manager()
    session = manager.get_session(session_id)
    
    if not session:
        await websocket.close(code=4004, reason="Session not found")
        return
    
    await websocket.accept()
    
    try:
        if session.mode == PRSessionMode.PIPELINE:
            await _handle_pipeline_session(websocket, session)
        else:
            await _handle_text_session(websocket, session)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected", session_id=session_id)
    except Exception as e:
        logger.error("WebSocket error", session_id=session_id, error=str(e))
        await websocket.close(code=1011, reason=str(e))


async def _handle_text_session(websocket: WebSocket, session):
    """Handle text-mode WebSocket session.

    Agent tasks run as background tasks so they continue even if the client disconnects.
    On reconnect, conversation history is loaded from Weaviate.
    """
    runner = session.runner

    # Set up event callback
    async def on_event(event: TextEvent):
        # Debug: log sources_used events to verify content is included
        if event.type.value == "sources_used":
            sources = event.data.get("sources", [])
            logger.info(
                "ws_send_sources_used",
                num_sources=len(sources),
                first_has_content=bool(sources[0].get("content")) if sources else False,
                first_content_len=len(sources[0].get("content", "")) if sources else 0,
                first_preview_len=len(sources[0].get("preview", "")) if sources else 0,
            )
            # Log full first source to verify all fields
            if sources:
                logger.info("ws_send_first_source", source=sources[0])
        await websocket.send_json({
            "type": event.type.value,
            "data": event.data,
        })

    runner.set_event_callback(on_event)

    # Load conversation history from Weaviate for reconnection support
    await runner._load_history()

    # Send ready event with conversation history for UI rebuild
    history = runner.get_history()
    await websocket.send_json({
        "type": "ready",
        "audio_config": None,  # No audio in text mode
        "conversation_history": history,
    })

    # Check if we need to trigger greeting (new session with no history)
    user_messages = [m for m in history if m.get("role") in ("user", "assistant")]
    if not user_messages:
        # Spawn greeting as background task
        async def run_greeting():
            try:
                await runner.trigger_greeting()
            except Exception as e:
                logger.error("greeting_task_failed", error=str(e))

        runner._active_task = asyncio.create_task(run_greeting())
        # Wait for it while connected
        try:
            await runner._active_task
        except asyncio.CancelledError:
            pass  # Task was cancelled, that's ok

    # Message loop
    try:
        while True:
            data = await websocket.receive_json()

            if data.get("type") == "message":
                text = data.get("text", "")
                if text:
                    # Spawn agent task in background
                    async def run_agent(msg: str):
                        try:
                            await runner.send_text(msg)
                        except Exception as e:
                            logger.error("agent_task_failed", error=str(e))

                    runner._active_task = asyncio.create_task(run_agent(text))
                    # Wait for it while connected
                    try:
                        await runner._active_task
                    except asyncio.CancelledError:
                        pass

            elif data.get("type") == "end":
                await runner.end_session()
                break

    except WebSocketDisconnect:
        # Clear callback but DON'T cancel the task - let it finish
        runner.set_event_callback(None)
        if runner._active_task and not runner._active_task.done():
            logger.info(
                "websocket_disconnected_task_continuing",
                session_id=session.id,
                task_running=True,
            )
        raise


async def _handle_pipeline_session(websocket: WebSocket, session):
    """Handle pipeline-mode WebSocket session.

    Uses PipelineSession which handles VAD, buffering, STT, agent execution,
    and TTS. Agent tasks run as background tasks so they continue even if
    the client disconnects. On reconnect, conversation history is loaded from Weaviate.
    """
    import base64
    from ..sessions.pipeline import PipelineEventType

    runner = session.runner

    # Get sample rate from tts_config if available
    output_sample_rate = 16000  # Default for Polly
    if hasattr(session.config, 'tts_config') and session.config.tts_config:
        if hasattr(session.config.tts_config, 'sample_rate'):
            output_sample_rate = session.config.tts_config.sample_rate

    # Event handler - translate pipeline events to WebSocket messages
    async def on_event(event) -> None:
        if event.type == PipelineEventType.TRANSCRIPT:
            text = event.data.get("text", "")
            if text != "[session_start]":  # Don't send internal trigger
                await websocket.send_json({
                    "type": "transcript",
                    "role": "user",
                    "text": text,
                })

        elif event.type == PipelineEventType.AGENT_RESPONSE:
            text = event.data.get("text", "")
            agent = event.data.get("agent", "Agent")
            await websocket.send_json({
                "type": "transcript",
                "role": "assistant",
                "text": text,
                "agent": agent,
            })

        elif event.type == PipelineEventType.AUDIO_START:
            await websocket.send_json({"type": "audio_start"})

        elif event.type == PipelineEventType.AUDIO_CHUNK:
            audio = event.data.get("audio", b"")
            audio_b64 = base64.b64encode(audio).decode()
            await websocket.send_json({
                "type": "audio",
                "audio": audio_b64,
            })

        elif event.type == PipelineEventType.AUDIO_END:
            await websocket.send_json({"type": "audio_end"})

        elif event.type == PipelineEventType.AGENT_HANDOFF:
            await websocket.send_json({
                "type": "agent_handoff",
                "data": event.data,
            })

        elif event.type == PipelineEventType.TOOL_CALL:
            await websocket.send_json({
                "type": "tool_call",
                "data": event.data,
            })

        elif event.type == PipelineEventType.TOOL_RESULT:
            await websocket.send_json({
                "type": "tool_result",
                "data": event.data,
            })

        elif event.type == PipelineEventType.AGENT_THINKING:
            await websocket.send_json({
                "type": "agent_thinking",
                "data": event.data,
            })

        elif event.type == PipelineEventType.ERROR:
            await websocket.send_json({
                "type": "error",
                "message": event.data.get("error", "Unknown error"),
            })

    runner.set_event_callback(on_event)

    # Load conversation history for reconnection support
    await runner._load_history()
    history = runner._history

    # Send ready event with audio config and conversation history
    await websocket.send_json({
        "type": "ready",
        "audio_config": {
            "input_sample_rate": 24000,  # For mic/Whisper
            "output_sample_rate": output_sample_rate,  # From session config
        },
        "conversation_history": history,
    })

    # Check if we need to trigger greeting (new session with no user/assistant history)
    user_messages = [m for m in history if m.get("role") in ("user", "assistant")]
    if not user_messages:
        # Spawn greeting as background task
        async def run_greeting():
            try:
                await runner.trigger_greeting()
            except Exception as e:
                logger.error("greeting_task_failed", error=str(e))

        runner._active_task = asyncio.create_task(run_greeting())
        # Wait for it while connected
        try:
            await runner._active_task
        except asyncio.CancelledError:
            pass  # Task was cancelled, that's ok

    # Message loop
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "audio":
                # Decode base64 PCM16 audio and feed to pipeline VAD
                audio_b64 = data.get("audio", "")
                audio_bytes = base64.b64decode(audio_b64)
                await runner.feed_audio(audio_bytes)

            elif msg_type == "text" or msg_type == "message":
                text = data.get("text", "")
                if text:
                    # Spawn agent task in background
                    async def run_agent(msg: str):
                        try:
                            await runner.send_text(msg)
                        except Exception as e:
                            logger.error("agent_task_failed", error=str(e))

                    runner._active_task = asyncio.create_task(run_agent(text))
                    # Wait for it while connected
                    try:
                        await runner._active_task
                    except asyncio.CancelledError:
                        pass

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "close" or msg_type == "end":
                break

    except WebSocketDisconnect:
        # Clear callback but DON'T cancel the task - let it finish
        runner.set_event_callback(None)
        if runner._active_task and not runner._active_task.done():
            logger.info(
                "websocket_disconnected_task_continuing",
                session_id=session.id,
                task_running=True,
            )
        raise


# Static files
static_dir = Path(__file__).parent.parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    
    @app.get("/")
    async def root():
        """Serve the main page."""
        return FileResponse(static_dir / "index.html")


def create_app() -> FastAPI:
    """Factory function for creating the app."""
    return app

