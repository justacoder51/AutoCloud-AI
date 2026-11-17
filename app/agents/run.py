"""Run LangGraph locally; --use-gemini explicitly permits one Vertex model request."""

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agents.orchestrator import WorkflowRequest, run_workflow
from app.data.schema import MetricRecord
from app.models.cost_analyser import ServiceUsage, load_usage
from app.services.vertex_service import DEFAULT_VERTEX_MODEL


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--input", type=Path, default=Path("data/processed/metrics.ndjson"))
    source.add_argument("--from-bigquery", action="store_true")
    parser.add_argument("--project", default=os.getenv("GCP_PROJECT_ID", "astute-sign-506809-j8"))
    parser.add_argument("--region", default=os.getenv("GCP_REGION", "asia-south1"))
    parser.add_argument("--service", default="autocloud-api")
    parser.add_argument("--days", type=int, choices=range(1, 31), default=7)
    parser.add_argument("--profile", choices=("exploratory", "conservative"), default="exploratory")
    parser.add_argument("--usage", type=Path, help="Explicit service billable units, not utilisation")
    parser.add_argument("--billing-table", help="Explicit fully qualified Billing export table; read only")
    parser.add_argument("--billing-days", type=int, choices=range(1, 32), default=1)
    parser.add_argument("--forecast-run", type=Path, help="Explicit native-model run directory, never joblib")
    parser.add_argument("--use-gemini", action="store_true", help="Permit one potentially billable Vertex request")
    parser.add_argument(
        "--check-vertex", action="store_true",
        help="Permit one Vertex connectivity probe without reading metrics or producing recommendations",
    )
    parser.add_argument("--model", default=os.getenv("VERTEX_MODEL", DEFAULT_VERTEX_MODEL))
    args = parser.parse_args()
    try:
        if args.check_vertex:
            from app.agents.contracts import validate_selection
            from app.agents.recommendation_agent import build_plan
            from app.services.vertex_service import VertexService, VertexSettings

            adapter = VertexService(VertexSettings(
                project_id=args.project, region=args.region, model=args.model,
            ))
            # Explicitly absent evidence; no synthetic observations are sent as real metrics.
            empty_plan = build_plan(
                [], project=args.project, region=args.region, service=args.service,
                now=datetime.now(timezone.utc),
            )
            validate_selection(adapter.select({
                "mode": "connectivity_probe_only", "data_status": "insufficient",
                "candidates": [], "model_status": "not_evaluated", "cost_status": "unknown",
            }), empty_plan)
            print(json.dumps({
                "mode": "vertex_connectivity_probe", "gemini_status": "succeeded",
                "model": args.model, "region": args.region, "recommendations": [],
                "execution_allowed": False,
                "note": "Connectivity and structured response only; no monitoring, ML or cost analysis performed.",
            }, indent=2))
            return 0
        if args.from_bigquery:
            from app.services.bigquery_service import BigQueryService

            rows = BigQueryService(
                args.project, args.region, "autocloud", "latest_metrics",
            ).read_history(args.service, args.days)
            records = [MetricRecord.model_validate(row) for row in rows]
        else:
            records = [
                MetricRecord.model_validate_json(line)
                for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()
            ]
        usage = load_usage(args.usage) if args.usage else None
        if usage is not None and not isinstance(usage, ServiceUsage):
            raise ValueError("The monitored service workflow accepts only service usage")
        billing_end = datetime.now(timezone.utc) if args.billing_table else None
        request = WorkflowRequest(
            project=args.project, region=args.region, service=args.service,
            records=tuple(records), usage=usage, use_gemini=args.use_gemini,
            billing_table=args.billing_table, billing_end=billing_end,
            billing_start=billing_end - timedelta(days=args.billing_days) if billing_end else None,
            forecast_run=args.forecast_run,
            training_profile=args.profile,
        )
        selector = None
        if args.use_gemini:
            from app.services.vertex_service import VertexService, VertexSettings

            selector = VertexService(VertexSettings(
                project_id=args.project, region=args.region, model=args.model,
            )).select
        result = run_workflow(request, selector=selector)
        print(json.dumps(result, indent=2, allow_nan=False))
        # A deterministic fallback is useful output, but must not mask a failed live check.
        return 2 if result["gemini"]["status"] in (
            "failed_or_rejected", "discarded_evidence_expired", "skipped_unusable_evidence",
        ) else 0
    except Exception as error:
        code = getattr(error, "code", None)
        print(json.dumps({
            "status": "workflow_failed", "error_type": type(error).__name__,
            **({"http_status": code} if type(code) is int and 400 <= code <= 599 else {}),
            **({"diagnostic": (
                "Selected model or regional endpoint is unavailable to this project. "
                "Check the model lifecycle, regional availability and project access."
            )} if code == 404 else {}),
        }))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
