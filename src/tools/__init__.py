"""Tool implementations for PR Buddy agents.

Tools are registered with the ToolRegistry and can be referenced
by name in agent YAML configurations.
"""

from .rag_tools import register_rag_tools
from .github_tools import register_github_tools

def register_all_tools() -> None:
    """Register all available tools with the ToolRegistry."""
    register_rag_tools()
    register_github_tools()

__all__ = [
    "register_all_tools",
    "register_rag_tools",
    "register_github_tools",
]

