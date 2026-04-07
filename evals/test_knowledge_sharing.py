"""End-to-end evals for author→reviewer knowledge sharing.

These tests verify that information indexed during author training
is reliably surfaced to reviewers with various question phrasings.

Run with: make eval
Requires: Weaviate running (localhost:8085), OPENAI_API_KEY set
"""

from __future__ import annotations

import pytest

from .scenarios import (
    edgar_approval_scenario,
    technical_decision_scenario,
    indirect_reference_scenario,
)


@pytest.mark.eval
class TestKnowledgeSharing:
    """Test that reviewer can find author-indexed knowledge."""

    @pytest.mark.timeout(120)
    async def test_edgar_approval(self, author_session, reviewer_session):
        """Author says 'edgar likes this' — reviewer should find it."""
        result = await edgar_approval_scenario.run(author_session, reviewer_session)
        print(result.summary())
        assert result.pass_rate >= 0.8, (
            f"Edgar approval: only {result.pass_rate:.0%} passed\n{result.summary()}"
        )

    @pytest.mark.timeout(120)
    async def test_technical_decision(self, author_session, reviewer_session):
        """Author explains why approach was chosen — reviewer should find reasoning."""
        result = await technical_decision_scenario.run(author_session, reviewer_session)
        print(result.summary())
        assert result.pass_rate >= 0.8, (
            f"Technical decision: only {result.pass_rate:.0%} passed\n{result.summary()}"
        )

    @pytest.mark.timeout(120)
    async def test_indirect_reference(self, author_session, reviewer_session):
        """Author provides context — reviewer asks with different wording."""
        result = await indirect_reference_scenario.run(author_session, reviewer_session)
        print(result.summary())
        # Lower bar for indirect references — harder to match semantically
        assert result.pass_rate >= 0.6, (
            f"Indirect reference: only {result.pass_rate:.0%} passed\n{result.summary()}"
        )
