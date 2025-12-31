"""Admin API for PR Buddy.

Provides endpoints for managing agent configurations and viewing system status.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..agents.config_manager import get_config_manager
from ..agents.registry import ToolRegistry
from ..agents.schema import AgentConfigSchema


router = APIRouter(prefix="/api/admin", tags=["admin"])


class AgentListResponse(BaseModel):
    """Response with list of agents."""
    
    agents: list[str]
    entry_point: str | None


class ToolListResponse(BaseModel):
    """Response with list of tools."""
    
    tools: list[dict[str, Any]]


class GraphNode(BaseModel):
    """Node in the agent graph."""
    
    id: str
    label: str
    is_entry_point: bool


class GraphEdge(BaseModel):
    """Edge in the agent graph."""
    
    source: str
    target: str


class GraphResponse(BaseModel):
    """Agent graph for visualization."""
    
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class ValidationResponse(BaseModel):
    """Validation result."""
    
    valid: bool
    errors: list[str]


class ReloadResponse(BaseModel):
    """Response from reload operation."""
    
    success: bool
    message: str


@router.get("/agents", response_model=AgentListResponse)
async def list_agents():
    """List all configured agents."""
    manager = get_config_manager()
    names = await manager.list_configs()
    entry_point = await manager.get_entry_point_name()
    
    return AgentListResponse(agents=names, entry_point=entry_point)


@router.get("/agents/{name}", response_model=AgentConfigSchema)
async def get_agent(name: str):
    """Get a specific agent configuration."""
    manager = get_config_manager()
    
    try:
        config = await manager.get_config(name)
        return config
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")


@router.post("/agents", response_model=AgentConfigSchema, status_code=status.HTTP_201_CREATED)
async def create_agent(config: AgentConfigSchema):
    """Create a new agent configuration."""
    manager = get_config_manager()
    
    # Check if already exists
    existing = await manager.list_configs()
    if config.name in existing:
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{config.name}' already exists"
        )
    
    await manager.save_config(config)
    return config


@router.put("/agents/{name}", response_model=AgentConfigSchema)
async def update_agent(name: str, config: AgentConfigSchema):
    """Update an existing agent configuration."""
    manager = get_config_manager()
    
    # Verify exists
    try:
        await manager.get_config(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    
    # If name changed, delete old config
    if config.name != name:
        await manager.delete_config(name)
    
    await manager.save_config(config)
    return config


@router.delete("/agents/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(name: str):
    """Delete an agent configuration."""
    manager = get_config_manager()
    
    deleted = await manager.delete_config(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")


@router.get("/tools", response_model=ToolListResponse)
async def list_tools():
    """List all registered tools."""
    tools = ToolRegistry.list_all()
    return ToolListResponse(tools=tools)


@router.get("/graph", response_model=GraphResponse)
async def get_agent_graph():
    """Get the agent graph for visualization."""
    manager = get_config_manager()
    configs = await manager.get_all_configs()
    
    nodes = []
    edges = []
    
    for config in configs:
        nodes.append(GraphNode(
            id=config.name,
            label=config.name,
            is_entry_point=config.is_entry_point,
        ))
        
        for target in config.routes_to:
            edges.append(GraphEdge(
                source=config.name,
                target=target,
            ))
    
    return GraphResponse(nodes=nodes, edges=edges)


@router.get("/validate", response_model=ValidationResponse)
async def validate_system():
    """Validate the agent system configuration."""
    manager = get_config_manager()
    errors = await manager.validate_system()
    
    return ValidationResponse(valid=len(errors) == 0, errors=errors)


@router.post("/reload", response_model=ReloadResponse)
async def reload_agents():
    """Reload agent configurations from disk."""
    # The config manager reads from disk on each call,
    # so this is mainly for cache invalidation in the factory
    
    # TODO: Clear cached agent systems if we add caching
    
    return ReloadResponse(
        success=True,
        message="Agent configurations will be reloaded on next session creation"
    )

