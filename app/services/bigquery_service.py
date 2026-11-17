"""Batch ingestion into an existing BigQuery table; no implicit provisioning."""

import hashlib
import json
import re
from datetime import datetime
from typing import Any

from app.data.schema import METRIC_FIELDS, MetricRecord


class BigQueryService:
    """Batch loads avoid row-by-row streaming; exact batch retries are idempotent.

    Overlapping batches may repeat logical record_id values. Consumers must use
    the documented deduplication query, keeping the latest collected_at value.
    """

    def __init__(self, project: str, region: str, dataset: str, table: str, client: Any = None):
        if re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project) is None:
            raise ValueError("Invalid project identifier")
        for identifier in (dataset, table):
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", identifier) is None:
                raise ValueError("Invalid dataset or table identifier")
        from google.cloud import bigquery

        self.client = client or bigquery.Client(project=project, location=region)
        self.table_id = f"{project}.{dataset}.{table}"
        self.region = region

    def read_history(self, service: str, days: int = 7) -> list[dict]:
        """Read a bounded, filtered history from the configured deduplication view."""
        if not 1 <= days <= 30:
            raise ValueError("History lookback must be between 1 and 30 days")
        from google.cloud import bigquery

        config = bigquery.QueryJobConfig(
            maximum_bytes_billed=100_000_000,
            query_parameters=[
                bigquery.ScalarQueryParameter("service", "STRING", service),
                bigquery.ScalarQueryParameter("days", "INT64", days),
                bigquery.ScalarQueryParameter("region", "STRING", self.region),
            ],
        )
        query = f"""
            SELECT * FROM `{self.table_id}`
            WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
              AND service_name = @service AND region = @region
              AND source = 'gcp-monitoring'
            ORDER BY timestamp
        """
        job = self.client.query(query, job_config=config, location=self.region)
        return [dict(row) for row in job.result(timeout=120)]

    def read_dashboard(self, service: str, start: datetime, end: datetime) -> list[dict]:
        """Read at most 24 hours from the deduplication view with fixed limits."""
        if start.utcoffset() is None or end.utcoffset() is None:
            raise ValueError("Dashboard bounds must be timezone aware")
        if not 0 <= (end - start).total_seconds() <= 24 * 3600:
            raise ValueError("Dashboard window exceeds 24 hours")
        from google.cloud import bigquery

        config = bigquery.QueryJobConfig(
            maximum_bytes_billed=100_000_000,
            query_parameters=[
                bigquery.ScalarQueryParameter("project", "STRING", self.table_id.split('.')[0]),
                bigquery.ScalarQueryParameter("service", "STRING", service),
                bigquery.ScalarQueryParameter("region", "STRING", self.region),
                bigquery.ScalarQueryParameter("start", "TIMESTAMP", start),
                bigquery.ScalarQueryParameter("end", "TIMESTAMP", end),
            ],
        )
        query = f"""
            SELECT * FROM `{self.table_id}`
            WHERE timestamp >= @start AND timestamp <= @end
              AND project_id = @project AND region = @region AND service_name = @service
              AND source = 'gcp-monitoring'
            ORDER BY timestamp
            LIMIT 1441
        """
        job = self.client.query(query, job_config=config, location=self.region, timeout=10)
        try:
            rows = [dict(row) for row in job.result(timeout=20)]
            if len(rows) > 1440:
                raise ValueError("Dashboard view returned too many records")
            return rows
        except Exception:
            # Best effort cancellation bounds work after a client-side timeout.
            try:
                job.cancel(timeout=5)
            except Exception:
                pass
            raise

    def write(self, records: list[MetricRecord]) -> int:
        """Load validated records; return only after a successful load job."""
        if not records:
            return 0
        from google.api_core.exceptions import Conflict
        from google.cloud import bigquery

        # Fail on missing or incorrectly located storage; never auto-create it.
        table = self.client.get_table(self.table_id)
        if table.location.lower() != self.region.lower():
            raise ValueError("BigQuery table location must match the configured region")
        rows = [record.model_dump(mode="json") for record in records]
        payload = json.dumps(rows, sort_keys=True, separators=(",", ":"))
        batch_id = hashlib.sha256((self.table_id + payload).encode()).hexdigest()
        job_id = f"autocloud_metrics_{batch_id}"
        schema = [
            bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("collected_at", "TIMESTAMP", mode="REQUIRED"),
            *[bigquery.SchemaField(name, "STRING", mode="REQUIRED") for name in (
                "record_id", "project_id", "region", "service_name", "source",
            )],
            bigquery.SchemaField("interval_seconds", "INTEGER", mode="REQUIRED"),
            *[bigquery.SchemaField(name, "INTEGER" if name in (
                "request_count", "network_ingress", "network_egress",
            ) else "FLOAT") for name in METRIC_FIELDS],
            bigquery.SchemaField("missing_fields", "STRING", mode="REPEATED"),
        ]
        config = bigquery.LoadJobConfig(
            schema=schema, write_disposition="WRITE_APPEND", create_disposition="CREATE_NEVER",
        )
        try:
            job = self.client.load_table_from_json(
                rows, self.table_id, job_id=job_id, location=self.region, job_config=config,
            )
        except Conflict:
            job = self.client.get_job(job_id, location=self.region)
        job.result(timeout=120)
        return len(rows)
