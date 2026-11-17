"""Public visitors can only read the fixed showcase, never privileged controls."""
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.dashboard_service import overview


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/costs"), ("GET", "/api/reviews"), ("POST", "/api/reviews"),
    ("POST", "/api/analysis"), ("GET", "/api/auth/session"),
    ("POST", "/api/projects/onboard"), ("GET", "/api/resources"),
    ("POST", "/api/overview?source=bigquery"),
    ("GET", "/api/overview?source=local"),
    ("GET", "/api/overview?source=bigquery&service=autocloud-dashboard"),
    ("GET", "/api/overview?source=bigquery&project=another-project"),
    ("GET", "/api/overview?source=bigquery&hours=1"),
    ("GET", "/api/overview?source=local&source=bigquery"),
])
def test_public_boundary_rejects_sensitive_routes_and_scope_changes(method, path):
    app = create_app(Settings(gcp_project_id="test-project", dashboard_public_showcase=True))
    with TestClient(app) as client:
        assert client.request(method, path).status_code == 403


def test_public_overview_is_read_only_and_health_works(tmp_path, monkeypatch):
    app = create_app(Settings(gcp_project_id="test-project", dashboard_public_showcase=True))
    app.state.analytics_data_root = tmp_path
    app.state.dashboard_history.read = Mock(return_value={"records": [], "status": "unavailable",
                                                         "query_source": "bigquery"})
    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 200
        assert client.get("/").json()["capabilities"]["public_read_only"]
        response = client.get("/api/overview?source=bigquery&hours=24")
        assert response.status_code == 200
        caps = response.json()["capabilities"]
        assert caps["public_read_only"]
        assert not any(caps[k] for k in ("cloud_reviews", "local_reviews", "gemini_enabled", "ai_workflow", "keyless_onboarding", "billing_configured"))


def test_public_ui_has_no_sign_in_billing_onboarding_or_write_controls(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("DASHBOARD_PUBLIC_SHOWCASE", "true")
    monkeypatch.setenv("AUTOCLOUD_API_AUTH", "none")
    payload = overview(tmp_path, "test-project", "asia-south1", "autocloud-api")
    payload["source"] = "bigquery"
    payload["capabilities"] = {"cloud_reviews": True, "local_reviews": True, "gemini_enabled": True, "public_explanations": True}
    response = Mock(status_code=200)
    response.json.return_value = payload
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.get.return_value = response
    monkeypatch.setattr(httpx, "Client", Mock(return_value=client))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app/dashboard/home.py")).run(timeout=30)
    assert not app.exception
    assert sorted(b.label for b in app.button) == sorted(["Refresh measurements", "Generate Gemini explanations"])
    assert not app.text_input
    assert not app.selectbox
    assert all(call.args[0].endswith("/api/overview") for call in client.get.call_args_list)
    assert any("Public read-only showcase" in str(i.value) for i in app.info)
