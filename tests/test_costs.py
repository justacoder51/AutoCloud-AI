"""Financial math uses explicitly synthetic usage, not claimed GCP costs."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.models.cost_analyser import (
    CostAnalyser, DEFAULT_PRICING, JobUsage, Pricing, ServiceUsage,
)
from app.services.billing_service import BillingExportService

START = datetime(2026, 11, 15, tzinfo=timezone.utc)
END = START + timedelta(hours=1)
PROJECT = "astute-sign-506809-j8"


def context():
    return {
        "project_id": PROJECT, "region": "asia-south1", "service_name": "synthetic-demo",
        "period_start": START, "period_end": END, "source": "synthetic_demo",
    }


def service(**changes):
    return ServiceUsage(**{
        **context(), "billing_mode": "request_based", "active_vcpu_seconds": "1000",
        "active_gib_seconds": "500", "requests": 1_000_000, **changes,
    })


def engine():
    return CostAnalyser.from_file(as_of=date(2026, 11, 15))


def test_request_estimate_uses_decimal_units_and_does_not_claim_real_cost():
    result = engine().estimate(service())
    assert result.estimated_cost == Decimal("0.42525")
    assert result.components["requests"] == Decimal("0.40")
    assert result.status == "illustrative_estimate"
    assert result.actual_billed_cost is result.measured_savings is None


def test_idle_cost_is_separate_from_active_cost():
    result = engine().estimate(service(idle_vcpu_seconds="100", idle_gib_seconds="50"))
    assert result.estimated_cost == Decimal("0.425625")
    assert result.components["idle_cpu"] == Decimal("0.0002500")


def test_instance_based_rates_have_no_request_charge():
    result = engine().estimate(service(billing_mode="instance_based"))
    assert result.components["requests"] == 0
    assert result.estimated_cost == Decimal("0.019")
    with pytest.raises(ValidationError):
        service(billing_mode="instance_based", idle_vcpu_seconds=1)


def test_each_job_attempt_obeys_minimum_and_100ms_rounding():
    usage = JobUsage(**context(), attempts=[
        {"instance_lifetime_seconds": "10", "vcpu": 1, "memory_gib": ".5"},
        {"instance_lifetime_seconds": "61.01", "vcpu": 1, "memory_gib": ".5"},
    ])
    assert engine().estimate(usage).estimated_cost == Decimal("0.0023009")
    with pytest.raises(ValidationError):
        JobUsage(**context(), attempts=[])


@pytest.mark.parametrize("changes", [
    {"active_vcpu_seconds": -1}, {"active_gib_seconds": "NaN"},
    {"requests": -1}, {"requests": 1.5},
    {"period_end": START}, {"period_start": START.replace(tzinfo=None)},
    {"source": "verified_metering", "evidence_reference": None},
])
def test_invalid_or_unsubstantiated_usage_is_rejected(changes):
    with pytest.raises(ValidationError):
        service(**changes)


def test_metered_input_is_still_an_estimate_and_unknown_region_is_rejected():
    usage = service(source="verified_metering", evidence_reference="fixture.csv")
    result = engine().estimate(usage)
    assert result.status == "estimated_not_billed"
    with pytest.raises(ValueError):
        engine().estimate(service(region="unknown-region"))


def test_stale_or_future_pricing_is_rejected():
    pricing = Pricing.model_validate_json(DEFAULT_PRICING.read_text())
    with pytest.raises(ValueError):
        CostAnalyser(pricing, pricing.expires_on + timedelta(days=1))
    with pytest.raises(ValueError):
        CostAnalyser(pricing, pricing.verified_on - timedelta(days=1))


def test_counterfactuals_do_not_claim_savings_and_allow_negative_or_zero_base():
    before = service()
    after = service(active_vcpu_seconds=500, active_gib_seconds=250, source="user_assumptions")
    report = engine().compare(before, after)
    assert Decimal(report["estimated_savings"]) == Decimal("0.012625")
    assert report["measured_savings"] is None
    expensive = engine().compare(before, service(active_vcpu_seconds=2000))
    assert Decimal(expensive["estimated_savings"]) < 0
    zero = service(active_vcpu_seconds=0, active_gib_seconds=0, requests=0)
    assert engine().compare(zero, zero)["savings_percentage"] is None
    with pytest.raises(ValueError):
        engine().compare(before, service(period_end=END + timedelta(hours=1)))


def billing_client(rows):
    client = Mock()
    client.get_table.return_value = SimpleNamespace(
        location="US", schema=[SimpleNamespace(name=name) for name in (
            "project", "service", "usage_start_time", "cost", "credits", "currency", "cost_type",
        )],
    )
    client.query.return_value.result.return_value = rows
    return client


def test_billing_export_keeps_credits_currency_and_project_scope():
    rows = [{"currency": "INR", "gross_cost": Decimal(100), "credits": Decimal(-10),
             "net_cost": Decimal(90), "service": "Cloud Run", "cost_type": "regular"}]
    client = billing_client(rows)
    reader = BillingExportService(PROJECT, f"{PROJECT}.billing.gcp_billing_export_v1_TEST", client)
    result = reader.read(PROJECT, START, END)
    assert result["rows"][0]["currency"] == "INR"
    assert result["rows"][0]["credits"] == -10
    assert result["status"] == "exported_usage_costs"
    query = client.query.call_args.args[0]
    assert "UNNEST(credits)" in query
    assert "project.id = @project" in query
    assert "gross_cost + credits" in query
    assert client.query.call_args.kwargs["location"] == "US"
    config = client.query.call_args.kwargs["job_config"]
    assert config.maximum_bytes_billed == 100_000_000


def test_empty_billing_is_unknown_not_a_zero_invoice():
    client = billing_client([])
    reader = BillingExportService(PROJECT, f"{PROJECT}.billing.export", client)
    result = reader.read(PROJECT, START, END)
    assert result["status"] == "no_exported_rows"
    assert result["rows"] == []


def test_invalid_billing_table_or_scope_is_rejected():
    with pytest.raises(ValueError):
        BillingExportService(PROJECT, 'project.dataset.table` WHERE TRUE', Mock())
    client = billing_client([])
    reader = BillingExportService(PROJECT, f"{PROJECT}.billing.export", client)
    with pytest.raises(ValueError):
        reader.read(PROJECT, START, START + timedelta(days=32))
    client.query.assert_not_called()


def test_cost_cli_without_usage_keeps_cost_unknown(monkeypatch, capsys):
    from app.models import cost_report

    monkeypatch.setattr("sys.argv", ["cost_report"])
    assert cost_report.main() == 0
    import json

    result = json.loads(capsys.readouterr().out)
    assert result["estimated"] is result["actual_exported"] is None
    assert result["status"] == "usage_or_billing_export_required"


def test_cost_cli_demo_is_explicitly_illustrative(monkeypatch, capsys):
    from app.models import cost_report
    import json

    monkeypatch.setattr("sys.argv", ["cost_report", "--demo"])
    assert cost_report.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["estimated"]["status"] == "illustrative_estimate"
    assert result["estimated"]["input_source"] == "synthetic_demo"
    assert result["actual_exported"] is None


def test_actual_export_read_does_not_depend_on_pricing(monkeypatch, capsys):
    from app.models import cost_report
    import json

    monkeypatch.setattr("sys.argv", [
        "cost_report", "--billing-table", f"{PROJECT}.billing.export",
        "--start", START.isoformat(), "--end", END.isoformat(),
    ])
    reader = Mock()
    reader.read.return_value = {"status": "no_exported_rows", "rows": []}
    monkeypatch.setattr(
        "app.services.billing_service.BillingExportService", Mock(return_value=reader),
    )
    monkeypatch.setattr(cost_report.CostAnalyser, "from_file", Mock(side_effect=AssertionError))
    assert cost_report.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["actual_exported"]["status"] == "no_exported_rows"
    assert result["estimated"] is None
