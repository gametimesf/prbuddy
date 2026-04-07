"""Automatic RAG context injection for reviewer sessions.

Before the reviewer agent processes a user message, this module queries
the RAG store with multiple strategies (hybrid, keyword, vector) and
formats the results as a system message for injection into the agent's input.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING

from ..observability.logging import get_logger

if TYPE_CHECKING:
    from ..rag.store import RAGResult, WeaviatePRRAGStore

logger = get_logger(__name__)

# Common English stop words to strip from keyword queries
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "both",
    "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "don", "now", "and", "but", "or", "if", "what", "which", "who",
    "whom", "this", "that", "these", "those", "am", "it", "its", "i",
    "me", "my", "we", "our", "you", "your", "he", "she", "they", "them",
    "his", "her", "about", "up", "any",
})

# Excluded doc types (same as rag_tools.py — don't surface internal docs)
_EXCLUDED_DOC_TYPES = {"conversation_author", "conversation_reviewer", "pr_context"}


def extract_keywords(question: str) -> str:
    """Extract meaningful keywords from a question for BM25 search.

    Strips stop words and short tokens to focus on content words,
    names, and technical terms that BM25 can match exactly.

    Args:
        question: The user's question.

    Returns:
        Space-separated keywords string.
    """
    words = question.lower().replace("?", "").replace("!", "").replace(",", "").split()
    keywords = [w for w in words if w not in _STOP_WORDS and len(w) > 1]
    return " ".join(keywords)


def _content_hash(content: str) -> str:
    """Hash first 200 chars of content for deduplication."""
    return hashlib.md5(content[:200].encode()).hexdigest()


def _filter_excluded(results: list[RAGResult]) -> list[RAGResult]:
    """Remove results with excluded doc types."""
    return [r for r in results if r.doc_type not in _EXCLUDED_DOC_TYPES]


async def build_rag_context(
    question: str,
    rag_store: WeaviatePRRAGStore,
    top_k: int = 5,
) -> str | None:
    """Query RAG with multiple strategies and format results for injection.

    Runs three parallel queries to maximize recall:
    1. Hybrid search (BM25 + vector) — balanced
    2. Keyword search (BM25 only) — catches exact name/term matches
    3. Vector search — catches semantic paraphrases

    Deduplicates, ranks by score, and formats as a system message.

    Args:
        question: The reviewer's question.
        rag_store: The PR-scoped RAG store.
        top_k: Max results to include in context.

    Returns:
        Formatted context string, or None if no results found.
    """
    keywords = extract_keywords(question)

    try:
        hybrid_results, keyword_results, vector_results = await asyncio.gather(
            rag_store.query(question, top_k=top_k),
            rag_store.search_keyword(keywords, top_k=3) if keywords else _empty(),
            rag_store.search_vector(question, top_k=3),
            return_exceptions=True,
        )
    except Exception as e:
        logger.warning("rag_context_injection_failed", error=str(e))
        return None

    # Collect all successful results
    all_results: list[RAGResult] = []
    for batch in [hybrid_results, keyword_results, vector_results]:
        if isinstance(batch, list):
            all_results.extend(batch)
        elif isinstance(batch, Exception):
            logger.warning("rag_query_partial_failure", error=str(batch))

    # Filter excluded types
    all_results = _filter_excluded(all_results)

    if not all_results:
        return None

    # Deduplicate by content hash
    seen: set[str] = set()
    unique: list[RAGResult] = []
    for r in all_results:
        h = _content_hash(r.content)
        if h not in seen:
            seen.add(h)
            unique.append(r)

    # Sort by score descending, take top_k
    unique.sort(key=lambda r: r.score, reverse=True)
    top_results = unique[:top_k]

    return format_rag_context(top_results)


async def _empty() -> list:
    """Return empty list (used when keywords are empty)."""
    return []


def format_rag_context(results: list[RAGResult]) -> str | None:
    """Format RAG results as a system message block.

    Args:
        results: Ranked, deduplicated RAG results.

    Returns:
        Formatted string for system message injection, or None if empty.
    """
    if not results:
        return None

    lines = [
        "## Author Knowledge Base Context",
        "The following information was indexed by the author or discovered during research.",
        "Use this to answer the reviewer's question. Cite the source type when relevant.",
        "",
    ]

    for i, r in enumerate(results, 1):
        # Truncate long content for context window efficiency
        content = r.content[:500].strip()
        if len(r.content) > 500:
            content += "..."

        source_info = ""
        if r.source_url:
            source_info = f", source={r.source_url}"
        elif r.file_path:
            source_info = f", file={r.file_path}"

        lines.append(f"[{i}] ({r.doc_type}, score={r.score:.2f}{source_info}):")
        lines.append(f"  {content}")
        lines.append("")

    return "\n".join(lines)
