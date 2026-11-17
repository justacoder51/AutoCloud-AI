"""Recompute trusted candidates before accepting any proposed recommendation."""

from datetime import datetime

from app.agents.recommendation_agent import (
    Recommendation, RecommendationPolicy, build_plan,
)
from app.data.schema import MetricRecord


def validate_recommendation(
    proposal: dict, records: list[MetricRecord], *, project: str, region: str,
    service: str, now: datetime, policy: RecommendationPolicy | None = None,
) -> Recommendation:
    """Treat proposals as untrusted; schema validity alone does not establish evidence."""
    candidate = Recommendation.model_validate(proposal)
    trusted = build_plan(
        records, project=project, region=region, service=service, now=now, policy=policy,
    )
    if trusted.data_status != "fresh" or candidate not in trusted.recommendations:
        raise ValueError("Recommendation is not supported by current trusted evidence and policy")
    return candidate
