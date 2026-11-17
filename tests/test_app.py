"""Verify milestone behavior and configuration guardrails."""

import json
import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings, load_settings
from app.main import create_app
from app.utils.logging import JsonFormatter


def test_health_and_honest_stage():
    with TestClient(create_app(Settings(environment="test"))) as client:
        assert client.get("/").json()["stage"] == "environment-setup"
        for path, status in (("/health/live", "ok"), ("/health/ready", "ready")):
            response = client.get(path)
            assert response.status_code == 200
            assert response.json() == {"status": status}
            assert len(response.headers["X-Request-ID"]) == 32
        assert client.get("/monitoring").status_code == 404


@pytest.mark.parametrize("values", [
    {"port": 0}, {"port": 65536}, {"min_instances": 2, "max_instances": 1},
    {"max_instances": 3}, {"environment": "production"},
])
def test_invalid_configuration(values):
    with pytest.raises(ValidationError):
        Settings(**values)


def test_environment_loading(monkeypatch):
    monkeypatch.setenv("PORT", "9090")
    monkeypatch.setenv("MAX_INSTANCES", "1")
    assert load_settings().port == 9090
    assert load_settings().max_instances == 1


def test_production_hides_documentation():
    settings = Settings(environment="production", gcp_project_id="test-project")
    with TestClient(create_app(settings)) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        root = client.get("/").json()
        assert root["stage"] == "configured"
        assert root["capabilities"]["autonomous_execution"] is False


def test_internal_errors_are_sanitized():
    application = create_app(Settings(environment="test"))

    @application.get("/failure")
    async def fail():
        raise RuntimeError("sensitive-value")

    with TestClient(application) as client:
        response = client.get("/failure")
        assert response.status_code == 500
        assert "sensitive-value" not in response.text
        assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_structured_logging():
    record = logging.LogRecord("autocloud", logging.INFO, "", 0, "test", (), None)
    record.status = 200
    payload = json.loads(JsonFormatter().format(record))
    assert payload["severity"] == "INFO"
    assert payload["status"] == 200
