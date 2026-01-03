"""Pydantic schemas for agent configuration.

These models define the structure of YAML configuration files and provide
validation when loading agent configs.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelSettingsSchema(BaseModel):
    """Settings for model behavior, including reasoning configuration."""
    
    model_config = ConfigDict(extra="allow")  # Allow additional OpenAI model settings
    
    temperature: float | None = Field(default=None, description="Sampling temperature")
    top_p: float | None = Field(default=None, description="Top-p sampling")
    max_tokens: int | None = Field(default=None, description="Maximum tokens in response")
    
    # Reasoning / thinking settings (for o1, o3 models)
    reasoning_effort: str | None = Field(
        default=None,
        description="Reasoning effort: 'low', 'medium', 'high' for extended thinking"
    )


class AgentConfigSchema(BaseModel):
    """Schema for agent configuration in YAML files.
    
    Example YAML:
        name: ReviewerQA
        is_entry_point: true
        model: gpt-4o
        model_settings:
          temperature: 0.7
          reasoning_effort: high
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
    
    model: str = Field(
        default="gpt-4o",
        description="Model to use for this agent (e.g., gpt-4o, o3-mini)"
    )
    
    model_settings: ModelSettingsSchema = Field(
        default_factory=ModelSettingsSchema,
        description="Model behavior settings"
    )
    
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

    output_type: str | None = Field(
        default=None,
        description="Name of structured output type (e.g., 'ReviewerResponse'). If set, agent returns structured Pydantic objects."
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
        # Note: Unknown routes are warnings, not errors (for shared agents across systems)
        for agent in self.agents:
            for target in agent.routes_to:
                if target not in agent_names:
                    # Just log a warning instead of failing validation
                    # This allows shared agents (like Research) to route to
                    # agents that only exist in specific systems
                    import logging
                    logging.warning(f"Agent '{agent.name}' routes to unknown agent '{target}' - route will be ignored")
        
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

