"""Registry for tools and MCP servers.

Provides string-based registration for tools and MCP servers so they can be
referenced by name in YAML configuration files.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Any

from agents import function_tool

if TYPE_CHECKING:
    from agents.tool import FunctionTool
    from agents.mcp import MCPServer


class ToolRegistry:
    """Registry mapping string names to tool functions.
    
    Tools are registered by name and can be retrieved individually or in bulk.
    This enables YAML configs to reference tools by string name.
    
    Example:
        >>> ToolRegistry.register("query_rag", query_rag_impl)
        >>> tools = ToolRegistry.get_many(["query_rag"])
    """
    
    _tools: dict[str, FunctionTool] = {}
    _impls: dict[str, Callable[..., Any]] = {}
    
    @classmethod
    def register(cls, name: str, func: Callable[..., Any]) -> None:
        """Register a tool function by name.
        
        Args:
            name: Unique string identifier for the tool.
            func: The implementation function to wrap as a tool.
        """
        cls._impls[name] = func
        cls._tools[name] = function_tool(func, name_override=name)
    
    @classmethod
    def get(cls, name: str) -> FunctionTool:
        """Get a single tool by name.
        
        Args:
            name: The tool name.
        
        Returns:
            The registered FunctionTool.
        
        Raises:
            KeyError: If tool is not registered.
        """
        if name not in cls._tools:
            raise KeyError(f"Tool '{name}' not registered. Available: {list(cls._tools.keys())}")
        return cls._tools[name]
    
    @classmethod
    def get_many(cls, names: list[str]) -> list[FunctionTool]:
        """Get multiple tools by name.
        
        Args:
            names: List of tool names.
        
        Returns:
            List of FunctionTool instances.
        """
        return [cls.get(name) for name in names]
    
    @classmethod
    def list_tools(cls) -> list[str]:
        """List all registered tool names."""
        return list(cls._tools.keys())
    
    @classmethod
    def list_all(cls) -> list[dict]:
        """List all registered tools with metadata for UI.
        
        Returns:
            List of dicts with name, description, and parameters.
        """
        result = []
        for name, tool in cls._tools.items():
            # Extract metadata from the FunctionTool
            description = ""
            parameters = []
            
            # Get description from docstring or tool
            if hasattr(tool, "description"):
                description = tool.description or ""
            elif name in cls._impls:
                doc = cls._impls[name].__doc__
                if doc:
                    description = doc.strip().split("\n")[0]
            
            # Get parameters from the schema if available
            if hasattr(tool, "params_json_schema"):
                schema = tool.params_json_schema
                if isinstance(schema, dict) and "properties" in schema:
                    for param_name, param_schema in schema["properties"].items():
                        parameters.append({
                            "name": param_name,
                            "type": param_schema.get("type", "string"),
                            "description": param_schema.get("description", ""),
                            "required": param_name in schema.get("required", []),
                        })
            
            result.append({
                "name": name,
                "description": description,
                "parameters": parameters,
            })
        
        return result
    
    @classmethod
    def is_registered(cls, name: str) -> bool:
        """Check if a tool is registered."""
        return name in cls._tools
    
    @classmethod
    def clear(cls) -> None:
        """Clear all registered tools. Mainly for testing."""
        cls._tools.clear()
        cls._impls.clear()


class MCPServerRegistry:
    """Registry mapping string names to MCP server factories.
    
    MCP servers are created on-demand via factory functions since they
    may need runtime configuration (auth tokens, etc.).
    
    Example:
        >>> MCPServerRegistry.register("github", lambda: create_github_mcp())
        >>> server = MCPServerRegistry.get("github")
    """
    
    _factories: dict[str, Callable[[], MCPServer]] = {}
    _instances: dict[str, MCPServer] = {}
    
    @classmethod
    def register(cls, name: str, factory: Callable[[], MCPServer]) -> None:
        """Register an MCP server factory by name.
        
        Args:
            name: Unique string identifier for the server.
            factory: Callable that creates an MCPServer instance.
        """
        cls._factories[name] = factory
    
    @classmethod
    def get(cls, name: str, cached: bool = True) -> MCPServer:
        """Get or create an MCP server by name.
        
        Args:
            name: The server name.
            cached: If True, reuse existing instance. If False, create new.
        
        Returns:
            An MCPServer instance.
        
        Raises:
            KeyError: If server is not registered.
        """
        if name not in cls._factories:
            raise KeyError(f"MCP server '{name}' not registered. Available: {list(cls._factories.keys())}")
        
        if cached and name in cls._instances:
            return cls._instances[name]
        
        instance = cls._factories[name]()
        if cached:
            cls._instances[name] = instance
        return instance
    
    @classmethod
    def get_many(cls, names: list[str], cached: bool = True) -> list[MCPServer]:
        """Get multiple MCP servers by name.
        
        Args:
            names: List of server names.
            cached: If True, reuse existing instances.
        
        Returns:
            List of MCPServer instances.
        """
        return [cls.get(name, cached=cached) for name in names]
    
    @classmethod
    def list_servers(cls) -> list[str]:
        """List all registered server names."""
        return list(cls._factories.keys())
    
    @classmethod
    def is_registered(cls, name: str) -> bool:
        """Check if a server is registered."""
        return name in cls._factories
    
    @classmethod
    def clear(cls) -> None:
        """Clear all registered servers. Mainly for testing."""
        cls._factories.clear()
        cls._instances.clear()


