"""Finite LangGraph workflow: evidence, readiness, costs, Gemini, policy, review."""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import TypedDict

import pandas as pd
from pydantic import AwareDatetime, Field, model_validator

from app.agents.contracts import (
    EXPLANATIONS, SUMMARY_TEXT, default_selection, validate_selection,
)
from app.agents.recommendation_agent import (
    RecommendationPlan, RecommendationPolicy, StrictModel, build_plan,
)
from app.agents.validation import validate_recommendation
from app.config import Settings
from app.data.schema import MetricRecord
from app.models.cost_analyser import CostAnalyser, ServiceUsage
from app.models.dataset import (
    HORIZONS, MIN_OBSERVED_MINUTES, TrainingProfile, quality_report, regularize_history,
)
from app.services.gcp_monitoring import validate_target


class WorkflowRequest(StrictModel):
    """Explicit inputs, with no API keys, commands or implicit trained artifacts."""

    project: str
    region: str = "asia-south1"
    service: str = "autocloud-api"
    records: tuple[MetricRecord, ...] = Field(max_length=44640)
    policy: RecommendationPolicy = Field(default_factory=RecommendationPolicy)
    min_instances: int = Field(default=0, ge=0, le=2)
    max_instances: int = Field(default=2, ge=1, le=2)
    usage: ServiceUsage | None = None
    billing_table: str | None = None
    billing_start: AwareDatetime | None = None
    billing_end: AwareDatetime | None = None
    billing_daily: bool = False
    forecast_run: Path | None = None
    training_profile: TrainingProfile = "exploratory"
    use_gemini: bool = False

    @model_validator(mode="after")
    def validate_scope(self):
        validate_target(self.project, self.region, self.service)
        Settings(min_instances=self.min_instances, max_instances=self.max_instances)
        if any(value is not None for value in (
            self.billing_table, self.billing_start, self.billing_end,
        )):
            if not all(value is not None for value in (
                self.billing_table, self.billing_start, self.billing_end,
            )):
                raise ValueError("Billing table and both time boundaries are required together")
            from app.services.billing_service import validate_billing_table

            validate_billing_table(self.billing_table)
            if not self.billing_start < self.billing_end <= self.billing_start + timedelta(days=31):
                raise ValueError("Billing window must be ordered and at most 31 days")
        if self.usage is not None:
            if (self.usage.project_id, self.usage.region, self.usage.service_name) != (
                self.project, self.region, self.service,
            ):
                raise ValueError("Usage must match the monitored project, region and service")
            if self.usage.source == "synthetic_demo":
                raise ValueError("Synthetic cost inputs do not belong in a real Monitoring workflow")
        return self


class WorkflowState(TypedDict, total=False):
    """Only node-owned state is returned; callers cannot prepopulate approval state."""

    plan: RecommendationPlan
    readiness: dict
    cost: dict | None
    actual_exported: dict | None
    forecasts: list | None
    selection: dict
    gemini_status: str
    error_type: str | None
    http_status: int | None
    result: dict


def build_workflow(
    request: WorkflowRequest, selector: Callable[[dict], dict] | None = None,
    clock: Callable[[], datetime] | None = None,
):
    """Compile an acyclic graph, with a single optional model request and no action tool."""
    from langgraph.graph import END, START, StateGraph

    clock = clock or (lambda: datetime.now(timezone.utc))
    # Round-trip at the boundary, including nested records, instead of trusting model_copy updates.
    request = WorkflowRequest.model_validate_json(request.model_dump_json())
    context = dict(project=request.project, region=request.region, service=request.service)

    def monitoring(_state):
        return {"plan": build_plan(
            list(request.records), **context, now=clock(), policy=request.policy,
        )}

    def models(_state):
        readiness = {
            "ready": False, "reasons": ["No observed history supplied"],
            "profile": request.training_profile,
            "minimum_observed_minutes": MIN_OBSERVED_MINUTES[request.training_profile],
            "horizons_minutes": list(HORIZONS), "deployment_ready": False,
        }
        if request.records:
            frame = pd.DataFrame([row.model_dump() for row in request.records])
            readiness = quality_report(regularize_history(frame), request.training_profile)
        forecasts = None
        if request.forecast_run is not None:
            from app.models.inference import predict_from_run

            forecasts = predict_from_run(
                request.forecast_run, list(request.records), **context, now=clock(),
            )
        return {"readiness": readiness, "forecasts": forecasts}

    def costs(_state):
        cost = None
        if request.usage is not None:
            now = clock()
            if request.usage.period_end > now:
                raise ValueError("Cost input period must not end in the future")
            cost = CostAnalyser.from_file(as_of=now.date()).estimate(request.usage).model_dump(mode="json")
        actual = None
        if request.billing_table is not None:
            from app.services.billing_service import BillingExportService

            actual = BillingExportService(request.project, request.billing_table).read(
                request.project, request.billing_start, request.billing_end,
                **({"daily": True} if request.billing_daily else {}),
            )
            # Preserve decimal precision while keeping report JSON portable.
            for row in actual["rows"]:
                for name, value in row.items():
                    if isinstance(value, Decimal):
                        row[name] = str(value)
        return {"cost": cost, "actual_exported": actual}

    def choose_route(state):
        return "gemini" if request.use_gemini and state["plan"].data_status == "fresh" else "policy"

    def gemini(state):
        plan = state["plan"]
        # Only a bounded evidence catalog and capability statuses leave the process.
        evidence = {
            "data_status": plan.data_status,
            "candidates": [item.model_dump(mode="json") for item in plan.recommendations],
            "model_status": "candidate_forecasts_available" if state["forecasts"] else "not_evaluated",
            "cost_status": (
                state["actual_exported"]["status"] if state["actual_exported"] is not None
                else "estimate_available" if state["cost"] else "unknown"
            ),
            "constraints": {
                "min_instances": request.min_instances, "max_instances": request.max_instances,
                "live_configuration_verified": False, "execution_allowed": False,
            },
        }
        try:
            if selector is None:
                raise ValueError("Gemini requested without a configured Vertex adapter")
            selected = validate_selection(selector(evidence), plan)
            return {
                "selection": selected.model_dump(mode="json"),
                "gemini_status": "succeeded", "error_type": None,
            }
        except Exception as error:
            # Model/API/validation failures cannot replace trusted evidence or authorise action.
            code = getattr(error, "code", None)
            return {
                "selection": default_selection(plan).model_dump(mode="json"),
                "gemini_status": "failed_or_rejected", "error_type": type(error).__name__,
                "http_status": code if type(code) is int and 400 <= code <= 599 else None,
            }

    def policy(state):
        now = clock()
        trusted = build_plan(list(request.records), **context, now=now, policy=request.policy)
        status = state.get("gemini_status", "skipped_unusable_evidence" if request.use_gemini else "disabled")
        draft = state.get("selection", default_selection(trusted).model_dump(mode="json"))
        if trusted.data_status != "fresh":
            draft = default_selection(trusted).model_dump(mode="json")
            if status == "succeeded":
                status = "discarded_evidence_expired"
        selected = validate_selection(draft, trusted)
        catalog = {item.action: item for item in trusted.recommendations}
        recommendations = []
        for action in selected.ordered_actions:
            item = validate_recommendation(
                catalog[action].model_dump(mode="json"), list(request.records),
                **context, now=now, policy=request.policy,
            )
            recommendations.append({
                **item.model_dump(mode="json"), "explanation": EXPLANATIONS[action],
                "explanation_source": "validated_template",
            })
        result = {
            "mode": "langgraph_recommendation_only",
            "workflow_status": "blocked_evidence" if trusted.data_status != "fresh" else (
                "awaiting_human_review" if recommendations else "no_supported_action"
            ),
            **context, "assessed_at": now.isoformat(), "data_status": trusted.data_status,
            "evidence_fingerprint": trusted.evidence_fingerprint,
            "latest_observation": trusted.latest_observation.isoformat() if trusted.latest_observation else None,
            "summary": SUMMARY_TEXT[selected.summary_code],
            "diagnostic": trusted.diagnostic,
            "recommendations": recommendations,
            "model_analysis": {
                "status": (
                    "candidate_withheld_stale" if state["forecasts"] and trusted.data_status != "fresh"
                    else "offline_candidate_inference" if state["forecasts"] else "not_evaluated"
                ),
                "readiness": state["readiness"],
                "anomaly_results": None,
                "forecasts": state["forecasts"] if trusted.data_status == "fresh" else None,
                "reason": (
                    "Forecasts are candidate outputs, not deployment approval; anomaly labels remain required."
                    if state["forecasts"] else
                    "No independently evaluated real-data model is loaded; readiness is not training."
                ),
            },
            "cost_analysis": {
                "status": (
                    state["actual_exported"]["status"] if state["actual_exported"] is not None
                    else "estimated_not_billed" if state["cost"] else "usage_or_billing_export_required"
                ),
                "estimate": state["cost"], "actual_exported": state["actual_exported"],
                "measured_savings": None,
            },
            "gemini": {
                "status": status, "error_type": state.get("error_type"),
                **({"http_status": state["http_status"]} if state.get("http_status") else {}),
            },
            "constraints": {
                "min_instances": request.min_instances, "max_instances": request.max_instances,
                "live_configuration_verified": False,
            },
            "execution_allowed": False,
        }
        return {"result": result}

    graph = StateGraph(WorkflowState)
    graph.add_node("monitoring", monitoring)
    graph.add_node("model_readiness", models)
    graph.add_node("cost_analysis", costs)
    graph.add_node("gemini", gemini)
    graph.add_node("policy", policy)
    graph.add_edge(START, "monitoring")
    graph.add_edge("monitoring", "model_readiness")
    graph.add_edge("model_readiness", "cost_analysis")
    graph.add_conditional_edges("cost_analysis", choose_route, {"gemini": "gemini", "policy": "policy"})
    graph.add_edge("gemini", "policy")
    graph.add_edge("policy", END)
    return graph.compile()


def run_workflow(request: WorkflowRequest, selector=None, clock=None) -> dict:
    """Run without caller-supplied internal state or persisted approvals."""
    graph = build_workflow(request, selector=selector, clock=clock)
    return graph.invoke({}, config={"recursion_limit": 10})["result"]
