"""Tests for Google OAuth sign-in, keyless onboarding, multi-tenant isolation, and live monitoring REST."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.data.schema import MetricRecord, MetricSample
from app.main import create_app
from app.services.dashboard_service import DashboardHistory
from app.services.gcp_monitoring import collect_monitoring_rest
from app.services.tenant_store import (
    CloudTenantStore,
    LocalTenantStore,
    OnboardedProject,
    contains_forbidden_key_material,
)
from app.services.user_auth import AuthenticatedUser


def _sample_records(project: str, region: str, service: str, count: int = 20) -> list[dict]:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=2)
    rows = []
    for idx in range(count):
        ts = now - timedelta(minutes=count - 1 - idx)
        rows.append(MetricRecord(
            timestamp=ts,
            collected_at=now + timedelta(minutes=1),
            project_id=project,
            region=region,
            service_name=service,
            cpu_utilization=0.92 if idx >= count - 3 else 0.35 + 0.01 * (idx % 5),
            memory_utilization=0.42,
            request_count=20.0 + idx,
            network_ingress=1000.0,
            network_egress=1200.0,
            instance_count=1.0,
            average_latency=45.0,
            error_rate=0.0,
        ).model_dump(mode="json"))
    return rows


def _sample_monitoring_metrics(count: int = 20) -> list[MetricSample]:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=2)
    samples: list[MetricSample] = []
    for idx in range(count):
        ts = now - timedelta(minutes=count - 1 - idx)
        samples.append(MetricSample(
            timestamp=ts,
            metric="cpu_utilization",
            value=0.92 if idx >= count - 3 else 0.35 + 0.01 * (idx % 5),
            weight=1,
            series_key='{"metric":"cpu"}',
        ))
        samples.append(MetricSample(
            timestamp=ts,
            metric="memory_utilization",
            value=0.42,
            weight=1,
            series_key='{"metric":"memory"}',
        ))
        samples.append(MetricSample(
            timestamp=ts,
            metric="request_count",
            value=25 + idx,
            weight=1,
            series_key='{"metric":"req"}',
        ))
    return samples


def _make_configured_app(tmp_path: Path, *, user_auth_required: bool = True, allow_dev: bool = True, env: str = "test"):
    settings = Settings(
        environment=env,
        gcp_project_id="host-proj-123",
        gcp_region="asia-south1",
        dashboard_allowed_services="autocloud-api,autocloud-dashboard",
        dashboard_user_auth_required=user_auth_required,
        dashboard_allow_dev_login=allow_dev if env != "production" else False,
        dashboard_session_secret="test-session-secret-with-at-least-thirty-two-bytes",
        google_oauth_client_id="client-id.apps.googleusercontent.com",
        google_oauth_client_secret="client-secret",
        dashboard_oauth_redirect_uri="https://dashboard.example.run.app/",
        dashboard_billing_table="host-proj-123.billing.gcp_billing_export",
    )
    app = create_app(settings)
    app.state.analytics_data_root = tmp_path

    def reader(project: str, region: str, service: str, hours: int, **kwargs):
        return _sample_records(project, region, service)

    def monitoring_reader(project: str, region: str, service: str, start: datetime, end: datetime, **kwargs):
        return _sample_monitoring_metrics()

    app.state.dashboard_history = DashboardHistory(
        reader=reader,
        monitoring_reader=monitoring_reader,
    )
    app.state.dashboard_billing = Mock(read=Mock(return_value={
        "status": "succeeded",
        "lookback_days": 1,
        "period_start": "2026-11-15T00:00:00+00:00",
        "period_end": "2026-11-16T00:00:00+00:00",
        "fetched_at": "2026-11-16T12:00:00+00:00",
        "cache_hit": False,
        "latest_export_time": "2026-11-16T12:00:00+00:00",
        "latest_usage_start_time": "2026-11-16T11:00:00+00:00",
        "scope": "host-only",
        "currency_totals": [],
        "daily_totals": [],
        "rows": [],
        "note": "Host billing",
    }))
    return app


def test_settings_rejects_unsafe_dev_login_or_missing_secret_in_production():
    with pytest.raises(ValueError, match="DASHBOARD_ALLOW_DEV_LOGIN"):
        Settings(
            environment="production",
            gcp_project_id="host-proj-123",
            dashboard_allow_dev_login=True,
        )
    with pytest.raises(ValueError, match="DASHBOARD_SESSION_SECRET"):
        Settings(
            environment="production",
            gcp_project_id="host-proj-123",
            dashboard_user_auth_required=True,
        )


def test_forbidden_key_material_detection():
    assert contains_forbidden_key_material({"private_key": "abc"})
    assert contains_forbidden_key_material({"type": "service_account", "project_id": "p1"})
    assert contains_forbidden_key_material({"notes": "-----BEGIN PRIVATE KEY-----"})
    assert contains_forbidden_key_material({"nested": [{"client_email": "x@y.iam.gserviceaccount.com"}]})
    assert not contains_forbidden_key_material({
        "project_id": "my-ext-proj-123",
        "region": "asia-south1",
        "display_name": "Payments",
    })


def test_google_access_token_must_match_verified_login(monkeypatch):
    from app.services.user_auth import verify_access_token_subject
    user = AuthenticatedUser(sub="alice-sub", email="alice@example.com", auth_provider="google_oauth", exp=9999999999)
    response = Mock(status_code=200)
    response.json.return_value = {"sub":"bob-sub", "email":"bob@example.com", "email_verified":True}
    client = Mock(); client.__enter__ = Mock(return_value=client); client.__exit__ = Mock(return_value=False)
    client.get.return_value = response
    monkeypatch.setattr(httpx, "Client", Mock(return_value=client))
    with pytest.raises(ValueError, match="does not belong"):
        verify_access_token_subject("fixture", user)
    response.json.return_value = {"sub":"alice-sub", "email":"alice@example.com", "email_verified":True}
    verify_access_token_subject("fixture", user)


def test_partial_iam_permissions_and_revocation_fail_closed(tmp_path):
    app = _make_configured_app(tmp_path)
    permissions = ["monitoring.timeSeries.list"]
    app.state.user_project_verifier = lambda *args: tuple(permissions)
    app.state.sa_permission_checker = lambda *args: ()
    app.state.project_service_discoverer = lambda *args: ("orders-api",)
    with TestClient(app) as client:
        token = client.post("/api/auth/dev-login", json={"email":"alice@example.com"}).json()["session_token"]
        headers = {"X-AutoCloud-User-Session":token, "X-AutoCloud-GCP-Access-Token":"fixture"}
        body = {"project_id":"alice-ext-proj1", "cloud_run_service":"orders-api"}
        assert client.post("/api/projects/onboard", headers=headers, json=body).status_code == 403
        permissions.append("run.services.list")
        assert client.post("/api/projects/onboard", headers=headers, json=body).status_code == 200
        url = "/api/overview?source=monitoring&project=alice-ext-proj1&service=orders-api"
        assert client.get(url, headers=headers).status_code == 200
        permissions.clear()
        assert client.get(url, headers=headers).status_code == 403


def test_oauth_callback_requires_original_browser_pending_state(monkeypatch):
    from types import SimpleNamespace
    from app.dashboard import onboarding
    fake = SimpleNamespace(query_params={"code":"attacker-code", "state":"attacker-state"},
        session_state={"oauth_pending_request":{"state":"victim-state"}}, sidebar=SimpleNamespace(error=Mock()))
    monkeypatch.setattr(onboarding, "st", fake)
    calls = Mock(side_effect=AssertionError("Mismatched state must never reach callback API"))
    monkeypatch.setattr(httpx, "Client", calls)
    onboarding._handle_oauth_query_params("http://localhost", {})
    calls.assert_not_called(); fake.sidebar.error.assert_called_once()


def test_oauth_pkce_state_replay_and_session_verification(tmp_path: Path):
    app = _make_configured_app(tmp_path, allow_dev=False)

    def fake_exchanger(*, code, code_verifier, client_id, client_secret, redirect_uri, expected_nonce):
        assert code == "auth-code-123"
        assert len(code_verifier) >= 43
        assert expected_nonce
        return {
            "user": AuthenticatedUser(
                sub="google-sub-1",
                email="alice@example.com",
                name="Alice",
                auth_provider="google_oauth",
                exp=int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
            ),
            "gcp_access_token": "ya29.alice-read-only",
            "expires_in": 3600,
        }

    app.state.oauth_code_exchanger = fake_exchanger
    with TestClient(app) as client:
        assert client.get("/api/overview").status_code == 401
        assert client.get("/api/resources").status_code == 401

        login = client.get("/api/auth/login")
        assert login.status_code == 200
        state = login.json()["state"]
        assert "code_challenge_method=S256" in login.json()["authorization_url"]

        cb = client.post("/api/auth/callback", json={"code": "auth-code-123", "state": state})
        assert cb.status_code == 200
        token = cb.json()["session_token"]
        assert cb.json()["user"]["email"] == "alice@example.com"

        # Single-use OAuth state replay MUST be rejected.
        replay = client.post("/api/auth/callback", json={"code": "auth-code-123", "state": state})
        assert replay.status_code == 403

        # Dev login is blocked when disabled.
        assert client.post("/api/auth/dev-login", json={"email": "alice@example.com"}).status_code == 403

        sess = client.get("/api/auth/session", headers={"X-AutoCloud-User-Session": token})
        assert sess.status_code == 200
        assert sess.json()["signed_in"] is True

        tampered = client.get("/api/overview", headers={"X-AutoCloud-User-Session": token + "x"})
        assert tampered.status_code == 401


def test_keyless_onboarding_and_strict_per_user_isolation(tmp_path: Path):
    app = _make_configured_app(tmp_path)
    sa_active: dict[str, tuple[str, ...]] = {}
    app.state.user_project_verifier = (
        lambda user, project_id, gcp_token, perms: (
            ("monitoring.timeSeries.list", "run.services.list")
            if (user.email == "alice@example.com" and project_id == "alice-ext-proj1")
            else ()
        )
    )
    app.state.sa_permission_checker = lambda project_id, perms: sa_active.get(project_id, ())
    app.state.project_service_discoverer = lambda project_id, region, tok: ("orders-api",)

    with TestClient(app) as client:
        tok_a = client.post("/api/auth/dev-login", json={"email": "alice@example.com"}).json()["session_token"]
        tok_b = client.post("/api/auth/dev-login", json={"email": "bob@example.com"}).json()["session_token"]
        hdr_a = {"X-AutoCloud-User-Session": tok_a}
        hdr_b = {"X-AutoCloud-User-Session": tok_b}

        # Host resource allowlist checks.
        res_a = client.get("/api/resources", headers=hdr_a).json()
        host_services = [r["service_name"] for r in res_a["resources"] if r["kind"] == "host"]
        assert host_services == ["autocloud-api", "autocloud-dashboard"]
        assert client.get("/api/overview?source=bigquery&service=autocloud-dashboard", headers=hdr_a).status_code == 200
        assert client.get("/api/overview?source=bigquery&service=rogue-service", headers=hdr_a).status_code == 403

        # Reject uploaded service-account keys & host-project re-onboarding.
        bad_key = client.post(
            "/api/projects/onboard",
            headers=hdr_a,
            json={"project_id": "alice-ext-proj1", "private_key": "-----BEGIN PRIVATE KEY-----"},
        )
        assert bad_key.status_code == 400
        assert "never accepted" in bad_key.json()["detail"].lower()

        host_dup = client.post(
            "/api/projects/onboard",
            headers=hdr_a,
            json={"project_id": "host-proj-123"},
        )
        assert host_dup.status_code == 409

        # Confused-deputy defense: Bob cannot onboard Alice's project without GCP IAM permissions.
        bob_attack = client.post(
            "/api/projects/onboard",
            headers=hdr_b,
            json={"project_id": "alice-ext-proj1"},
        )
        assert bob_attack.status_code == 403

        # Alice onboards keyless -> pending IAM delegation with read-only gcloud instructions.
        onb = client.post(
            "/api/projects/onboard",
            headers=hdr_a,
            json={"project_id": "alice-ext-proj1", "region": "asia-south1", "cloud_run_service": "orders-api"},
        )
        assert onb.status_code == 200
        onb_json = onb.json()
        assert onb_json["project"]["status"] == "pending_iam_delegation"
        assert onb_json["key_uploads_accepted"] is False
        assert onb_json["execution_allowed"] is False
        assert any("roles/monitoring.viewer" in cmd for cmd in onb_json["setup_commands"])

        # Reading before SA IAM delegation completes (without user OAuth token) returns 409.
        assert client.get(
            "/api/overview?source=monitoring&project=alice-ext-proj1&service=orders-api",
            headers=hdr_a,
        ).status_code == 403

        # Grant read-only delegation & re-verify.
        sa_active["alice-ext-proj1"] = ("monitoring.timeSeries.list", "run.services.list")
        ver = client.post("/api/projects/alice-ext-proj1/verify", headers=hdr_a)
        assert ver.status_code == 200
        assert ver.json()["project"]["status"] == "verified_active"

        hdr_a["X-AutoCloud-GCP-Access-Token"] = "fixture-current-user-token"
        # Alice reads Monitoring metrics and isolated cost status for her project.
        ov_a = client.get(
            "/api/overview?source=monitoring&project=alice-ext-proj1&service=orders-api",
            headers=hdr_a,
        )
        assert ov_a.status_code == 200
        assert ov_a.json()["source"] == "monitoring"
        assert ov_a.json()["target"]["kind"] == "onboarded"
        assert ov_a.json()["target"]["owner_sub"] == "dev:alice@example.com"

        costs_ext = client.get("/api/costs?project=alice-ext-proj1&service=orders-api", headers=hdr_a)
        assert costs_ext.status_code == 200
        assert costs_ext.json()["status"] == "not_applicable_external_project"

        # External projects only support source=monitoring (never host BigQuery).
        assert client.get(
            "/api/overview?source=bigquery&project=alice-ext-proj1&service=orders-api",
            headers=hdr_a,
        ).status_code == 403

        # Bob is STRICTLY isolated from Alice's onboarded project AND Alice's reviews.
        assert client.get("/api/projects", headers=hdr_b).json()["projects"] == []
        bob_res = client.get("/api/resources", headers=hdr_b).json()["resources"]
        assert all(r["project_id"] != "alice-ext-proj1" for r in bob_res)
        assert client.get(
            "/api/overview?source=monitoring&project=alice-ext-proj1&service=orders-api",
            headers=hdr_b,
        ).status_code == 403
        assert client.post(
            "/api/analysis",
            headers=hdr_b,
            json={"project": "alice-ext-proj1", "service": "orders-api", "source": "monitoring"},
        ).status_code == 403

        # Review isolation on both external AND shared host resources.
        plan_a = ov_a.json()["recommendation_plan"]
        # Seed high CPU on host to guarantee a recommendation for review isolation check.
        ov_host_a = client.get("/api/overview?source=local&service=autocloud-api", headers=hdr_a).json()
        if ov_host_a["recommendation_plan"] and ov_host_a["recommendation_plan"]["recommendations"]:
            fp = ov_host_a["recommendation_plan"]["evidence_fingerprint"]
            cap_a = client.post(
                "/api/reviews/capture",
                headers=hdr_a,
                json={"source": "local", "hours": 24, "evidence_fingerprint": fp, "service": "autocloud-api"},
            )
            assert cap_a.status_code == 200
            rid_a = cap_a.json()["saved_ids"][0]
            assert client.get("/api/reviews?service=autocloud-api", headers=hdr_b).json()["items"] == []
            assert client.post(
                f"/api/reviews/{rid_a}/decision?service=autocloud-api",
                headers=hdr_b,
                json={"decision": "approved", "reviewer": "Bob", "note": "Cross-tenant attempt"},
            ).status_code == 404

        assert plan_a is not None
        assert client.delete("/api/projects/alice-ext-proj1", headers=hdr_b).status_code == 404
        assert client.delete("/api/projects/alice-ext-proj1", headers=hdr_a).status_code == 200
        assert client.get(
            "/api/overview?source=monitoring&project=alice-ext-proj1&service=orders-api",
            headers=hdr_a,
        ).status_code == 403


def test_cloud_tenant_store_isolation_and_revocation():
    from tests.test_reviews import _FakeBucket, _FakeStorageClient

    bucket = _FakeBucket()
    store = CloudTenantStore("host-proj-123", "asia-south1", "autocloud-reviews", client=_FakeStorageClient(bucket))
    now = datetime.now(timezone.utc)
    rec = OnboardedProject(
        owner_sub="sub-a",
        owner_email="a@example.com",
        project_id="proj-a-123",
        region="asia-south1",
        display_name="Proj A",
        status="verified_active",
        verified_permissions=("monitoring.timeSeries.list",),
        sa_delegated_permissions=("monitoring.timeSeries.list",),
        services=("svc-1",),
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
        verified_at=now.isoformat(),
    )
    store.upsert_project(rec)
    assert [p.project_id for p in store.list_projects("sub-a")] == ["proj-a-123"]
    assert store.list_projects("sub-b") == []
    assert store.get_project("sub-b", "proj-a-123") is None
    assert not store.revoke_project("sub-b", "proj-a-123", now)
    assert store.revoke_project("sub-a", "proj-a-123", now + timedelta(seconds=1))
    assert store.get_project("sub-a", "proj-a-123") is None
    exp_ts = int((now + timedelta(minutes=5)).timestamp())
    assert store.consume_oauth_nonce("oauth-jti-1", exp_ts) is True
    assert store.consume_oauth_nonce("oauth-jti-1", exp_ts) is False


def test_collect_monitoring_rest_parses_metrics_and_preserves_missingness(monkeypatch):
    ts_str = "2026-11-16T12:00:00Z"

    def fake_get(self, url, params=None, headers=None, **kwargs):
        assert headers["Authorization"] == "Bearer oauth-read-tok"
        flt = params.get("filter", "")
        series = []
        if "cpu/utilizations" in flt:
            series = [{"points": [{"interval": {"endTime": ts_str}, "value": {"distributionValue": {"mean": 0.44, "count": 5}}}]}]
        elif "request_count" in flt:
            series = [{"points": [{"interval": {"endTime": ts_str}, "value": {"int64Value": "120"}}]}]
        resp = Mock()
        resp.json.return_value = {"timeSeries": series}
        resp.raise_for_status = Mock()
        return resp

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    end = datetime(2026, 11, 16, 12, 1, tzinfo=timezone.utc)
    start = end - timedelta(hours=1)
    samples = collect_monitoring_rest("ext-proj-1", "asia-south1", "svc-1", start, end, bearer_token="oauth-read-tok")
    by_metric = {s.metric: s for s in samples}
    assert by_metric["cpu_utilization"].value == pytest.approx(0.44)
    assert by_metric["request_count"].value == pytest.approx(120.0)
    assert "memory_utilization" not in by_metric


def test_streamlit_renders_experimental_models_anomalies_and_onboarding_without_key_upload(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from app.services.dashboard_service import overview
    from app.services.model_dashboard import model_panel

    run_dir = Path(__file__).resolve().parents[1] / "models" / "runs" / "20261116T051914Z_48d41482"
    rows = [
        MetricRecord.model_validate_json(line)
        for line in (run_dir / "history.ndjson").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ][182:212]
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    shifted = []
    for idx, r in enumerate(rows):
        ts = now - timedelta(minutes=len(rows) - idx)
        shifted.append(r.model_copy(update={"timestamp": ts, "collected_at": now}))

    ov = overview(tmp_path, "astute-sign-506809-j8", "asia-south1", "autocloud-api", now,
                  records=[r.model_dump() for r in shifted])
    ov["source"] = "bigquery"
    ov["models"] = model_panel(ov["records"], str(run_dir), project="astute-sign-506809-j8",
                               region="asia-south1", service="autocloud-api", now=now)
    session_payload = {
        "signed_in": True,
        "user": {"sub": "dev:alice@example.com", "email": "alice@example.com", "name": "Alice", "auth_provider": "dev_local", "exp": 9999999999},
        "user_auth_required": True,
        "google_oauth_enabled": True,
        "dev_login_enabled": True,
    }
    res_payload = {
        "user": session_payload["user"],
        "reader_service_account": "autocloud-api-reader@host.iam.gserviceaccount.com",
        "execution_allowed": False,
        "key_uploads_accepted": False,
        "resources": [
            {
                "project_id": "astute-sign-506809-j8",
                "region": "asia-south1",
                "service_name": "autocloud-api",
                "kind": "host",
                "display_name": "astute-sign-506809-j8 · autocloud-api (host)",
                "allowed_sources": ["bigquery", "monitoring", "local"],
                "billing_applicable": True,
                "models_scoped": True,
            },
        ],
    }

    def fake_get(url, **kwargs):
        resp = Mock(status_code=200)
        if url.endswith("/api/auth/session"):
            resp.json.return_value = session_payload
        elif url.endswith("/api/resources"):
            resp.json.return_value = res_payload
        else:
            resp.json.return_value = ov
        return resp

    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.get.side_effect = fake_get
    monkeypatch.setattr(httpx, "Client", Mock(return_value=client))

    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app/dashboard/home.py")).run(timeout=30)
    assert not app.exception
    # 3 dataframes: evaluation, forecasts vs persistence, and anomaly scores vs thresholds.
    assert len(app.dataframe) == 3
    assert any("Minutes flagged by the model" == m.label for m in app.metric)
    assert any("keyless" in str(c.value).lower() for c in app.caption)
    # Never any file_uploader widget requesting service-account key files.
    assert len(app.get("file_uploader")) == 0
