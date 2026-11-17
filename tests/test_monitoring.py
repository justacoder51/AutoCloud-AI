"""Offline fixtures verify math and cloud adapters; none are production data."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.data.collector import collection_interval
from app.data.processor import process_samples
from app.data.schema import MetricRecord, MetricSample
from app.data.storage import save_records
from app.services.gcp_monitoring import CloudMonitoringService, decode_series, make_request

END = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
START = END - timedelta(minutes=5)
PROJECT = "astute-sign-506809-j8"


def sample(metric, value, key="revision-a", weight=1, code="", timestamp=END):
    return MetricSample(
        timestamp=timestamp, metric=metric, value=value, weight=weight,
        series_key=key, response_code=code,
    )


def process(samples):
    return process_samples(samples, PROJECT, "asia-south1", "autocloud-api", START, END, END)


def test_weighted_distribution_means_and_label_sums():
    records = process([
        sample("cpu_utilization", .2, weight=9),
        sample("cpu_utilization", .8, "revision-b", weight=1),
        sample("average_latency", 100, weight=2),
        sample("average_latency", 400, "revision-b", weight=1),
        sample("instance_count", 1.5, "active"),
        sample("instance_count", 2, "idle"),
        sample("network_ingress", 20, "internet"),
        sample("network_ingress", 80, "google"),
    ])
    row = records[0]
    assert row.cpu_utilization == pytest.approx(.26)
    assert row.average_latency == 200
    assert row.instance_count == 3.5
    assert row.network_ingress == 100
    assert row.request_count is None
    assert "request_count" in row.missing_fields
    assert row.source == "gcp-monitoring"


def test_error_rate_uses_only_5xx_and_deduplicates_exact_series():
    success = sample("request_count", 80, "ok", code="2xx")
    row = process([
        success, success,
        sample("request_count", 10, "client-errors", code="404"),
        sample("request_count", 10, "server-errors", code="5xx"),
    ])[0]
    assert row.request_count == 100
    assert row.error_rate == .1


@pytest.mark.parametrize("code,count,expected", [
    ("200", 5, 0), ("", 5, None), ("other", 5, None), ("2xx", 0, None),
])
def test_missing_labels_and_no_traffic_are_not_invented_rates(code, count, expected):
    row = process([sample("request_count", count, code=code)])[0]
    assert row.error_rate == expected
    assert row.memory_utilization is None


def test_no_observations_yields_no_synthetic_rows():
    assert process([]) == []
    assert process([sample("cpu_utilization", .2, timestamp=START)]) == []
    assert process([sample("cpu_utilization", .2, timestamp=END + timedelta(minutes=1))]) == []


def test_invalid_utilization_is_missing_and_fractional_counters_removed():
    row = process([
        sample("cpu_utilization", 25),
        sample("request_count", 1.5),
        sample("memory_utilization", .3),
    ])[0]
    assert row.cpu_utilization is None
    assert row.request_count is None
    assert row.memory_utilization == .3


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_invalid_samples_rejected(value):
    with pytest.raises(ValidationError):
        sample("cpu_utilization", value)


def test_minute_window_lag_and_no_timezone_guessing():
    start, end = collection_interval(END + timedelta(seconds=49), 60)
    assert end == END - timedelta(minutes=3)
    assert end - start == timedelta(minutes=60)
    with pytest.raises(ValueError):
        collection_interval(datetime(2026, 11, 15), 60)
    with pytest.raises(ValueError):
        collection_interval(END, 1441)


def test_monitoring_requests_preserve_distribution_and_filter_service():
    request = make_request(PROJECT, "asia-south1", "autocloud-api", "cpu_utilization", START, END)
    assert request["aggregation"]["per_series_aligner"] == "ALIGN_SUM"
    assert request["aggregation"]["alignment_period"] == {"seconds": 60}
    assert 'resource.type="cloud_run_revision"' in request["filter"]
    assert 'resource.labels.location="asia-south1"' in request["filter"]
    assert request["view"] == "FULL"
    gauge = make_request(PROJECT, "asia-south1", "autocloud-api", "instance_count", START, END)
    assert gauge["aggregation"]["per_series_aligner"] == "ALIGN_MEAN"
    with pytest.raises(ValueError):
        make_request(PROJECT, "asia-south1", 'x" OR true', "request_count", START, END)


def test_monitoring_api_errors_propagate():
    client = Mock()
    client.list_time_series.return_value = []
    adapter = CloudMonitoringService(client)
    assert adapter.collect(PROJECT, "asia-south1", "autocloud-api", START, END) == []
    assert client.list_time_series.call_count == 7
    client.list_time_series.side_effect = PermissionError("fixture")
    with pytest.raises(PermissionError):
        CloudMonitoringService(client).collect(PROJECT, "asia-south1", "autocloud-api", START, END)


def test_decode_distribution_keeps_actual_sample_count():
    series = SimpleNamespace(
        metric=SimpleNamespace(labels={}), resource=SimpleNamespace(labels={"revision_name": "a"}),
        points=[SimpleNamespace(
            interval=SimpleNamespace(end_time=END),
            value=SimpleNamespace(distribution_value=SimpleNamespace(mean=.4, count=10)),
        )],
    )
    point = decode_series("cpu_utilization", series)[0]
    assert point.value == .4
    assert point.weight == 10
    series.points[0].value.distribution_value.count = 0
    assert decode_series("cpu_utilization", series) == []


def test_storage_preserves_nulls_and_logical_keys(tmp_path):
    row = process([sample("cpu_utilization", .5)])[0]
    later = MetricRecord(**{**row.model_dump(), "collected_at": END + timedelta(minutes=1)})
    assert row.record_id == later.record_id
    output = tmp_path / "observations.ndjson"
    save_records([row], output)
    payload = json.loads(output.read_text())
    assert payload["request_count"] is None
    assert payload["source"] == "gcp-monitoring"
    save_records([], output)
    assert output.read_text() == ""


def test_bigquery_batch_retry_and_error_handling():
    pytest.importorskip("google.cloud.bigquery")
    from google.api_core.exceptions import Conflict
    from app.services.bigquery_service import BigQueryService

    client = Mock()
    client.get_table.return_value = SimpleNamespace(location="asia-south1")
    store = BigQueryService(PROJECT, "asia-south1", "autocloud", "infrastructure_metrics", client)
    rows = process([sample("cpu_utilization", .5)])
    assert store.write([]) == 0
    assert store.write(rows) == 1
    first_job_id = client.load_table_from_json.call_args.kwargs["job_id"]
    assert store.write(rows) == 1
    assert client.load_table_from_json.call_args.kwargs["job_id"] == first_job_id
    config = client.load_table_from_json.call_args.kwargs["job_config"]
    assert config.create_disposition == "CREATE_NEVER"
    client.load_table_from_json.side_effect = Conflict("existing job")
    assert store.write(rows) == 1
    assert client.get_job.call_args.args[0] == first_job_id
    client.get_job.return_value.result.side_effect = RuntimeError("load failure")
    with pytest.raises(RuntimeError):
        store.write(rows)


def test_bigquery_refuses_wrong_region():
    pytest.importorskip("google.cloud.bigquery")
    from app.services.bigquery_service import BigQueryService

    client = Mock()
    client.get_table.return_value = SimpleNamespace(location="US")
    store = BigQueryService(PROJECT, "asia-south1", "autocloud", "infrastructure_metrics", client)
    with pytest.raises(ValueError):
        store.write(process([sample("cpu_utilization", .5)]))
    client.load_table_from_json.assert_not_called()


def test_bigquery_history_is_parameterized_and_budgeted():
    pytest.importorskip("google.cloud.bigquery")
    from app.services.bigquery_service import BigQueryService

    client = Mock()
    client.query.return_value.result.return_value = [{"service_name": "fixture"}]
    store = BigQueryService(PROJECT, "asia-south1", "autocloud", "latest_metrics", client)
    untrusted_service = "fixture' OR TRUE"
    assert store.read_history(untrusted_service) == [{"service_name": "fixture"}]
    query = client.query.call_args.args[0]
    config = client.query.call_args.kwargs["job_config"]
    assert untrusted_service not in query
    assert config.maximum_bytes_billed == 100_000_000
    assert config.query_parameters[0].value == untrusted_service
    with pytest.raises(ValueError):
        store.read_history("fixture", days=31)
