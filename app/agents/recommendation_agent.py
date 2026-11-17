"""Deterministic investigation candidates for the later LLM workflow."""

from datetime import datetime, timedelta
from hashlib import sha256
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.data.schema import MetricRecord


class StrictModel(BaseModel):
    """Reject extra fields and non-finite values at recommendation boundaries."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class RecommendationPolicy(StrictModel):
    """Engineering heuristics; these are not learned thresholds or service SLOs."""

    consecutive_minutes: int = Field(default=3, ge=3, le=30)
    max_age_seconds: int = Field(default=900, ge=60, le=3600)
    cpu_threshold: float = Field(default=.9, gt=0, le=1)
    memory_threshold: float = Field(default=.9, gt=0, le=1)
    error_threshold: float = Field(default=.05, gt=0, le=1)


class Evidence(StrictModel):
    """Exact observed values, in record order, rather than LLM-written numbers."""

    metric: Literal["cpu_utilization", "memory_utilization", "error_rate"]
    record_ids: tuple[str, ...]
    timestamps: tuple[AwareDatetime, ...]
    values: tuple[float, ...]
    threshold: float
    unit: Literal["fraction"] = "fraction"


class Recommendation(StrictModel):
    """Reviewable investigation; no mutation is supported by this first stage."""

    action: Literal["review_capacity", "investigate_memory", "investigate_errors"]
    problem: str
    evidence: Evidence
    proposed_action: str
    expected_performance_impact: str = "Unknown until the cause is investigated."
    estimated_financial_impact: None = None
    confidence: None = None
    uncertainty: str = (
        "Heuristic threshold evidence only; no calibrated probability or causal diagnosis."
    )
    operational_risks: str = (
        "Changing capacity without workload and performance evaluation can harm availability."
    )
    approval_status: Literal["pending_review"] = "pending_review"
    execution_allowed: Literal[False] = False


class RecommendationPlan(StrictModel):
    """Source-bound catalog from which a future orchestrator may select candidates."""

    project_id: str
    region: str
    service_name: str
    assessed_at: AwareDatetime
    latest_observation: AwareDatetime | None
    data_status: Literal["fresh", "stale", "insufficient", "incomplete_window"]
    source: Literal["gcp-monitoring"] = "gcp-monitoring"
    evidence_fingerprint: str
    recommendations: tuple[Recommendation, ...] = ()
    model_status: Literal["not_evaluated"] = "not_evaluated"
    cost_status: Literal["not_evaluated"] = "not_evaluated"
    mode: Literal["deterministic_policy_preview"] = "deterministic_policy_preview"
    diagnostic: str


def build_plan(
    records: list[MetricRecord], *, project: str, region: str, service: str,
    now: datetime, policy: RecommendationPolicy | None = None,
) -> RecommendationPlan:
    """Require one target and a fresh consecutive window; never fill missing values."""
    policy = policy or RecommendationPolicy()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Assessment time must be timezone aware")
    if not all((project, region, service)):
        raise ValueError("An explicit project, region and service are required")
    latest = {}
    for record in records:
        if (record.project_id, record.region, record.service_name) != (project, region, service):
            raise ValueError("Mixed or unexpected metric target")
        if record.timestamp > now or record.collected_at > now:
            raise ValueError("Future-dated metric evidence")
        previous = latest.get(record.record_id)
        if previous and record.collected_at == previous.collected_at and record != previous:
            raise ValueError("Conflicting records at the same collection time")
        if previous is None or record.collected_at > previous.collected_at:
            latest[record.record_id] = record
    ordered = sorted(latest.values(), key=lambda record: record.timestamp)
    window = ordered[-policy.consecutive_minutes:]
    payload = "\n".join(record.model_dump_json() for record in window)
    fingerprint = sha256((payload + policy.model_dump_json()).encode()).hexdigest()
    observed = window[-1].timestamp if window else None
    context = dict(
        project_id=project, region=region, service_name=service, assessed_at=now,
        latest_observation=observed, evidence_fingerprint=fingerprint,
    )
    if observed is not None and (now - observed).total_seconds() > policy.max_age_seconds:
        return RecommendationPlan(
            **context, data_status="stale", diagnostic="Collect fresh metrics before recommendations.",
        )
    if len(window) < policy.consecutive_minutes:
        return RecommendationPlan(
            **context, data_status="insufficient", diagnostic="Not enough distinct observed minutes.",
        )
    if any(b.timestamp - a.timestamp != timedelta(minutes=1) for a, b in zip(window, window[1:])):
        return RecommendationPlan(
            **context, data_status="incomplete_window", diagnostic="Recent observation minutes have gaps.",
        )
    rules = (
        ("cpu_utilization", policy.cpu_threshold, "review_capacity",
         "Sustained high observed CPU utilisation", "Review CPU pressure and capacity constraints."),
        ("memory_utilization", policy.memory_threshold, "investigate_memory",
         "Sustained high observed memory utilisation", "Inspect memory pressure and application logs."),
        ("error_rate", policy.error_threshold, "investigate_errors",
         "Sustained elevated observed server error rate", "Inspect failing requests and application logs."),
    )
    recommendations = []
    for metric, threshold, action, problem, proposed_action in rules:
        values = tuple(getattr(record, metric) for record in window)
        if any(value is None or value <= threshold for value in values):
            continue
        recommendations.append(Recommendation(
            action=action, problem=problem, proposed_action=proposed_action,
            evidence=Evidence(
                metric=metric, threshold=threshold, values=values,
                record_ids=tuple(record.record_id for record in window),
                timestamps=tuple(record.timestamp for record in window),
            ),
        ))
    return RecommendationPlan(
        **context, data_status="fresh", recommendations=tuple(recommendations),
        diagnostic=(
            "Investigation candidates found; no scaling authorised."
            if recommendations else
            "No sustained threshold breach established; missing values do not imply normal operation."
        ),
    )
