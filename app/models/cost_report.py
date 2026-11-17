"""Cost diagnostics, explicit usage estimates and optional read-only Billing export."""

import argparse
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from app.models.cost_analyser import DEFAULT_PRICING, CostAnalyser, ServiceUsage, load_usage


def serialize(value):
    """Preserve decimal precision and timestamps in JSON."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Unsupported output type: {type(value).__name__}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--usage", type=Path)
    source.add_argument(
        "--demo", action="store_true", help="Explicitly illustrative input, not GCP usage",
    )
    source.add_argument("--billing-table")
    parser.add_argument("--alternative", type=Path)
    parser.add_argument("--pricing", type=Path, default=DEFAULT_PRICING)
    parser.add_argument("--project", default="astute-sign-506809-j8")
    parser.add_argument("--start", type=datetime.fromisoformat)
    parser.add_argument("--end", type=datetime.fromisoformat)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        analyser = None if arguments.billing_table else CostAnalyser.from_file(arguments.pricing)
        report = {
            "estimated": None, "actual_exported": None,
            "status": "usage_or_billing_export_required",
        }
        if analyser is not None:
            report["pricing_verified_on"] = analyser.pricing.verified_on.isoformat()
            report["supported_regions"] = analyser.pricing.regions
        usage = None
        if arguments.usage:
            usage = load_usage(arguments.usage)
        elif arguments.demo:
            start = datetime(2026, 11, 15, tzinfo=timezone.utc)
            usage = ServiceUsage(
                project_id=arguments.project, region="asia-south1", service_name="synthetic-demo",
                period_start=start, period_end=start + timedelta(hours=1),
                source="synthetic_demo", billing_mode="request_based",
                active_vcpu_seconds="1000", active_gib_seconds="500", requests=1_000_000,
            )
        if usage:
            report["estimated"] = analyser.estimate(usage).model_dump(mode="json")
            report["status"] = "report_generated"
        if arguments.alternative:
            if usage is None:
                parser.error("--alternative requires --usage or --demo")
            report["comparison"] = analyser.compare(usage, load_usage(arguments.alternative))
        if arguments.billing_table:
            if not arguments.start or not arguments.end:
                parser.error("--billing-table needs --start and --end with UTC offsets")
            from app.services.billing_service import BillingExportService

            report["actual_exported"] = BillingExportService(
                arguments.project, arguments.billing_table,
            ).read(arguments.project, arguments.start, arguments.end)
            report["status"] = "report_generated"
        payload = json.dumps(report, indent=2, default=serialize, allow_nan=False)
        if arguments.output:
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(payload, encoding="utf-8")
        print(payload)
        return 0
    except Exception as error:
        message = (
            str(error) if type(error) in (ValueError, FileNotFoundError) else type(error).__name__
        )
        print(json.dumps({
            "status": "failed", "error_type": type(error).__name__, "reason": message,
        }))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
