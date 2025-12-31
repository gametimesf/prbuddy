"""Tests for agent configuration management."""

from pathlib import Path

import pytest

from src.agents.config_manager import FileSystemConfigManager, MultiDirConfigManager, set_config_manager
from src.agents.schema import AgentConfigSchema


class TestFileSystemConfigManager:
    """Tests for FileSystemConfigManager."""
    
    @pytest.fixture
    def simple_config_dir(self, tmp_path: Path) -> Path:
        """Create a simple config directory for testing FileSystemConfigManager."""
        config_dir = tmp_path / "simple_agents"
        config_dir.mkdir()
        
        (config_dir / "test_agent.yaml").write_text("""
name: TestAgent
instructions: |
  You are a test agent.
handoff_trigger: Test agent
routes_to: []
tools: []
mcp_servers: []
is_entry_point: true
""")
        return config_dir
    
    @pytest.fixture
    def simple_config_manager(self, simple_config_dir: Path) -> FileSystemConfigManager:
        """Create a simple config manager for testing."""
        manager = FileSystemConfigManager(simple_config_dir)
        set_config_manager(manager)
        return manager
    
    @pytest.mark.asyncio
    async def test_list_configs(self, simple_config_manager):
        """Test listing agent configs."""
        names = await simple_config_manager.list_configs()
        
        assert "TestAgent" in names
    
    @pytest.mark.asyncio
    async def test_get_config(self, simple_config_manager):
        """Test getting a specific config."""
        config = await simple_config_manager.get_config("TestAgent")
        
        assert config.name == "TestAgent"
        assert config.is_entry_point is True
    
    @pytest.mark.asyncio
    async def test_get_config_not_found(self, simple_config_manager):
        """Test getting non-existent config raises KeyError."""
        with pytest.raises(KeyError):
            await simple_config_manager.get_config("NonExistent")
    
    @pytest.mark.asyncio
    async def test_save_config(self, simple_config_manager, simple_config_dir):
        """Test saving a new config."""
        new_config = AgentConfigSchema(
            name="NewAgent",
            instructions="New agent instructions",
            is_entry_point=False,
        )
        
        await simple_config_manager.save_config(new_config)
        
        # Verify it was saved
        loaded = await simple_config_manager.get_config("NewAgent")
        assert loaded.name == "NewAgent"
    
    @pytest.mark.asyncio
    async def test_delete_config(self, simple_config_manager, simple_config_dir):
        """Test deleting a config."""
        # First create a config to delete
        config = AgentConfigSchema(
            name="ToDelete",
            instructions="Will be deleted",
        )
        await simple_config_manager.save_config(config)
        
        # Delete it
        deleted = await simple_config_manager.delete_config("ToDelete")
        assert deleted is True
        
        # Verify it's gone
        with pytest.raises(KeyError):
            await simple_config_manager.get_config("ToDelete")
    
    @pytest.mark.asyncio
    async def test_delete_config_not_found(self, simple_config_manager):
        """Test deleting non-existent config returns False."""
        deleted = await simple_config_manager.delete_config("NonExistent")
        assert deleted is False
    
    @pytest.mark.asyncio
    async def test_validate_system(self, simple_config_manager):
        """Test system validation."""
        errors = await simple_config_manager.validate_system()
        
        # With TestAgent as entry point, system should be valid
        assert len(errors) == 0
    
    @pytest.mark.asyncio
    async def test_get_entry_point_name(self, simple_config_manager):
        """Test getting entry point name."""
        entry_point = await simple_config_manager.get_entry_point_name()
        
        assert entry_point == "TestAgent"


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


class TestMultiDirConfigManager:
    """Tests for MultiDirConfigManager."""
    
    @pytest.fixture
    def multi_config_dirs(self, tmp_path: Path) -> tuple[Path, Path]:
        """Create multiple config directories."""
        common_dir = tmp_path / "common"
        author_dir = tmp_path / "author"
        
        common_dir.mkdir()
        author_dir.mkdir()
        
        # Create a common agent
        (common_dir / "research.yaml").write_text("""
name: Research
instructions: |
  You gather context.
handoff_trigger: Research agent
routes_to: []
tools: []
mcp_servers: []
is_entry_point: false
""")
        
        # Create an author-specific agent
        (author_dir / "author_training.yaml").write_text("""
name: AuthorTraining
instructions: |
  You train the author.
handoff_trigger: Author training
routes_to:
  - Research
tools: []
mcp_servers: []
is_entry_point: true
""")
        
        return common_dir, author_dir
    
    @pytest.fixture
    def multi_manager(self, multi_config_dirs) -> MultiDirConfigManager:
        """Create a multi-directory config manager."""
        common_dir, author_dir = multi_config_dirs
        return MultiDirConfigManager([common_dir, author_dir])
    
    @pytest.mark.asyncio
    async def test_list_configs_from_all_dirs(self, multi_manager):
        """Test that configs from all directories are listed."""
        names = await multi_manager.list_configs()
        
        assert "Research" in names
        assert "AuthorTraining" in names
    
    @pytest.mark.asyncio
    async def test_get_config_from_any_dir(self, multi_manager):
        """Test getting a config from any directory."""
        research = await multi_manager.get_config("Research")
        author = await multi_manager.get_config("AuthorTraining")
        
        assert research.name == "Research"
        assert author.name == "AuthorTraining"
    
    @pytest.mark.asyncio
    async def test_get_all_configs(self, multi_manager):
        """Test getting all configs from all directories."""
        configs = await multi_manager.get_all_configs()
        
        names = [c.name for c in configs]
        assert "Research" in names
        assert "AuthorTraining" in names
    
    @pytest.mark.asyncio
    async def test_save_not_supported(self, multi_manager):
        """Test that save is not supported."""
        config = AgentConfigSchema(name="Test", instructions="Test")
        
        with pytest.raises(NotImplementedError):
            await multi_manager.save_config(config)
    
    @pytest.mark.asyncio
    async def test_delete_not_supported(self, multi_manager):
        """Test that delete is not supported."""
        with pytest.raises(NotImplementedError):
            await multi_manager.delete_config("Test")

