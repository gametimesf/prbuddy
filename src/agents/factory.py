"""Agent factory for creating the complete agent system.

This module provides a generic config-to-agent transformer that:
1. Loads declarative configs from YAML files via AgentConfigManager
2. Creates Agent instances with optional structured output
3. Wires up handoffs based on routes_to declarations

Voice mode uses pipeline (Agent + TTS), not OpenAI Realtime API.
"""

from __future__ import annotations

import structlog
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

logger = structlog.get_logger()

from agents import Agent, function_tool, handoff, ModelSettings
from agents.model_settings import Reasoning

from .config_manager import (
    AgentConfigManager,
    FileSystemConfigManager,
    MultiDirConfigManager,
    get_config_manager,
    set_config_manager,
)
from .registry import ToolRegistry, MCPServerRegistry
from .schema import AgentConfigSchema
from .tools import init_registries
from .types import AgentContext

if TYPE_CHECKING:
    from agents.mcp import MCPServer


@dataclass
class AgentSystem:
    """Container for agents.

    Dynamic implementation that supports any number of agents loaded from config.
    """

    agents: dict[str, Agent[AgentContext]] = field(default_factory=dict)
    entry_point_name: str = ""

    @property
    def entry_point(self) -> Agent[AgentContext]:
        """The starting agent for conversations."""
        if not self.entry_point_name or self.entry_point_name not in self.agents:
            raise ValueError(f"Entry point '{self.entry_point_name}' not found in agents")
        return self.agents[self.entry_point_name]

    def get_agent(self, name: str) -> Agent[AgentContext] | None:
        """Get an agent by name."""
        return self.agents.get(name)

    def list_agents(self) -> list[str]:
        """List all agent names."""
        return list(self.agents.keys())


async def _resolve_mcp_servers(
    server_names: list[str],
    runtime_mcp_servers: dict[str, MCPServer] | None = None,
) -> list[MCPServer]:
    """Resolve MCP server names to actual server instances.

    Args:
        server_names: List of MCP server names from config.
        runtime_mcp_servers: Optional dict of runtime-provided MCP servers.

    Returns:
        List of MCPServer instances (connected and ready to use).
    """
    servers: list[MCPServer] = []
    runtime_mcp_servers = runtime_mcp_servers or {}

    for name in server_names:
        if name in runtime_mcp_servers:
            # Use runtime-provided server (assumed to be connected)
            servers.append(runtime_mcp_servers[name])
        elif MCPServerRegistry.is_registered(name):
            server = MCPServerRegistry.get(name)
            # Connect the server before use (required by agents SDK)
            try:
                await server.connect()
                servers.append(server)
            except Exception as e:
                print(f"Warning: Failed to connect MCP server '{name}': {e}")
        else:
            # Skip unregistered servers with warning
            print(f"Warning: MCP server '{name}' not registered, skipping")

    return servers


async def _build_agents(
    configs: list[AgentConfigSchema],
    runtime_mcp_servers: dict[str, MCPServer] | None = None,
    tool_overrides: dict[str, Callable[..., Any]] | None = None,
) -> dict[str, Agent[AgentContext]]:
    """Create agent instances from configs (without handoffs).

    Args:
        configs: List of agent configurations.
        runtime_mcp_servers: Optional dict of runtime MCP servers.
        tool_overrides: Optional dict mapping tool names to mock implementations.
                        Used for testing to inject mock tools instead of real ones.

    Returns:
        Dict mapping agent name to agent instance.
    """
    agents: dict[str, Agent[AgentContext]] = {}

    for cfg in configs:
        # Resolve tools - check overrides first, then registry
        tools = []
        for tool_name in cfg.tools:
            if tool_overrides and tool_name in tool_overrides:
                # Use the override (mock) function
                tools.append(function_tool(
                    tool_overrides[tool_name],
                    name_override=tool_name,
                ))
            else:
                # Fall back to registry (real implementation)
                tools.append(ToolRegistry.get(tool_name))

        # Resolve MCP servers (async to allow connection)
        mcp_servers = await _resolve_mcp_servers(cfg.mcp_servers, runtime_mcp_servers)

        # Build model settings for the agent
        model_settings = None
        if cfg.model_settings:
            # Build reasoning object if needed
            reasoning = None
            if cfg.model_settings.reasoning_effort is not None:
                reasoning = Reasoning(effort=cfg.model_settings.reasoning_effort)

            # Get tool_choice if specified (forces tool calling)
            tool_choice = getattr(cfg.model_settings, 'tool_choice', None)

            # Only create ModelSettings if at least one value is set
            if (cfg.model_settings.temperature is not None or
                cfg.model_settings.top_p is not None or
                cfg.model_settings.max_tokens is not None or
                reasoning is not None or
                tool_choice is not None):
                model_settings = ModelSettings(
                    temperature=cfg.model_settings.temperature,
                    top_p=cfg.model_settings.top_p,
                    max_tokens=cfg.model_settings.max_tokens,
                    reasoning=reasoning,
                    tool_choice=tool_choice,
                )

        # Resolve output_type if specified
        output_type = None
        if cfg.output_type:
            from .output_types import get_output_type
            output_type = get_output_type(cfg.output_type)
            if output_type is None:
                print(f"Warning: Unknown output_type '{cfg.output_type}' for agent '{cfg.name}'")

        # Create agent with model and settings
        agent_kwargs: dict[str, Any] = dict(
            name=cfg.name,
            instructions=cfg.instructions,
            tools=tools,
            handoffs=[],  # Will be wired up after all agents created
            handoff_description=cfg.handoff_trigger,
            mcp_servers=mcp_servers,
            model=cfg.model,
        )

        # Only add optional kwargs if they have values
        if model_settings is not None:
            agent_kwargs["model_settings"] = model_settings
        if output_type is not None:
            agent_kwargs["output_type"] = output_type

        agent = Agent(**agent_kwargs)
        agents[cfg.name] = agent

        # Log agent creation with tools and MCP servers
        tool_names = [getattr(t, '__name__', str(t)) for t in tools]
        mcp_names = [getattr(s, 'name', str(s)) for s in mcp_servers]
        logger.info(
            "agent_created",
            agent=cfg.name,
            tool_count=len(tools),
            tools=tool_names,
            mcp_server_count=len(mcp_servers),
            mcp_servers=mcp_names,
        )

    return agents


def _wire_handoffs(
    agents: dict[str, Agent[AgentContext]],
    configs: list[AgentConfigSchema],
) -> None:
    """Wire up handoffs between agents.

    Args:
        agents: Dict mapping agent name to Agent instance.
        configs: List of agent configurations.
    """
    for cfg in configs:
        agent = agents[cfg.name]
        handoffs_list = []

        for target_name in cfg.routes_to:
            target_agent = agents.get(target_name)
            if target_agent:
                # Use the target's handoff_trigger as the description
                handoffs_list.append(handoff(
                    target_agent,
                    tool_description_override=target_agent.handoff_description,
                ))

        agent.handoffs = handoffs_list
        if handoffs_list:
            logger.info(
                "handoffs_wired",
                agent=cfg.name,
                handoff_count=len(handoffs_list),
                targets=[h.agent_name for h in handoffs_list],
            )


async def create_agent_system(
    runtime_mcp_servers: dict[str, MCPServer] | None = None,
    config_manager: AgentConfigManager | None = None,
    tool_overrides: dict[str, Callable[..., Any]] | None = None,
    entry_point_override: str | None = None,
) -> AgentSystem:
    """Create the complete agent system.

    Uses declarative configs from YAML files to build the system.

    Args:
        runtime_mcp_servers: Optional dict of runtime MCP servers.
        config_manager: Optional config manager. Uses default if not provided.
        tool_overrides: Optional dict mapping tool names to mock implementations.
                        Used for testing to inject mock tools instead of real ones.
        entry_point_override: Optional override for the entry point agent name.

    Returns:
        AgentSystem with all agents properly configured.
    """
    # Ensure registries are initialized
    init_registries()

    # Get config manager
    if config_manager is None:
        try:
            config_manager = get_config_manager()
        except RuntimeError:
            # Initialize default filesystem manager
            config_manager = FileSystemConfigManager(Path("config/agents"))
            set_config_manager(config_manager)

    # Load all configs
    configs = await config_manager.get_all_configs()

    if not configs:
        raise ValueError("No agent configs found")

    # Validate system
    errors = await config_manager.validate_system()
    if errors:
        raise ValueError(f"Agent system validation failed: {errors}")

    # Get entry point
    entry_point_name = entry_point_override or await config_manager.get_entry_point_name()
    if not entry_point_name:
        raise ValueError("No entry point agent defined")

    # Create all agents (async to connect MCP servers)
    agents = await _build_agents(configs, runtime_mcp_servers, tool_overrides)

    # Wire handoffs
    _wire_handoffs(agents, configs)

    return AgentSystem(
        agents=agents,
        entry_point_name=entry_point_name,
    )


# Synchronous wrapper for backwards compatibility
def create_agent_system_sync(
    runtime_mcp_servers: dict[str, MCPServer] | None = None,
) -> AgentSystem:
    """Synchronous wrapper for create_agent_system.

    Note: This blocks the event loop. Use create_agent_system directly when possible.
    """
    import asyncio
    return asyncio.get_event_loop().run_until_complete(
        create_agent_system(runtime_mcp_servers)
    )


# ============================================================================
# PR Buddy System-Specific Factory Functions
# ============================================================================

def _get_config_base_path() -> Path:
    """Get the base path for config directories.

    Returns path relative to project root, handling both runtime and test scenarios.
    """
    # Try to find config relative to this file's location
    # factory.py is at: prbuddy/src/agents/factory.py
    # config is at: prbuddy/config/agents/
    module_path = Path(__file__).parent.parent.parent / "config" / "agents"
    if module_path.exists():
        return module_path

    # Fallback to relative path (for tests with temp directories)
    return Path("config/agents")


async def create_author_system(
    runtime_mcp_servers: dict[str, MCPServer] | None = None,
    tool_overrides: dict[str, Callable[..., Any]] | None = None,
    config_base: Path | None = None,
) -> AgentSystem:
    """Create the author training agent system.

    Loads agents from common/ and author/ directories.
    Entry point is AuthorTraining.

    Args:
        runtime_mcp_servers: Optional dict of runtime MCP servers.
        tool_overrides: Optional dict mapping tool names to mock implementations.
        config_base: Optional base path for config directories (for testing).

    Returns:
        AgentSystem configured for author training sessions.
    """
    base = config_base or _get_config_base_path()

    config_manager = MultiDirConfigManager([
        base / "common",
        base / "author",
    ])

    return await create_agent_system(
        runtime_mcp_servers=runtime_mcp_servers,
        config_manager=config_manager,
        tool_overrides=tool_overrides,
        entry_point_override="AuthorTraining",
    )


async def create_reviewer_system(
    runtime_mcp_servers: dict[str, MCPServer] | None = None,
    tool_overrides: dict[str, Callable[..., Any]] | None = None,
    config_base: Path | None = None,
) -> AgentSystem:
    """Create the reviewer Q&A agent system.

    Loads agents from common/ and reviewer/ directories.
    Entry point is ReviewerQA.

    Args:
        runtime_mcp_servers: Optional dict of runtime MCP servers.
        tool_overrides: Optional dict mapping tool names to mock implementations.
        config_base: Optional base path for config directories (for testing).

    Returns:
        AgentSystem configured for reviewer Q&A sessions.
    """
    base = config_base or _get_config_base_path()

    config_manager = MultiDirConfigManager([
        base / "common",
        base / "reviewer",
    ])

    return await create_agent_system(
        runtime_mcp_servers=runtime_mcp_servers,
        config_manager=config_manager,
        tool_overrides=tool_overrides,
        entry_point_override="ReviewerQA",
    )
