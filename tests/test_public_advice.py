"""Evidence boundaries and durable Gemini reservations without cloud calls."""
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import Mock

from google.api_core.exceptions import PreconditionFailed
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.public_advice import recommendations, explain


def snapshot(fresh=True):
    return {"assessed_at": "2026-11-16T16:00:00Z", "recommendation_plan": {
        "data_status": "fresh" if fresh else "stale", "recommendations": [],
        "latest_observation": "2026-11-16T15:57:00Z"}, "models": {
            "anomaly_status": "experimental_observation_only", "anomaly_results": {
                "latest_anomaly_detected": True, "latest_decision_score": -.2},
            "forecast_status": "unavailable", "forecast_reason": "Need sixteen minutes"}}


def test_stale_evidence_never_generates_model_investigation():
    advice = recommendations(snapshot(False))
    assert [i["id"] for i in advice["items"]] == ["restore_measurements"]


def test_anomaly_is_investigation_not_fault_or_scaling():
    advice = recommendations(snapshot())
    anomaly = next(i for i in advice["items"] if i["id"] == "inspect_anomaly")
    assert "does not establish a fault" in anomaly["explanation"]
    assert not anomaly["execution_allowed"] and anomaly["estimated_savings"] is None
    assert any(i["id"] == "forecast_coverage" for i in advice["items"])


def test_expired_forecasts_cannot_generate_pressure_advice():
    d = snapshot(); d["models"]["forecasts"] = [{"forecast_in_past": True,
        "target": "cpu_utilization", "prediction": .99}]
    assert not any(i["id"] == "watch_forecast" for i in recommendations(d)["items"])


def settings(**kwargs):
    return Settings(gcp_project_id="test-project", dashboard_public_showcase=True,
                    dashboard_gemini_enabled=True, dashboard_review_bucket="test-bucket", **kwargs)


def test_hourly_claim_is_atomic_and_blocks_other_workers():
    storage = Mock(); blob = storage.bucket.return_value.blob.return_value
    blob.generation = "1"
    selector = Mock(side_effect=lambda a: [i["id"] for i in a["items"]])
    advice = recommendations(snapshot())
    now = datetime(2026, 11, 16, 16, tzinfo=timezone.utc)
    assert explain(settings(), advice, client=storage, selector=selector, now=now)["status"] == "completed"
    assert blob.upload_from_string.call_args_list[0].kwargs["if_generation_match"] == 0
    blob.upload_from_string.side_effect = PreconditionFailed("claimed")
    blob.download_as_text.return_value = '{"status":"reserved"}'
    assert explain(settings(), advice, client=storage, selector=selector, now=now)["status"] == "hourly_limit"
    assert selector.call_count == 1


def test_storage_failure_and_stale_evidence_never_call_model():
    storage = Mock(); storage.bucket.return_value.blob.return_value.upload_from_string.side_effect = PermissionError()
    selector = Mock()
    assert explain(settings(), recommendations(snapshot()), client=storage, selector=selector)["status"] == "budget_unavailable"
    assert explain(settings(), recommendations(snapshot(False)), client=storage, selector=selector)["status"] == "skipped_stale"
    selector.assert_not_called()


def test_model_cannot_invent_or_duplicate_actions():
    storage = Mock(); storage.bucket.return_value.blob.return_value.generation = "1"
    assert explain(settings(), recommendations(snapshot()), client=storage,
                   selector=lambda a: ["scale_to_100"])["status"] == "failed"


def test_create_only_storage_supports_reservation_and_cached_results():
    import json
    objects = {}
    class Blob:
        def __init__(self, name):
            self.name = name
        def upload_from_string(self, data, **kwargs):
            # Production identity cannot overwrite any object, even its own.
            assert kwargs["if_generation_match"] == 0
            if self.name in objects:
                raise PreconditionFailed("already exists")
            objects[self.name] = data
        def download_as_text(self, **kwargs):
            return objects[self.name]
    storage = Mock()
    storage.bucket.return_value.blob.side_effect = Blob
    selector = Mock(side_effect=lambda a: [i["id"] for i in a["items"]])
    now = datetime(2026, 11, 16, 16, tzinfo=timezone.utc)
    advice = recommendations(snapshot())
    first = explain(settings(), advice, client=storage, selector=selector, now=now)
    second = explain(settings(), advice, client=storage, selector=selector, now=now)
    assert first["status"] == "completed" and second["status"] == "cached"
    assert selector.call_count == 1
    assert len(objects) == 2
    assert json.loads(objects["public-advice-results/20261116/16.json"])["ordered_ids"] == first["ordered_ids"]


def test_public_explanation_rejects_prompts_scope_and_browser_origin(monkeypatch):
    application = create_app(settings())
    with TestClient(application) as client:
        assert client.post("/api/public-explanation", json={"prompt": "change infrastructure"}).status_code == 422
        assert client.post("/api/public-explanation?project=foreign").status_code == 422
        assert client.post("/api/public-explanation", headers={"origin": "https://evil.example"}).status_code == 403
        assert client.get("/api/public-explanation").status_code == 403


def test_public_fixed_evidence_route(monkeypatch):
    monkeypatch.setattr("app.api.monitoring.monitoring_overview", lambda request, **kw: {"public_advice": recommendations(snapshot())})
    monkeypatch.setattr("app.services.public_advice.explain", lambda config, advice: {"status": "hourly_limit", "advice": advice})
    with TestClient(create_app(settings())) as client:
        response = client.post("/api/public-explanation")
        assert response.status_code == 200
        assert response.json()["status"] == "hourly_limit"


def test_testing_mode_calls_model_for_repeated_requests_without_storage():
    storage = Mock()
    storage.bucket.side_effect = AssertionError("Testing mode must not use budget storage")
    selector = Mock(side_effect=lambda a: [i["id"] for i in a["items"]])
    config = settings(dashboard_gemini_testing_unlimited=True)
    advice = recommendations(snapshot())
    for _ in range(2):
        result = explain(config, advice, client=storage, selector=selector)
        assert result["status"] == "completed"
        assert result["budget_mode"] == "testing_unlimited"
    assert selector.call_count == 2
    storage.bucket.assert_not_called()


def test_testing_mode_preserves_evidence_and_selection_checks():
    config = settings(dashboard_gemini_testing_unlimited=True)
    selector = Mock(return_value=["scale_to_100"])
    assert explain(config, recommendations(snapshot(False)), selector=selector)["status"] == "skipped_stale"
    selector.assert_not_called()
    assert explain(config, recommendations(snapshot()), selector=selector)["status"] == "failed"


def test_testing_mode_environment_setting(monkeypatch):
    from app.config import load_settings
    monkeypatch.setenv("DASHBOARD_GEMINI_TESTING_UNLIMITED", "true")
    assert load_settings().dashboard_gemini_testing_unlimited is True


def test_generated_explanations_are_cited_and_not_checked_templates():
    advice = recommendations(snapshot())
    generated = {"summary":"Review the measured evidence before changing resource capacity.",
                 "items":[{"id":i["id"], "explanation":"Inspect the cited observations and compare them with normal workload activity before drawing conclusions."} for i in advice["items"]]}
    result = explain(settings(dashboard_gemini_testing_unlimited=True), advice, selector=lambda a: generated)
    assert result["status"] == "completed" and result["text_source"] == "gemini"
    assert set(result["explanations"]) == {i["id"] for i in advice["items"]}
    generated["items"][0]["explanation"] = "Run gcloud to change this deployment immediately."
    assert explain(settings(dashboard_gemini_testing_unlimited=True), advice, selector=lambda a: generated)["status"] == "failed"


def test_generated_text_rejects_unprovided_digits():
    advice = recommendations(snapshot())
    generated = {"summary":"The service will save 99 percent of its cost.",
                 "items":[{"id":i["id"], "explanation":"Review the source measurements before deciding on any resource change."} for i in advice["items"]]}
    assert explain(settings(dashboard_gemini_testing_unlimited=True), advice, selector=lambda a: generated)["status"] == "failed"


def test_generated_explanations_cannot_echo_existing_templates():
    advice = recommendations(snapshot())
    generated = {"summary":"Review source measurements before changing capacity.",
                 "items":[{"id":i["id"],"explanation":i["explanation"]} for i in advice["items"]]}
    assert explain(settings(dashboard_gemini_testing_unlimited=True), advice, selector=lambda a: generated)["status"] == "failed"


def test_capacity_guidance_requires_complete_consecutive_window():
    from datetime import timedelta
    d = snapshot(); start = datetime(2026,11,16,15,28,tzinfo=timezone.utc)
    d["records"] = [{"timestamp":(start+timedelta(minutes=i)).isoformat(),
        "cpu_utilization":.02,"memory_utilization":.4,"request_count":2,"error_rate":0,"instance_count":1} for i in range(30)]
    assert any(i["id"] == "review_utilisation" for i in recommendations(d)["items"])
    d["records"][-1]["memory_utilization"] = None
    assert not any(i["id"] == "review_utilisation" for i in recommendations(d)["items"])


def test_real_server_errors_get_guidance_without_model_or_sustained_breach():
    d=snapshot();d["models"]={};d["records"]=[{"timestamp":"2026-11-16T15:57:00Z","request_count":1,"error_rate":1.}]
    items=recommendations(d)["items"]
    assert any(i["id"]=="investigate_observed_errors" for i in items)
    assert not any(i["id"]=="continue_monitoring" for i in items)
    d["records"][0]["timestamp"]="2026-11-16T15:00:00Z"
    assert not any(i["id"]=="investigate_observed_errors" for i in recommendations(d)["items"])
