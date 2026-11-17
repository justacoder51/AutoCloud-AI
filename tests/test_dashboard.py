"""Evidence handling and the read-only dashboard API, without cloud access."""

import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.data.schema import MetricRecord
from app.data.storage import save_records
from app.main import create_app
from app.services.dashboard_service import experiment_status, overview
from app.services.dashboard_service import DashboardHistory
from unittest.mock import Mock

import pytest

NOW = datetime(2026, 11, 15, 20, tzinfo=timezone.utc)


def metric(minutes=0, **kwargs):
    return MetricRecord(
        timestamp=NOW - timedelta(minutes=minutes), collected_at=NOW,
        project_id="test-project", region="asia-south1", service_name="autocloud-api",
        **kwargs,
    )


def test_scoped_deduplication_preserves_unknown_requests(tmp_path):
    row = metric(1)
    older = row.model_copy(update={"collected_at": NOW - timedelta(seconds=10), "request_count": 99})
    foreign = metric(2).model_copy(update={"project_id": "another-project"})
    save_records([older, row, foreign], tmp_path / "processed/metrics.ndjson")
    result = overview(tmp_path, "test-project", "asia-south1", "autocloud-api", NOW)
    assert result["snapshot_status"] == "loaded"
    assert len(result["records"]) == 1
    assert result["summary"]["observed_request_total"] is None
    assert result["summary"]["latest_values"]["cpu_utilization"] is None
    assert result["costs"]["actual_billed_cost"] is None


def test_stale_observations_are_explicit_and_no_recommendation_is_invented(tmp_path):
    save_records([metric(30, cpu_utilization=.99)], tmp_path / "processed/metrics.ndjson")
    result = overview(tmp_path, "test-project", "asia-south1", "autocloud-api", NOW)
    assert result["recommendation_plan"]["data_status"] == "stale"
    assert result["recommendation_plan"]["recommendations"] == []


def test_measured_zero_and_missing_are_distinct(tmp_path):
    save_records([metric(1), metric(0, request_count=0)], tmp_path / "processed/metrics.ndjson")
    result = overview(tmp_path, "test-project", "asia-south1", "autocloud-api", NOW)
    assert result["summary"]["observed_request_total"] == 0
    assert result["summary"]["request_minutes_with_measurements"] == 1
    assert result["summary"]["missing_counts"]["request_count"] == 1


def test_future_evidence_and_malformed_snapshots_fail_closed(tmp_path):
    path = tmp_path / "processed/metrics.ndjson"
    save_records([metric(-1)], path)
    assert overview(tmp_path, "test-project", "asia-south1", "autocloud-api", NOW)["snapshot_status"] == "invalid_snapshot"
    path.write_text('{"secret":"never expose"}')
    result = overview(tmp_path, "test-project", "asia-south1", "autocloud-api", NOW)
    assert result["snapshot_status"] == "invalid_snapshot"
    assert "never expose" not in json.dumps(result)


def test_missing_file_and_missing_configuration_are_explicit(tmp_path):
    assert overview(tmp_path, None, "asia-south1", "autocloud-api", NOW)["snapshot_status"] == "project_not_configured"
    assert overview(tmp_path, "test-project", "asia-south1", "autocloud-api", NOW)["snapshot_status"] == "unavailable"


def test_stale_progress_is_not_reported_as_completed_and_private_fields_are_excluded(tmp_path):
    runs = tmp_path / "training_runs"
    directory = runs / ("a" * 32)
    directory.mkdir(parents=True)
    (runs / "active.json").write_text(json.dumps({"run_id": "a" * 32}))
    (directory / "status.json").write_text(json.dumps({
        "stage": "sending_traffic", "updated_at": (NOW - timedelta(minutes=5)).isoformat(),
        "successful_requests": 21, "credentials": "never expose",
    }))
    result = experiment_status(tmp_path, NOW)
    assert result["progress_status"] == "may_have_stalled"
    assert result["stage"] == "sending_traffic"
    assert result["successful_requests"] == 21
    assert "credentials" not in result


def test_path_traversal_marker_is_rejected(tmp_path):
    runs = tmp_path / "training_runs"
    runs.mkdir()
    (runs / "active.json").write_text('{"run_id":"../../outside"}')
    assert experiment_status(tmp_path, NOW)["stage"] == "unreadable"


def test_read_only_api_uses_configured_target(tmp_path):
    application = create_app(Settings(environment="test", gcp_project_id="test-project"))
    application.state.analytics_data_root = tmp_path
    timestamp = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=1)
    row = metric(1, request_count=7).model_copy(update={"timestamp": timestamp, "collected_at": timestamp})
    save_records([row], tmp_path / "processed/metrics.ndjson")
    with TestClient(application) as client:
        response = client.get("/api/overview")
        assert response.status_code == 200
        result = response.json()
        assert result["project"] == "test-project"
        assert result["snapshot_status"] == "loaded"
        assert result["summary"]["observed_request_total"] == 7
        assert result["actions"]["execution_allowed"] is False
        assert client.post("/api/overview").status_code == 405


def test_bigquery_cache_coalesces_reads_and_refreshes_after_ttl():
    clock = [0.0]
    reader = Mock(return_value=[])
    history = DashboardHistory(reader=reader, clock=lambda: clock[0])
    first = history.read("test-project", "asia-south1", "autocloud-api", 1)
    assert first["status"] == "succeeded"
    assert not first["cache_hit"]
    second = history.read("test-project", "asia-south1", "autocloud-api", 1)
    assert second["cache_hit"]
    assert second["fetched_at"] == first["fetched_at"]
    reader.assert_called_once()
    clock[0] = 61
    assert not history.read("test-project", "asia-south1", "autocloud-api", 1)["cache_hit"]
    assert reader.call_count == 2


def test_bigquery_error_is_sanitized_cached_and_never_falls_back(tmp_path):
    save_records([metric(1, request_count=99)], tmp_path / "processed/metrics.ndjson")
    reader = Mock(side_effect=RuntimeError("secret-provider-error"))
    history = DashboardHistory(reader=reader)
    query = history.read("test-project", "asia-south1", "autocloud-api", 1)
    result = overview(tmp_path, "test-project", "asia-south1", "autocloud-api",
                      records=query["records"], query=query)
    assert result["source"] == "bigquery"
    assert result["snapshot_status"] == "bigquery_unavailable"
    assert result["records"] == []
    assert result["summary"] is None
    assert "secret-provider-error" not in json.dumps(result)
    assert history.read("test-project", "asia-south1", "autocloud-api", 1)["cache_hit"]
    reader.assert_called_once()


def test_bigquery_api_coverage_missingness_and_empty_result(tmp_path):
    application = create_app(Settings(environment="test", gcp_project_id="test-project"))
    application.state.analytics_data_root = tmp_path

    def reader(service, start, end):
        return [metric().model_copy(update={"timestamp": end, "collected_at": end}).model_dump()]

    application.state.dashboard_history = DashboardHistory(reader=reader)
    with TestClient(application) as client:
        result = client.get('/api/overview?source=bigquery&hours=1').json()
        assert result["source"] == "bigquery"
        assert result["snapshot_status"] == "loaded"
        assert result["coverage"]["observed_minutes"] == 1
        assert result["coverage"]["gap_minutes"] == 59
        assert result["summary"]["observed_request_total"] is None
        assert client.get('/api/overview?source=bigquery&hours=25').status_code == 422
        assert client.get('/api/overview?source=unknown').status_code == 422
        application.state.dashboard_history = DashboardHistory(reader=Mock(return_value=[]))
        result = client.get('/api/overview?source=bigquery&hours=1').json()
        assert result["snapshot_status"] == "empty"
        assert result["coverage"]["gap_minutes"] == 60
        assert result["summary"] is None


def test_bigquery_dashboard_query_is_scoped_budgeted_and_bounded():
    from app.services.bigquery_service import BigQueryService

    client = Mock()
    client.query.return_value.result.return_value = []
    store = BigQueryService("test-project", "asia-south1", "autocloud", "latest_metrics", client)
    store.read_dashboard("api' OR TRUE", NOW - timedelta(hours=1), NOW)
    sql = client.query.call_args.args[0]
    config = client.query.call_args.kwargs["job_config"]
    assert "api' OR TRUE" not in sql
    assert "project_id = @project" in sql
    assert "region = @region" in sql
    assert "timestamp <= @end" in sql and "LIMIT 1441" in sql
    assert config.maximum_bytes_billed == 100_000_000
    assert {p.name: p.value for p in config.query_parameters}["service"] == "api' OR TRUE"
    client.query.return_value.result.assert_called_once_with(timeout=20)
    with pytest.raises(ValueError):
        store.read_dashboard("api", NOW - timedelta(days=2), NOW)


def test_bigquery_timeout_requests_cancellation():
    from app.services.bigquery_service import BigQueryService

    client = Mock()
    client.query.return_value.result.side_effect = TimeoutError()
    store = BigQueryService("test-project", "asia-south1", "autocloud", "latest_metrics", client)
    with pytest.raises(TimeoutError):
        store.read_dashboard("api", NOW - timedelta(hours=1), NOW)
    client.query.return_value.cancel.assert_called_once_with(timeout=5)
