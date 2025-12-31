"""Pipeline voice session for PR Buddy.

Composes separate STT, agent, and TTS components for voice interactions.
Provides more flexibility than the realtime API while still supporting
voice input and output.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from agents import Agent, Runner

if TYPE_CHECKING:
    from ..voice.stt.base import STTProvider
    from ..voice.tts.base import TTSProvider, TTSConfig
    from .pr_context import PRContext


class PipelineEventType(str, Enum):
    """Event types for pipeline sessions."""
    
    # Audio states
    LISTENING = "listening"
    PROCESSING_AUDIO = "processing_audio"
    
    # Transcription
    TRANSCRIPT = "transcript"
    
    # Agent states
    AGENT_THINKING = "agent_thinking"
    AGENT_RESPONSE = "agent_response"
    
    # Audio output
    AUDIO_START = "audio_start"
    AUDIO_CHUNK = "audio_chunk"
    AUDIO_END = "audio_end"
    
    # Tool events
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    
    # Session events
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"
    AGENT_HANDOFF = "agent_handoff"
    
    # Error
    ERROR = "error"


@dataclass
class PipelineEvent:
    """Event emitted by a pipeline session."""
    
    type: PipelineEventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=lambda: asyncio.get_event_loop().time())


# Event callback type
EventCallback = Callable[[PipelineEvent], Coroutine[Any, Any, None]]


class PipelineSession:
    """Voice session using STT + Agent + TTS pipeline.
    
    Processes audio input through Whisper STT, runs the agent,
    and synthesizes the response with TTS.
    
    Includes Voice Activity Detection (VAD) to detect speech
    and silence for natural conversation flow.
    """
    
    # VAD constants (aligned with fan-ops-voice)
    SILENCE_THRESHOLD = 1.5  # seconds of silence before processing
    ENERGY_THRESHOLD = 800   # RMS threshold for speech detection
    MIN_AUDIO_LENGTH = 4800  # Minimum bytes (~0.1s at 24kHz 16-bit)
    
    def __init__(
        self,
        session_id: str,
        stt: "STTProvider",
        agent: Agent,
        tts: "TTSProvider",
        tts_config: "TTSConfig",
        *,
        pr_context: "PRContext | None" = None,
        on_event: EventCallback | None = None,
    ) -> None:
        """Initialize the pipeline session.
        
        Args:
            session_id: Unique session identifier.
            stt: Speech-to-text provider.
            agent: The starting agent.
            tts: Text-to-speech provider.
            tts_config: TTS configuration.
            pr_context: Optional PR context.
            on_event: Optional event callback.
        """
        self.session_id = session_id
        self.stt = stt
        self.agent = agent
        self.tts = tts
        self.tts_config = tts_config
        self.pr_context = pr_context
        self._on_event = on_event
        
        # VAD state
        self._audio_buffer: list[bytes] = []
        self._last_audio_time = 0.0
        self._is_speaking = False
        self._is_processing = False
        self._is_playing = False
        
        # Conversation state
        self._history: list[dict[str, str]] = []
        self._current_agent = agent
    
    async def _emit(self, event_type: PipelineEventType, data: dict[str, Any] | None = None) -> None:
        """Emit an event."""
        if self._on_event:
            event = PipelineEvent(type=event_type, data=data or {})
            await self._on_event(event)
    
    @staticmethod
    def _get_audio_energy(audio_data: bytes) -> float:
        """Calculate RMS energy to detect speech vs silence.
        
        Args:
            audio_data: PCM16 audio bytes.
        
        Returns:
            Raw RMS energy value.
        """
        if len(audio_data) < 2:
            return 0.0
        import struct
        samples = struct.unpack(f"<{len(audio_data)//2}h", audio_data)
        if not samples:
            return 0.0
        return (sum(s * s for s in samples) / len(samples)) ** 0.5
    
    async def feed_audio(self, audio_bytes: bytes) -> None:
        """Feed audio chunk into the pipeline.
        
        The pipeline will buffer audio, detect speech/silence,
        and process when appropriate.
        
        Args:
            audio_bytes: PCM16 audio chunk.
        """
        import time
        
        if self._is_processing or self._is_playing:
            # Don't accumulate while processing or playing
            return
        
        energy = self._get_audio_energy(audio_bytes)
        current_time = time.time()
        
        if energy > self.ENERGY_THRESHOLD:
            # Speech detected
            if not self._is_speaking:
                await self._emit(PipelineEventType.LISTENING)
            self._is_speaking = True
            self._audio_buffer.append(audio_bytes)
            self._last_audio_time = current_time
        elif self._is_speaking:
            # Still accumulating during brief pauses
            self._audio_buffer.append(audio_bytes)
            
            # Check for silence timeout
            if current_time - self._last_audio_time > self.SILENCE_THRESHOLD:
                await self._process_audio()
    
    async def process_audio_chunk(self, audio: bytes, format: str = "webm") -> None:
        """Process a complete audio chunk (e.g., from browser recording).
        
        This bypasses VAD since the browser already handles speech detection
        via start/stop recording.
        
        Args:
            audio: Complete audio chunk.
            format: Audio format ('webm', 'wav', 'pcm').
        """
        if self._is_processing:
            return
        
        self._is_processing = True
        await self._emit(PipelineEventType.PROCESSING_AUDIO)
        
        try:
            # Transcribe directly (Whisper supports webm)
            transcript = await self.stt.transcribe(audio, audio_format=format)
            
            if not transcript.strip():
                self._is_processing = False
                return
            
            await self._emit(PipelineEventType.TRANSCRIPT, {"text": transcript})
            
            # Process with agent
            response = await self._run_agent(transcript)
            
            # Synthesize response
            await self._synthesize_and_stream(response)
            
        except Exception as e:
            await self._emit(PipelineEventType.ERROR, {"error": str(e)})
        finally:
            self._is_processing = False
    
    async def _process_audio(self) -> None:
        """Process collected audio through the pipeline (via VAD)."""
        if not self._audio_buffer:
            self._is_speaking = False
            return
        
        # Check minimum audio length
        total_bytes = sum(len(chunk) for chunk in self._audio_buffer)
        if total_bytes < self.MIN_AUDIO_LENGTH:
            self._audio_buffer.clear()
            self._is_speaking = False
            return
        
        self._is_processing = True
        self._is_speaking = False
        await self._emit(PipelineEventType.PROCESSING_AUDIO)
        
        try:
            # Combine audio buffer
            audio = b"".join(self._audio_buffer)
            self._audio_buffer.clear()
            
            # Transcribe (use 'wav' format to wrap raw PCM for Whisper)
            transcript = await self.stt.transcribe(audio, audio_format="pcm")
            
            if not transcript.strip():
                self._is_processing = False
                return
            
            await self._emit(PipelineEventType.TRANSCRIPT, {"text": transcript})
            
            # Process with agent
            response = await self._run_agent(transcript)
            
            # Synthesize response
            self._is_playing = True
            await self._synthesize_and_stream(response)
            
        except Exception as e:
            await self._emit(PipelineEventType.ERROR, {"error": str(e)})
        finally:
            self._is_processing = False
            self._is_playing = False
    
    async def _run_agent(self, text: str) -> str:
        """Run the agent on the transcribed text.
        
        Args:
            text: Transcribed user input.
        
        Returns:
            Agent response text.
        """
        await self._emit(PipelineEventType.AGENT_THINKING)
        
        # Add to history
        self._history.append({"role": "user", "content": text})
        
        # Run agent
        result = await Runner.run(
            self._current_agent,
            input=self._history,
        )
        
        response = result.final_output if result.final_output else ""
        
        # Check for handoff
        if result.last_agent != self._current_agent:
            await self._emit(PipelineEventType.AGENT_HANDOFF, {
                "from": self._current_agent.name,
                "to": result.last_agent.name,
            })
            self._current_agent = result.last_agent
        
        # Add response to history
        self._history.append({"role": "assistant", "content": response})
        
        await self._emit(PipelineEventType.AGENT_RESPONSE, {"text": response})
        
        return response
    
    async def _synthesize_and_stream(self, text: str) -> None:
        """Synthesize text to audio and stream chunks.
        
        Args:
            text: Text to synthesize.
        """
        await self._emit(PipelineEventType.AUDIO_START)
        
        try:
            async for chunk in self.tts.synthesize_stream(text, self.tts_config):
                await self._emit(PipelineEventType.AUDIO_CHUNK, {"audio": chunk})
        except Exception as e:
            # Log error but don't crash - the text response was already sent
            import structlog
            logger = structlog.get_logger(__name__)
            logger.error("TTS synthesis failed", error=str(e))
            await self._emit(PipelineEventType.ERROR, {"error": f"TTS failed: {str(e)}"})
        finally:
            await self._emit(PipelineEventType.AUDIO_END)
    
    async def send_text(self, text: str) -> str:
        """Process a text message (for hybrid mode).
        
        Args:
            text: User's text input.
        
        Returns:
            Agent response.
        """
        self._is_processing = True
        
        try:
            response = await self._run_agent(text)
            await self._synthesize_and_stream(response)
            return response
        finally:
            self._is_processing = False
    
    async def trigger_greeting(self) -> str:
        """Trigger the agent's greeting and synthesize it.
        
        Returns:
            Greeting text.
        """
        await self._emit(PipelineEventType.SESSION_STARTED)
        
        self._is_processing = True
        
        try:
            # Get greeting
            result = await Runner.run(
                self._current_agent,
                input=[{"role": "user", "content": "Hello"}],
            )
            
            greeting = result.final_output if result.final_output else "Hello! How can I help you?"
            
            await self._emit(PipelineEventType.AGENT_RESPONSE, {"text": greeting})
            
            # Synthesize greeting
            await self._synthesize_and_stream(greeting)
            
            return greeting
        finally:
            self._is_processing = False
    
    async def end_session(self) -> None:
        """End the session."""
        await self._emit(PipelineEventType.SESSION_ENDED)

