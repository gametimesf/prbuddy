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
from ..voice.config import PollyVoiceConfig, ElevenLabsVoiceConfig, WhisperSTTConfig
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
    mode: Literal["text", "pipeline", "realtime"] = Field(
        default="text",
        description="Session mode: text, pipeline, or realtime"
    )
    session_type: Literal["author", "reviewer"] = Field(
        default="author",
        description="Session type: author (training) or reviewer (Q&A)"
    )
    tts_provider: Literal["polly", "elevenlabs"] | None = Field(
        default=None,
        description="TTS provider for voice modes"
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
    if request.tts_provider == "polly":
        tts_config = PollyVoiceConfig(voice_id=request.voice_id or "Joanna")
    elif request.tts_provider == "elevenlabs":
        tts_config = ElevenLabsVoiceConfig(voice_id=request.voice_id or "Rachel")
    
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
        if session.mode == PRSessionMode.REALTIME:
            await _handle_realtime_session(websocket, session)
        elif session.mode == PRSessionMode.PIPELINE:
            await _handle_pipeline_session(websocket, session)
        else:
            await _handle_text_session(websocket, session)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected", session_id=session_id)
    except Exception as e:
        logger.error("WebSocket error", session_id=session_id, error=str(e))
        await websocket.close(code=1011, reason=str(e))


async def _handle_text_session(websocket: WebSocket, session):
    """Handle text-mode WebSocket session."""
    runner = session.runner
    
    # Set up event callback
    async def on_event(event: TextEvent):
        await websocket.send_json({
            "type": event.type.value,
            "data": event.data,
        })
    
    runner._on_event = on_event
    
    # Send greeting
    await runner.trigger_greeting()
    
    # Message loop
    while True:
        data = await websocket.receive_json()
        
        if data.get("type") == "message":
            text = data.get("text", "")
            await runner.send_text(text)
        elif data.get("type") == "end":
            await runner.end_session()
            break


async def _handle_pipeline_session(websocket: WebSocket, session):
    """Handle pipeline-mode WebSocket session."""
    import base64
    from ..voice.audio_utils import convert_to_pcm_async
    
    runner = session.runner
    
    # Set up event callback
    async def on_event(event: PipelineEvent):
        data = event.data.copy()
        
        # Encode audio as base64
        if "audio" in data:
            data["audio"] = base64.b64encode(data["audio"]).decode("utf-8")
        
        await websocket.send_json({
            "type": event.type.value,
            "data": data,
        })
    
    runner._on_event = on_event
    
    # Send greeting
    await runner.trigger_greeting()
    
    # Message loop
    while True:
        data = await websocket.receive_json()
        
        if data.get("type") == "audio":
            # Decode base64 audio
            audio_bytes = base64.b64decode(data.get("audio", ""))
            audio_format = data.get("format", "webm")  # Browser typically sends webm
            
            # Use process_audio_chunk for browser-recorded audio (bypasses VAD)
            # since the browser already handles recording start/stop
            if hasattr(runner, 'process_audio_chunk'):
                await runner.process_audio_chunk(audio_bytes, format=audio_format)
            else:
                # Fallback: convert to PCM and use VAD-based feed_audio
                pcm_audio = await convert_to_pcm_async(audio_bytes, audio_format)
                if pcm_audio:
                    await runner.feed_audio(pcm_audio)
        elif data.get("type") == "message":
            text = data.get("text", "")
            await runner.send_text(text)
        elif data.get("type") == "end":
            await runner.end_session()
            break


async def _handle_realtime_session(websocket: WebSocket, session):
    """Handle realtime-mode WebSocket session.
    
    Uses OpenAI Realtime API through the RealtimeRunner.
    """
    import base64
    from agents.realtime import RealtimeSession
    
    runner = session.runner
    
    # Create a custom audio handler that sends to WebSocket
    class WebSocketAudioHandler:
        def __init__(self, ws: WebSocket):
            self.ws = ws
        
        async def send_audio(self, audio: bytes):
            await self.ws.send_json({
                "type": "audio",
                "audio": base64.b64encode(audio).decode("utf-8"),
            })
        
        async def send_text(self, text: str, is_final: bool = False):
            await self.ws.send_json({
                "type": "transcript" if is_final else "transcript_delta",
                "text": text,
            })
    
    audio_handler = WebSocketAudioHandler(websocket)
    
    # Start the realtime session
    async with runner.run() as realtime_session:
        # Send initial greeting prompt
        await realtime_session.send_user_text("Hello, I'm ready to discuss this PR.")
        
        # Message loop
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=0.1)
                
                if data.get("type") == "audio":
                    audio = base64.b64decode(data.get("audio", ""))
                    await realtime_session.send_audio(audio)
                elif data.get("type") == "message":
                    text = data.get("text", "")
                    await realtime_session.send_user_text(text)
                elif data.get("type") == "end":
                    break
                    
            except asyncio.TimeoutError:
                # Process any pending events from the realtime session
                pass


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

