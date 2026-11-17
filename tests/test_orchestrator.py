"""Real LangGraph execution with synthetic fixtures and offline model clients."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import httpx
from google import genai
from google.oauth2.credentials import Credentials
from google.genai import errors, types
from pydantic import ValidationError

from app.agents.orchestrator import WorkflowRequest, run_workflow
from app.data.schema import MetricRecord
from app.models.cost_analyser import ServiceUsage
from app.services.vertex_service import VertexService, VertexSettings

NOW = datetime(2026, 11, 15, 15, tzinfo=timezone.utc)
PROJECT = "fixture-project"


def request(pressure=True, **changes):
    rows = tuple(MetricRecord(
        timestamp=NOW - timedelta(minutes=minute), collected_at=NOW,
        project_id=PROJECT, region="asia-south1", service_name="fixture-service",
        cpu_utilization=.95 if pressure else .1, memory_utilization=.96 if pressure else .2,
        error_rate=0, request_count=10,
    ) for minute in (5, 4, 3))
    return WorkflowRequest(**{
        "project": PROJECT, "service": "fixture-service", "records": rows, **changes,
    })


def run(req, selector=None, clock=None):
    return run_workflow(req, selector=selector, clock=clock or (lambda: NOW))


def response(order=None, **changes):
    return {"summary_code": "investigate_observed_pressure", "ordered_actions": (
        order if order is not None else ["investigate_memory", "review_capacity"]
    ), **changes}


def test_actual_graph_default_is_offline_and_does_not_evaluate_untrained_models():
    selector = Mock(side_effect=AssertionError("Must not call Gemini"))
    result = run(request(), selector)
    selector.assert_not_called()
    assert result["gemini"]["status"] == "disabled"
    assert result["workflow_status"] == "awaiting_human_review"
    assert result["model_analysis"]["status"] == "not_evaluated"
    assert result["model_analysis"]["readiness"]["ready"] is False
    assert result["model_analysis"]["forecasts"] is None
    assert result["cost_analysis"]["estimate"] is None
    assert result["execution_allowed"] is False
    assert all(item["execution_allowed"] is False for item in result["recommendations"])
    json.dumps(result, allow_nan=False)


def test_one_opt_in_gemini_call_can_prioritise_but_cannot_replace_facts():
    selector = Mock(return_value=response())
    result = run(request(use_gemini=True), selector)
    selector.assert_called_once()
    assert result["gemini"]["status"] == "succeeded"
    assert [item["action"] for item in result["recommendations"]] == [
        "investigate_memory", "review_capacity",
    ]
    assert result["recommendations"][0]["evidence"]["values"] == [.96] * 3
    assert result["recommendations"][0]["explanation_source"] == "validated_template"


@pytest.mark.parametrize("payload", [
    response(["review_capacity"]), response(["review_capacity"] * 2),
    response(["scale_to_999"]), response(summary_code="no_supported_action"),
    response(confidence=.99), {"raw_shell": "delete everything"},
])
def test_invalid_gemini_output_falls_back_without_suppressing_supported_pressure(payload):
    result = run(request(use_gemini=True), Mock(return_value=payload))
    assert result["gemini"]["status"] == "failed_or_rejected"
    assert len(result["recommendations"]) == 2
    assert result["execution_allowed"] is False


def test_provider_error_is_sanitised_and_has_no_retry_loop():
    selector = Mock(side_effect=RuntimeError("secret-provider-body"))
    result = run(request(use_gemini=True), selector)
    assert result["gemini"] == {"status": "failed_or_rejected", "error_type": "RuntimeError"}
    selector.assert_called_once()
    assert "secret-provider-body" not in json.dumps(result)


def test_provider_http_status_is_preserved_without_exposing_response_body():
    selector = Mock(side_effect=errors.ClientError(403, {
        "error": {"message": "private-provider-details"},
    }))
    result = run(request(use_gemini=True), selector)
    assert result["gemini"]["http_status"] == 403
    assert "private-provider-details" not in json.dumps(result)


def test_stale_evidence_skips_model_call_and_blocked_report_retains_readiness_diagnostic():
    selector = Mock()
    result = run(request(use_gemini=True), selector, lambda: NOW + timedelta(hours=1))
    selector.assert_not_called()
    assert result["workflow_status"] == "blocked_evidence"
    assert result["gemini"]["status"] == "skipped_unusable_evidence"
    assert not result["recommendations"]


def test_evidence_expiring_during_call_discards_model_selection():
    ticks = iter([NOW, NOW + timedelta(hours=1)])
    result = run(request(use_gemini=True), Mock(return_value=response()), lambda: next(ticks))
    assert result["gemini"]["status"] == "discarded_evidence_expired"
    assert result["workflow_status"] == "blocked_evidence"
    assert not result["recommendations"]


def test_no_breach_still_allows_a_live_structured_smoke_check_without_fabricated_actions():
    selector = Mock(return_value={"summary_code": "no_supported_action", "ordered_actions": []})
    result = run(request(pressure=False, use_gemini=True), selector)
    assert result["gemini"]["status"] == "succeeded"
    assert result["workflow_status"] == "no_supported_action"
    assert not result["recommendations"]


def test_empty_history_is_blocked_without_a_fake_zero_cost_or_healthy_result():
    result = run(request(records=()))
    assert result["data_status"] == "insufficient"
    assert result["model_analysis"]["readiness"]["ready"] is False
    assert result["cost_analysis"]["estimate"] is None


def usage(**changes):
    return ServiceUsage(**{
        "project_id": PROJECT, "region": "asia-south1", "service_name": "fixture-service",
        "period_start": NOW - timedelta(hours=1), "period_end": NOW,
        "source": "user_assumptions", "billing_mode": "request_based",
        "active_vcpu_seconds": "1000", "active_gib_seconds": "500", "requests": 600,
        **changes,
    })


def test_explicit_cost_inputs_reuse_the_decimal_engine_and_preserve_provenance():
    result = run(request(usage=usage()))
    cost = result["cost_analysis"]
    assert cost["status"] == "estimated_not_billed"
    assert cost["estimate"]["input_source"] == "user_assumptions"
    assert cost["actual_exported"] is cost["measured_savings"] is None
    assert all(item["estimated_financial_impact"] is None for item in result["recommendations"])


def test_wrong_scope_synthetic_usage_and_out_of_bounds_constraints_are_rejected():
    for cost in (usage(project_id="other-project"), usage(source="synthetic_demo")):
        with pytest.raises(ValidationError):
            request(usage=cost)
    for changes in ({"max_instances": 3}, {"min_instances": 2, "max_instances": 1}):
        with pytest.raises(ValidationError):
            request(**changes)


def test_future_usage_cannot_trigger_a_model_call():
    selector = Mock()
    with pytest.raises(ValueError, match="future"):
        run(request(use_gemini=True, usage=usage(period_end=NOW + timedelta(hours=1))), selector)
    selector.assert_not_called()


def sdk_response(text=None, reason="STOP"):
    return SimpleNamespace(
        text=text or json.dumps(response()), candidates=[SimpleNamespace(finish_reason=reason)],
    )


def test_vertex_request_uses_real_sdk_types_structured_output_and_no_tools():
    client = Mock()
    client.models.generate_content.return_value = sdk_response()
    adapter = VertexService(VertexSettings(project_id=PROJECT), client=client)
    assert adapter.select({"data_status": "fresh"}) == response()
    args = client.models.generate_content.call_args.kwargs
    config = args["config"]
    assert isinstance(config, types.GenerateContentConfig)
    assert config.response_mime_type == "application/json"
    assert config.max_output_tokens == 256
    assert config.tools is None
    assert config.automatic_function_calling.disable is True
    assert config.thinking_config.thinking_level == types.ThinkingLevel.MINIMAL
    assert config.thinking_config.thinking_budget is None
    assert config.temperature is None
    client.close.assert_not_called()


def test_vertex_constructs_adc_client_with_regional_endpoint_timeout_and_one_attempt():
    client = Mock()
    client.models.generate_content.return_value = sdk_response()
    with patch("google.genai.Client", return_value=client) as constructor:
        VertexService(VertexSettings(project_id=PROJECT)).select({})
    args = constructor.call_args.kwargs
    assert args["vertexai"] is True
    assert args["location"] == "asia-south1"
    assert args["http_options"].timeout == 30000
    assert args["http_options"].retry_options.attempts == 1
    client.close.assert_called_once()


@pytest.mark.parametrize("text,reason", [
    ("bad json", "STOP"), ("[]", "STOP"), ("{}", "MAX_TOKENS"),
    ("{}", "SAFETY"), ("x" * 8001, "STOP"),
])
def test_vertex_rejects_invalid_incomplete_blocked_and_oversize_responses(text, reason):
    client = Mock()
    client.models.generate_content.return_value = sdk_response(text, reason)
    with pytest.raises(ValueError):
        VertexService(VertexSettings(project_id=PROJECT), client).select({})


def test_payload_is_bounded_before_call_and_global_fallback_is_disallowed():
    client = Mock()
    with pytest.raises(ValueError, match="payload"):
        VertexService(VertexSettings(project_id=PROJECT), client).select({"x": "a" * 32001})
    client.models.generate_content.assert_not_called()
    with pytest.raises(ValidationError):
        VertexSettings(project_id=PROJECT, region="global")


def test_real_sdk_serializes_to_regional_vertex_http_without_network():
    captured = []

    def handle(http_request):
        captured.append(http_request)
        return httpx.Response(200, json={"candidates": [{
            "content": {"role": "model", "parts": [{"text": json.dumps(response())}]},
            "finishReason": "STOP",
        }]})

    with genai.Client(
        vertexai=True, project=PROJECT, location="asia-south1",
        credentials=Credentials(token="offline-test-fixture"),
        http_options=types.HttpOptions(
            api_version="v1", retry_options=types.HttpRetryOptions(attempts=1),
            client_args={"transport": httpx.MockTransport(handle), "trust_env": False},
            async_client_args={"transport": httpx.MockTransport(handle), "trust_env": False},
        ),
    ) as client:
        assert VertexService(VertexSettings(project_id=PROJECT), client).select({}) == response()
    assert len(captured) == 1
    assert captured[0].url.host == "asia-south1-aiplatform.googleapis.com"
    payload = json.loads(captured[0].content)
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    # The pinned SDK serializes nested ThinkingConfig using protobuf field names.
    assert payload["generationConfig"]["thinkingConfig"]["thinking_level"] == "MINIMAL"
    assert "thinking_budget" not in payload["generationConfig"]["thinkingConfig"]
    assert "temperature" not in payload["generationConfig"]
    assert "/models/gemini-3.5-flash-lite:" in captured[0].url.path
    assert "tools" not in payload


def test_cli_reports_failed_live_check_with_nonzero_exit_and_useful_fallback(monkeypatch, capsys):
    from app.agents import run as cli

    monkeypatch.setattr("sys.argv", ["run", "--from-bigquery", "--use-gemini"])
    monkeypatch.setattr(
        "app.services.bigquery_service.BigQueryService.read_history", lambda *args: [],
    )
    monkeypatch.setattr(cli, "run_workflow", lambda *args, **kwargs: {
        "gemini": {"status": "failed_or_rejected"}, "recommendations": [],
    })
    # Constructor normally opens an ADC client. Stub storage construction as well as its read.
    monkeypatch.setattr("app.services.bigquery_service.BigQueryService.__init__", lambda *args: None)
    assert cli.main() == 2
    assert json.loads(capsys.readouterr().out)["gemini"]["status"] == "failed_or_rejected"


def test_vertex_connectivity_probe_needs_no_metrics_and_never_claims_analysis(monkeypatch, capsys):
    from app.agents import run as cli

    monkeypatch.setattr("sys.argv", ["run", "--check-vertex"])
    selector = Mock(return_value={
        "summary_code": "insufficient_recent_evidence", "ordered_actions": [],
    })
    monkeypatch.setattr("app.services.vertex_service.VertexService.select", selector)
    monkeypatch.setattr(cli, "run_workflow", Mock(side_effect=AssertionError("No workflow probe")))
    assert cli.main() == 0
    selector.assert_called_once()
    assert selector.call_args.args[0]["data_status"] == "insufficient"
    result = json.loads(capsys.readouterr().out)
    assert result["gemini_status"] == "succeeded"
    assert result["mode"] == "vertex_connectivity_probe"
    assert not result["recommendations"]
    assert result["execution_allowed"] is False


def test_retired_or_unverified_model_profiles_are_rejected_before_a_request():
    assert VertexSettings(project_id=PROJECT).model == "gemini-3.5-flash-lite"
    for model in ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-unverified-model"):
        with pytest.raises(ValidationError):
            VertexSettings(project_id=PROJECT, model=model)


def test_cli_404_diagnostic_does_not_echo_provider_details(monkeypatch, capsys):
    from app.agents import run as cli

    monkeypatch.setattr("sys.argv", ["run", "--check-vertex", "--model=gemini-3.5-flash-lite"])
    monkeypatch.setattr("app.services.vertex_service.VertexService.select", Mock(
        side_effect=errors.ClientError(404, {"error": {"message": "private details"}}),
    ))
    assert cli.main() == 1
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["http_status"] == 404
    assert "regional endpoint" in result["diagnostic"]
    assert "private details" not in output


def test_graph_reads_billing_with_explicit_window_and_preserves_decimal_currency_and_scope(monkeypatch):
    from decimal import Decimal

    exported = {
        "status": "exported_usage_costs", "scope": "All Cloud Run resources in the project",
        "rows": [{"currency": "INR", "gross_cost": Decimal("10.000000001"),
                  "credits": Decimal("-2"), "net_cost": Decimal("8.000000001")}],
    }
    reader = Mock()
    reader.read.return_value = exported
    monkeypatch.setattr("app.services.billing_service.BillingExportService", Mock(return_value=reader))
    result = run(request(
        billing_table=f"{PROJECT}.billing.export", billing_start=NOW - timedelta(days=1),
        billing_end=NOW,
    ))
    cost = result["cost_analysis"]
    assert cost["status"] == "exported_usage_costs"
    assert cost["actual_exported"]["rows"][0]["net_cost"] == "8.000000001"
    assert cost["actual_exported"]["rows"][0]["currency"] == "INR"
    assert cost["estimate"] is cost["measured_savings"] is None
    assert "All Cloud Run" in cost["actual_exported"]["scope"]
    json.dumps(result, allow_nan=False)


def test_graph_empty_export_is_unknown_and_billing_input_validation_is_local(monkeypatch):
    reader = Mock()
    reader.read.return_value = {"status": "no_exported_rows", "rows": []}
    constructor = Mock(return_value=reader)
    monkeypatch.setattr("app.services.billing_service.BillingExportService", constructor)
    result = run(request(
        billing_table=f"{PROJECT}.billing.export", billing_start=NOW - timedelta(days=1), billing_end=NOW,
    ))
    assert result["cost_analysis"]["status"] == "no_exported_rows"
    for changes in (
        {"billing_table": f"{PROJECT}.billing.export"},
        {"billing_table": "bad`table", "billing_start": NOW - timedelta(days=1), "billing_end": NOW},
        {"billing_table": f"{PROJECT}.billing.export", "billing_start": NOW, "billing_end": NOW},
    ):
        with pytest.raises(ValidationError):
            request(**changes)


def test_explicit_forecast_run_is_reported_as_candidate_and_cannot_authorise_scaling(monkeypatch):
    from pathlib import Path

    candidate = [{"target": "request_count", "prediction": 25.0, "confidence": None}]
    infer = Mock(return_value=candidate)
    monkeypatch.setattr("app.models.inference.predict_from_run", infer)
    result = run(request(forecast_run=Path("models/runs/explicit-candidate")))
    infer.assert_called_once()
    assert result["model_analysis"]["status"] == "offline_candidate_inference"
    assert result["model_analysis"]["forecasts"] == candidate
    assert result["model_analysis"]["anomaly_results"] is None
    assert result["execution_allowed"] is False


def test_forecasts_are_withheld_if_evidence_expires_before_final_policy(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr("app.models.inference.predict_from_run", Mock(return_value=[{"prediction": 1.0}]))
    ticks = iter([NOW, NOW, NOW + timedelta(hours=1)])
    result = run(request(forecast_run=Path("models/runs/explicit-candidate")), clock=lambda: next(ticks))
    assert result["model_analysis"]["status"] == "candidate_withheld_stale"
    assert result["model_analysis"]["forecasts"] is None
    assert result["workflow_status"] == "blocked_evidence"
