"""FastAPI server for PR Buddy.

Provides REST API and WebSocket endpoints for PR sessions.
"""

from .app import create_app, app

__all__ = ["create_app", "app"]

