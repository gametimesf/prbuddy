"""Technical decision scenario — tests reasoning retrieval."""

from .base import EvalScenario

technical_decision_scenario = EvalScenario(
    name="technical_decision",
    description="Author explains why a specific approach was chosen over alternatives.",
    author_statements=[
        "we chose to add the security group rule directly instead of using a shared module because this is a one-off for fan-ops-voice",
        "the shared module would need changes that affect all services and we didn't want that blast radius",
    ],
    reviewer_questions=[
        "why didn't you use the shared module?",
        "what was the reasoning for this approach?",
        "why not update the shared security group module instead?",
        "is there a reason this is done inline instead of in the module?",
    ],
    expected_in_response=["blast radius"],
    expected_not_in_response=["I don't have information"],
)
