"""Run one real Monitoring collection; persistence requires explicit flags."""

import argparse
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import load_settings
from app.data.processor import process_samples
from app.data.storage import archive_records, save_records
from app.services.gcp_monitoring import CloudMonitoringService, validate_target
from app.utils.logging import configure_logging


def collection_interval(
    now: datetime, minutes: int, lag_seconds: int = 180,
) -> tuple[datetime, datetime]:
    """Query complete UTC minutes, leaving room for Monitoring ingestion delay."""
    if now.tzinfo is None or not 1 <= minutes <= 1440 or not 120 <= lag_seconds <= 3600:
        raise ValueError("Use aware time, 1..1440 minutes and 120..3600 seconds lag")
    end = (now.astimezone(timezone.utc) - timedelta(seconds=lag_seconds)).replace(
        second=0, microsecond=0,
    )
    return end - timedelta(minutes=minutes), end


def main() -> int:
    """Collect using ADC; never interpret API errors as a successful empty run."""
    settings = load_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=settings.gcp_project_id)
    parser.add_argument("--region", default=settings.gcp_region)
    parser.add_argument("--service", default="autocloud-api")
    parser.add_argument("--minutes", type=int, default=60)
    parser.add_argument("--lag-seconds", type=int, default=180)
    parser.add_argument("--output", type=Path, default=Path("data/processed/metrics.ndjson"))
    parser.add_argument("--write-bigquery", action="store_true")
    parser.add_argument("--dataset", default="autocloud")
    parser.add_argument("--table", default="infrastructure_metrics")
    parser.add_argument(
        "--archive-bucket", help="Optional existing bucket; enables archive writes",
    )
    arguments = parser.parse_args()
    if not arguments.project:
        parser.error("--project or GCP_PROJECT_ID is required")
    configure_logging(settings.log_level)
    logger = logging.getLogger("autocloud")
    try:
        validate_target(arguments.project, arguments.region, arguments.service)
        now = datetime.now(timezone.utc)
        start, end = collection_interval(now, arguments.minutes, arguments.lag_seconds)
        samples = CloudMonitoringService().collect(
            arguments.project, arguments.region, arguments.service, start, end,
        )
        records = process_samples(
            samples, arguments.project, arguments.region, arguments.service, start, end, now,
        )
        save_records(records, arguments.output)
        written = 0
        if arguments.write_bigquery:
            from app.services.bigquery_service import BigQueryService

            written = BigQueryService(
                arguments.project, arguments.region, arguments.dataset, arguments.table,
            ).write(records)
        archive = None
        if arguments.archive_bucket:
            archive = archive_records(records, arguments.project, arguments.archive_bucket)
        print(json.dumps({
            "source": "gcp-monitoring", "start": start.isoformat(), "end": end.isoformat(),
            "samples": len(samples), "records": len(records), "bigquery_rows": written,
            "output": str(arguments.output), "archive": archive,
            "status": "collected" if records else "no_observations",
        }))
        return 0
    except Exception as error:
        # Keep credentials/API response bodies out of logs. Propagate failure
        # through the exit status; the local output remains available for retry.
        logger.error("Collection failed (%s)", type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
