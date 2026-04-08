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

import structlog

from agents import Agent, Runner

from ..agents.hooks import create_logging_hooks
from .system_message import generate_pr_context_message
from .flow_mode import BackgroundProcessor, FlowModePhase

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from ..rag.store import WeaviatePRRAGStore
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

    # Structured output metadata (confidence, sources, etc.)
    STRUCTURED_METADATA = "structured_metadata"

    # Flow mode events
    FLOW_MODE_STARTED = "flow_mode_started"
    FLOW_MODE_ENDED = "flow_mode_ended"
    FLOW_ACKNOWLEDGEMENT = "flow_acknowledgement"
    FLOW_ENGAGEMENT_SIGNAL = "flow_engagement_signal"
    FLOW_TRANSCRIPT_CHUNK = "flow_transcript_chunk"

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
    
    # VAD constants
    SILENCE_THRESHOLD = 1.5  # seconds of silence before processing
    ENERGY_THRESHOLD = 1500  # RMS threshold for speech detection (higher = less sensitive)
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
        session_type: str = "author",
        on_event: EventCallback | None = None,
        rag_store: "WeaviatePRRAGStore | None" = None,
    ) -> None:
        """Initialize the pipeline session.

        Args:
            session_id: Unique session identifier.
            stt: Speech-to-text provider.
            agent: The starting agent.
            tts: Text-to-speech provider.
            tts_config: TTS configuration.
            pr_context: Optional PR context.
            session_type: 'author' or 'reviewer' for history persistence.
            on_event: Optional event callback.
            rag_store: Optional RAG store for history persistence.
        """
        self.session_id = session_id
        self.stt = stt
        self.agent = agent
        self.tts = tts
        self.tts_config = tts_config
        self.pr_context = pr_context
        self.session_type = session_type
        self._on_event = on_event
        self._rag_store = rag_store
        self._history_loaded = False

        # VAD state
        self._audio_buffer: list[bytes] = []
        self._last_audio_time = 0.0
        self._is_speaking = False
        self._is_processing = False
        self._is_playing = False

        # Conversation state - will be loaded from RAG or initialized with PR context
        self._history: list[dict[str, str]] = []
        self._current_agent = agent

        # Background task tracking - allows agent to continue if client disconnects
        self._active_task: asyncio.Task | None = None

        # Pending selection to be prepended to next agent input
        self._pending_selection: dict[str, Any] | None = None

        # Flow mode state
        self._flow_mode_enabled = False
        self._flow_processor: BackgroundProcessor | None = None
        self._flow_ack_task: asyncio.Task | None = None
    
    async def _emit(self, event_type: PipelineEventType, data: dict[str, Any] | None = None) -> None:
        """Emit an event. Gracefully handles disconnected clients."""
        if self._on_event:
            event = PipelineEvent(type=event_type, data=data or {})
            try:
                await self._on_event(event)
            except Exception as e:
                # Client likely disconnected - log but don't fail the agent
                logger.debug(
                    "event_emission_failed",
                    event_type=event_type.value,
                    error=str(e),
                )
                # Clear callback to avoid repeated failures
                self._on_event = None

    def set_event_callback(self, callback: EventCallback | None) -> None:
        """Set or clear the event callback. Used for WebSocket reconnection."""
        self._on_event = callback

    def set_pending_selection(self, selection: dict[str, Any] | None) -> None:
        """Set selection to be included with next agent input.

        The selection will be prepended to the transcribed text before
        sending to the agent.

        Args:
            selection: Selection data with 'text', 'hasSelection', and 'context'.
        """
        self._pending_selection = selection
        if selection and selection.get("hasSelection"):
            logger.info("pending_selection_set", text_len=len(selection.get("text", "")))

    # =========================================================================
    # Flow Mode Methods
    # =========================================================================

    @property
    def is_flow_mode(self) -> bool:
        """Check if flow mode is currently enabled."""
        return self._flow_mode_enabled

    async def enable_flow_mode(self) -> None:
        """Enable flow mode for continuous capture.

        In flow mode:
        - Audio is transcribed but agent doesn't respond
        - System gives short acknowledgements on pauses
        - Background processor indexes and researches
        - Engagement triggers full agent response
        """
        if self._flow_mode_enabled:
            return

        # Ensure history is loaded
        await self._load_history()

        # Create background processor
        pr_url = self.pr_context.github_url if self.pr_context else ""
        self._flow_processor = BackgroundProcessor(
            rag_store=self._rag_store,
            pr_url=pr_url,
            on_acknowledgement=self._handle_flow_acknowledgement,
        )

        await self._flow_processor.start()
        self._flow_mode_enabled = True

        # Start acknowledgement check loop
        self._flow_ack_task = asyncio.create_task(self._flow_ack_loop())

        await self._emit(PipelineEventType.FLOW_MODE_STARTED)
        logger.info("flow_mode_enabled", session_id=self.session_id)

    async def disable_flow_mode(self) -> None:
        """Disable flow mode and return to normal turn-based mode."""
        if not self._flow_mode_enabled:
            return

        # Stop acknowledgement loop
        if self._flow_ack_task and not self._flow_ack_task.done():
            self._flow_ack_task.cancel()
            try:
                await self._flow_ack_task
            except asyncio.CancelledError:
                pass
        self._flow_ack_task = None

        # Stop background processor
        if self._flow_processor:
            await self._flow_processor.stop()
            self._flow_processor = None

        self._flow_mode_enabled = False
        await self._emit(PipelineEventType.FLOW_MODE_ENDED)
        logger.info("flow_mode_disabled", session_id=self.session_id)

    async def trigger_flow_engagement(self) -> str:
        """Trigger engagement mode in flow mode.

        Called when user clicks "Ready for questions" button or
        says an engagement keyword.

        Returns:
            Agent response for engagement.
        """
        if not self._flow_mode_enabled or not self._flow_processor:
            return "Flow mode is not active."

        # Get capture summary
        summary = await self._flow_processor.transition_to_engagement()

        # Build engagement context
        transcript = summary["transcript"]
        if not transcript.strip():
            return "I didn't catch anything. Could you explain your changes?"

        # Create engagement prompt with captured context
        engagement_prompt = self._build_engagement_prompt(summary)

        logger.info(
            "flow_engagement_triggered",
            transcript_length=len(transcript),
            questions=len(summary["pending_questions"]),
        )

        await self._emit(PipelineEventType.FLOW_ENGAGEMENT_SIGNAL, summary)

        # Disable flow mode and run normal agent response
        await self.disable_flow_mode()

        # Process with agent (will synthesize and stream)
        self._is_processing = True
        try:
            response = await self._run_agent(engagement_prompt)
            await self._synthesize_and_stream(response)
            return response
        finally:
            self._is_processing = False

    def _build_engagement_prompt(self, summary: dict[str, Any]) -> str:
        """Build the engagement prompt from flow mode summary.

        Args:
            summary: Summary from BackgroundProcessor.transition_to_engagement().

        Returns:
            Prompt string for the agent.
        """
        transcript = summary["transcript"]
        questions = summary.get("pending_questions", [])

        prompt_parts = [
            "[FLOW MODE CAPTURE COMPLETE]",
            "",
            "The author just explained their PR changes. Here's what they said:",
            "",
            f'"""{transcript}"""',
            "",
        ]

        if questions:
            prompt_parts.extend([
                "Questions that came up during their explanation:",
                "",
            ])
            for i, q in enumerate(questions[:3], 1):
                prompt_parts.append(f"{i}. {q['text']}")
            prompt_parts.append("")

        prompt_parts.extend([
            "Please:",
            "1. Briefly acknowledge what you understood (1-2 sentences)",
            "2. Ask the most important clarifying question",
            "3. Index key insights to the knowledge base",
        ])

        return "\n".join(prompt_parts)

    async def _handle_flow_acknowledgement(self, ack_text: str) -> None:
        """Handle acknowledgement callback from flow processor.

        Args:
            ack_text: Acknowledgement text to speak.
        """
        await self._emit(PipelineEventType.FLOW_ACKNOWLEDGEMENT, {"text": ack_text})

        # Synthesize the short acknowledgement
        await self._synthesize_and_stream(ack_text)

    async def _flow_ack_loop(self) -> None:
        """Background loop to check for pause acknowledgements."""
        while self._flow_mode_enabled and self._flow_processor:
            try:
                await self._flow_processor.check_for_pause_acknowledgement()
                await asyncio.sleep(0.5)  # Check every 500ms
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("flow_ack_loop_error", error=str(e))
                await asyncio.sleep(1.0)

    def _extract_response_and_metadata(self, raw_output: Any) -> tuple[str, dict[str, Any] | None]:
        """Extract displayable text and metadata from agent output.

        Handles both structured output (Pydantic models) and plain text.

        Args:
            raw_output: The raw output from the agent (could be str or Pydantic model).

        Returns:
            Tuple of (response_text, metadata_dict or None).
        """
        # Check for ReviewerResponse structured output
        if hasattr(raw_output, 'answer'):
            metadata = {
                "confidence": getattr(raw_output, 'confidence', None),
                "sources_used": getattr(raw_output, 'sources_used', []),
                "needs_author_clarification": getattr(raw_output, 'needs_author_clarification', False),
            }
            return raw_output.answer, metadata

        # Check for AuthorTrainingResponse structured output
        if hasattr(raw_output, 'response') and hasattr(raw_output, 'question_type'):
            metadata = {
                "question_type": getattr(raw_output, 'question_type', None),
                "topics_covered": getattr(raw_output, 'topics_covered', []),
                "suggested_topics": getattr(raw_output, 'suggested_topics', []),
            }
            return raw_output.response, metadata

        # Check for ResearchResponse structured output
        if hasattr(raw_output, 'summary') and hasattr(raw_output, 'documents_indexed'):
            metadata = {
                "documents_indexed": getattr(raw_output, 'documents_indexed', 0),
                "source_types": getattr(raw_output, 'source_types', []),
                "unblocked_context_found": getattr(raw_output, 'unblocked_context_found', False),
            }
            return raw_output.summary, metadata

        # Plain text output
        return str(raw_output) if raw_output else "", None

    async def _load_history(self) -> None:
        """Load conversation history from RAG store."""
        logger.debug(
            "load_history_start",
            history_loaded=self._history_loaded,
            has_rag_store=bool(self._rag_store),
            session_type=self.session_type,
        )
        if self._history_loaded or not self._rag_store:
            # No RAG store - initialize with PR context only
            if not self._history_loaded and self.pr_context:
                self._history = [{
                    "role": "system",
                    "content": generate_pr_context_message(self.pr_context),
                }]
            self._history_loaded = True
            logger.debug("load_history_skipped", reason="already_loaded_or_no_rag")
            return

        self._history_loaded = True
        history = await self._rag_store.load_conversation_history(self.session_type)
        logger.info(
            "load_history_result",
            loaded_messages=len(history) if history else 0,
            session_type=self.session_type,
        )
        if history:
            # Use loaded history (includes PR context from when it was saved)
            self._history = history
        elif self.pr_context:
            # No saved history - start fresh with PR context
            self._history = [{
                "role": "system",
                "content": generate_pr_context_message(self.pr_context),
            }]

    async def _save_history(self) -> None:
        """Save conversation history to RAG store."""
        if not self._rag_store or not self._history:
            return

        await self._rag_store.save_conversation_history(
            self.session_type, self._history
        )
    
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
                await self._emit(PipelineEventType.ERROR, {
                    "error": "no_speech_detected",
                    "message": "Didn't catch that. Try again.",
                })
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
                await self._emit(PipelineEventType.ERROR, {
                    "error": "no_speech_detected",
                    "message": "Didn't catch that. Try again.",
                })
                self._is_processing = False
                return

            await self._emit(PipelineEventType.TRANSCRIPT, {"text": transcript})

            # Flow mode: feed to processor, check for engagement
            if self._flow_mode_enabled and self._flow_processor:
                await self._emit(PipelineEventType.FLOW_TRANSCRIPT_CHUNK, {"text": transcript})

                # Feed transcript to flow processor
                is_engagement = await self._flow_processor.feed_transcript(transcript)

                if is_engagement:
                    # User said an engagement keyword - trigger engagement
                    logger.info("engagement_keyword_detected_in_audio", transcript=transcript[:50])
                    await self.trigger_flow_engagement()

                # Don't run agent in flow mode - just capture
                self._is_processing = False
                return

            # Normal mode: process with agent
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
        # Get and clear any pending selection
        selection = self._pending_selection
        self._pending_selection = None

        # Prepend selection context to message if present
        if selection and selection.get("hasSelection"):
            selection_text = selection.get("text", "")
            context = selection.get("context", {})
            file_path = context.get("filePath", "")
            file_info = f" (from {file_path})" if file_path else ""
            text = f"Current diff selection{file_info}:\n```\n{selection_text}\n```\n\nUser question: {text}"
            logger.info("selection_prepended_voice", file_path=file_path, selection_len=len(selection_text))

        await self._emit(PipelineEventType.AGENT_THINKING)

        # Add to history
        self._history.append({"role": "user", "content": text})

        # Create hooks for logging agent activities
        async def emit_hook_event(event_type: str, data: dict[str, Any]) -> None:
            """Emit hook events as pipeline events."""
            if event_type == "tool_start":
                await self._emit(PipelineEventType.TOOL_CALL, data)
            elif event_type == "tool_end":
                await self._emit(PipelineEventType.TOOL_RESULT, data)
            elif event_type == "agent_handoff":
                # Translate field names to match frontend expectations
                await self._emit(PipelineEventType.AGENT_HANDOFF, {
                    "from": data.get("from_agent"),
                    "to": data.get("to_agent"),
                    "status": "completed",
                    "turn": data.get("turn"),
                })
            elif event_type == "agent_start":
                await self._emit(PipelineEventType.AGENT_THINKING, {
                    "agent": data.get("agent"),
                    "turn": data.get("turn"),
                })

        hooks = create_logging_hooks(on_event=emit_hook_event)

        # Build agent input — inject RAG context for reviewer sessions
        run_input = self._history
        if self.session_type == "reviewer" and self._rag_store:
            from .context_injection import build_rag_context
            rag_context = await build_rag_context(text, self._rag_store)
            if rag_context:
                run_input = self._history.copy()
                run_input.insert(-1, {"role": "system", "content": rag_context})
                logger.info("rag_context_injected", question=text[:80])

        # Run agent with timeout to prevent hanging
        try:
            result = await asyncio.wait_for(
                Runner.run(
                    self._current_agent,
                    input=run_input,
                    hooks=hooks,
                ),
                timeout=120.0,  # 2 minute timeout
            )
        except asyncio.TimeoutError:
            logger.error("agent_timeout", agent=self._current_agent.name, timeout=120)
            await self._emit(PipelineEventType.ERROR, {"error": "Agent timed out after 120 seconds"})
            return "I apologize, but I'm taking too long to respond. Please try again."

        # Handle structured output vs plain text
        response, metadata = self._extract_response_and_metadata(result.final_output)

        # Emit structured metadata if present
        if metadata:
            await self._emit(PipelineEventType.STRUCTURED_METADATA, metadata)

        # Check for handoff
        if result.last_agent != self._current_agent:
            logger.info(
                "agent_handoff_complete",
                from_agent=self._current_agent.name,
                to_agent=result.last_agent.name,
            )
            self._current_agent = result.last_agent

        # Add response to history
        self._history.append({"role": "assistant", "content": response})

        # Save history for cross-session persistence
        await self._save_history()

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

        Loads conversation history from RAG if available, then generates
        a context-aware greeting.

        Returns:
            Greeting text.
        """
        await self._emit(PipelineEventType.SESSION_STARTED)

        # Load conversation history (includes PR context)
        await self._load_history()

        self._is_processing = True

        try:
            # Build input with history + greeting trigger
            input_messages = self._history.copy()
            input_messages.append({"role": "user", "content": "Hello"})

            # Create hooks for logging agent activities
            async def emit_hook_event(event_type: str, data: dict[str, Any]) -> None:
                """Emit hook events as pipeline events."""
                if event_type == "tool_start":
                    await self._emit(PipelineEventType.TOOL_CALL, data)
                elif event_type == "tool_end":
                    await self._emit(PipelineEventType.TOOL_RESULT, data)
                elif event_type == "agent_handoff":
                    # Translate field names to match frontend expectations
                    await self._emit(PipelineEventType.AGENT_HANDOFF, {
                        "from": data.get("from_agent"),
                        "to": data.get("to_agent"),
                        "status": "completed",
                        "turn": data.get("turn"),
                    })
                elif event_type == "agent_start":
                    await self._emit(PipelineEventType.AGENT_THINKING, {
                        "agent": data.get("agent"),
                        "turn": data.get("turn"),
                    })

            hooks = create_logging_hooks(on_event=emit_hook_event)

            # Get greeting with timeout
            try:
                result = await asyncio.wait_for(
                    Runner.run(
                        self._current_agent,
                        input=input_messages,
                        hooks=hooks,
                    ),
                    timeout=60.0,  # 1 minute timeout for greeting
                )
                # Handle structured output vs plain text
                greeting, metadata = self._extract_response_and_metadata(result.final_output)
                if not greeting:
                    greeting = "Hello! How can I help you?"

                # Emit structured metadata if present
                if metadata:
                    await self._emit(PipelineEventType.STRUCTURED_METADATA, metadata)

            except asyncio.TimeoutError:
                logger.error("greeting_timeout", agent=self._current_agent.name, timeout=60)
                greeting = "Hello! I'm ready to help you with this PR. What would you like to discuss?"

            # Add to history for continuity
            self._history.append({"role": "user", "content": "Hello"})
            self._history.append({"role": "assistant", "content": greeting})

            # Save history for cross-session persistence
            await self._save_history()

            await self._emit(PipelineEventType.AGENT_RESPONSE, {"text": greeting})

            # Synthesize greeting
            await self._synthesize_and_stream(greeting)

            return greeting
        finally:
            self._is_processing = False
    
    async def end_session(self) -> None:
        """End the session."""
        await self._emit(PipelineEventType.SESSION_ENDED)

