"""Agent run hooks for logging and monitoring.

This module provides hooks that can be passed to Runner.run() to log
all agent activities including tool calls, handoffs, and completions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Coroutine

import structlog

from agents import Agent, RunHooks

if TYPE_CHECKING:
    from agents.run_context import RunContextWrapper
    from agents.tool import FunctionTool

logger = structlog.get_logger(__name__)


# Event callback type for UI updates
EventCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


@dataclass
class LoggingRunHooks(RunHooks[Any]):
    """Run hooks that log all agent activities.

    Logs:
    - Agent start/end
    - Tool start/end with names and results
    - Handoffs between agents

    Optionally emits events for UI updates via on_event callback.
    """

    on_event: EventCallback | None = None
    _current_turn: int = field(default=0, init=False)

    async def on_agent_start(
        self,
        context: "RunContextWrapper[Any]",
        agent: Agent[Any],
    ) -> None:
        """Called when an agent starts processing."""
        self._current_turn += 1
        logger.info(
            "agent_start",
            agent=agent.name,
            turn=self._current_turn,
        )
        if self.on_event:
            await self.on_event("agent_start", {
                "agent": agent.name,
                "turn": self._current_turn,
            })

    async def on_agent_end(
        self,
        context: "RunContextWrapper[Any]",
        agent: Agent[Any],
        output: Any,
    ) -> None:
        """Called when an agent finishes processing."""
        output_preview = str(output)[:200] if output else "(no output)"
        logger.info(
            "agent_end",
            agent=agent.name,
            turn=self._current_turn,
            output_preview=output_preview,
        )
        if self.on_event:
            await self.on_event("agent_end", {
                "agent": agent.name,
                "turn": self._current_turn,
                "output_preview": output_preview,
            })

    async def on_handoff(
        self,
        context: "RunContextWrapper[Any]",
        from_agent: Agent[Any],
        to_agent: Agent[Any],
    ) -> None:
        """Called when an agent hands off to another agent."""
        logger.info(
            "agent_handoff",
            from_agent=from_agent.name,
            to_agent=to_agent.name,
            turn=self._current_turn,
        )
        if self.on_event:
            await self.on_event("agent_handoff", {
                "from_agent": from_agent.name,
                "to_agent": to_agent.name,
                "turn": self._current_turn,
            })

    async def on_tool_start(
        self,
        context: "RunContextWrapper[Any]",
        agent: Agent[Any],
        tool: Any,
    ) -> None:
        """Called when a tool is about to be executed."""
        tool_name = getattr(tool, "name", str(tool))
        logger.info(
            "tool_start",
            agent=agent.name,
            tool=tool_name,
            turn=self._current_turn,
        )
        if self.on_event:
            await self.on_event("tool_start", {
                "agent": agent.name,
                "tool": tool_name,
                "turn": self._current_turn,
            })

    async def on_tool_end(
        self,
        context: "RunContextWrapper[Any]",
        agent: Agent[Any],
        tool: Any,
        result: str,
    ) -> None:
        """Called when a tool finishes execution."""
        tool_name = getattr(tool, "name", str(tool))
        result_preview = str(result)[:200] if result else "(no result)"
        logger.info(
            "tool_end",
            agent=agent.name,
            tool=tool_name,
            result_preview=result_preview,
            turn=self._current_turn,
        )
        if self.on_event:
            await self.on_event("tool_end", {
                "agent": agent.name,
                "tool": tool_name,
                "result_preview": result_preview,
                "turn": self._current_turn,
            })


def create_logging_hooks(
    on_event: EventCallback | None = None,
) -> LoggingRunHooks:
    """Create logging hooks with optional event callback.

    Args:
        on_event: Optional callback for UI event emission.

    Returns:
        LoggingRunHooks instance.
    """
    return LoggingRunHooks(on_event=on_event)
