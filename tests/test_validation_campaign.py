"""Harness safety and label provenance; synthetic unit data is not ML evidence."""
from datetime import datetime, timedelta, timezone
import json

from fastapi.testclient import TestClient
import pytest

from app.validation import lab_app
from app.validation.evaluate import request_labels
from app.validation.protocol import digest, make_plan, phase_at, rpm_at, verify_plan
from infrastructure.validation_campaign import check_target, valid_receipt


@pytest.fixture
def enabled_lab(monkeypatch):
    monkeypatch.setenv("AUTOCLOUD_COMPONENT", "validation_lab")
    monkeypatch.setenv("LAB_RUN_ID", "a"*32)
    monkeypatch.setenv("LAB_EXPIRES_AT", (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat())
    monkeypatch.setattr(lab_app, "actuate", lambda fault: {"fault": fault, "allocated_bytes": 0})
    return TestClient(lab_app.app)


def test_lab_is_disabled_outside_dedicated_component_and_expires(enabled_lab, monkeypatch):
    request = {"run_id": "a"*32, "sequence": 0}
    assert enabled_lab.post("/work", json=request).status_code == 200
    assert enabled_lab.post("/work", json=request, headers={"Origin": "https://example.org"}).status_code == 403
    monkeypatch.setenv("AUTOCLOUD_COMPONENT", "api")
    assert enabled_lab.post("/work", json=request).status_code == 410
    monkeypatch.setenv("AUTOCLOUD_COMPONENT", "validation_lab")
    monkeypatch.setenv("LAB_EXPIRES_AT", "2000-01-01T00:00:00+00:00")
    assert enabled_lab.post("/work", json=request).status_code == 410


def test_fault_receipt_and_parameters_are_bounded(enabled_lab):
    request = {"run_id": "a"*32, "sequence": 1, "fault": "http_503"}
    response = enabled_lab.post("/work", json=request)
    assert response.status_code == 503
    body = response.json()
    now = datetime.now(timezone.utc)
    assert valid_receipt(body, "a"*32, 1, "http_503", now-timedelta(seconds=1), now)
    assert not valid_receipt(body, "b"*32, 1, "http_503", now, now)
    assert not valid_receipt({}, "a"*32, 1, "http_503", now, now)
    for modified in ({"sequence": 1800}, {"fault": "arbitrary_command"}, {"memory_bytes": 999999999}):
        assert enabled_lab.post("/work", json={**request, **modified}).status_code == 422
    assert enabled_lab.get("/docs").status_code == 404


def test_plan_has_multiple_regimes_and_repeated_probes_and_detects_edits():
    plan = make_plan()
    verify_plan(plan)
    assert plan["duration_minutes"] == 120
    faults = [p["fault"] for p in plan["phases"] if "fault" in p]
    assert all(faults.count(fault) == 3 for fault in set(faults)) and len(set(faults)) == 4
    assert phase_at(plan, 120*60) is None
    for second in range(120*60):
        phase = phase_at(plan, second)
        assert 0 <= rpm_at(phase, second) <= 24
    plan["maximum_requests"] += 1
    with pytest.raises(ValueError):
        verify_plan(plan)


def test_stress_exposure_is_not_automatically_a_fault_label():
    def event(sequence, fault, status=200, latency=.1, confirmed=True, phase="episode_00"):
        return {"sequence": sequence, "receipt_confirmed": confirmed, "status": status,
                "latency_seconds": latency, "received_at": f"2026-11-16T12:0{sequence}:10Z",
                "intended_fault": fault, "phase": phase if phase != "episode_00" else f"episode_{sequence:02d}",
                "receipt": {"started_at": f"2026-11-16T12:0{sequence}:09Z"}}
    labels, episodes = request_labels([
        event(0, "memory_growth"), event(1, "http_503", 503),
        event(2, "latency", latency=2), event(3, "none", phase="low"),
        event(4, "cpu_stress", confirmed=False)], 1)
    assert len(labels) == 4
    assert [v["impact"] for v in labels.values()] == [0, 1, 1, 0]
    assert not list(labels.values())[0]["control_only"]
    assert list(labels.values())[-1]["control_only"]
    with pytest.raises(ValueError):
        request_labels([event(0, "none"), event(0, "none")], 1)


def test_memory_probe_cleans_up_on_recovery(monkeypatch):
    monkeypatch.setattr(lab_app, "cpu_work", lambda seconds: None)
    try:
        receipt = lab_app.actuate("memory_growth")
        assert receipt["allocated_bytes"] == 64*1024*1024
        assert lab_app.actuate("none")["allocated_bytes"] == 0
    finally:
        lab_app._memory = None


class Reply:
    ok = True
    def __init__(self, value): self.value = value
    def json(self): return self.value


def target_fixture():
    from app.validation.protocol import PROJECT, SERVICE, REGION
    return {"uri": "https://autocloud-validation-lab-example.a.run.app",
        "template": {"containers": [{"image": f"{REGION}-docker.pkg.dev/{PROJECT}/autocloud/autocloud-validation-lab@sha256:"+"b"*64,
            "resources": {"limits": {"cpu": "1", "memory": "512Mi"}, "cpuIdle": True},
            "env": [{"name": k, "value": v} for k,v in {
                "LAB_RUN_ID": "a"*32, "LAB_PLAN_SHA256": "c"*64,
                "AUTOCLOUD_COMPONENT": "validation_lab",
                "LAB_EXPIRES_AT": (datetime.now(timezone.utc)+timedelta(minutes=130)).isoformat()}.items()]}],
            "serviceAccount": f"{SERVICE}@{PROJECT}.iam.gserviceaccount.com",
            "maxInstanceRequestConcurrency": 1, "timeout": "10s", "scaling": {"maxInstanceCount": 1}}}


def test_target_preflight_blocks_public_access_wrong_image_and_excess_resources():
    service, policy = target_fixture(), {"bindings": []}
    class Session:
        def get(self, url, **kwargs): return Reply(policy if url.endswith(":getIamPolicy") else service)
    assert check_target(Session(), "a"*32, "sha256:"+"b"*64)[0].startswith("https://")
    with pytest.raises(ValueError): check_target(Session(), "a"*32, "sha256:"+"d"*64)
    policy["bindings"] = [{"members": ["allUsers"]}]
    with pytest.raises(ValueError): check_target(Session(), "a"*32, "sha256:"+"b"*64)
    policy["bindings"] = []
    service["template"]["scaling"]["maxInstanceCount"] = 2
    with pytest.raises(ValueError): check_target(Session(), "a"*32, "sha256:"+"b"*64)


def test_public_application_has_no_lab_endpoints():
    from app.main import app
    assert not any(route.path in {"/work", "/control"} for route in app.routes)


def test_short_campaign_never_exceeds_user_time_or_request_limits():
    plan = make_plan(30)
    verify_plan(plan)
    assert plan["duration_minutes"] == 30 and plan["maximum_requests"] == 450
    assert sum("fault" in phase for phase in plan["phases"]) == 4
    assert phase_at(plan, 1800) is None
    assert plan["deployment"]["max_age_minutes"] == 45


def test_offline_scoring_uses_frozen_artifacts_and_never_promotes(tmp_path):
    """Fabricated telemetry exercises math only; never written to a real study."""
    import hashlib
    from app.data.schema import MetricRecord
    from app.validation.evaluate import evaluate
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = now-timedelta(minutes=60)
    plan = make_plan()
    plan["registered_at"] = (start-timedelta(minutes=1)).isoformat()
    def save(name, value):
        (tmp_path/name).write_text(json.dumps(value), encoding="utf-8")
    save("plan.json", plan)
    save("execution.json", {"plan_sha256": digest(plan), "started_at": start.isoformat()})
    (tmp_path/"execution-events.ndjson").write_text(json.dumps({"status": "failed", "requests": 0,
        "finished_at": (start+timedelta(minutes=50)).isoformat()})+"\n")
    payload = "".join(MetricRecord(timestamp=start+timedelta(minutes=i+1), collected_at=now,
        project_id=plan["project"], region=plan["region"], service_name=plan["service"],
        cpu_utilization=.2, memory_utilization=.3, request_count=12, network_ingress=100,
        network_egress=100, average_latency=.1, error_rate=0, instance_count=1).model_dump_json()+"\n"
        for i in range(50)).encode()
    (tmp_path/"observations.ndjson").write_bytes(payload)
    (tmp_path/"requests.ndjson").write_bytes(b"")
    save("observations-source.json", {"sha256": hashlib.sha256(payload).hexdigest(),
        "requests_sha256": hashlib.sha256(b"").hexdigest(), "plan_sha256": digest(plan),
        "captured_at": now.isoformat()})
    result = evaluate(tmp_path)
    assert len(result["forecasts"]) == 9
    assert all(item["persistence"]["mae"] == 0 for item in result["forecasts"].values())
    assert result["operational_promotion"] == "not_approved" and not result["execution_allowed"]
    assert result["campaign_status"] == "failed"
    assert result["anomalies"]["minute_metrics"]["recall"] is None
    verify_plan(plan)  # Both code and model checksums remain unchanged.
