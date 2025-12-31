"""Pydantic schemas for agent configuration.

These models define the structure of YAML configuration files and provide
validation when loading agent configs.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AgentConfigSchema(BaseModel):
    """Schema for agent configuration in YAML files.
    
    Example YAML:
        name: ReviewerQA
        is_entry_point: true
        instructions: |
          You are the PR author's AI representative...
        handoff_trigger: Answer reviewer questions about the PR
        routes_to:
          - Research
        tools:
          - query_rag
        mcp_servers:
          - github
    """
    
    model_config = ConfigDict(extra="forbid")  # Fail on unknown fields
    
    name: str = Field(..., description="Unique name for this agent")
    
    instructions: str = Field(..., description="System prompt / instructions for this agent")
    
    handoff_trigger: str = Field(
        default="",
        description="Description of when other agents should hand off to this agent"
    )
    
    routes_to: list[str] = Field(
        default_factory=list,
        description="Names of agents this agent can hand off to"
    )
    
    tools: list[str] = Field(
        default_factory=list,
        description="Tool names to attach to this agent (from ToolRegistry)"
    )
    
    mcp_servers: list[str] = Field(
        default_factory=list,
        description="MCP server names to attach to this agent (from MCPServerRegistry)"
    )
    
    is_entry_point: bool = Field(
        default=False,
        description="If True, this is the starting agent for conversations"
    )


class AgentSystemSchema(BaseModel):
    """Schema for validating a complete agent system configuration.
    
    Used to validate that all agent references are valid and exactly
    one entry point is defined.
    """
    
    agents: list[AgentConfigSchema] = Field(
        ...,
        description="List of all agent configurations"
    )
    
    def validate_system(self) -> list[str]:
        """Validate the agent system configuration.
        
        Returns:
            List of validation errors (empty if valid).
        """
        errors: list[str] = []
        
        # Collect all agent names
        agent_names = {agent.name for agent in self.agents}
        
        # Check for duplicate names
        if len(agent_names) != len(self.agents):
            seen = set()
            for agent in self.agents:
                if agent.name in seen:
                    errors.append(f"Duplicate agent name: {agent.name}")
                seen.add(agent.name)
        
        # Check that all routes_to references exist
        for agent in self.agents:
            for target in agent.routes_to:
                if target not in agent_names:
                    errors.append(f"Agent '{agent.name}' routes to unknown agent '{target}'")
        
        # Check exactly one entry point
        entry_points = [a.name for a in self.agents if a.is_entry_point]
        if len(entry_points) == 0:
            errors.append("No entry point defined. Set is_entry_point: true on one agent.")
        elif len(entry_points) > 1:
            errors.append(f"Multiple entry points defined: {entry_points}. Only one allowed.")
        
        return errors
    
    def get_entry_point_name(self) -> str | None:
        """Get the name of the entry point agent."""
        for agent in self.agents:
            if agent.is_entry_point:
                return agent.name
        return None

