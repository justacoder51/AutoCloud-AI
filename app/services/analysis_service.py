"""Explicit dashboard workflow requests with per-worker coalescing and cooldown."""

from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic


class AnalysisBusy(ValueError):
    """Another request used this worker's recent analysis budget."""


class DashboardAnalysis:
    def __init__(self, clock=monotonic):
        self.clock = clock
        self.lock = Lock()
        self.cached = None

    def run(
        self,
        settings,
        history,
        *,
        hours,
        use_gemini,
        include_billing,
        connectivity_check=False,
        selector=None,
        project_id: str | None = None,
        region: str | None = None,
        service_name: str | None = None,
        source: str = "bigquery",
        owner_key: str | None = None,
        bearer_token: str | None = None,
        billing_allowed: bool = True,
    ):
        from app.agents.orchestrator import WorkflowRequest, run_workflow
        from app.data.schema import MetricRecord

        target_project = project_id or settings.gcp_project_id
        target_region = region or settings.gcp_region
        target_service = service_name or "autocloud-api"
        key = (
            owner_key or "__shared__", target_project, target_region, target_service,
            source, hours, use_gemini, include_billing, connectivity_check,
        )
        with self.lock:
            if self.cached and self.clock() - self.cached[1] < 60:
                if key != self.cached[0]:
                    raise AnalysisBusy("Wait 60 seconds before changing the analysis options.")
                return {**self.cached[2], "cache_hit": True}
            # Reserve the budget before any cloud request; failures also cool down.
            payload = {"status": "unavailable", "cache_hit": False, "cache_seconds": 60,
                       "result": None, "execution_allowed": False}
            self.cached = (key, self.clock(), payload)
            try:
                if connectivity_check:
                    from app.agents.contracts import validate_selection
                    from app.agents.recommendation_agent import build_plan
                    from app.services.vertex_service import VertexService, VertexSettings

                    now = datetime.now(timezone.utc)
                    empty = build_plan([], project=target_project,
                                       region=target_region, service=target_service, now=now)
                    select = selector or VertexService(VertexSettings(
                        project_id=settings.gcp_project_id, region=settings.gcp_region,
                        model=settings.dashboard_gemini_model,
                    )).select
                    validate_selection(select({"mode":"connectivity_probe_only",
                        "data_status":"insufficient", "candidates":[],
                        "model_status":"not_evaluated", "cost_status":"unknown"}), empty)
                    result = {"mode":"connectivity_probe_only", "workflow_status":"connectivity_checked",
                              "assessed_at":now.isoformat(), "data_status":"insufficient",
                              "gemini":{"status":"succeeded"}, "recommendations":[],
                              "summary":"Gemini connection and structured response verified. No monitoring, model accuracy, cost analysis or infrastructure action was evaluated.",
                              "execution_allowed":False}
                    payload.update(status="completed", result=result, completed_at=datetime.now(timezone.utc).isoformat())
                    self.cached = (key, self.clock(), payload)
                    return payload
                measured = history.read(
                    target_project, target_region, target_service, hours,
                    source=source, owner_key=owner_key, bearer_token=bearer_token,
                )
                if measured["status"] != "succeeded":
                    raise ValueError("Monitoring read unavailable")
                records = tuple(MetricRecord.model_validate(row) for row in measured["records"])
                now = datetime.now(timezone.utc)
                if any(row.timestamp > now or row.collected_at > now for row in records):
                    raise ValueError("Future evidence")
                if use_gemini and selector is None:
                    from app.services.vertex_service import VertexService, VertexSettings

                    selector = VertexService(VertexSettings(
                        project_id=settings.gcp_project_id, region=settings.gcp_region,
                        model=settings.dashboard_gemini_model,
                    )).select
                use_billing = bool(include_billing and billing_allowed)
                request = WorkflowRequest(
                    project=target_project, region=target_region,
                    service=target_service, records=records,
                    min_instances=settings.min_instances, max_instances=settings.max_instances,
                    use_gemini=use_gemini,
                    billing_table=settings.dashboard_billing_table if use_billing else None,
                    billing_start=now-timedelta(days=1) if use_billing else None,
                    billing_end=now if use_billing else None,
                    billing_daily=use_billing,
                )
                result = run_workflow(request, selector=selector)
                payload.update(status="completed", result=result,
                               completed_at=datetime.now(timezone.utc).isoformat())
            except Exception as error:
                payload["error_type"] = type(error).__name__
            self.cached = (key, self.clock(), payload)
            return payload
