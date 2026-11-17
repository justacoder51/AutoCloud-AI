"""Cached project-level exported costs; no invoice, estimates or savings inferred."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from threading import Lock
from time import monotonic
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ExportedCostRow(BaseModel):
    """Keep signed amounts and export delivery metadata in their recorded currency."""

    model_config = ConfigDict(allow_inf_nan=False)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    service: Literal["Cloud Run"]
    cost_type: str = Field(min_length=1, max_length=64)
    usage_date: date
    gross_cost: Decimal
    credits: Decimal
    net_cost: Decimal
    latest_export_time: AwareDatetime
    latest_usage_start_time: AwareDatetime

    @model_validator(mode="after")
    def validate_net(self):
        with localcontext() as context:
            context.prec = 50
            if self.gross_cost + self.credits != self.net_cost:
                raise ValueError("Exported net must equal cost plus signed credits")
        return self


class BillingDashboard:
    """One cache entry per worker, including failures; never discovers export tables."""

    def __init__(self, reader=None, clock=monotonic):
        self.reader = reader
        self.clock = clock
        self.lock = Lock()
        self.cached = None

    def read(self, project: str | None, table: str | None, days: int) -> dict:
        """Read 1..31 trailing days only when requested, preserving exact decimals."""
        if not 1 <= days <= 31:
            raise ValueError("Billing lookback must be 1..31 days")
        base = {
            "status": "not_configured", "project": project, "lookback_days": days,
            "scope": "All Cloud Run resources and regions in this project; not autocloud-api alone or the final invoice",
            "rows": [], "currency_totals": [], "daily_totals": [],
            "actual_billed_cost": None, "estimated_cost": None, "measured_savings": None,
            "estimate_status": "verified_billable_usage_required", "cache_seconds": 300,
            "cache_hit": False, "fetched_at": None,
            "latest_export_time": None, "latest_usage_start_time": None,
            "note": "Export delivery and adjustments can lag usage. Missing rows/days do not imply zero cost. Dates are UTC.",
        }
        if not project or not table:
            return base
        key = (project, table, days)
        with self.lock:
            if self.cached and self.cached[0] == key and self.clock() - self.cached[1] < 300:
                return {**self.cached[2], "cache_hit": True}
            end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
            start = end - timedelta(days=days)
            result = {**base, "status": "unavailable", "source_table": table,
                      "period_start": start.isoformat(), "period_end": end.isoformat(),
                      "maximum_bytes_billed": 100_000_000}
            try:
                from app.services.billing_service import BillingExportService, validate_billing_table

                validate_billing_table(table)
                reader = self.reader or BillingExportService(project, table).read
                exported = reader(project, start, end, daily=True)
                if exported.get("project") != project or exported.get("source_table") != table:
                    raise ValueError("Billing response scope mismatch")
                rows = [ExportedCostRow.model_validate(row) for row in exported["rows"]]
                if len(rows) > 1000:
                    raise ValueError("Too many exported cost rows")
                seen = set()
                totals, daily = {}, {}
                with localcontext() as context:
                    context.prec = 50
                    for row in rows:
                        if not start.date() <= row.usage_date <= end.date():
                            raise ValueError("Billing date outside requested window")
                        identity = (row.currency, row.usage_date, row.cost_type)
                        if identity in seen:
                            raise ValueError("Duplicate billing aggregate")
                        seen.add(identity)
                        for groups, group_key in ((totals, row.currency), (daily, (row.currency, row.usage_date))):
                            summary = groups.setdefault(group_key, {
                                "currency": row.currency, "gross_cost": Decimal(0),
                                "credits": Decimal(0), "net_cost": Decimal(0),
                            })
                            for field in ("gross_cost", "credits", "net_cost"):
                                summary[field] += getattr(row, field)
                    result["currency_totals"] = [
                        {name: str(value) if isinstance(value, Decimal) else value for name, value in totals[key].items()}
                        for key in sorted(totals)
                    ]
                    result["daily_totals"] = [
                        {"usage_date": key[1].isoformat(), **{
                            name: str(value) if isinstance(value, Decimal) else value for name, value in daily[key].items()
                        }} for key in sorted(daily)
                    ]
                result.update(
                    status="exported_usage_costs" if rows else "no_exported_rows",
                    rows=[row.model_dump(mode="json") for row in rows],
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    latest_export_time=max((row.latest_export_time for row in rows), default=None),
                    latest_usage_start_time=max((row.latest_usage_start_time for row in rows), default=None),
                )
                for field in ("latest_export_time", "latest_usage_start_time"):
                    if result[field] is not None:
                        result[field] = result[field].isoformat()
            except Exception as error:
                result = {**base, "status": "unavailable", "period_start": start.isoformat(),
                          "period_end": end.isoformat(), "error_type": type(error).__name__}
            self.cached = (key, self.clock(), result)
            return result
