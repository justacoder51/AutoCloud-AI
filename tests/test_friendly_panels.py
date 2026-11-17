"""Exercise presentation states without cloud calls or local socket access."""

from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from app.dashboard import advice_panels, model_panels


def capture_ui(monkeypatch, module):
    ui = MagicMock()
    ui.columns.side_effect = lambda count: [ui for _ in range(count)]
    monkeypatch.setattr(module, "st", ui)
    return ui


def text(ui):
    return " ".join(str(call) for call in ui.mock_calls)


@pytest.mark.parametrize("flag,threshold,expected", [
    (True, False, "Unusual pattern"), (True, True, "Review this measured activity"),
    (False, True, "monitoring limit"), (False, False, "No flag"),
    (None, None, "Assessment incomplete"),
])
def test_distinguishes_model_flags_thresholds_and_unknown_evidence(flag, threshold, expected):
    title, message = model_panels.anomaly_message({"rows": [{}],
        "latest_anomaly_detected": flag, "latest_threshold_baseline": threshold})
    assert expected in title
    assert "healthy" not in title.lower()


def test_stale_or_absent_assessment_is_not_presented_as_current():
    assert model_panels.anomaly_message({})[0] == "No current anomaly assessment"
    title, message = model_panels.anomaly_message({"rows": [{}], "age_seconds": 901,
        "latest_anomaly_detected": True, "latest_threshold_baseline": True})
    assert title == "Historical assessment"


def test_missing_models_show_explanations_and_no_invented_accuracy(monkeypatch):
    ui = capture_ui(monkeypatch, model_panels)
    model_panels.render_models({"models": {}})
    shown = text(ui)
    assert "16 consecutive minutes" in shown
    assert "Not evaluated" in shown
    assert "0 / 9" not in shown
    assert "cost savings have not been established" in shown


def test_saved_studies_keep_original_and_newer_results_distinct(monkeypatch):
    ui = capture_ui(monkeypatch, model_panels)
    root = Path(__file__).resolve().parents[1]
    validation = json.loads((root / "config/measured-validation.json").read_text())
    evaluation = json.loads((root / "config/dashboard-evaluation.json").read_text())["evaluation"]
    data = {"models": {"evaluation": evaluation}, "measured_validation": validation}
    before = deepcopy(data)
    model_panels.render_models(data)
    shown = text(ui)
    assert "Original test" in shown and "Newer study" in shown
    assert "0 / 9" in shown and "3 / 9" in shown
    assert "not an accuracy percentage" in shown
    assert "35" in shown and "false alarms" in shown
    assert "include zero" in shown
    assert data == before


def test_forecast_table_formats_percentages_and_excludes_expired_horizons(monkeypatch):
    ui = capture_ui(monkeypatch, model_panels)
    base = {"target": "cpu_utilization", "horizon_minutes": 5,
            "timestamp": "2026-11-17T08:20:00Z", "origin": "2026-11-17T08:15:00Z",
            "prediction": .25, "persistence_prediction": .2, "forecast_in_past": False}
    model_panels.render_models({"models": {"forecasts": [base, {**base, "forecast_in_past": True, "prediction": .99}]},
        "records": [{"timestamp": "2026-11-17T08:15:00Z", "cpu_utilization": .2,
                     "memory_utilization": .4, "request_count": 3}]})
    table = ui.dataframe.call_args_list[0].args[0]
    assert len(table) == 1
    assert table.iloc[0]["Model estimate"] == "25.0%"
    assert table.iloc[0]["Keep current value"] == "20.0%"
    assert "IST" in table.iloc[0]["Prediction for"]
    chart = ui.line_chart.call_args.args[0]
    assert chart["Experimental estimate"].dropna().iloc[0] == 25
    assert chart["Measured"].dropna().iloc[0] == 20


def test_advice_has_next_steps_keeps_evidence_and_never_makes_http_requests(monkeypatch):
    import httpx
    blocker = Mock(side_effect=AssertionError("Rendering must not call an API"))
    monkeypatch.setattr(httpx, "Client", blocker)
    ui = capture_ui(monkeypatch, advice_panels)
    evidence = {"latest_decision_score": -.1867, "latest_threshold_baseline": False}
    data = {"assessed_at": "2026-11-17T08:16:00Z", "public_advice": {"data_status": "fresh",
        "items": [{"id": "inspect_anomaly", "title": "Original title", "kind": "experimental",
                   "explanation": "The flag does not establish a fault.", "evidence": evidence}]}}
    before = deepcopy(data)
    advice_panels.render_advice(data)
    shown = text(ui)
    assert "Next step" in shown and "simply idle" in shown
    assert "needs confirmation" in shown
    ui.json.assert_called_once_with(evidence)
    assert data == before
    blocker.assert_not_called()


def test_stale_advice_warns_before_capacity_decisions(monkeypatch):
    ui = capture_ui(monkeypatch, advice_panels)
    advice_panels.render_advice({})
    assert "not confirmed fresh" in text(ui)
    assert "not a confirmation" in text(ui)


@pytest.mark.parametrize("status,words", [
    ("skipped_stale", "not fresh enough"), ("failed", "response checks"),
    ("disabled", "switched off"), ("budget_unavailable", "storage"),
    ("hourly_limit", "hourly"), ("unknown_future_status", "does not establish a specific cause"),
])
def test_gemini_fallback_explains_recorded_status_without_inventing_a_cause(status, words):
    assert words in advice_panels.gemini_status_message(status)
