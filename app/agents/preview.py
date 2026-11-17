"""Preview deterministic investigations from a local real Monitoring snapshot."""

import argparse
from datetime import datetime, timezone
from pathlib import Path

from app.agents.recommendation_agent import build_plan
from app.data.schema import MetricRecord


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/processed/metrics.ndjson"))
    parser.add_argument("--project", default="astute-sign-506809-j8")
    parser.add_argument("--region", default="asia-south1")
    parser.add_argument("--service", default="autocloud-api")
    args = parser.parse_args()
    try:
        records = [
            MetricRecord.model_validate_json(line)
            for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        plan = build_plan(
            records, project=args.project, region=args.region, service=args.service,
            now=datetime.now(timezone.utc),
        )
        print(plan.model_dump_json(indent=2))
        return 0
    except (OSError, ValueError) as error:
        # Do not echo untrusted input, credentials or cloud error bodies.
        print('{"status":"preview_failed","error_type":"' + type(error).__name__ + '"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
