"""Read-only project-level Cloud Run costs from a supplied Billing export."""

import re
from datetime import datetime, timedelta
from typing import Any


def validate_billing_table(table_id: str) -> None:
    """Validate identifiers before client construction or SQL interpolation."""
    identifier = r"[A-Za-z_][A-Za-z0-9_]{0,1023}"
    project = r"[a-z][a-z0-9-]{4,28}[a-z0-9]"
    if re.fullmatch(f"{project}\\.{identifier}\\.{identifier}", table_id) is None:
        raise ValueError("Use a fully qualified project.dataset.billing_table identifier")


class BillingExportService:
    """No automatic Billing-export discovery, configuration or currency conversion."""

    def __init__(self, query_project: str, table_id: str, client: Any = None):
        validate_billing_table(table_id)
        from google.cloud import bigquery

        self.client = client or bigquery.Client(project=query_project)
        self.table_id = table_id

    def read(self, project: str, start: datetime, end: datetime, *, daily: bool = False) -> dict:
        """Include signed credits; separate currencies and cost types, never fake zero bills."""
        if start.tzinfo is None or end.tzinfo is None or not start < end:
            raise ValueError("Billing window needs ordered timezone-aware timestamps")
        if end - start > timedelta(days=31):
            raise ValueError("Billing window must not exceed 31 days")
        from google.cloud import bigquery

        table = self.client.get_table(self.table_id, timeout=10)
        required = {
            "project", "service", "usage_start_time", "cost", "credits", "currency", "cost_type",
        }
        if daily:
            required.add("export_time")
        if not required.issubset({field.name for field in table.schema}):
            raise ValueError("Table lacks the documented standard Billing export fields")
        day_input = "DATE(usage_start_time, 'UTC') AS usage_date, export_time, usage_start_time," if daily else ""
        day_select = "usage_date," if daily else ""
        delivery_select = "MAX(export_time) AS latest_export_time, MAX(usage_start_time) AS latest_usage_start_time," if daily else ""
        day_group = ", usage_date" if daily else ""
        row_limit = "LIMIT 1001" if daily else ""
        query = f"""
            WITH usage AS (
                SELECT {day_input} currency, service.description AS service, cost_type,
                       CAST(cost AS NUMERIC) AS gross_cost,
                       IFNULL((SELECT SUM(CAST(c.amount AS NUMERIC))
                               FROM UNNEST(credits) AS c), 0) AS credits
                FROM `{self.table_id}`
                WHERE usage_start_time >= @start AND usage_start_time < @end
                  AND project.id = @project AND service.description = @service
            )
            SELECT {day_select} {delivery_select} currency, service, cost_type, SUM(gross_cost) AS gross_cost,
                   SUM(credits) AS credits, SUM(gross_cost + credits) AS net_cost
            FROM usage GROUP BY currency, service, cost_type {day_group}
            ORDER BY currency, cost_type {day_group}
            {row_limit}
        """
        config = bigquery.QueryJobConfig(
            maximum_bytes_billed=100_000_000,
            query_parameters=[
                bigquery.ScalarQueryParameter("start", "TIMESTAMP", start),
                bigquery.ScalarQueryParameter("end", "TIMESTAMP", end),
                bigquery.ScalarQueryParameter("project", "STRING", project),
                bigquery.ScalarQueryParameter("service", "STRING", "Cloud Run"),
            ],
        )
        job = self.client.query(query, job_config=config, location=table.location, timeout=10)
        try:
            rows = [dict(row) for row in job.result(timeout=20 if daily else 120)]
            if daily and len(rows) > 1000:
                raise ValueError("Dashboard billing result exceeds row limit")
        except Exception:
            try:
                job.cancel(timeout=5)
            except Exception:
                pass
            raise
        return {
            "status": "exported_usage_costs" if rows else "no_exported_rows",
            "scope": (
                "All Cloud Run resources in the project; not a single service or final invoice"
            ),
            "project": project, "source_table": self.table_id,
            "period_start": start.isoformat(), "period_end": end.isoformat(),
            "rows": rows, "note": "Export delivery and adjustments may lag usage",
        }
