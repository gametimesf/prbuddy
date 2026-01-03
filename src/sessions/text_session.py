"""Text-only session for PR Buddy.

Provides a simplified session that handles only text input/output
without any audio processing. Uses streaming to emit tool and handoff events.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Coroutine
from uuid import uuid4

from agents import Agent, Runner
from agents.run import RunResultStreaming
from agents.stream_events import (
    RawResponsesStreamEvent,
    RunItemStreamEvent,
)
from agents.items import (
    ToolCallItem,
    ToolCallOutputItem,
    HandoffCallItem,
    HandoffOutputItem,
    MessageOutputItem,
    ReasoningItem,
)

from ..observability.logging import get_logger
from .system_message import generate_pr_context_message

if TYPE_CHECKING:
    from .pr_context import PRContext

logger = get_logger(__name__)


class TextEventType(str, Enum):
    """Event types for text sessions."""

    # User input received
    USER_MESSAGE = "user_message"

    # Agent is processing
    AGENT_THINKING = "agent_thinking"

    # Agent response (final)
    AGENT_RESPONSE = "agent_response"

    # Agent response chunk (streaming)
    AGENT_RESPONSE_CHUNK = "agent_response_chunk"

    # Tool invocation
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"

    # Session events
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"

    # Handoff between agents
    AGENT_HANDOFF = "agent_handoff"

    # Knowledge base events
    KB_INDEXED = "kb_indexed"
    KB_QUERIED = "kb_queried"

    # Sources used for answer (for UI display)
    SOURCES_USED = "sources_used"

    # Structured output metadata (confidence, sources, etc.)
    STRUCTURED_METADATA = "structured_metadata"

    # Error occurred
    ERROR = "error"


@dataclass
class TextEvent:
    """Event emitted by a text session."""
    
    type: TextEventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=lambda: asyncio.get_event_loop().time())


# Type for event callbacks
TextEventCallback = Callable[[TextEvent], Coroutine[Any, Any, None]]


class TextSession:
    """Text-only session for agent interactions.
    
    Handles text input/output without any audio processing.
    Suitable for chat-based interfaces.
    
    Features:
    - Session persistence: history is saved to RAG store for resumption
    - Proactive research: auto-researches new PRs on first connect
    """
    
    def __init__(
        self,
        session_id: str,
        agent: Agent,
        *,
        pr_context: "PRContext | None" = None,
        session_type: str = "author",
        on_event: TextEventCallback | None = None,
        rag_store: Any | None = None,
    ) -> None:
        """Initialize a text session.
        
        Args:
            session_id: Unique session identifier.
            agent: The starting agent for this session.
            pr_context: Optional PR context.
            session_type: 'author' or 'reviewer'.
            on_event: Optional callback for session events.
            rag_store: Optional RAG store for persistence.
        """
        self.session_id = session_id
        self.agent = agent
        self.pr_context = pr_context
        self.session_type = session_type
        self._on_event = on_event
        self._history: list[dict[str, str]] = []
        self._current_agent = agent
        self._rag_store = rag_store
        self._history_loaded = False
        self._save_counter = 0
        # Track active tool calls by ID for matching results
        self._active_tool_calls: dict[str, str] = {}  # call_id -> tool_name
        # Also track as FIFO queue since SDK call_ids may not match between start/end
        self._tool_call_queue: list[str] = []  # tool_names in FIFO order

        # Track parent agent for auto-restore when Research doesn't hand back
        self._parent_agent: Agent | None = None

        # Background task tracking - allows agent to continue if client disconnects
        self._active_task: asyncio.Task | None = None

        # Initialize history with PR context as system message
        if self.pr_context:
            self._history.append({
                "role": "system",
                "content": generate_pr_context_message(self.pr_context),
            })

    async def _emit(self, event_type: TextEventType, data: dict[str, Any] | None = None) -> None:
        """Emit an event. Gracefully handles disconnected clients."""
        if self._on_event:
            event = TextEvent(type=event_type, data=data or {})
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

    def set_event_callback(self, callback: "TextEventCallback | None") -> None:
        """Set or clear the event callback. Used for WebSocket reconnection."""
        self._on_event = callback
    
    async def send_text(self, text: str) -> str:
        """Process a text message and get a response.
        
        Uses streaming mode to emit tool call and handoff events in real-time.
        
        Args:
            text: User's input text.
        
        Returns:
            Agent's response text.
        """
        await self._emit(TextEventType.USER_MESSAGE, {"text": text})
        await self._emit(TextEventType.AGENT_THINKING)
        
        # Add user message to history
        self._history.append({"role": "user", "content": text})
        
        try:
            # Run the agent with streaming to capture tool calls and handoffs
            result: RunResultStreaming = Runner.run_streamed(
                self._current_agent,
                input=self._history,
            )
            
            response_text = ""
            current_agent_name = self._current_agent.name
            
            # Process streaming events
            async for event in result.stream_events():
                if isinstance(event, RunItemStreamEvent):
                    item = event.item
                    
                    # Tool call starting
                    if isinstance(item, ToolCallItem):
                        tool_name = item.raw_item.name if hasattr(item.raw_item, 'name') else "unknown"
                        tool_args = item.raw_item.arguments if hasattr(item.raw_item, 'arguments') else "{}"
                        # Use call_id if available (matches ToolCallOutputItem), fall back to id
                        call_id = getattr(item.raw_item, 'call_id', None) or getattr(item.raw_item, 'id', None) or str(uuid4())

                        # Track this call for matching with result
                        self._active_tool_calls[call_id] = tool_name
                        self._tool_call_queue.append(tool_name)

                        logger.info(
                            "Tool call started",
                            tool=tool_name,
                            call_id=call_id,
                            agent=current_agent_name,
                            arguments=tool_args[:200] if len(str(tool_args)) > 200 else tool_args,
                        )
                        
                        await self._emit(TextEventType.TOOL_CALL, {
                            "tool": tool_name,
                            "call_id": call_id,
                            "arguments": tool_args,
                            "agent": current_agent_name,
                        })
                        
                        # Special handling for RAG tools
                        if tool_name == "index_to_rag":
                            await self._emit(TextEventType.KB_INDEXED, {
                                "tool": tool_name,
                                "agent": current_agent_name,
                            })
                        elif tool_name == "query_rag":
                            await self._emit(TextEventType.KB_QUERIED, {
                                "tool": tool_name,
                                "agent": current_agent_name,
                            })
                    
                    # Tool call completed
                    elif isinstance(item, ToolCallOutputItem):
                        # raw_item can be either a dict or object depending on SDK version
                        raw = item.raw_item or {}
                        is_dict = isinstance(raw, dict)

                        # Get call_id to look up tool name from stored ToolCallItem
                        if is_dict:
                            call_id = raw.get('call_id')
                        else:
                            call_id = getattr(raw, 'call_id', None)

                        # Look up tool name from stored call (by call_id or FIFO queue)
                        tool_name = self._active_tool_calls.pop(call_id, None) if call_id else None
                        if tool_name is None and self._tool_call_queue:
                            # SDK call_ids may not match - use FIFO queue as fallback
                            tool_name = self._tool_call_queue.pop(0)
                        tool_name = tool_name or "unknown"

                        # Truncate output for display
                        output_str = str(item.output)
                        if len(output_str) > 200:
                            output_str = output_str[:200] + "..."

                        # Check if tool failed
                        is_success = True
                        if isinstance(item.output, dict) and item.output.get("success") is False:
                            is_success = False
                            logger.warning(
                                "Tool call failed",
                                tool=tool_name,
                                call_id=call_id,
                                error=item.output.get("error"),
                            )
                        else:
                            logger.info(
                                "Tool call completed",
                                tool=tool_name,
                                call_id=call_id,
                                output_preview=output_str,
                            )

                        await self._emit(TextEventType.TOOL_RESULT, {
                            "tool": tool_name,
                            "call_id": call_id,
                            "success": is_success,
                            "output_preview": output_str,
                        })

                        # Emit sources for query_rag results (for UI display)
                        # Check by output structure (more robust than tool_name matching)
                        output = item.output
                        if isinstance(output, str):
                            import json
                            try:
                                output = json.loads(output)
                            except json.JSONDecodeError:
                                output = {}

                        # Detect query_rag output by structure: has "results" list with "content"/"doc_type"
                        is_rag_output = (
                            isinstance(output, dict) and
                            "results" in output and
                            isinstance(output.get("results"), list) and
                            output.get("success") is not False
                        )

                        if is_rag_output or tool_name == "query_rag":
                            results = output.get("results", []) if isinstance(output, dict) else []
                            if results:
                                logger.info(
                                    "query_rag_citations",
                                    count=len(results),
                                    doc_types=[r.get("doc_type") for r in results[:5]],
                                )
                                sources = [
                                    {
                                        "doc_type": r.get("doc_type", "unknown"),
                                        "preview": r.get("content", "")[:150] if r.get("content") else "",
                                        "content": r.get("content", ""),
                                        "source_url": r.get("source"),
                                        "file_path": r.get("file_path"),
                                    }
                                    for r in results[:5]
                                ]
                                if sources:
                                    logger.info(
                                        "sources_used_emit",
                                        count=len(sources),
                                        has_content=[bool(s.get("content")) for s in sources],
                                    )
                                await self._emit(TextEventType.SOURCES_USED, {
                                    "sources": sources,
                                })
                    
                    # Handoff initiated
                    elif isinstance(item, HandoffCallItem):
                        # Extract target from raw_item.name (e.g., "transfer_to_research" -> "Research")
                        tool_name = getattr(item.raw_item, 'name', '') if item.raw_item else ''
                        if tool_name.startswith('transfer_to_'):
                            # Convert "transfer_to_research" -> "Research"
                            target_name = tool_name.replace('transfer_to_', '').replace('_', ' ').title().replace(' ', '')
                        else:
                            target_name = getattr(item, 'target_agent', None)
                            target_name = target_name.name if target_name else "unknown"

                        # Track parent for auto-restore if Research doesn't hand back
                        if target_name == "Research":
                            self._parent_agent = self._current_agent

                        logger.info(
                            "Agent handoff initiated",
                            from_agent=current_agent_name,
                            to_agent=target_name,
                        )

                        await self._emit(TextEventType.AGENT_HANDOFF, {
                            "from": current_agent_name,
                            "to": target_name,
                            "status": "initiated",
                        })
                    
                    # Handoff completed
                    elif isinstance(item, HandoffOutputItem):
                        target = getattr(item, 'target_agent', None)
                        if target:
                            from_agent_name = self._current_agent.name
                            logger.info(
                                "Agent handoff completed",
                                from_agent=from_agent_name,
                                to_agent=target.name,
                            )
                            # Update both local variable and instance state
                            current_agent_name = target.name
                            self._current_agent = target
                            await self._emit(TextEventType.AGENT_HANDOFF, {
                                "from": from_agent_name,
                                "to": target.name,
                                "status": "completed",
                            })
                    
                    # Reasoning (for models that support it)
                    elif isinstance(item, ReasoningItem):
                        await self._emit(TextEventType.AGENT_THINKING, {
                            "reasoning": item.raw_item.summary if hasattr(item.raw_item, 'summary') else None,
                        })
            
            # Get final result (must wait for streaming to complete)
            raw_output = result.final_output

            # Handle structured output vs plain text
            response_text, metadata = self._extract_response_and_metadata(raw_output)

            # Emit structured metadata if present
            if metadata:
                await self._emit(TextEventType.STRUCTURED_METADATA, metadata)

            # Update current agent if changed
            if result.last_agent != self._current_agent:
                self._current_agent = result.last_agent

            # Auto-restore parent if Research didn't hand back
            if (self._current_agent.name == "Research" and
                self._parent_agent is not None):
                logger.info(
                    "Auto-restoring parent agent (Research didn't hand back)",
                    from_agent="Research",
                    to_agent=self._parent_agent.name,
                )
                self._current_agent = self._parent_agent
                self._parent_agent = None

            # Add assistant response to history
            self._history.append({"role": "assistant", "content": response_text})

            # Save history periodically
            await self._save_history()

            await self._emit(TextEventType.AGENT_RESPONSE, {"text": response_text})

            return response_text
            
        except Exception as e:
            error_msg = f"Error processing message: {str(e)}"
            await self._emit(TextEventType.ERROR, {"error": error_msg})
            raise
    
    async def _load_history(self) -> None:
        """Load conversation history from RAG store."""
        if self._history_loaded or not self._rag_store:
            return
        
        self._history_loaded = True
        history = await self._rag_store.load_conversation_history(self.session_type)
        if history:
            self._history = history
    
    async def _save_history(self) -> None:
        """Save conversation history to RAG store."""
        if not self._rag_store or not self._history:
            return
        
        # Save every 2 messages to reduce writes
        self._save_counter += 1
        if self._save_counter % 2 == 0:
            await self._rag_store.save_conversation_history(
                self.session_type, self._history
            )
    
    async def trigger_greeting(self) -> str:
        """Trigger the agent's greeting message.
        
        For new PRs or stale sessions:
        1. Checks if PR has been researched
        2. If not, triggers automatic research
        3. Generates greeting based on what we know
        
        For resumed sessions:
        1. Loads history from RAG store
        2. Generates a welcome-back message with summary
        
        Returns:
            Agent's greeting text.
        """
        await self._emit(TextEventType.SESSION_STARTED)
        
        # Load previous history if exists
        await self._load_history()
        
        # Check research status
        has_research = False
        research_summary = None
        if self._rag_store:
            has_research = await self._rag_store.has_been_researched()
            research_summary = await self._rag_store.get_research_summary()
        
        # Build context-aware greeting prompt (PR context is already in history as system message)
        # Count non-system messages for resume detection
        user_assistant_messages = [m for m in self._history if m.get("role") in ("user", "assistant")]
        
        if user_assistant_messages:
            # Resuming session - include history summary
            message_count = len(user_assistant_messages)
            greeting_prompt = (
                f"[SESSION RESUMED] We have {message_count} previous messages in our conversation. "
                f"The knowledge base has {research_summary.get('total_documents', 0) if research_summary else 0} documents. "
                "Welcome the user back and briefly remind them where we left off. "
                "If there's more you'd like to learn about the PR, mention it."
            )
        elif has_research and research_summary:
            # Returning to a researched PR - summarize what we know
            greeting_prompt = (
                f"[RESEARCHED PR] This PR has already been researched. "
                f"We have {research_summary.get('total_documents', 0)} documents indexed: "
                f"diffs={research_summary.get('document_types', {}).get('diff', 0)}, "
                f"descriptions={research_summary.get('document_types', {}).get('description', 0)}, "
                f"author explanations={research_summary.get('explanation_count', 0)}. "
                "Greet the author and summarize what you already know about this PR. "
                "Ask if there's anything specific they'd like to add or clarify."
            )
        else:
            # New PR - trigger research first
            if self.session_type == "author":
                greeting_prompt = (
                    "[NEW PR - RESEARCH NEEDED] This is a new PR with no existing context. "
                    "First, use fetch_pr_info and fetch_pr_diff to gather basic context about the PR. "
                    "Use the owner, repo, and pr_number from the PR context above. "
                    "Index the results to the knowledge base. "
                    "Then greet the author with a brief summary of what you found, "
                    "and ask them to explain the main purpose and key decisions."
                )
            else:  # reviewer
                greeting_prompt = (
                    "[NEW REVIEWER SESSION] This PR may not have been trained by the author yet. "
                    "Check the knowledge base for context with query_rag. "
                    "If little content exists, let the reviewer know and offer to fetch basic PR info."
                )
        
        try:
            logger.info(
                "Triggering greeting",
                agent=self._current_agent.name,
                session_type=self.session_type,
                has_history=bool(user_assistant_messages),
                has_research=has_research,
                pr_context=f"{self.pr_context.owner}/{self.pr_context.repo}#{self.pr_context.number}" if self.pr_context else None,
            )
            
            # Build input: start with existing history (includes PR context as system message)
            # then add the greeting prompt
            greeting_input = self._history.copy()
            greeting_input.append({"role": "system", "content": greeting_prompt})
            
            result: RunResultStreaming = Runner.run_streamed(
                self._current_agent,
                input=greeting_input,
            )
            
            current_agent_name = self._current_agent.name
            
            # Process streaming events for initial tool calls
            async for event in result.stream_events():
                if isinstance(event, RunItemStreamEvent):
                    item = event.item
                    
                    if isinstance(item, ToolCallItem):
                        tool_name = item.raw_item.name if hasattr(item.raw_item, 'name') else "unknown"
                        tool_args = item.raw_item.arguments if hasattr(item.raw_item, 'arguments') else "{}"
                        call_id = item.raw_item.id if hasattr(item.raw_item, 'id') else str(uuid4())
                        
                        # Track this call for matching with result
                        self._active_tool_calls[call_id] = tool_name
                        
                        logger.info(
                            "Greeting tool call started",
                            tool=tool_name,
                            call_id=call_id,
                            agent=current_agent_name,
                            arguments=tool_args[:200] if len(str(tool_args)) > 200 else tool_args,
                        )
                        
                        await self._emit(TextEventType.TOOL_CALL, {
                            "tool": tool_name,
                            "call_id": call_id,
                            "agent": current_agent_name,
                        })
                    
                    elif isinstance(item, ToolCallOutputItem):
                        # Get call_id from raw_item to look up tool name
                        call_id = item.raw_item.call_id if hasattr(item.raw_item, 'call_id') else None
                        tool_name = self._active_tool_calls.pop(call_id, "unknown") if call_id else "unknown"
                        output_str = str(item.output)
                        
                        # Check if tool failed
                        is_success = True
                        if isinstance(item.output, dict) and item.output.get("success") is False:
                            is_success = False
                            logger.warning(
                                "Greeting tool call failed",
                                tool=tool_name,
                                call_id=call_id,
                                error=item.output.get("error"),
                            )
                        else:
                            logger.info(
                                "Greeting tool call completed",
                                tool=tool_name,
                                call_id=call_id,
                                output_preview=output_str[:200] if len(output_str) > 200 else output_str,
                            )
                        
                        await self._emit(TextEventType.TOOL_RESULT, {
                            "tool": tool_name,
                            "call_id": call_id,
                            "success": is_success,
                        })
                    
                    elif isinstance(item, HandoffOutputItem):
                        target = getattr(item, 'target_agent', None)
                        if target:
                            logger.info(
                                "Greeting handoff completed",
                                from_agent=self._current_agent.name,
                                to_agent=target.name,
                            )
                            current_agent_name = target.name
                            await self._emit(TextEventType.AGENT_HANDOFF, {
                                "from": self._current_agent.name,
                                "to": target.name,
                                "status": "completed",
                            })
            
            raw_output = result.final_output

            # Handle structured output vs plain text
            response_text, metadata = self._extract_response_and_metadata(raw_output)
            if not response_text:
                response_text = self._get_default_greeting()

            # Emit structured metadata if present
            if metadata:
                await self._emit(TextEventType.STRUCTURED_METADATA, metadata)

            # Update current agent if changed
            if result.last_agent != self._current_agent:
                self._current_agent = result.last_agent

            await self._emit(TextEventType.AGENT_RESPONSE, {"text": response_text})

            return response_text

        except Exception as e:
            error_msg = f"Error generating greeting: {str(e)}"
            await self._emit(TextEventType.ERROR, {"error": error_msg})
            raise
    
    def _get_default_greeting(self) -> str:
        """Get default greeting based on session type."""
        if self.session_type == "author":
            return (
                "Hello! I'm ready to learn about your PR. "
                "Can you start by explaining the main purpose of your changes?"
            )
        else:
            return (
                "Hello! I'm here to answer questions about this PR. "
                "What would you like to know?"
            )
    
    def get_history(self) -> list[dict[str, str]]:
        """Get the conversation history."""
        return self._history.copy()
    
    def clear_history(self) -> None:
        """Clear the conversation history."""
        self._history.clear()
    
    async def end_session(self) -> None:
        """End the session and save history."""
        # Save final history
        if self._rag_store and self._history:
            await self._rag_store.save_conversation_history(
                self.session_type, self._history
            )
        await self._emit(TextEventType.SESSION_ENDED)

