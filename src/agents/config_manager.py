"""Agent configuration management.

Provides an abstract interface for loading, saving, and managing agent
configurations. The FileSystemConfigManager implementation reads YAML
files from a directory.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString, FoldedScalarString

from .schema import AgentConfigSchema, AgentSystemSchema

if TYPE_CHECKING:
    pass


class AgentConfigManager(ABC):
    """Abstract base class for agent configuration management.
    
    Provides CRUD operations for agent configs, enabling runtime
    management through an admin interface.
    """
    
    @abstractmethod
    async def list_configs(self) -> list[str]:
        """List all agent config names.
        
        Returns:
            List of agent names (without file extensions).
        """
        ...
    
    @abstractmethod
    async def get_config(self, name: str) -> AgentConfigSchema:
        """Load a single agent config by name.
        
        Args:
            name: The agent name.
        
        Returns:
            The agent configuration.
        
        Raises:
            KeyError: If agent config not found.
        """
        ...
    
    @abstractmethod
    async def get_all_configs(self) -> list[AgentConfigSchema]:
        """Load all agent configs.
        
        Returns:
            List of all agent configurations.
        """
        ...
    
    @abstractmethod
    async def save_config(self, config: AgentConfigSchema) -> None:
        """Create or update an agent config.
        
        Args:
            config: The agent configuration to save.
        """
        ...
    
    @abstractmethod
    async def delete_config(self, name: str) -> bool:
        """Delete an agent config.
        
        Args:
            name: The agent name to delete.
        
        Returns:
            True if deleted, False if not found.
        """
        ...
    
    async def validate_system(self) -> list[str]:
        """Validate the complete agent system.
        
        Returns:
            List of validation errors (empty if valid).
        """
        configs = await self.get_all_configs()
        system = AgentSystemSchema(agents=configs)
        return system.validate_system()
    
    async def get_entry_point_name(self) -> str | None:
        """Get the name of the entry point agent.
        
        Returns:
            Name of the entry point agent, or None if not defined.
        """
        configs = await self.get_all_configs()
        for config in configs:
            if config.is_entry_point:
                return config.name
        return None


class FileSystemConfigManager(AgentConfigManager):
    """File system implementation of AgentConfigManager.
    
    Reads and writes YAML files from a directory. Each agent is stored
    as a separate file named {name}.yaml (lowercase with underscores).
    
    Example:
        manager = FileSystemConfigManager(Path("config/agents"))
        configs = await manager.get_all_configs()
    """
    
    def __init__(self, config_dir: Path | str) -> None:
        """Initialize the file system config manager.
        
        Args:
            config_dir: Directory containing agent YAML files.
        """
        self._dir = Path(config_dir)
    
    def _name_to_filename(self, name: str) -> str:
        """Convert agent name to filename.
        
        Example: "ReviewerQA" -> "reviewer_qa.yaml"
        """
        # Convert CamelCase to snake_case
        result = []
        for i, char in enumerate(name):
            if char.isupper() and i > 0:
                result.append("_")
            result.append(char.lower())
        return "".join(result) + ".yaml"
    
    def _filename_to_path(self, name: str) -> Path:
        """Get full path for an agent config file."""
        return self._dir / self._name_to_filename(name)
    
    async def list_configs(self) -> list[str]:
        """List all agent config names."""
        if not self._dir.exists():
            return []
        
        names = []
        for path in self._dir.glob("*.yaml"):
            try:
                with open(path) as f:
                    data = yaml.safe_load(f)
                    if data and "name" in data:
                        names.append(data["name"])
            except Exception:
                continue
        return names
    
    async def get_config(self, name: str) -> AgentConfigSchema:
        """Load a single agent config by name."""
        # Try direct filename first
        path = self._filename_to_path(name)
        
        if not path.exists():
            # Search all files for matching name
            for p in self._dir.glob("*.yaml"):
                try:
                    with open(p) as f:
                        data = yaml.safe_load(f)
                        if data and data.get("name") == name:
                            return AgentConfigSchema(**data)
                except Exception:
                    continue
            raise KeyError(f"Agent config '{name}' not found in {self._dir}")
        
        with open(path) as f:
            data = yaml.safe_load(f)
            return AgentConfigSchema(**data)
    
    async def get_all_configs(self) -> list[AgentConfigSchema]:
        """Load all agent configs."""
        if not self._dir.exists():
            return []
        
        configs = []
        for path in sorted(self._dir.glob("*.yaml")):
            try:
                with open(path) as f:
                    data = yaml.safe_load(f)
                    if data:
                        configs.append(AgentConfigSchema(**data))
            except Exception as e:
                # Log but continue loading other configs
                print(f"Warning: Failed to load {path}: {e}")
                continue
        return configs
    
    async def save_config(self, config: AgentConfigSchema) -> None:
        """Create or update an agent config."""
        self._dir.mkdir(parents=True, exist_ok=True)
        
        path = self._filename_to_path(config.name)
        
        # Convert to dict for YAML serialization
        data = config.model_dump(exclude_defaults=False)
        
        # Use ruamel.yaml for proper block scalar formatting
        ryaml = YAML()
        ryaml.default_flow_style = False
        ryaml.preserve_quotes = True
        ryaml.width = 100  # Line width before wrapping
        
        # Convert multiline strings to block scalars
        if "instructions" in data and data["instructions"]:
            data["instructions"] = LiteralScalarString(data["instructions"])
        
        if "handoff_trigger" in data and data["handoff_trigger"]:
            # Use folded scalar for handoff_trigger (single paragraph)
            data["handoff_trigger"] = FoldedScalarString(data["handoff_trigger"])
        
        with open(path, "w") as f:
            ryaml.dump(data, f)
    
    async def delete_config(self, name: str) -> bool:
        """Delete an agent config."""
        path = self._filename_to_path(name)
        
        if not path.exists():
            # Search for matching name
            for p in self._dir.glob("*.yaml"):
                try:
                    with open(p) as f:
                        data = yaml.safe_load(f)
                        if data and data.get("name") == name:
                            p.unlink()
                            return True
                except Exception:
                    continue
            return False
        
        path.unlink()
        return True


class MultiDirConfigManager(AgentConfigManager):
    """Config manager that merges configs from multiple directories.
    
    Useful for loading agents from separate directories (e.g., common + system-specific).
    Read operations merge from all directories; write operations are not supported.
    
    Example:
        manager = MultiDirConfigManager([
            Path("config/agents/common"),
            Path("config/agents/author"),
        ])
        configs = await manager.get_all_configs()
    """
    
    def __init__(self, dirs: list[Path | str]) -> None:
        """Initialize with multiple config directories.
        
        Args:
            dirs: List of directories to load configs from.
        """
        self._dirs = [Path(d) for d in dirs]
        self._managers = [FileSystemConfigManager(d) for d in self._dirs]
    
    async def list_configs(self) -> list[str]:
        """List all agent config names from all directories."""
        names = []
        for manager in self._managers:
            names.extend(await manager.list_configs())
        return list(set(names))  # Remove duplicates
    
    async def get_config(self, name: str) -> AgentConfigSchema:
        """Load a single agent config by name from any directory."""
        for manager in self._managers:
            try:
                return await manager.get_config(name)
            except KeyError:
                continue
        raise KeyError(f"Agent config '{name}' not found in any directory")
    
    async def get_all_configs(self) -> list[AgentConfigSchema]:
        """Load all agent configs from all directories."""
        configs = []
        seen_names = set()
        
        for manager in self._managers:
            for config in await manager.get_all_configs():
                if config.name not in seen_names:
                    configs.append(config)
                    seen_names.add(config.name)
        
        return configs
    
    async def save_config(self, config: AgentConfigSchema) -> None:
        """Save not supported for multi-directory manager."""
        raise NotImplementedError(
            "MultiDirConfigManager does not support save operations. "
            "Use FileSystemConfigManager for a specific directory instead."
        )
    
    async def delete_config(self, name: str) -> bool:
        """Delete not supported for multi-directory manager."""
        raise NotImplementedError(
            "MultiDirConfigManager does not support delete operations. "
            "Use FileSystemConfigManager for a specific directory instead."
        )


# Default config manager instance
_default_manager: AgentConfigManager | None = None


def get_config_manager() -> AgentConfigManager:
    """Get the default config manager instance.
    
    Returns:
        The default AgentConfigManager.
    
    Raises:
        RuntimeError: If no manager has been set.
    """
    global _default_manager
    if _default_manager is None:
        raise RuntimeError("Config manager not initialized. Call set_config_manager() first.")
    return _default_manager


def set_config_manager(manager: AgentConfigManager) -> None:
    """Set the default config manager instance.
    
    Args:
        manager: The config manager to use as default.
    """
    global _default_manager
    _default_manager = manager


def init_filesystem_config_manager(config_dir: Path | str = "config/agents") -> FileSystemConfigManager:
    """Initialize the default config manager with FileSystem backend.
    
    Args:
        config_dir: Directory containing agent YAML files.
    
    Returns:
        The initialized FileSystemConfigManager.
    """
    manager = FileSystemConfigManager(config_dir)
    set_config_manager(manager)
    return manager

