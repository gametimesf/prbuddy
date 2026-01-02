"""Tool registration for the agent system.

This module bootstraps all available tools into the ToolRegistry so they
can be referenced by name in YAML configuration files.

Call init_registries() at application startup before loading agent configs.
"""

from __future__ import annotations

import os

from agents.mcp import MCPServerStreamableHttp, MCPServerStreamableHttpParams

from .registry import ToolRegistry, MCPServerRegistry


def create_unblocked_mcp() -> MCPServerStreamableHttp:
    """Factory function to create Unblocked MCP server.

    Uses UNBLOCKED_API_KEY from environment for Bearer token auth.
    The Unblocked MCP provides tools for semantic search across PRs,
    docs, historical context, and integrated services (GitHub, Jira, Slack).

    Note: Uses Streamable HTTP transport (not SSE) as required by Unblocked API.
    """
    api_key = os.environ.get("UNBLOCKED_API_KEY")
    if not api_key:
        raise ValueError("UNBLOCKED_API_KEY not set")

    return MCPServerStreamableHttp(
        params=MCPServerStreamableHttpParams(
            url="https://getunblocked.com/api/mcpsse",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,  # 60 seconds for Unblocked semantic searches
            sse_read_timeout=300.0,  # 5 minutes for SSE reads
        ),
        name="unblocked",
        cache_tools_list=True,  # Tools don't change often
    )


def register_all_tools() -> None:
    """Register all available tools with the ToolRegistry.

    This must be called before loading agent configs that reference tools.
    """
    # Import tool implementations here to avoid circular imports
    from src.tools.rag_tools import register_rag_tools
    from src.tools.github_tools import register_github_tools
    from src.tools.context_tools import register_context_tools

    # Register all tools
    register_rag_tools()
    register_github_tools()
    register_context_tools()


def register_mcp_servers() -> None:
    """Register all available MCP servers with the MCPServerRegistry.

    This must be called before loading agent configs that reference MCP servers.

    Note: MCP servers are created lazily via factory functions since they
    require runtime configuration (auth tokens, etc.).
    """
    # Only register Unblocked MCP if API key is configured
    if os.environ.get("UNBLOCKED_API_KEY"):
        MCPServerRegistry.register("unblocked", create_unblocked_mcp)
    else:
        import structlog
        logger = structlog.get_logger(__name__)
        logger.warning("UNBLOCKED_API_KEY not set, Unblocked MCP server disabled")


def init_registries() -> None:
    """Initialize all registries.
    
    Convenience function to call at application startup.
    """
    register_all_tools()
    register_mcp_servers()

