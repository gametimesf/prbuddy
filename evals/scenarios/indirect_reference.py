"""Indirect reference scenario — tests when reviewer doesn't use exact terms."""

from .base import EvalScenario

indirect_reference_scenario = EvalScenario(
    name="indirect_reference",
    description="Author provides context that reviewer asks about with different wording.",
    author_statements=[
        "this is a temporary workaround until the team migrates to envoy-based service mesh",
        "maria from platform team is leading the envoy migration, should be done by Q3",
    ],
    reviewer_questions=[
        "is this a permanent change?",
        "are there plans to do this differently later?",
        "who's working on the long-term solution?",
        "when will the proper fix land?",
    ],
    expected_in_response=["envoy"],
    expected_not_in_response=[],
)
