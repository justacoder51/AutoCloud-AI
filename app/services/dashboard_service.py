"""Read scoped dashboard evidence; cloud reads are explicit and cached."""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from time import monotonic

from app.agents.recommendation_agent import build_plan
from app.data.schema import METRIC_FIELDS, MetricRecord


class DashboardHistory:
    """Coalesce queries and cache successes or sanitized failures for 60 seconds."""

    def __init__(self, reader=None, clock=monotonic, monitoring_reader=None):
        self.reader = reader
        self.monitoring_reader = monitoring_reader
        self.clock = clock
        self.lock = Lock()
        self.cached = None
        self.cached_by_key: dict[tuple, tuple[float, dict]] = {}

    def read(
        self,
        project: str,
        region: str,
        service: str,
        hours: int,
        *,
        source: str = "bigquery",
        owner_key: str | None = None,
        bearer_token: str | None = None,
    ) -> dict:
        """Keep isolated cache entries per scope owner and source; never fall back to local files."""
        if not 1 <= hours <= 24:
            raise ValueError("Dashboard lookback must be 1..24 hours")
        cache_key = (owner_key or "__shared__", source, project, region, service, hours)
        with self.lock:
            entry = self.cached_by_key.get(cache_key)
            if entry and self.clock() - entry[0] < 60:
                return {**entry[1], "cache_hit": True}
            now = datetime.now(timezone.utc)
            end = now.replace(second=0, microsecond=0)
            start = end - timedelta(hours=hours) + timedelta(minutes=1)
            payload = {"records": [], "status": "unavailable", "cache_hit": False,
                       "window_start": start.isoformat(), "window_end": end.isoformat(),
                       "expected_minutes": hours * 60, "fetched_at": None,
                       "cache_seconds": 60, "maximum_bytes_billed": 100_000_000,
                       "query_source": source}
            try:
                if source == "monitoring":
                    from app.data.processor import process_samples
                    from app.services.gcp_monitoring import collect_monitoring_rest

                    m_reader = self.monitoring_reader or collect_monitoring_rest
                    samples = m_reader(project, region, service, start, end, bearer_token=bearer_token)
                    processed = process_samples(samples, project, region, service, start, end, now)
                    payload["records"] = [rec.model_dump(mode="json") for rec in processed]
                else:
                    if self.reader is None:
                        from app.services.bigquery_service import BigQueryService

                        reader = BigQueryService(project, region, "autocloud", "latest_metrics").read_dashboard
                    else:
                        reader = self.reader
                    payload["records"] = reader(service, start, end)
                payload["status"] = "succeeded"
                payload["fetched_at"] = datetime.now(timezone.utc).isoformat()
            except Exception as error:
                payload["error_type"] = type(error).__name__
            ts_now = self.clock()
            self.cached = ((project, region, service, hours), ts_now, payload)
            self.cached_by_key[cache_key] = (ts_now, payload)
            return payload


def experiment_status(data_root: Path, now: datetime) -> dict:
    """Expose bounded progress fields; heartbeat age is not process liveness."""
    runs = data_root / "training_runs"
    try:
        marker = json.loads((runs / "active.json").read_text(encoding="utf-8"))
        run_id = marker["run_id"]
        if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("Invalid run identifier")
        raw = json.loads((runs / run_id / "status.json").read_text(encoding="utf-8"))
        fields = (
            "run_id", "stage", "started_at", "expected_finish", "updated_at",
            "duration_minutes", "requests_upper_bound", "attempted_requests",
            "successful_requests", "completed_phases", "phase", "requests_per_minute",
            "trained", "deployment_allowed",
        )
        result = {key: raw[key] for key in fields if key in raw}
        result["training_hold_requested"] = (runs / run_id / "HOLD_TRAINING").exists()
        if (result["training_hold_requested"] and raw["stage"] == "training_not_ready"
                and raw.get("training", {}).get("result", {}).get("status") == "training_paused"):
            result["recorded_stage"] = raw["stage"]
            result["stage"] = "training_paused"
        updated = datetime.fromisoformat(raw["updated_at"])
        age = (now - updated).total_seconds()
        terminal = raw["stage"] in {"completed", "training_not_ready", "stopped", "failed"}
        result["progress_age_seconds"] = max(0, age)
        result["progress_status"] = (
            "terminal" if terminal else "may_have_stalled" if age > 180 else "recent_heartbeat"
        )
        result["note"] = "Recorded progress only; heartbeat recency does not verify worker liveness."
        return result
    except FileNotFoundError:
        return {"stage": "unavailable", "progress_status": "unknown"}
    except (OSError, ValueError, KeyError, TypeError):
        return {"stage": "unreadable", "progress_status": "unknown"}


def overview(data_root: Path, project: str | None, region: str, service: str,
             now: datetime | None = None, *, records: list[dict] | None = None,
             query: dict | None = None) -> dict:
    """Scope and deduplicate measured evidence, preserving all missing values."""
    now = now or datetime.now(timezone.utc)
    result = {
        "assessed_at": now.isoformat(), "project": project, "region": region,
        "service": service,
        "source": (query.get("query_source") or "bigquery") if query else "local_gcp_monitoring_snapshot",
        "snapshot_status": "unavailable", "records": [], "summary": None,
        "recommendation_plan": None, "experiment": experiment_status(data_root, now),
        "models": {"status": "not_loaded", "anomaly_results": None, "forecasts": None},
        "costs": {"status": "not_loaded", "actual_billed_cost": None, "estimated_cost": None},
        "actions": {"status": "not_implemented", "execution_allowed": False},
    }
    if not project:
        result["snapshot_status"] = "project_not_configured"
        return result
    if query:
        result["query"] = {key: value for key, value in query.items() if key != "records"}
        if query["status"] != "succeeded":
            result["snapshot_status"] = (
                "monitoring_unavailable" if query.get("query_source") == "monitoring" else "bigquery_unavailable"
            )
            return result
    try:
        if records is None:
            path = data_root / "processed" / "metrics.ndjson"
            if path.stat().st_size > 20_000_000:
                raise ValueError("Snapshot exceeds dashboard limit")
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                       if line.strip()]
        latest = {}
        for raw in records:
            row = MetricRecord.model_validate(raw)
            if (row.project_id, row.region, row.service_name) != (project, region, service):
                if query:
                    raise ValueError("Unexpected BigQuery target")
                continue
            if query and not (datetime.fromisoformat(query["window_start"]) <= row.timestamp
                              <= datetime.fromisoformat(query["window_end"])):
                raise ValueError("BigQuery evidence outside requested window")
            if row.timestamp > now or row.collected_at > now:
                raise ValueError("Future evidence")
            previous = latest.get(row.record_id)
            if previous and previous.collected_at == row.collected_at and previous != row:
                raise ValueError("Conflicting evidence")
            if previous is None or row.collected_at > previous.collected_at:
                latest[row.record_id] = row
        rows = sorted(latest.values(), key=lambda row: row.timestamp)
        plan = build_plan(rows, project=project, region=region, service=service, now=now)
        result["snapshot_status"] = "loaded" if rows else "empty"
        result["recommendation_plan"] = plan.model_dump(mode="json")
        result["records"] = [row.model_dump(mode="json") for row in rows]
        if rows:
            counts = [row.request_count for row in rows if row.request_count is not None]
            result["summary"] = {
                "observed_minutes": len(rows), "latest_observation": rows[-1].timestamp.isoformat(),
                "age_seconds": (now - rows[-1].timestamp).total_seconds(),
                "latest_values": {name: getattr(rows[-1], name) for name in METRIC_FIELDS},
                "observed_request_total": sum(counts) if counts else None,
                "request_minutes_with_measurements": len(counts),
                "missing_counts": {name: sum(getattr(row, name) is None for row in rows)
                                   for name in METRIC_FIELDS},
            }
        if query:
            result["coverage"] = {
                "expected_minutes": query["expected_minutes"], "observed_minutes": len(rows),
                "gap_minutes": max(0, query["expected_minutes"] - len(rows)),
                "observed_fraction": len(rows) / query["expected_minutes"],
                "note": "Observation coverage is not ML training readiness.",
            }
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError):
        result["snapshot_status"] = "invalid_snapshot"
    return result
