"""RAG tool implementations for PR Buddy agents.

These tools allow agents to query and index documents in the
PR-scoped knowledge base.
"""

from __future__ import annotations

from typing import Any

from ..agents.registry import ToolRegistry
from ..rag.store import get_rag_store


# Doc types that should NOT be included in search results
# These are for persistence/system use, not answering questions
EXCLUDED_DOC_TYPES = {
    "conversation_author",
    "conversation_reviewer",
    "pr_context",
}


async def query_rag_impl(
    question: str,
    top_k: int = 5,
    doc_types: list[str] | None = None,
) -> dict[str, Any]:
    """Search the PR knowledge base for relevant context.

    Uses hybrid search (combining keyword and semantic similarity)
    to find the most relevant documents for a given question.

    IMPORTANT: Use specific, targeted queries. Don't use generic queries like
    "PR purpose" for every question. Tailor the query to what you're looking for:
    - For "why" questions: query for "reason", "decision", "motivation"
    - For "how" questions: query for "implementation", "mechanism", "approach"
    - For specific topics: query for that topic directly

    Args:
        question: The search query - be SPECIFIC to the user's question.
        top_k: Number of results to return (default: 5, increase for broad questions).
        doc_types: Optional filter by document types (e.g., ["diff", "author_explanation"]).

    Returns:
        Dict with success status and list of matching documents.
        Each document includes content, doc_type, source_url, and relevance score.
    """
    try:
        store = get_rag_store()
    except RuntimeError:
        return {
            "success": False,
            "error": "RAG store not initialized. PR context may not be set.",
        }

    try:
        results = await store.query(
            question,
            top_k=top_k,
            doc_types=doc_types,
        )

        # Filter out excluded doc types (conversation history, system context)
        filtered_results = [
            r for r in results
            if r.doc_type not in EXCLUDED_DOC_TYPES
        ]

        return {
            "success": True,
            "results": [
                {
                    "content": r.content,
                    "doc_type": r.doc_type,
                    "source": r.source_url,
                    "file_path": r.file_path,
                    "score": r.score,
                }
                for r in filtered_results
            ],
            "count": len(filtered_results),
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Search failed: {str(e)}",
        }


async def index_to_rag_impl(
    content: str,
    doc_type: str,
    source_url: str | None = None,
    file_path: str | None = None,
) -> dict[str, Any]:
    """Add a document to the PR knowledge base.
    
    Use this to index new context like author explanations,
    code snippets, or external documentation.
    
    Args:
        content: The text content to index.
        doc_type: Type of document. Common types:
            - "author_explanation": Author's explanation of a decision
            - "diff": Code diff or changes
            - "description": PR description
            - "issue": Linked issue content
            - "doc": Documentation
            - "comment": PR comments
        source_url: Optional URL to the source.
        file_path: Optional file path for code-related content.
    
    Returns:
        Dict with success status and document ID.
    """
    try:
        store = get_rag_store()
    except RuntimeError:
        return {
            "success": False,
            "error": "RAG store not initialized. PR context may not be set.",
        }
    
    if not content.strip():
        return {
            "success": False,
            "error": "Content cannot be empty.",
        }
    
    try:
        doc_id = await store.add_document(
            doc_type=doc_type,
            content=content,
            file_path=file_path,
            source_url=source_url,
        )
        
        return {
            "success": True,
            "doc_id": doc_id,
            "message": f"Indexed document of type '{doc_type}'",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Indexing failed: {str(e)}",
        }


async def get_readiness_score_impl() -> dict[str, Any]:
    """Get the readiness score for the current PR knowledge base.
    
    Analyzes the indexed content to determine how well the agent
    can answer reviewer questions.
    
    Returns:
        Dict with readiness score (0-1) and breakdown by category.
    """
    try:
        store = get_rag_store()
    except RuntimeError:
        return {
            "success": False,
            "error": "RAG store not initialized.",
        }
    
    try:
        doc_counts = await store.get_document_types()
        
        # Calculate readiness based on document coverage
        # Weights for different document types
        weights = {
            "diff": 0.2,
            "description": 0.15,
            "author_explanation": 0.35,
            "issue": 0.1,
            "comment": 0.1,
            "doc": 0.1,
        }
        
        score = 0.0
        breakdown = {}
        
        for doc_type, weight in weights.items():
            count = doc_counts.get(doc_type, 0)
            # Diminishing returns - first few documents of each type are most valuable
            type_score = min(1.0, count / 3) * weight
            score += type_score
            breakdown[doc_type] = {
                "count": count,
                "contribution": round(type_score, 3),
            }
        
        # Cap at 1.0
        score = min(1.0, score)
        
        # Determine readiness level
        if score >= 0.8:
            level = "high"
            message = "The knowledge base is comprehensive. Ready for reviewers."
        elif score >= 0.5:
            level = "medium"
            message = "The knowledge base has good coverage but could use more author explanations."
        else:
            level = "low"
            message = "The knowledge base needs more context. Consider adding explanations."
        
        return {
            "success": True,
            "score": round(score, 3),
            "level": level,
            "message": message,
            "breakdown": breakdown,
            "total_documents": sum(doc_counts.values()),
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to calculate readiness: {str(e)}",
        }


async def trigger_research_impl(
    focus: str | None = None,
) -> dict[str, Any]:
    """Trigger the Research agent to gather more context.
    
    Use this when the user explicitly requests to refresh or gather
    more context from GitHub, Jira, or other sources.
    
    Args:
        focus: Optional focus area for research (e.g., "comments", "related PRs", "linked issues").
    
    Returns:
        Dict with instructions to hand off to Research agent.
    """
    return {
        "success": True,
        "action": "handoff_to_research",
        "message": f"Please hand off to the Research agent to gather more context{f' focusing on: {focus}' if focus else ''}.",
        "focus": focus,
    }


def register_rag_tools() -> None:
    """Register RAG tools with the ToolRegistry."""
    ToolRegistry.register("query_rag", query_rag_impl)
    ToolRegistry.register("index_to_rag", index_to_rag_impl)
    ToolRegistry.register("get_readiness_score", get_readiness_score_impl)
    ToolRegistry.register("trigger_research", trigger_research_impl)

