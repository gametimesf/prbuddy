"""Tests for agent configuration management."""

import pytest

from src.agents.config_manager import FileSystemConfigManager
from src.agents.schema import AgentConfigSchema


class TestFileSystemConfigManager:
    """Tests for FileSystemConfigManager."""
    
    @pytest.mark.asyncio
    async def test_list_configs(self, config_manager):
        """Test listing agent configs."""
        names = await config_manager.list_configs()
        
        assert "AuthorTraining" in names
        assert "ReviewerQA" in names
        assert "Research" in names
    
    @pytest.mark.asyncio
    async def test_get_config(self, config_manager):
        """Test getting a specific config."""
        config = await config_manager.get_config("AuthorTraining")
        
        assert config.name == "AuthorTraining"
        assert config.is_entry_point is True
    
    @pytest.mark.asyncio
    async def test_get_config_not_found(self, config_manager):
        """Test getting non-existent config raises KeyError."""
        with pytest.raises(KeyError):
            await config_manager.get_config("NonExistent")
    
    @pytest.mark.asyncio
    async def test_save_config(self, config_manager, config_dir):
        """Test saving a new config."""
        new_config = AgentConfigSchema(
            name="NewAgent",
            instructions="New agent instructions",
            is_entry_point=False,
        )
        
        await config_manager.save_config(new_config)
        
        # Verify it was saved
        loaded = await config_manager.get_config("NewAgent")
        assert loaded.name == "NewAgent"
    
    @pytest.mark.asyncio
    async def test_delete_config(self, config_manager, config_dir):
        """Test deleting a config."""
        # First create a config to delete
        config = AgentConfigSchema(
            name="ToDelete",
            instructions="Will be deleted",
        )
        await config_manager.save_config(config)
        
        # Delete it
        deleted = await config_manager.delete_config("ToDelete")
        assert deleted is True
        
        # Verify it's gone
        with pytest.raises(KeyError):
            await config_manager.get_config("ToDelete")
    
    @pytest.mark.asyncio
    async def test_delete_config_not_found(self, config_manager):
        """Test deleting non-existent config returns False."""
        deleted = await config_manager.delete_config("NonExistent")
        assert deleted is False
    
    @pytest.mark.asyncio
    async def test_validate_system(self, config_manager):
        """Test system validation."""
        errors = await config_manager.validate_system()
        
        # With AuthorTraining as entry point, system should be valid
        assert len(errors) == 0
    
    @pytest.mark.asyncio
    async def test_get_entry_point_name(self, config_manager):
        """Test getting entry point name."""
        entry_point = await config_manager.get_entry_point_name()
        
        assert entry_point == "AuthorTraining"


class TestAgentConfigSchema:
    """Tests for AgentConfigSchema validation."""
    
    def test_valid_config(self):
        """Test creating a valid config."""
        config = AgentConfigSchema(
            name="TestAgent",
            instructions="Test instructions",
            routes_to=["OtherAgent"],
            tools=["tool1", "tool2"],
            is_entry_point=True,
        )
        
        assert config.name == "TestAgent"
        assert len(config.routes_to) == 1
        assert len(config.tools) == 2
    
    def test_config_defaults(self):
        """Test config default values."""
        config = AgentConfigSchema(
            name="TestAgent",
            instructions="Test",
        )
        
        assert config.handoff_trigger == ""
        assert config.routes_to == []
        assert config.tools == []
        assert config.mcp_servers == []
        assert config.is_entry_point is False
    
    def test_config_extra_fields_forbidden(self):
        """Test that extra fields are rejected."""
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError):
            AgentConfigSchema(
                name="Test",
                instructions="Test",
                unknown_field="value",
            )

