"""Narrow Gemini output contracts; numeric facts stay in deterministic code."""

from typing import Literal

from pydantic import Field

from app.agents.recommendation_agent import RecommendationPlan, StrictModel

Action = Literal["review_capacity", "investigate_memory", "investigate_errors"]
Summary = Literal[
    "investigate_observed_pressure", "no_supported_action", "insufficient_recent_evidence",
]


class AgentSelection(StrictModel):
    """Gemini can order supported investigations and choose a checked summary."""

    summary_code: Summary
    ordered_actions: tuple[Action, ...] = Field(max_length=3)


SUMMARY_TEXT = {
    "investigate_observed_pressure": (
        "Sustained observed threshold breaches warrant investigation before any capacity change."
    ),
    "no_supported_action": (
        "No sustained threshold breach is established. Missing measurements do not establish health."
    ),
    "insufficient_recent_evidence": (
        "Recent evidence is stale, insufficient or incomplete. Refresh observations before acting."
    ),
}

EXPLANATIONS = {
    "review_capacity": (
        "CPU utilisation exceeded the configured heuristic in every cited minute. "
        "Review capacity and application behaviour; this does not establish a CPU bottleneck."
    ),
    "investigate_memory": (
        "Memory utilisation exceeded the configured heuristic in every cited minute. "
        "Inspect application logs and memory behaviour; this does not establish a memory leak."
    ),
    "investigate_errors": (
        "The observed server error rate exceeded the configured heuristic in every cited minute. "
        "Inspect failing requests before proposing a capacity change."
    ),
}


def default_selection(plan: RecommendationPlan) -> AgentSelection:
    """Safe deterministic ordering when Gemini is disabled or unavailable."""
    summary = "insufficient_recent_evidence" if plan.data_status != "fresh" else (
        "investigate_observed_pressure" if plan.recommendations else "no_supported_action"
    )
    return AgentSelection(
        summary_code=summary, ordered_actions=tuple(item.action for item in plan.recommendations),
    )


def validate_selection(payload: dict, plan: RecommendationPlan) -> AgentSelection:
    """Reject omissions, duplicates, invented actions and false all-clear summaries."""
    selection = AgentSelection.model_validate(payload)
    expected = default_selection(plan)
    if (
        selection.summary_code != expected.summary_code
        or len(selection.ordered_actions) != len(expected.ordered_actions)
        or set(selection.ordered_actions) != set(expected.ordered_actions)
    ):
        raise ValueError("Gemini selection is inconsistent with the evidence catalog")
    return selection
