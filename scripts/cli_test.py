#!/usr/bin/env python3
"""CLI tool for testing agent conversations without the UI.

Usage:
    python scripts/cli_test.py https://github.com/owner/repo/pull/123
    python scripts/cli_test.py https://github.com/owner/repo/pull/123 author

Commands during conversation:
    quit/exit - End the session
    /status   - Show session info
    /history  - Show conversation history (last 5)
"""
import argparse
import json
import sys
from typing import Optional

import requests

BASE_URL = "http://localhost:8000"


def create_session(pr_url: str, session_type: str = "reviewer", mode: str = "text") -> dict:
    """Create a new session."""
    resp = requests.post(
        f"{BASE_URL}/api/sessions",
        json={
            "pr_url": pr_url,
            "mode": mode,
            "session_type": session_type,
        },
    )
    resp.raise_for_status()
    return resp.json()


def send_message(session_id: str, text: str) -> str:
    """Send a message and get response."""
    resp = requests.post(
        f"{BASE_URL}/api/sessions/{session_id}/message",
        json={"text": text},
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


def get_pr_status(owner: str, repo: str, pr_number: int) -> dict:
    """Get PR status and knowledge base info."""
    resp = requests.get(f"{BASE_URL}/api/pr/{owner}/{repo}/{pr_number}/status")
    resp.raise_for_status()
    return resp.json()


def parse_pr_url(pr_url: str) -> tuple[str, str, int]:
    """Parse PR URL into (owner, repo, pr_number)."""
    # Handle formats like:
    # https://github.com/owner/repo/pull/123
    # owner/repo#123
    if "github.com" in pr_url:
        parts = pr_url.rstrip("/").split("/")
        owner = parts[-4]
        repo = parts[-3]
        pr_number = int(parts[-1])
    elif "#" in pr_url:
        repo_part, pr_number = pr_url.split("#")
        parts = repo_part.split("/")
        owner = parts[-2] if len(parts) >= 2 else parts[0]
        repo = parts[-1]
        pr_number = int(pr_number)
    else:
        raise ValueError(f"Cannot parse PR URL: {pr_url}")
    return owner, repo, pr_number


def print_status(session_id: str, pr_url: str):
    """Print session and PR status."""
    try:
        owner, repo, pr_number = parse_pr_url(pr_url)
        status = get_pr_status(owner, repo, pr_number)
        print(f"\n--- Session Status ---")
        print(f"Session ID: {session_id}")
        print(f"PR: {status.get('title', 'Unknown')}")
        print(f"Documents indexed: {status.get('document_count', 0)}")
        doc_types = status.get("document_types", {})
        if doc_types:
            print(f"  - Explanations: {doc_types.get('author_explanation', 0)}")
            print(f"  - Diffs: {doc_types.get('diff', 0)}")
            print(f"  - Comments: {doc_types.get('comment', 0)}")
        print("----------------------\n")
    except Exception as e:
        print(f"Error getting status: {e}\n")


def main():
    parser = argparse.ArgumentParser(description="CLI tool for testing PR Buddy agent conversations")
    parser.add_argument("pr_url", help="GitHub PR URL (e.g., https://github.com/owner/repo/pull/123)")
    parser.add_argument("session_type", nargs="?", default="reviewer", choices=["reviewer", "author"],
                        help="Session type (default: reviewer)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    args = parser.parse_args()

    # Create session
    print(f"\nCreating {args.session_type} session for: {args.pr_url}")
    try:
        session = create_session(args.pr_url, args.session_type)
        session_id = session["session_id"]
        print(f"Session created: {session_id}")
        print(f"WebSocket URL: {session.get('websocket_url', 'N/A')}")
    except requests.exceptions.RequestException as e:
        print(f"Error creating session: {e}")
        sys.exit(1)

    print("\nType your messages. Commands: quit, /status, /history")
    print("-" * 50)

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        # Handle commands
        if user_input.lower() in ["quit", "exit"]:
            print("Goodbye!")
            break
        elif user_input == "/status":
            print_status(session_id, args.pr_url)
            continue
        elif user_input == "/history":
            print("\n(History not yet implemented via REST API)")
            continue

        # Send message
        try:
            print("\n[Thinking...]", end="", flush=True)
            response = send_message(session_id, user_input)
            print("\r" + " " * 20 + "\r", end="")  # Clear "Thinking..."
            print(f"\nAgent: {response}")
        except requests.exceptions.RequestException as e:
            print(f"\nError: {e}")


if __name__ == "__main__":
    main()
