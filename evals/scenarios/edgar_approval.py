"""Edgar approval scenario — tests person-name retrieval."""

from .base import EvalScenario

edgar_approval_scenario = EvalScenario(
    name="edgar_approval",
    description="Author explicitly states Edgar likes the approach. Reviewer should find this.",
    author_statements=[
        "edgar reviewed the approach and likes it because it enables access for only a single service explicitly",
        "yeah and edgar plans to fix this more generally via envoy later",
    ],
    reviewer_questions=[
        "is edgar ok with that?",
        "did edgar approve this approach?",
        "what does edgar think about this change?",
        "has anyone reviewed the approach?",
        "who approved the design?",
    ],
    expected_in_response=["edgar"],
    expected_not_in_response=["I don't have information"],
)
