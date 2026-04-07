"""GitHub tool implementations for PR Buddy agents.

These tools allow agents to fetch PR context from GitHub.
Uses the GitHub MCP server when available, or direct API calls.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from ..agents.registry import ToolRegistry


# GitHub API base URL
GITHUB_API_BASE = "https://api.github.com"


def _get_github_headers() -> dict[str, str]:
    """Get headers for GitHub API requests."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    return headers


async def fetch_pr_diff_impl(
    owner: str,
    repo: str,
    pr_number: int,
) -> dict[str, Any]:
    """Fetch the diff for a pull request.
    
    Gets the unified diff showing all file changes in the PR.
    
    Args:
        owner: Repository owner (username or organization).
        repo: Repository name.
        pr_number: Pull request number.
    
    Returns:
        Dict with success status and diff content.
    """
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}"
    
    headers = _get_github_headers()
    headers["Accept"] = "application/vnd.github.diff"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, follow_redirects=True)
            response.raise_for_status()
            
            return {
                "success": True,
                "diff": response.text,
                "url": f"https://github.com/{owner}/{repo}/pull/{pr_number}/files",
            }
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "error": f"GitHub API error: {e.response.status_code}",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to fetch diff: {str(e)}",
        }


async def fetch_pr_info_impl(
    owner: str,
    repo: str,
    pr_number: int,
) -> dict[str, Any]:
    """Fetch basic information about a pull request.
    
    Gets the PR title, description, author, status, and other metadata.
    
    Args:
        owner: Repository owner.
        repo: Repository name.
        pr_number: Pull request number.
    
    Returns:
        Dict with PR information.
    """
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=_get_github_headers(), follow_redirects=True)
            response.raise_for_status()
            
            data = response.json()
            
            return {
                "success": True,
                "title": data.get("title"),
                "description": data.get("body") or "",
                "author": data.get("user", {}).get("login"),
                "state": data.get("state"),
                "draft": data.get("draft", False),
                "mergeable": data.get("mergeable"),
                "base_branch": data.get("base", {}).get("ref"),
                "head_branch": data.get("head", {}).get("ref"),
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
                "url": data.get("html_url"),
                "additions": data.get("additions", 0),
                "deletions": data.get("deletions", 0),
                "changed_files": data.get("changed_files", 0),
            }
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "error": f"GitHub API error: {e.response.status_code}",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to fetch PR info: {str(e)}",
        }


async def fetch_pr_comments_impl(
    owner: str,
    repo: str,
    pr_number: int,
) -> dict[str, Any]:
    """Fetch comments on a pull request.
    
    Gets both issue-style comments and review comments.
    
    Args:
        owner: Repository owner.
        repo: Repository name.
        pr_number: Pull request number.
    
    Returns:
        Dict with list of comments.
    """
    # Fetch issue comments
    issue_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{pr_number}/comments"
    
    # Fetch review comments
    review_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}/comments"
    
    try:
        async with httpx.AsyncClient() as client:
            issue_response = await client.get(issue_url, headers=_get_github_headers())
            issue_response.raise_for_status()
            issue_comments = issue_response.json()
            
            review_response = await client.get(review_url, headers=_get_github_headers())
            review_response.raise_for_status()
            review_comments = review_response.json()
            
            comments = []
            
            # Process issue comments
            for c in issue_comments:
                comments.append({
                    "type": "issue_comment",
                    "author": c.get("user", {}).get("login"),
                    "body": c.get("body"),
                    "created_at": c.get("created_at"),
                    "url": c.get("html_url"),
                })
            
            # Process review comments
            for c in review_comments:
                comments.append({
                    "type": "review_comment",
                    "author": c.get("user", {}).get("login"),
                    "body": c.get("body"),
                    "path": c.get("path"),
                    "line": c.get("line"),
                    "created_at": c.get("created_at"),
                    "url": c.get("html_url"),
                })
            
            # Sort by created_at
            comments.sort(key=lambda x: x.get("created_at", ""))
            
            return {
                "success": True,
                "comments": comments,
                "count": len(comments),
            }
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "error": f"GitHub API error: {e.response.status_code}",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to fetch comments: {str(e)}",
        }


async def fetch_pr_files_impl(
    owner: str,
    repo: str,
    pr_number: int,
) -> dict[str, Any]:
    """Fetch the list of files changed in a pull request.
    
    Args:
        owner: Repository owner.
        repo: Repository name.
        pr_number: Pull request number.
    
    Returns:
        Dict with list of changed files.
    """
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}/files"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=_get_github_headers())
            response.raise_for_status()
            
            files = response.json()
            
            return {
                "success": True,
                "files": [
                    {
                        "filename": f.get("filename"),
                        "status": f.get("status"),
                        "additions": f.get("additions", 0),
                        "deletions": f.get("deletions", 0),
                        "changes": f.get("changes", 0),
                        "patch": f.get("patch"),
                    }
                    for f in files
                ],
                "count": len(files),
            }
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "error": f"GitHub API error: {e.response.status_code}",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to fetch files: {str(e)}",
        }


async def fetch_file_content_impl(
    owner: str,
    repo: str,
    path: str,
    ref: str | None = None,
) -> dict[str, Any]:
    """Fetch the content of a file from a repository.
    
    Args:
        owner: Repository owner.
        repo: Repository name.
        path: Path to the file in the repository.
        ref: Optional git ref (branch, tag, or commit SHA).
    
    Returns:
        Dict with file content.
    """
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
    
    params = {}
    if ref:
        params["ref"] = ref
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=_get_github_headers(), params=params)
            response.raise_for_status()
            
            data = response.json()
            
            # Content is base64 encoded
            import base64
            content = base64.b64decode(data.get("content", "")).decode("utf-8")
            
            return {
                "success": True,
                "content": content,
                "path": data.get("path"),
                "sha": data.get("sha"),
                "url": data.get("html_url"),
            }
    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "error": f"GitHub API error: {e.response.status_code}",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to fetch file: {str(e)}",
        }


def register_github_tools() -> None:
    """Register GitHub tools with the ToolRegistry."""
    ToolRegistry.register("fetch_pr_diff", fetch_pr_diff_impl)
    ToolRegistry.register("fetch_pr_info", fetch_pr_info_impl)
    ToolRegistry.register("fetch_pr_comments", fetch_pr_comments_impl)
    ToolRegistry.register("fetch_pr_files", fetch_pr_files_impl)
    ToolRegistry.register("fetch_file_content", fetch_file_content_impl)


