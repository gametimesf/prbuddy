"""Browser extension tool implementations for PR Buddy agents.

These tools enable agents to interact with the Chrome extension,
such as getting the currently highlighted text from the browser.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable

from ..agents.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Track pending selection requests per session
# Maps request_id -> asyncio.Future
_pending_requests: dict[str, asyncio.Future] = {}

# Callback to send tool requests to the extension
# Set by the session handler when a session is created
_tool_request_callback: Callable[[str, str, dict], None] | None = None

# Pre-stored selection from message payload (avoids WebSocket round-trip)
# Set when a message is received with selection data attached
_stored_selection: dict[str, Any] | None = None


def set_tool_request_callback(callback: Callable[[str, str, dict], None] | None) -> None:
    """Set the callback for sending tool requests to the extension.

    The callback will be called with (request_id, tool_name, params) when
    a tool needs to request data from the browser extension.

    Args:
        callback: Function to call when a tool request needs to be sent.
                  Should send the request over WebSocket to the extension.
    """
    global _tool_request_callback
    _tool_request_callback = callback


def set_stored_selection(selection: dict[str, Any] | None) -> None:
    """Store a selection that was sent with a message.

    This allows the agent to access the selection immediately without
    a WebSocket round-trip to the extension.

    Args:
        selection: Selection data from the message payload, or None to clear.
    """
    global _stored_selection
    _stored_selection = selection
    if selection:
        logger.info(f"set_stored_selection: stored selection with text={selection.get('text', '')[:50]}")


def get_stored_selection() -> dict[str, Any] | None:
    """Get and clear the stored selection.

    Returns:
        The stored selection, or None if none stored.
    """
    global _stored_selection
    selection = _stored_selection
    _stored_selection = None  # Clear after retrieval (one-time use)
    return selection


async def get_browser_selection_impl() -> dict[str, Any]:
    """Get the currently highlighted/selected text from the browser.

    This tool requests the browser extension to capture whatever text
    the user has currently selected on the GitHub PR page. Useful when
    the user references "this", "this code", "the selected text", or
    similar phrases in their question.

    The extension will return:
    - The selected text
    - Context about where the selection is (file path, line number, etc.)

    Returns:
        Dict with:
        - success: Whether the request succeeded
        - text: The selected text (if any)
        - hasSelection: Whether there was a selection
        - context: Additional context about the selection:
            - type: 'diff', 'comment', 'description', 'code_block', 'title', 'unknown'
            - filePath: File path if selection is in a diff
            - lineNumber: Line number if available
            - changeType: 'addition', 'deletion', or 'context' for diff selections
    """
    global _tool_request_callback

    # First, check if we have a stored selection from the message payload
    stored = get_stored_selection()
    if stored and stored.get("hasSelection"):
        logger.info(f"get_browser_selection using stored selection: {stored.get('text', '')[:50]}")
        return {
            "success": True,
            "hasSelection": True,
            "text": stored.get("text", ""),
            "context": stored.get("context", {}),
        }

    if _tool_request_callback is None:
        return {
            "success": False,
            "error": "Browser extension not connected. This tool only works when using the Chrome extension.",
            "hasSelection": False,
        }

    # Generate unique request ID
    request_id = str(uuid.uuid4())

    # Create future to await response
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    _pending_requests[request_id] = future

    try:
        # Send request to extension via WebSocket
        logger.info(f"get_browser_selection requesting selection, request_id={request_id}")
        _tool_request_callback(request_id, "get_browser_selection", {})

        # Wait for response with timeout (20s to allow for content script injection)
        result = await asyncio.wait_for(future, timeout=20.0)
        logger.info(f"get_browser_selection received result, request_id={request_id}, hasSelection={result.get('hasSelection')}")

        # Check if there was a selection
        if not result.get("hasSelection", False):
            return {
                "success": True,
                "hasSelection": False,
                "text": "",
                "message": "No text is currently selected in the browser. Ask the user to highlight the text they're referring to.",
            }

        return {
            "success": True,
            "hasSelection": True,
            "text": result.get("text", ""),
            "context": result.get("context", {}),
        }

    except asyncio.TimeoutError:
        return {
            "success": False,
            "error": "Timed out waiting for browser selection. The extension may not be responding.",
            "hasSelection": False,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get browser selection: {str(e)}",
            "hasSelection": False,
        }
    finally:
        _pending_requests.pop(request_id, None)


def resolve_browser_selection(request_id: str, result: dict) -> bool:
    """Resolve a pending browser selection request.

    Called by the WebSocket handler when the extension sends a tool_response
    for a get_browser_selection request.

    Args:
        request_id: The request ID that was sent to the extension.
        result: The result from the extension containing selection data.

    Returns:
        True if the request was found and resolved, False otherwise.
    """
    logger.info(f"resolve_browser_selection called, request_id={request_id}, pending_count={len(_pending_requests)}")

    future = _pending_requests.get(request_id)
    if future is None:
        logger.warning(f"resolve_browser_selection: request_id={request_id} not found in pending requests")
        return False

    if future.done():
        logger.warning(f"resolve_browser_selection: request_id={request_id} future already done (timed out?)")
        return False

    logger.info(f"resolve_browser_selection: resolving request_id={request_id} with hasSelection={result.get('hasSelection')}")
    future.set_result(result)
    return True


def register_extension_tools() -> None:
    """Register extension tools with the ToolRegistry."""
    ToolRegistry.register("get_browser_selection", get_browser_selection_impl)
