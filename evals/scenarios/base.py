"""Base classes for eval scenarios."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QuestionResult:
    """Result of a single reviewer question."""

    question: str
    response: str
    passed: bool
    missing_expected: list[str] = field(default_factory=list)
    found_unexpected: list[str] = field(default_factory=list)


@dataclass
class EvalResult:
    """Result of running a full scenario."""

    scenario_name: str
    question_results: list[QuestionResult]

    @property
    def pass_rate(self) -> float:
        if not self.question_results:
            return 0.0
        return sum(1 for r in self.question_results if r.passed) / len(self.question_results)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.question_results if r.passed)

    @property
    def total_count(self) -> int:
        return len(self.question_results)

    def summary(self) -> str:
        lines = [
            f"Scenario: {self.scenario_name}",
            f"Pass rate: {self.pass_rate:.0%} ({self.passed_count}/{self.total_count})",
        ]
        for r in self.question_results:
            status = "PASS" if r.passed else "FAIL"
            lines.append(f"  [{status}] {r.question}")
            if not r.passed:
                if r.missing_expected:
                    lines.append(f"    Missing: {r.missing_expected}")
                if r.found_unexpected:
                    lines.append(f"    Unexpected: {r.found_unexpected}")
                lines.append(f"    Response: {r.response[:200]}...")
        return "\n".join(lines)


@dataclass
class EvalScenario:
    """A test scenario for knowledge sharing between author and reviewer.

    Defines what the author says during training and what the reviewer
    should be able to find with various phrasings.
    """

    name: str
    description: str
    author_statements: list[str]
    reviewer_questions: list[str]
    expected_in_response: list[str]
    expected_not_in_response: list[str] = field(default_factory=list)

    async def run(
        self,
        author_session,
        reviewer_session,
    ) -> EvalResult:
        """Run the scenario end-to-end.

        Args:
            author_session: TextSession configured as author.
            reviewer_session: TextSession configured as reviewer.

        Returns:
            EvalResult with per-question pass/fail.
        """
        # Phase 1: Author training — send each statement
        for stmt in self.author_statements:
            await author_session.send_text(stmt)

        # Phase 2: Reviewer questions — test each phrasing
        results = []
        for question in self.reviewer_questions:
            response = await reviewer_session.send_text(question)

            missing = [
                exp for exp in self.expected_in_response
                if exp.lower() not in response.lower()
            ]
            found_unexpected = [
                exp for exp in self.expected_not_in_response
                if exp.lower() in response.lower()
            ]

            passed = len(missing) == 0 and len(found_unexpected) == 0

            results.append(QuestionResult(
                question=question,
                response=response,
                passed=passed,
                missing_expected=missing,
                found_unexpected=found_unexpected,
            ))

        return EvalResult(scenario_name=self.name, question_results=results)
