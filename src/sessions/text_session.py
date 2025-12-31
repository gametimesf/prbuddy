"""Text-only session for PR Buddy.

Provides a simplified session that handles only text input/output
without any audio processing.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Coroutine
from uuid import uuid4

from agents import Agent, Runner

if TYPE_CHECKING:
    from .pr_context import PRContext


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
    """
    
    def __init__(
        self,
        session_id: str,
        agent: Agent,
        *,
        pr_context: "PRContext | None" = None,
        on_event: TextEventCallback | None = None,
    ) -> None:
        """Initialize a text session.
        
        Args:
            session_id: Unique session identifier.
            agent: The starting agent for this session.
            pr_context: Optional PR context.
            on_event: Optional callback for session events.
        """
        self.session_id = session_id
        self.agent = agent
        self.pr_context = pr_context
        self._on_event = on_event
        self._history: list[dict[str, str]] = []
        self._current_agent = agent
    
    async def _emit(self, event_type: TextEventType, data: dict[str, Any] | None = None) -> None:
        """Emit an event to the callback if registered."""
        if self._on_event:
            event = TextEvent(type=event_type, data=data or {})
            await self._on_event(event)
    
    async def send_text(self, text: str) -> str:
        """Process a text message and get a response.
        
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
            # Run the agent
            result = await Runner.run(
                self._current_agent,
                input=self._history,
            )
            
            # Extract response text
            response_text = result.final_output if result.final_output else ""
            
            # Check for agent handoff
            if result.last_agent != self._current_agent:
                await self._emit(TextEventType.AGENT_HANDOFF, {
                    "from": self._current_agent.name,
                    "to": result.last_agent.name,
                })
                self._current_agent = result.last_agent
            
            # Add assistant response to history
            self._history.append({"role": "assistant", "content": response_text})
            
            await self._emit(TextEventType.AGENT_RESPONSE, {"text": response_text})
            
            return response_text
            
        except Exception as e:
            error_msg = f"Error processing message: {str(e)}"
            await self._emit(TextEventType.ERROR, {"error": error_msg})
            raise
    
    async def trigger_greeting(self) -> str:
        """Trigger the agent's greeting message.
        
        Returns:
            Agent's greeting text.
        """
        await self._emit(TextEventType.SESSION_STARTED)
        
        # Use empty history to get initial greeting
        try:
            result = await Runner.run(
                self._current_agent,
                input=[{"role": "user", "content": "Hello"}],
            )
            
            response_text = result.final_output if result.final_output else "Hello! How can I help you?"
            
            # Don't add greeting exchange to history
            await self._emit(TextEventType.AGENT_RESPONSE, {"text": response_text})
            
            return response_text
            
        except Exception as e:
            error_msg = f"Error generating greeting: {str(e)}"
            await self._emit(TextEventType.ERROR, {"error": error_msg})
            raise
    
    def get_history(self) -> list[dict[str, str]]:
        """Get the conversation history."""
        return self._history.copy()
    
    def clear_history(self) -> None:
        """Clear the conversation history."""
        self._history.clear()
    
    async def end_session(self) -> None:
        """End the session."""
        await self._emit(TextEventType.SESSION_ENDED)

