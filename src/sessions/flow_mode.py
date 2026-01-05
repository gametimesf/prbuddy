"""Flow Mode for continuous author capture.

Enables authors to explain their PR changes in a natural, uninterrupted flow
while the system continuously captures, indexes, and researches in the background.

Key components:
- FlowModeState: Tracks capture vs engagement mode, transcripts, questions
- BackgroundProcessor: Handles async indexing and research
- EngagementDetector: Detects when user wants to engage (keyword or button)
- AcknowledgementGenerator: Produces short "uh huh", "got it" responses
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Coroutine

import structlog

if TYPE_CHECKING:
    from ..rag.store import WeaviatePRRAGStore

logger = structlog.get_logger(__name__)


class FlowModePhase(str, Enum):
    """Current phase of flow mode."""
    CAPTURE = "capture"      # User is speaking, system is listening
    ENGAGEMENT = "engagement"  # System is asking questions


@dataclass
class TranscriptChunk:
    """A chunk of transcribed speech."""
    id: str
    text: str
    timestamp: float
    is_final: bool = True
    topics: list[str] = field(default_factory=list)


@dataclass
class Question:
    """A clarifying question generated during capture."""
    id: str
    text: str
    topic: str
    priority: float  # 0-1, higher = ask sooner
    generated_at: float
    context: list[str] = field(default_factory=list)  # Transcript excerpts
    answered_by: str | None = None  # Transcript chunk ID if answered
    confidence_answered: float = 0.0


@dataclass
class ResearchResult:
    """Result from background research."""
    topic: str
    findings: list[dict[str, Any]]
    timestamp: float
    source: str  # "rag", "unblocked", "github"


@dataclass
class FlowModeState:
    """State for continuous capture mode."""

    phase: FlowModePhase = FlowModePhase.CAPTURE

    # Transcript accumulation
    transcript_chunks: list[TranscriptChunk] = field(default_factory=list)
    current_utterance: str = ""
    last_speech_time: float = 0.0
    total_speech_duration: float = 0.0

    # Topic tracking
    topics_mentioned: set[str] = field(default_factory=set)
    topics_explained: dict[str, float] = field(default_factory=dict)

    # Question management
    pending_questions: list[Question] = field(default_factory=list)
    asked_questions: list[Question] = field(default_factory=list)

    # Research tracking
    research_results: list[ResearchResult] = field(default_factory=list)

    # Acknowledgement tracking
    last_acknowledgement_time: float = 0.0
    acknowledgement_count: int = 0


# Engagement keywords that signal user wants to interact
ENGAGEMENT_KEYWORDS = [
    # Direct questions to AI
    "what do you think",
    "any questions",
    "got it",
    "make sense",
    "anything else",
    "what else",
    "need to know",
    "understand",
    "clear so far",
    "following",
    "with me",
    "your thoughts",
    # Completion signals
    "that's it",
    "that's all",
    "done explaining",
    "finished",
    "over to you",
    "your turn",
    "ready for questions",
]

# Short acknowledgements to give during pauses
ACKNOWLEDGEMENTS = [
    "got it",
    "mm-hmm",
    "okay",
    "right",
    "uh-huh",
    "I see",
    "makes sense",
    "understood",
]


class EngagementDetector:
    """Detects engagement signals in transcript."""

    def __init__(self, keywords: list[str] | None = None):
        self.keywords = [k.lower() for k in (keywords or ENGAGEMENT_KEYWORDS)]

    def check_for_engagement(self, text: str) -> tuple[bool, float]:
        """Check if text contains an engagement signal.

        Args:
            text: Transcript text to check.

        Returns:
            Tuple of (is_engagement_signal, confidence).
        """
        text_lower = text.lower().strip()

        # Check for exact or partial keyword matches
        for keyword in self.keywords:
            if keyword in text_lower:
                # Higher confidence for shorter utterances (more likely intentional)
                word_count = len(text_lower.split())
                confidence = min(1.0, 0.7 + (0.3 * (1.0 / max(word_count, 1))))
                logger.info(
                    "engagement_keyword_detected",
                    keyword=keyword,
                    confidence=confidence,
                )
                return True, confidence

        return False, 0.0


class AcknowledgementGenerator:
    """Generates short acknowledgements for flow mode."""

    def __init__(self, acknowledgements: list[str] | None = None):
        self.acknowledgements = acknowledgements or ACKNOWLEDGEMENTS
        self._last_used: str | None = None

    def generate(self) -> str:
        """Generate a random acknowledgement, avoiding repeats.

        Returns:
            Short acknowledgement string.
        """
        # Filter out last used to avoid repetition
        available = [a for a in self.acknowledgements if a != self._last_used]
        if not available:
            available = self.acknowledgements

        ack = random.choice(available)
        self._last_used = ack
        return ack


class BackgroundProcessor:
    """Processes transcript stream in background while user talks.

    Handles:
    - Indexing transcript chunks to RAG
    - Triggering background research based on topics
    - Generating and refining clarifying questions
    """

    # Time between acknowledgements (seconds)
    MIN_ACK_INTERVAL = 8.0
    # Pause duration that triggers acknowledgement (seconds)
    PAUSE_FOR_ACK = 2.5
    # How often to run the question refinement loop (seconds)
    REFINEMENT_INTERVAL = 5.0

    def __init__(
        self,
        rag_store: "WeaviatePRRAGStore",
        pr_url: str,
        on_acknowledgement: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        on_research_complete: Callable[[ResearchResult], Coroutine[Any, Any, None]] | None = None,
    ):
        """Initialize background processor.

        Args:
            rag_store: RAG store for indexing.
            pr_url: PR URL for context.
            on_acknowledgement: Callback when acknowledgement should be spoken.
            on_research_complete: Callback when research completes.
        """
        self.rag_store = rag_store
        self.pr_url = pr_url
        self._on_acknowledgement = on_acknowledgement
        self._on_research_complete = on_research_complete

        self.state = FlowModeState()
        self.engagement_detector = EngagementDetector()
        self.ack_generator = AcknowledgementGenerator()

        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._research_tasks: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        """Start background processing loops."""
        if self._running:
            return

        self._running = True
        self.state.last_speech_time = time.time()
        logger.info("flow_mode_started", pr_url=self.pr_url)

    async def stop(self) -> None:
        """Stop background processing."""
        self._running = False

        # Cancel any pending research tasks
        for task in self._research_tasks.values():
            if not task.done():
                task.cancel()
        self._research_tasks.clear()

        logger.info(
            "flow_mode_stopped",
            transcript_chunks=len(self.state.transcript_chunks),
            questions_generated=len(self.state.pending_questions),
        )

    async def feed_transcript(self, text: str, is_final: bool = True) -> bool:
        """Feed a transcript chunk from STT.

        Args:
            text: Transcribed text.
            is_final: Whether this is a final transcript (vs interim).

        Returns:
            True if engagement signal detected.
        """
        if not self._running or not text.strip():
            return False

        current_time = time.time()

        # Create transcript chunk
        chunk = TranscriptChunk(
            id=f"chunk_{len(self.state.transcript_chunks)}_{int(current_time)}",
            text=text.strip(),
            timestamp=current_time,
            is_final=is_final,
        )

        self.state.transcript_chunks.append(chunk)
        self.state.last_speech_time = current_time

        logger.debug(
            "transcript_chunk_received",
            chunk_id=chunk.id,
            text_preview=text[:50] if len(text) > 50 else text,
        )

        # Index to RAG immediately
        await self._index_chunk(chunk)

        # Check for engagement signal
        is_engagement, confidence = self.engagement_detector.check_for_engagement(text)
        if is_engagement:
            logger.info(
                "engagement_signal_in_transcript",
                text=text,
                confidence=confidence,
            )
            return True

        return False

    async def check_for_pause_acknowledgement(self) -> str | None:
        """Check if we should give an acknowledgement due to pause.

        Call this periodically to check if user has paused long enough
        for an acknowledgement.

        Returns:
            Acknowledgement text if one should be given, None otherwise.
        """
        if not self._running or self.state.phase != FlowModePhase.CAPTURE:
            return None

        current_time = time.time()
        time_since_speech = current_time - self.state.last_speech_time
        time_since_ack = current_time - self.state.last_acknowledgement_time

        # Check if pause is long enough and we haven't acknowledged recently
        if time_since_speech >= self.PAUSE_FOR_ACK and time_since_ack >= self.MIN_ACK_INTERVAL:
            # Only acknowledge if we have some transcript content
            if len(self.state.transcript_chunks) > 0:
                ack = self.ack_generator.generate()
                self.state.last_acknowledgement_time = current_time
                self.state.acknowledgement_count += 1

                logger.info(
                    "acknowledgement_triggered",
                    pause_duration=time_since_speech,
                    acknowledgement=ack,
                    count=self.state.acknowledgement_count,
                )

                if self._on_acknowledgement:
                    await self._on_acknowledgement(ack)

                return ack

        return None

    async def _index_chunk(self, chunk: TranscriptChunk) -> None:
        """Index a transcript chunk to RAG.

        Args:
            chunk: Transcript chunk to index.
        """
        try:
            await self.rag_store.add_document(
                doc_type="author_flow_transcript",
                content=chunk.text,
                source_url=self.pr_url,
                metadata={
                    "chunk_id": chunk.id,
                    "timestamp": chunk.timestamp,
                    "is_final": chunk.is_final,
                },
            )
            logger.debug("chunk_indexed", chunk_id=chunk.id)
        except Exception as e:
            logger.error("chunk_index_failed", chunk_id=chunk.id, error=str(e))

    def get_full_transcript(self) -> str:
        """Get the full concatenated transcript.

        Returns:
            All transcript chunks joined together.
        """
        return " ".join(chunk.text for chunk in self.state.transcript_chunks)

    def get_pending_questions(self) -> list[Question]:
        """Get unanswered questions sorted by priority.

        Returns:
            List of questions with low answered confidence, sorted by priority.
        """
        unanswered = [
            q for q in self.state.pending_questions
            if q.confidence_answered < 0.7
        ]
        return sorted(unanswered, key=lambda q: -q.priority)

    async def transition_to_engagement(self) -> dict[str, Any]:
        """Transition from capture to engagement mode.

        Returns:
            Summary of capture phase for engagement agent.
        """
        self.state.phase = FlowModePhase.ENGAGEMENT

        # Get summary for engagement
        transcript = self.get_full_transcript()
        questions = self.get_pending_questions()

        logger.info(
            "transitioning_to_engagement",
            transcript_length=len(transcript),
            pending_questions=len(questions),
            research_results=len(self.state.research_results),
        )

        return {
            "transcript": transcript,
            "transcript_chunks": len(self.state.transcript_chunks),
            "pending_questions": [
                {"text": q.text, "topic": q.topic, "priority": q.priority}
                for q in questions[:5]  # Top 5 questions
            ],
            "research_results": [
                {"topic": r.topic, "source": r.source}
                for r in self.state.research_results
            ],
            "topics_mentioned": list(self.state.topics_mentioned),
            "acknowledgement_count": self.state.acknowledgement_count,
        }

    def reset(self) -> None:
        """Reset state for a new flow mode session."""
        self.state = FlowModeState()
        self._research_tasks.clear()
        logger.info("flow_mode_reset")
