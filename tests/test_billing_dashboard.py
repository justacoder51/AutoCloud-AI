"""Billing dashboard contracts using mocked exports, not actual financial results."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.billing_dashboard import BillingDashboard
from app.services.billing_service import BillingExportService

PROJECT = "test-project"
TABLE = PROJECT + ".billing.export"


def export_reader(rows):
    def read(project, start, end, **kwargs):
        return {"project": project, "source_table": TABLE, "rows": [
            {"currency": "INR", "service": "Cloud Run", "cost_type": "regular",
             "usage_date": start.date(), "latest_export_time": end,
             "latest_usage_start_time": start, **row} for row in rows
        ]}
    return Mock(side_effect=read)


def test_totals_preserve_currency_signed_credits_and_small_exact_values():
    reader = export_reader([
        {"gross_cost": Decimal("100.000000001"), "credits": Decimal("-10"), "net_cost": Decimal("90.000000001")},
        {"currency": "USD", "gross_cost": Decimal(".000000002"), "credits": Decimal("0"), "net_cost": Decimal(".000000002")},
        {"cost_type": "adjustment", "gross_cost": Decimal("-2"), "credits": Decimal("1"), "net_cost": Decimal("-1")},
    ])
    result = BillingDashboard(reader).read(PROJECT, TABLE, 1)
    assert result["status"] == "exported_usage_costs"
    totals = {row["currency"]: row for row in result["currency_totals"]}
    assert Decimal(totals["INR"]["net_cost"]) == Decimal("89.000000001")
    assert Decimal(totals["INR"]["credits"]) == -9
    assert Decimal(totals["USD"]["net_cost"]) == Decimal(".000000002")
    assert len(result["daily_totals"]) == 2
    assert result["actual_billed_cost"] is result["estimated_cost"] is result["measured_savings"] is None


def test_no_rows_is_unknown_but_real_exported_zero_is_allowed():
    result = BillingDashboard(export_reader([])).read(PROJECT, TABLE, 1)
    assert result["status"] == "no_exported_rows"
    assert result["currency_totals"] == []
    assert result["actual_billed_cost"] is None
    result = BillingDashboard(export_reader([{"gross_cost": 1, "credits": -1, "net_cost": 0}])).read(PROJECT, TABLE, 1)
    assert result["status"] == "exported_usage_costs"
    assert result["currency_totals"][0]["net_cost"] == "0"


def test_billing_requests_and_failures_are_cached_without_revealing_errors():
    clock = [0.0]
    reader = export_reader([])
    panel = BillingDashboard(reader, clock=lambda: clock[0])
    first = panel.read(PROJECT, TABLE, 1)
    cached = panel.read(PROJECT, TABLE, 1)
    assert cached["cache_hit"] and cached["period_end"] == first["period_end"]
    reader.assert_called_once()
    clock[0] = 301
    panel.read(PROJECT, TABLE, 1)
    assert reader.call_count == 2
    failure = Mock(side_effect=RuntimeError("secret-credential-detail"))
    panel = BillingDashboard(failure)
    result = panel.read(PROJECT, TABLE, 1)
    assert result["status"] == "unavailable"
    assert "secret-credential-detail" not in str(result)
    assert panel.read(PROJECT, TABLE, 1)["cache_hit"]
    failure.assert_called_once()


@pytest.mark.parametrize("row", [
    {"gross_cost": "NaN", "credits": 0, "net_cost": 0},
    {"gross_cost": 1, "credits": -1, "net_cost": 3},
    {"gross_cost": 1, "credits": 0, "net_cost": 1, "currency": "INR+USD"},
    {"gross_cost": 1, "credits": 0, "net_cost": 1, "service": "BigQuery"},
])
def test_invalid_financial_rows_fail_closed(row):
    result = BillingDashboard(export_reader([row])).read(PROJECT, TABLE, 1)
    assert result["status"] == "unavailable"
    assert result["rows"] == result["currency_totals"] == []


def test_duplicate_daily_cost_types_and_wrong_project_are_rejected():
    row = {"gross_cost": 1, "credits": 0, "net_cost": 1}
    assert BillingDashboard(export_reader([row, row])).read(PROJECT, TABLE, 1)["status"] == "unavailable"
    reader = Mock(return_value={"project": "wrong-project", "source_table": TABLE, "rows": []})
    assert BillingDashboard(reader).read(PROJECT, TABLE, 1)["status"] == "unavailable"


def test_api_requires_config_and_bounds_days_without_browser_table_override():
    application = create_app(Settings(environment="test", gcp_project_id=PROJECT))
    with TestClient(application) as client:
        assert client.get('/api/costs').json()["status"] == "not_configured"
        assert client.get('/api/costs?days=32').status_code == 422
        assert client.get('/api/costs?days=0').status_code == 422
        assert client.post('/api/costs').status_code == 405
    application = create_app(Settings(environment="test", gcp_project_id=PROJECT, dashboard_billing_table=TABLE))
    reader = export_reader([])
    application.state.dashboard_billing = BillingDashboard(reader)
    with TestClient(application) as client:
        assert client.get('/api/costs?days=7&table=ignored.billing.table').json()["status"] == "no_exported_rows"
        assert reader.call_args.args[0] == PROJECT
        assert reader.call_args.kwargs == {"daily": True}


def test_daily_export_query_preserves_bounds_budgets_credits_and_delivery_metadata():
    client = Mock()
    client.get_table.return_value = SimpleNamespace(location="asia-south1", schema=[SimpleNamespace(name=name) for name in (
        "project", "service", "usage_start_time", "cost", "credits", "currency", "cost_type", "export_time",
    )])
    client.query.return_value.result.return_value = []
    end = datetime.now(timezone.utc)
    BillingExportService(PROJECT, TABLE, client).read(PROJECT, end - timedelta(days=1), end, daily=True)
    sql = client.query.call_args.args[0]
    config = client.query.call_args.kwargs["job_config"]
    assert "DATE(usage_start_time, 'UTC')" in sql
    assert "MAX(export_time)" in sql and "UNNEST(credits)" in sql
    assert "GROUP BY currency, service, cost_type , usage_date" in sql
    assert "usage_start_time < @end" in sql
    assert "LIMIT 1001" in sql
    assert config.maximum_bytes_billed == 100_000_000
    client.query.return_value.result.assert_called_once_with(timeout=20)


@pytest.mark.parametrize("with_rows", [False, True])
def test_streamlit_only_reads_billing_after_explicit_submit(tmp_path, monkeypatch, with_rows):
    """Mocked billing UI test; no actual charges or cloud requests are involved."""
    from pathlib import Path
    import httpx
    from app.services.dashboard_service import overview

    AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
    payload = overview(tmp_path, PROJECT, "asia-south1", "autocloud-api", records=[])
    payload["source"] = "bigquery"
    fixture_rows = [{"gross_cost": "1.01", "credits": "-0.01", "net_cost": "1.00"}] if with_rows else []
    billing = BillingDashboard(export_reader(fixture_rows)).read(PROJECT, TABLE, 1)
    billing_calls = []

    def get(url, **kwargs):
        response = Mock()
        if url.endswith('/api/costs'):
            billing_calls.append(kwargs)
            response.json.return_value = billing
        else:
            response.json.return_value = payload
        return response

    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.get.side_effect = get
    monkeypatch.setattr(httpx, "Client", Mock(return_value=client))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app/dashboard/home.py')).run(timeout=30)
    assert not app.exception
    assert billing_calls == []
    next(button for button in app.button if button.label == 'Read billing export').click().run(timeout=30)
    assert not app.exception
    assert len(billing_calls) == 1
    if with_rows:
        assert any(item.label == 'Exported net cost' and item.value == '1.00' for item in app.metric)
    else:
        assert any('Cost is unknown, not zero' in item.value for item in app.warning)
