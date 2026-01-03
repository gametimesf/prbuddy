"""Structured output types for agents.

These Pydantic models define the structure of agent responses when
using the output_type parameter for structured outputs.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ReviewerResponse(BaseModel):
    """Structured output for ReviewerQA agent responses.

    The agent returns structured data that separates the spoken/displayed
    answer from metadata (confidence, sources) that the UI displays separately.
    """

    answer: str = Field(
        ...,
        description="The answer to display/speak to the reviewer. Should be concise and factual."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        ...,
        description=(
            "Confidence level based on source quality: "
            "'high' if answer comes from author explanations, "
            "'medium' if from PR diff/description, "
            "'low' if inferred or uncertain"
        )
    )
    sources_used: list[str] = Field(
        default_factory=list,
        description="List of source types used (e.g., 'author_explanation', 'diff', 'pr_description')"
    )
    needs_author_clarification: bool = Field(
        default=False,
        description="True if the question cannot be fully answered from available context"
    )


class AuthorTrainingResponse(BaseModel):
    """Structured output for AuthorTraining agent responses.

    Separates the conversational response from training metadata.
    """

    response: str = Field(
        ...,
        description="The response to display/speak to the author"
    )
    question_type: Literal["clarification", "challenge", "acknowledgment", "summary"] = Field(
        default="acknowledgment",
        description="Type of response for UI styling"
    )
    topics_covered: list[str] = Field(
        default_factory=list,
        description="Topics the author's response addressed (for progress tracking)"
    )
    suggested_topics: list[str] = Field(
        default_factory=list,
        description="Topics not yet covered that could improve training"
    )


class ResearchResponse(BaseModel):
    """Structured output for Research agent responses.

    Summarizes research findings with metadata about what was indexed.
    """

    summary: str = Field(
        ...,
        description="Summary of research findings to present to the user"
    )
    documents_indexed: int = Field(
        default=0,
        description="Number of documents indexed during research"
    )
    source_types: list[str] = Field(
        default_factory=list,
        description="Types of sources found (diff, description, comment, etc.)"
    )
    unblocked_context_found: bool = Field(
        default=False,
        description="Whether tribal knowledge was found via Unblocked"
    )


# Registry mapping output type names to classes
OUTPUT_TYPE_REGISTRY: dict[str, type[BaseModel]] = {
    "ReviewerResponse": ReviewerResponse,
    "AuthorTrainingResponse": AuthorTrainingResponse,
    "ResearchResponse": ResearchResponse,
}


def get_output_type(name: str) -> type[BaseModel] | None:
    """Get an output type class by name.

    Args:
        name: The output type name from YAML config.

    Returns:
        The Pydantic model class, or None if not found.
    """
    return OUTPUT_TYPE_REGISTRY.get(name)
