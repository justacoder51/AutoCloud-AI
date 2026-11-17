"""Read supported Cloud Run metrics without fabricating absent series."""

import json
import logging
import re
from datetime import datetime
from typing import Any

import httpx
from pydantic import ValidationError

from app.data.schema import MetricSample

logger = logging.getLogger("autocloud")

# Metric descriptors checked against Google's Cloud Run metric catalogue.
# Distribution points use ALIGN_SUM to preserve count/mean weighting, rather
# than applying numeric-only ALIGN_MEAN to distribution-valued metrics.
METRICS = {
    "cpu_utilization": ("container/cpu/utilizations", "distribution"),
    "memory_utilization": ("container/memory/utilizations", "distribution"),
    "request_count": ("request_count", "counter"),
    "network_ingress": ("container/network/received_bytes_count", "counter"),
    "network_egress": ("container/network/sent_bytes_count", "counter"),
    "average_latency": ("request_latencies", "distribution"),
    "instance_count": ("container/instance_count", "gauge"),
}


def validate_target(project: str, region: str, service: str) -> None:
    """Prevent interpolation of untrusted Monitoring filter expressions."""
    patterns = (
        (project, r"[a-z][a-z0-9-]{4,28}[a-z0-9]"),
        (region, r"[a-z]+-[a-z]+[0-9]+"),
        (service, r"[a-z][a-z0-9-]{0,48}[a-z0-9]|[a-z]"),
    )
    if any(re.fullmatch(pattern, value) is None for value, pattern in patterns):
        raise ValueError("Invalid project, region or service identifier")


def make_request(
    project: str, region: str, service: str, metric: str,
    start: datetime, end: datetime,
) -> dict[str, Any]:
    """Build a paginated FULL-view Monitoring request for one service."""
    validate_target(project, region, service)
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("A nonempty timezone-aware interval is required")
    suffix, kind = METRICS[metric]
    return {
        "name": f"projects/{project}",
        "filter": (
            f'metric.type="run.googleapis.com/{suffix}" '
            'AND resource.type="cloud_run_revision" '
            f'AND resource.labels.service_name="{service}" '
            f'AND resource.labels.location="{region}"'
        ),
        "interval": {"start_time": start, "end_time": end},
        "aggregation": {
            "alignment_period": {"seconds": 60},
            "per_series_aligner": "ALIGN_MEAN" if kind == "gauge" else "ALIGN_SUM",
        },
        "view": "FULL",
    }


def decode_series(metric: str, series: Any) -> list[MetricSample]:
    """Convert numeric values or distribution means; drop invalid points."""
    _, kind = METRICS[metric]
    labels = dict(series.metric.labels)
    series_key = json.dumps({
        "metric": metric, "labels": labels,
        "resource": dict(series.resource.labels),
    }, sort_keys=True)
    samples = []
    for point in series.points:
        if kind == "distribution":
            distribution = point.value.distribution_value
            if distribution.count <= 0:
                continue
            value, weight = distribution.mean, distribution.count
        else:
            # Proto-plus's protobuf oneof distinguishes integer zero from an
            # unset double field. The request's aligner determines the type.
            value = point.value.double_value if kind == "gauge" else point.value.int64_value
            weight = 1
        try:
            samples.append(MetricSample(
                timestamp=point.interval.end_time,
                metric=metric, value=value, weight=weight, series_key=series_key,
                response_code=labels.get("response_code_class") or labels.get("response_code", ""),
            ))
        except ValidationError:
            logger.warning("Discarded an invalid Monitoring point")
    return samples


class CloudMonitoringService:
    """A read-only adapter; callers can inject a client for offline tests."""

    def __init__(self, client: Any = None):
        if client is None:
            from google.cloud import monitoring_v3

            client = monitoring_v3.MetricServiceClient()
        self.client = client

    def collect(
        self, project: str, region: str, service: str,
        start: datetime, end: datetime,
    ) -> list[MetricSample]:
        """Collect all seven metrics, consuming all pages returned by the SDK.

        An empty series is valid. Permission, network and API errors propagate:
        they must never be disguised as an empty successful observation.
        """
        samples = []
        for metric in METRICS:
            request = make_request(project, region, service, metric, start, end)
            for series in self.client.list_time_series(request=request, timeout=30):
                samples.extend(decode_series(metric, series))
        return samples


def collect_monitoring_rest(
    project: str,
    region: str,
    service: str,
    start: datetime,
    end: datetime,
    *,
    bearer_token: str | None = None,
) -> list[MetricSample]:
    """Read Cloud Run metrics via Monitoring v3 REST JSON using server ADC or user OAuth token."""
    validate_target(project, region, service)
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("A nonempty timezone-aware interval is required")
    token = bearer_token
    if not token:
        import google.auth
        from google.auth.transport.requests import Request as AuthRequest

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(AuthRequest())
        token = creds.token
    url = f"https://monitoring.googleapis.com/v3/projects/{project}/timeSeries"
    headers = {"Authorization": f"Bearer {token}"}
    samples: list[MetricSample] = []
    with httpx.Client(timeout=20.0, trust_env=False) as client:
        for metric, (suffix, kind) in METRICS.items():
            page_token: str | None = None
            for _ in range(10):
                params: dict[str, Any] = {
                    "filter": (
                        f'metric.type="run.googleapis.com/{suffix}" '
                        'AND resource.type="cloud_run_revision" '
                        f'AND resource.labels.service_name="{service}" '
                        f'AND resource.labels.location="{region}"'
                    ),
                    "interval.startTime": start.isoformat(),
                    "interval.endTime": end.isoformat(),
                    "aggregation.alignmentPeriod": "60s",
                    "aggregation.perSeriesAligner": "ALIGN_MEAN" if kind == "gauge" else "ALIGN_SUM",
                    "view": "FULL",
                }
                if page_token:
                    params["pageToken"] = page_token
                resp = client.get(url, params=params, headers=headers)
                resp.raise_for_status()
                body = resp.json()
                for series in body.get("timeSeries", []):
                    labels = dict(series.get("metric", {}).get("labels", {}))
                    resource_labels = dict(series.get("resource", {}).get("labels", {}))
                    series_key = json.dumps(
                        {"metric": metric, "labels": labels, "resource": resource_labels},
                        sort_keys=True,
                    )
                    for point in series.get("points", []):
                        val_obj = point.get("value", {})
                        if kind == "distribution":
                            dist = val_obj.get("distributionValue") or {}
                            count = int(dist.get("count", 0))
                            if count <= 0:
                                continue
                            value = float(dist.get("mean", 0.0))
                            weight = count
                        elif kind == "gauge":
                            if "doubleValue" not in val_obj:
                                continue
                            value = float(val_obj["doubleValue"])
                            weight = 1
                        else:
                            if "int64Value" not in val_obj:
                                continue
                            value = int(val_obj["int64Value"])
                            weight = 1
                        ts = point.get("interval", {}).get("endTime")
                        if not ts:
                            continue
                        try:
                            samples.append(MetricSample(
                                timestamp=ts,
                                metric=metric,
                                value=value,
                                weight=weight,
                                series_key=series_key,
                                response_code=labels.get("response_code_class") or labels.get("response_code", ""),
                            ))
                        except ValidationError:
                            logger.warning("Discarded an invalid Monitoring REST point")
                page_token = body.get("nextPageToken")
                if not page_token:
                    break
    return samples
