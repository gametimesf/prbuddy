"""Tests for session management."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.sessions.manager import PRSessionManager, PRSessionConfig, PRSessionMode
from src.sessions.pr_context import PRContext
from src.sessions.text_session import TextSession, TextEventType


class TestPRSessionManager:
    """Tests for PRSessionManager."""
    
    @pytest.fixture
    def manager(self, mock_weaviate_client):
        """Create a session manager with mock client."""
        with patch("src.sessions.manager.create_schema"):
            return PRSessionManager(mock_weaviate_client)
    
    @pytest.mark.asyncio
    async def test_create_text_session(
        self, manager, pr_context, patch_config_base, register_mock_tools
    ):
        """Test creating a text session."""
        config = PRSessionConfig(
            mode=PRSessionMode.TEXT,
            session_type="author",
        )
        
        session = await manager.create_session(pr_context, config)
        
        assert session.id is not None
        assert session.mode == PRSessionMode.TEXT
        assert session.session_type == "author"
        assert session.pr_context.pr_id == pr_context.pr_id
    
    @pytest.mark.asyncio
    async def test_get_session(
        self, manager, pr_context, patch_config_base, register_mock_tools
    ):
        """Test getting a session by ID."""
        session = await manager.create_session(pr_context)
        
        retrieved = manager.get_session(session.id)
        
        assert retrieved is session
    
    @pytest.mark.asyncio
    async def test_get_session_not_found(self, manager):
        """Test getting non-existent session returns None."""
        result = manager.get_session("nonexistent-id")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_list_sessions(
        self, manager, pr_context, patch_config_base, register_mock_tools
    ):
        """Test listing all sessions."""
        await manager.create_session(pr_context)
        await manager.create_session(pr_context)
        
        sessions = manager.list_sessions()
        
        assert len(sessions) == 2
    
    @pytest.mark.asyncio
    async def test_delete_session(
        self, manager, pr_context, patch_config_base, register_mock_tools
    ):
        """Test deleting a session."""
        session = await manager.create_session(pr_context)
        
        deleted = await manager.delete_session(session.id)
        
        assert deleted is True
        assert manager.get_session(session.id) is None
    
    @pytest.mark.asyncio
    async def test_delete_session_not_found(self, manager):
        """Test deleting non-existent session returns False."""
        deleted = await manager.delete_session("nonexistent")
        
        assert deleted is False
    
    @pytest.mark.asyncio
    async def test_list_sessions_for_pr(
        self, manager, patch_config_base, register_mock_tools
    ):
        """Test listing sessions for a specific PR."""
        pr1 = PRContext(owner="owner", repo="repo1", number=1)
        pr2 = PRContext(owner="owner", repo="repo2", number=2)
        
        await manager.create_session(pr1)
        await manager.create_session(pr1)
        await manager.create_session(pr2)
        
        sessions = manager.list_sessions_for_pr(pr1)
        
        assert len(sessions) == 2


class TestTextSession:
    """Tests for TextSession."""
    
    @pytest.fixture
    def session(self, mock_agent, pr_context):
        """Create a text session."""
        return TextSession(
            session_id="test-session",
            agent=mock_agent,
            pr_context=pr_context,
        )
    
    def test_session_creation(self, session):
        """Test session is created correctly."""
        assert session.session_id == "test-session"
        assert session.pr_context is not None
    
    def test_get_history_empty(self, session):
        """Test getting history with only system context message."""
        history = session.get_history()
        
        # History should only contain the system message with PR context
        assert len(history) == 1
        assert history[0]["role"] == "system"
        assert "PR Context" in history[0]["content"]
    
    def test_clear_history(self, session):
        """Test clearing history."""
        session._history = [{"role": "user", "content": "test"}]
        
        session.clear_history()
        
        assert session.get_history() == []
    
    @pytest.mark.asyncio
    async def test_event_callback(self, mock_agent, pr_context):
        """Test that events are emitted."""
        events = []
        
        async def capture_event(event):
            events.append(event)
        
        session = TextSession(
            session_id="test",
            agent=mock_agent,
            pr_context=pr_context,
            on_event=capture_event,
        )
        
        await session._emit(TextEventType.SESSION_STARTED)
        
        assert len(events) == 1
        assert events[0].type == TextEventType.SESSION_STARTED


class TestTextEventType:
    """Tests for TextEventType enum."""
    
    def test_event_types_exist(self):
        """Test that required event types exist."""
        assert TextEventType.USER_MESSAGE
        assert TextEventType.AGENT_RESPONSE
        assert TextEventType.AGENT_THINKING
        assert TextEventType.ERROR
        assert TextEventType.SESSION_STARTED
        assert TextEventType.SESSION_ENDED

