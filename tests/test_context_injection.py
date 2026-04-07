"""Tests for automatic RAG context injection."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.sessions.context_injection import (
    build_rag_context,
    extract_keywords,
    format_rag_context,
    _filter_excluded,
)


@dataclass
class FakeRAGResult:
    """Minimal RAG result for testing."""

    content: str
    doc_type: str
    score: float
    source_url: str | None = None
    file_path: str | None = None
    chunk_index: int | None = None


class TestExtractKeywords:
    def test_strips_stop_words(self):
        result = extract_keywords("is edgar ok with that?")
        assert "is" not in result
        assert "with" not in result
        assert "edgar" in result
        assert "ok" in result

    def test_strips_punctuation(self):
        result = extract_keywords("what did the team decide?")
        assert "?" not in result

    def test_preserves_names(self):
        result = extract_keywords("did edgar approve the approach")
        assert "edgar" in result
        assert "approve" in result
        assert "approach" in result

    def test_preserves_technical_terms(self):
        result = extract_keywords("why is MongoDB used instead of DynamoDB")
        assert "mongodb" in result
        assert "dynamodb" in result

    def test_empty_input(self):
        assert extract_keywords("") == ""

    def test_all_stop_words(self):
        assert extract_keywords("is it the") == ""

    def test_short_words_removed(self):
        result = extract_keywords("is X ok")
        # "X" is only 1 char, should be removed
        assert "ok" in result


class TestFilterExcluded:
    def test_removes_conversation_types(self):
        results = [
            FakeRAGResult(content="author conv", doc_type="conversation_author", score=0.9),
            FakeRAGResult(content="real content", doc_type="author_explanation", score=0.8),
            FakeRAGResult(content="reviewer conv", doc_type="conversation_reviewer", score=0.7),
            FakeRAGResult(content="pr ctx", doc_type="pr_context", score=0.6),
        ]
        filtered = _filter_excluded(results)
        assert len(filtered) == 1
        assert filtered[0].doc_type == "author_explanation"

    def test_keeps_all_valid_types(self):
        results = [
            FakeRAGResult(content="a", doc_type="author_explanation", score=0.9),
            FakeRAGResult(content="b", doc_type="diff", score=0.8),
            FakeRAGResult(content="c", doc_type="comment", score=0.7),
        ]
        filtered = _filter_excluded(results)
        assert len(filtered) == 3


class TestFormatRagContext:
    def test_formats_results(self):
        results = [
            FakeRAGResult(
                content="Edgar reviewed and approved the approach",
                doc_type="author_explanation",
                score=0.92,
            ),
        ]
        formatted = format_rag_context(results)
        assert formatted is not None
        assert "Author Knowledge Base Context" in formatted
        assert "Edgar reviewed" in formatted
        assert "author_explanation" in formatted
        assert "0.92" in formatted

    def test_includes_source_url(self):
        results = [
            FakeRAGResult(
                content="content",
                doc_type="issue",
                score=0.8,
                source_url="https://jira.example.com/PROJ-123",
            ),
        ]
        formatted = format_rag_context(results)
        assert "source=https://jira.example.com/PROJ-123" in formatted

    def test_includes_file_path(self):
        results = [
            FakeRAGResult(
                content="content",
                doc_type="diff",
                score=0.7,
                file_path="src/main.py",
            ),
        ]
        formatted = format_rag_context(results)
        assert "file=src/main.py" in formatted

    def test_truncates_long_content(self):
        results = [
            FakeRAGResult(content="x" * 600, doc_type="diff", score=0.5),
        ]
        formatted = format_rag_context(results)
        assert "..." in formatted
        # Should be truncated to ~500 chars
        content_line = [l for l in formatted.split("\n") if l.startswith("  x")][0]
        assert len(content_line.strip()) < 520

    def test_returns_none_for_empty(self):
        assert format_rag_context([]) is None

    def test_multiple_results_numbered(self):
        results = [
            FakeRAGResult(content="first", doc_type="author_explanation", score=0.9),
            FakeRAGResult(content="second", doc_type="diff", score=0.8),
        ]
        formatted = format_rag_context(results)
        assert "[1]" in formatted
        assert "[2]" in formatted


class TestBuildRagContext:
    @pytest.fixture
    def mock_rag_store(self):
        store = AsyncMock()
        store.query = AsyncMock(return_value=[])
        store.search_keyword = AsyncMock(return_value=[])
        store.search_vector = AsyncMock(return_value=[])
        return store

    async def test_returns_none_when_no_results(self, mock_rag_store):
        result = await build_rag_context("test question", mock_rag_store)
        assert result is None

    async def test_calls_all_three_search_strategies(self, mock_rag_store):
        await build_rag_context("is edgar ok with this", mock_rag_store)
        mock_rag_store.query.assert_called_once()
        mock_rag_store.search_keyword.assert_called_once()
        mock_rag_store.search_vector.assert_called_once()

    async def test_deduplicates_results(self, mock_rag_store):
        # Same content from hybrid and keyword search
        same_result = FakeRAGResult(
            content="Edgar approved the approach",
            doc_type="author_explanation",
            score=0.9,
        )
        mock_rag_store.query.return_value = [same_result]
        mock_rag_store.search_keyword.return_value = [same_result]
        mock_rag_store.search_vector.return_value = []

        result = await build_rag_context("edgar approval", mock_rag_store)
        assert result is not None
        # Should only appear once despite being in two result sets
        assert result.count("Edgar approved") == 1

    async def test_ranks_by_score(self, mock_rag_store):
        low = FakeRAGResult(content="low score result", doc_type="diff", score=0.3)
        high = FakeRAGResult(content="high score result", doc_type="author_explanation", score=0.95)
        mock_rag_store.query.return_value = [low]
        mock_rag_store.search_vector.return_value = [high]

        result = await build_rag_context("test", mock_rag_store)
        assert result is not None
        # High score should appear first ([1])
        lines = result.split("\n")
        first_result_line = next(l for l in lines if l.startswith("[1]"))
        assert "0.95" in first_result_line

    async def test_filters_excluded_doc_types(self, mock_rag_store):
        excluded = FakeRAGResult(content="conversation", doc_type="conversation_author", score=0.99)
        valid = FakeRAGResult(content="explanation", doc_type="author_explanation", score=0.8)
        mock_rag_store.query.return_value = [excluded, valid]

        result = await build_rag_context("test", mock_rag_store)
        assert result is not None
        assert "conversation" not in result
        assert "explanation" in result

    async def test_handles_partial_query_failure(self, mock_rag_store):
        mock_rag_store.query.return_value = [
            FakeRAGResult(content="good result", doc_type="author_explanation", score=0.9)
        ]
        mock_rag_store.search_keyword.side_effect = Exception("BM25 failed")

        result = await build_rag_context("test", mock_rag_store)
        # Should still return results from the successful queries
        assert result is not None
        assert "good result" in result

    async def test_respects_top_k(self, mock_rag_store):
        results = [
            FakeRAGResult(content=f"result {i}", doc_type="diff", score=0.9 - i * 0.1)
            for i in range(10)
        ]
        mock_rag_store.query.return_value = results

        result = await build_rag_context("test", mock_rag_store, top_k=3)
        assert result is not None
        assert "[3]" in result
        assert "[4]" not in result
