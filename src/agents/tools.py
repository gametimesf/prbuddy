"""Tool registration for the agent system.

This module bootstraps all available tools into the ToolRegistry so they
can be referenced by name in YAML configuration files.

Call init_registries() at application startup before loading agent configs.
"""

from __future__ import annotations

from .registry import ToolRegistry, MCPServerRegistry


def register_all_tools() -> None:
    """Register all available tools with the ToolRegistry.
    
    This must be called before loading agent configs that reference tools.
    """
    # Import tool implementations here to avoid circular imports
    from src.tools.rag_tools import register_rag_tools
    from src.tools.github_tools import register_github_tools
    
    # Register all tools
    register_rag_tools()
    register_github_tools()


def register_mcp_servers() -> None:
    """Register all available MCP servers with the MCPServerRegistry.
    
    This must be called before loading agent configs that reference MCP servers.
    
    Note: MCP servers are created lazily via factory functions since they
    require runtime configuration (auth tokens, etc.).
    """
    # MCP servers are typically passed in at runtime via the factory.
    # Register pre-configured servers here when available.
    pass


def init_registries() -> None:
    """Initialize all registries.
    
    Convenience function to call at application startup.
    """
    register_all_tools()
    register_mcp_servers()

