"""Tests for PR context parsing and utilities."""

import pytest

from src.sessions.pr_context import PRContext


class TestPRContext:
    """Tests for PRContext class."""
    
    def test_create_context(self):
        """Test creating a PR context directly."""
        ctx = PRContext(owner="openai", repo="gpt-4", number=123)
        
        assert ctx.owner == "openai"
        assert ctx.repo == "gpt-4"
        assert ctx.number == 123
        assert ctx.pr_id == "openai/gpt-4#123"
    
    def test_from_full_url(self):
        """Test parsing from full GitHub URL."""
        url = "https://github.com/facebook/react/pull/42"
        ctx = PRContext.from_url(url)
        
        assert ctx.owner == "facebook"
        assert ctx.repo == "react"
        assert ctx.number == 42
    
    def test_from_url_without_protocol(self):
        """Test parsing URL without https://."""
        url = "github.com/microsoft/vscode/pull/999"
        ctx = PRContext.from_url(url)
        
        assert ctx.owner == "microsoft"
        assert ctx.repo == "vscode"
        assert ctx.number == 999
    
    def test_from_short_reference(self):
        """Test parsing short owner/repo#number format."""
        url = "torvalds/linux#12345"
        ctx = PRContext.from_url(url)
        
        assert ctx.owner == "torvalds"
        assert ctx.repo == "linux"
        assert ctx.number == 12345
    
    def test_invalid_url(self):
        """Test that invalid URLs raise ValueError."""
        with pytest.raises(ValueError):
            PRContext.from_url("not-a-valid-url")
        
        with pytest.raises(ValueError):
            PRContext.from_url("https://gitlab.com/owner/repo/merge_requests/1")
    
    def test_tenant_name(self):
        """Test tenant name generation."""
        ctx = PRContext(owner="my-org", repo="my-repo", number=42)
        
        # Should be sanitized (hyphens become underscores)
        assert ctx.tenant_name == "my_org_my_repo_42"
    
    def test_github_url(self):
        """Test GitHub URL generation."""
        ctx = PRContext(owner="owner", repo="repo", number=1)
        
        assert ctx.github_url == "https://github.com/owner/repo/pull/1"
    
    def test_api_path(self):
        """Test API path generation."""
        ctx = PRContext(owner="owner", repo="repo", number=1)
        
        assert ctx.api_path == "/repos/owner/repo/pulls/1"
    
    def test_to_dict(self):
        """Test serialization to dict."""
        ctx = PRContext(
            owner="owner",
            repo="repo",
            number=1,
            author="user",
            title="My PR",
        )
        
        d = ctx.to_dict()
        
        assert d["owner"] == "owner"
        assert d["repo"] == "repo"
        assert d["number"] == 1
        assert d["author"] == "user"
        assert d["title"] == "My PR"
        assert d["pr_id"] == "owner/repo#1"
        assert d["github_url"] == "https://github.com/owner/repo/pull/1"
    
    def test_from_dict(self):
        """Test deserialization from dict."""
        d = {
            "owner": "owner",
            "repo": "repo",
            "number": 1,
            "author": "user",
        }
        
        ctx = PRContext.from_dict(d)
        
        assert ctx.owner == "owner"
        assert ctx.repo == "repo"
        assert ctx.number == 1
        assert ctx.author == "user"

