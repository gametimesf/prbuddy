"""Agent system for PR Buddy.

Provides YAML-based declarative agent configuration, factory functions,
and tool/MCP server registries.
"""

from .config_manager import (
    AgentConfigManager,
    FileSystemConfigManager,
    get_config_manager,
    set_config_manager,
    init_filesystem_config_manager,
)
from .factory import (
    AgentSystem,
    create_agent_system,
)
from .registry import ToolRegistry, MCPServerRegistry
from .schema import AgentConfigSchema, AgentSystemSchema
from .types import AgentContext

__all__ = [
    # Config management
    "AgentConfigManager",
    "FileSystemConfigManager",
    "get_config_manager",
    "set_config_manager",
    "init_filesystem_config_manager",
    # Factory
    "AgentSystem",
    "create_agent_system",
    # Registry
    "ToolRegistry",
    "MCPServerRegistry",
    # Schema
    "AgentConfigSchema",
    "AgentSystemSchema",
    # Types
    "AgentContext",
]
