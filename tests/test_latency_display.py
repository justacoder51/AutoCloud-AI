"""Latency display preserves gaps and discloses historical measurement age."""

from copy import deepcopy

from app.dashboard.latency import latency_card


NOW = "2026-11-17T08:16:00+00:00"


def test_latest_idle_minute_retains_timestamped_historical_latency_without_filling():
    rows = [
        {"timestamp": "2026-11-17T08:12:00+00:00", "average_latency": 123.45, "request_count": 2},
        {"timestamp": "2026-11-17T08:13:00+00:00", "average_latency": None, "request_count": 0},
    ]
    original = deepcopy(rows)
    card = latency_card(list(reversed(rows)), NOW)
    assert card["value"] == "123.45"
    assert "Historical measurement" in card["caption"]
    assert "08:12:00+00:00" in card["caption"]
    assert "age 4m 0s" in card["caption"]
    assert "No requests measured" in card["caption"]
    assert rows == original


def test_missing_latency_describes_missing_collection_instead_of_asserting_no_traffic():
    for requests in (None, 4):
        card = latency_card([{"timestamp": NOW, "average_latency": None,
                              "request_count": requests}], NOW)
        assert card["value"] == "Not measured"
        assert "collection may be delayed or incomplete" in card["caption"]
        assert "No requests measured" not in card["caption"]


def test_stale_latency_is_historical_even_when_it_is_the_latest_observation():
    card = latency_card([{"timestamp": "2026-11-17T07:16:00+00:00",
                          "average_latency": 50}], NOW)
    assert card["value"] == "50.00"
    assert "Historical measurement" in card["caption"]
    assert "age 60m 0s" in card["caption"]


def test_measured_zero_is_valid_and_empty_window_is_not_fabricated():
    card = latency_card([{"timestamp": NOW, "average_latency": 0}], NOW)
    assert card["value"] == "0.00"
    assert "Latest measured minute" in card["caption"]
    assert latency_card([], NOW)["value"] == "Not measured"


def test_dashboard_renders_historical_latency_beside_latest_missing_metrics(tmp_path, monkeypatch):
    from datetime import datetime, timedelta
    from pathlib import Path
    from unittest.mock import Mock

    import httpx
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    from app.data.schema import MetricRecord
    from app.services.dashboard_service import overview

    now = datetime.fromisoformat(NOW)
    rows = [MetricRecord(timestamp=now - timedelta(minutes=minutes), collected_at=now,
                         project_id="test-project", region="asia-south1", service_name="autocloud-api",
                         request_count=requests, average_latency=latency).model_dump(mode="json")
            for minutes, requests, latency in ((4, 2, 123.45), (3, 0, None))]
    payload = overview(tmp_path, "test-project", "asia-south1", "autocloud-api", now, records=rows)
    payload["source"] = "bigquery"
    payload["capabilities"] = {}
    response = Mock(status_code=200)
    response.json.return_value = payload
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.get.return_value = response
    monkeypatch.setenv("DASHBOARD_PUBLIC_SHOWCASE", "true")
    monkeypatch.setenv("AUTOCLOUD_API_AUTH", "none")
    monkeypatch.setattr(httpx, "Client", Mock(return_value=client))
    st.cache_data.clear()
    try:
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app/dashboard/home.py")).run(timeout=30)
        assert not app.exception
        assert any(m.label == "Last measured latency (ms)" and m.value == "123.45" for m in app.metric)
        assert any("Historical measurement" in c.value and "No requests measured" in c.value for c in app.caption)
        assert payload["summary"]["latest_values"]["average_latency"] is None
    finally:
        st.cache_data.clear()
