"""Aggregate supported aligned samples with explicit missingness."""

import logging
from datetime import datetime

import numpy as np
import pandas as pd
from pydantic import ValidationError

from app.data.schema import METRIC_FIELDS, MetricRecord, MetricSample
from app.services.gcp_monitoring import METRICS, validate_target

logger = logging.getLogger("autocloud")


def process_samples(
    samples: list[MetricSample], project: str, region: str, service: str,
    start: datetime, end: datetime, collected_at: datetime,
) -> list[MetricRecord]:
    """Produce UTC minute-end records across revision/state/network series.

    Distribution means are weighted by actual sample count. Counters are summed.
    Instance counts are sums of per-series temporal means (may be fractional).
    No forward fill, interpolation or missing-to-zero conversion is performed.
    Error rate means observed 5xx / total requests; unclassified codes yield null.
    """
    validate_target(project, region, service)
    if start.tzinfo is None or end.tzinfo is None or collected_at.tzinfo is None:
        raise ValueError("Timestamps must be timezone-aware")
    if start >= end:
        raise ValueError("start must precede end")
    if not samples:
        return []
    frame = pd.DataFrame([sample.model_dump() for sample in samples])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame[
        (frame["timestamp"] > start) & (frame["timestamp"] <= end)
        & frame["metric"].isin(METRICS)
        & np.isfinite(frame["value"]) & (frame["value"] >= 0)
    ]
    # Remove exact duplicate series points, never distinct revisions/labels.
    frame = frame.drop_duplicates(["timestamp", "metric", "series_key"])
    records = []
    for timestamp, window in frame.groupby("timestamp", sort=True):
        values = {name: None for name in METRIC_FIELDS}
        for metric, points in window.groupby("metric"):
            if metric in ("cpu_utilization", "memory_utilization", "average_latency"):
                if metric != "average_latency":
                    points = points[points["value"] <= 1]
                if not points.empty:
                    values[metric] = float(np.average(points["value"], weights=points["weight"]))
            elif metric == "instance_count":
                values[metric] = float(points["value"].sum())
            else:
                # DELTA integer counters must not be silently truncated.
                points = points[points["value"] == np.floor(points["value"])]
                if points.empty:
                    continue
                values[metric] = int(points["value"].sum())
                if metric == "request_count" and values[metric] > 0:
                    codes = points["response_code"].astype(str)
                    if codes.str.fullmatch(r"[1-5](?:xx|[0-9]{2})").all():
                        errors = points.loc[codes.str.startswith("5"), "value"].sum()
                        values["error_rate"] = float(errors / values[metric])
        if all(value is None for value in values.values()):
            continue
        try:
            records.append(MetricRecord(
                timestamp=timestamp.to_pydatetime(), collected_at=collected_at,
                project_id=project, region=region, service_name=service, **values,
            ))
        except ValidationError:
            logger.warning("Discarded an invalid metric window")
    return records
