"""System message generation for PR context injection.

Provides functions to generate and inject PR context into
conversation history as a system message.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .pr_context import PRContext


def generate_pr_context_message(context: "PRContext") -> str:
    """Generate a system message with PR context.

    This message is injected at the start of every conversation
    to ensure the agent always knows the current PR context.

    The message provides:
    - PR identification (owner, repo, number)
    - PR metadata (title, author, state, branches)
    - PR statistics (additions, deletions, files changed)
    - Instructions for using GitHub tools

    For full details including description and enrichments,
    agents should call the get_pr_context tool.

    Args:
        context: PRContext with PR metadata.

    Returns:
        Formatted system message string.
    """
    # Build stats line
    stats = f"+{context.additions} -{context.deletions} across {context.changed_files} files"

    # Build branch info if available
    branch_info = ""
    if context.head_branch and context.base_branch:
        branch_info = f"\n- Branch: {context.head_branch} → {context.base_branch}"

    # Build state info
    state_info = context.state or "unknown"
    if context.draft:
        state_info = f"{state_info} (draft)"

    return (
        f"## Current PR Context\n"
        f"You are working on PR #{context.number} in {context.owner}/{context.repo}.\n\n"
        f"**Title:** {context.title or 'Unknown'}\n"
        f"**Author:** {context.author or 'Unknown'}\n"
        f"**State:** {state_info}\n"
        f"**Changes:** {stats}"
        f"{branch_info}\n"
        f"**URL:** {context.github_url}\n\n"
        f"For full PR details including description and enrichments, "
        f"call the `get_pr_context` tool.\n\n"
        f"IMPORTANT: When calling GitHub tools, use these values:\n"
        f"- owner: \"{context.owner}\"\n"
        f"- repo: \"{context.repo}\"\n"
        f"- pr_number: {context.number}"
    )


def inject_pr_context_message(
    history: list[dict[str, str]],
    context: "PRContext",
) -> list[dict[str, str]]:
    """Inject or update PR context as a system message in conversation history.

    If the first message in history is already a system message,
    it will be updated. Otherwise, a new system message is prepended.

    Args:
        history: Conversation history (list of {role, content} dicts).
        context: PRContext to inject.

    Returns:
        Updated history with PR context system message.
    """
    system_content = generate_pr_context_message(context)

    # Check if first message is system message
    if history and history[0].get("role") == "system":
        # Update existing system message
        history[0]["content"] = system_content
    else:
        # Prepend new system message
        history.insert(0, {"role": "system", "content": system_content})

    return history
