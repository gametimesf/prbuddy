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
    
    # VAD thresholds (adjust based on testing)
    VAD_SILENCE_THRESHOLD = 0.01  # RMS below this = silence
    VAD_SPEECH_FRAMES = 3  # Frames of speech to start recording
    VAD_SILENCE_FRAMES = 15  # Frames of silence to stop recording
    
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
        
        # Audio buffer for collecting speech
        self._audio_buffer: list[bytes] = []
        self._is_speaking = False
        self._speech_frames = 0
        self._silence_frames = 0
        
        # Conversation state
        self._history: list[dict[str, str]] = []
        self._current_agent = agent
        self._is_processing = False
    
    async def _emit(self, event_type: PipelineEventType, data: dict[str, Any] | None = None) -> None:
        """Emit an event."""
        if self._on_event:
            event = PipelineEvent(type=event_type, data=data or {})
            await self._on_event(event)
    
    def _calculate_rms(self, audio: bytes) -> float:
        """Calculate RMS (volume) of audio samples.
        
        Args:
            audio: PCM16 audio bytes.
        
        Returns:
            RMS value (0.0 to 1.0).
        """
        if len(audio) < 2:
            return 0.0
        
        # Convert bytes to 16-bit samples
        import struct
        samples = struct.unpack(f"<{len(audio)//2}h", audio)
        
        # Calculate RMS
        if not samples:
            return 0.0
        
        sum_squares = sum(s * s for s in samples)
        rms = (sum_squares / len(samples)) ** 0.5
        
        # Normalize to 0-1 range (16-bit max is 32767)
        return rms / 32767.0
    
    async def feed_audio(self, audio_bytes: bytes) -> None:
        """Feed audio data into the pipeline.
        
        Performs VAD and collects speech, then processes when
        speech ends.
        
        Args:
            audio_bytes: PCM16 audio chunk.
        """
        if self._is_processing:
            return  # Don't collect while processing
        
        rms = self._calculate_rms(audio_bytes)
        is_speech = rms > self.VAD_SILENCE_THRESHOLD
        
        if is_speech:
            self._speech_frames += 1
            self._silence_frames = 0
            
            # Start recording after threshold
            if self._speech_frames >= self.VAD_SPEECH_FRAMES:
                if not self._is_speaking:
                    self._is_speaking = True
                    await self._emit(PipelineEventType.LISTENING)
                
                self._audio_buffer.append(audio_bytes)
        else:
            self._silence_frames += 1
            
            if self._is_speaking:
                self._audio_buffer.append(audio_bytes)
                
                # End of speech detected
                if self._silence_frames >= self.VAD_SILENCE_FRAMES:
                    self._is_speaking = False
                    self._speech_frames = 0
                    
                    # Process the collected audio
                    await self._process_audio()
    
    async def _process_audio(self) -> None:
        """Process collected audio through the pipeline."""
        if not self._audio_buffer:
            return
        
        self._is_processing = True
        await self._emit(PipelineEventType.PROCESSING_AUDIO)
        
        try:
            # Combine audio buffer
            audio = b"".join(self._audio_buffer)
            self._audio_buffer.clear()
            
            # Transcribe
            transcript = await self.stt.transcribe(audio)
            
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

