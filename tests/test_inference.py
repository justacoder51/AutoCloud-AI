"""Native model IO checks use synthetic fixtures, never claimed production models."""

import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.data.schema import MetricRecord
from app.data.storage import serialize_records
from app.models.dataset import quality_report, regularize_history
from app.models.inference import checked_file, export_native_forecasts, predict_from_run
from app.models.resource_predictor import ResourcePredictor


def fixture_records(start, minutes):
    """Source-labelled records exercise schema gates in an isolated fixture project."""
    import math

    return [MetricRecord(
        timestamp=start + timedelta(minutes=i), collected_at=start + timedelta(minutes=i + 3),
        project_id="fixture-project", region="asia-south1", service_name="fixture-service",
        cpu_utilization=.4 + .1 * math.sin(i / 30), memory_utilization=.3 + .03 * math.cos(i / 40),
        request_count=20 + i % 8, network_ingress=1000 + i % 100,
        network_egress=2000 + i % 200, average_latency=50 + i % 10,
        error_rate=.01 + .001 * math.sin(i / 20), instance_count=1,
    ) for i in range(minutes)]


@pytest.fixture(scope="module")
def native_run(tmp_path_factory):
    directory = tmp_path_factory.mktemp("synthetic-native-run")
    training = fixture_records(datetime(2026, 11, 1, tzinfo=timezone.utc), 200)
    history = regularize_history(pd.DataFrame([row.model_dump() for row in training]))
    predictor = ResourcePredictor(depths=(2,))
    predictor.fit(history)
    snapshot = serialize_records(training).encode()
    (directory / "history.ndjson").write_bytes(snapshot)
    report = {
        "source": "gcp-monitoring", "trained": True, "quality": quality_report(history),
        "project": "fixture-project", "region": "asia-south1", "service": "fixture-service",
        "history_sha256": hashlib.sha256(snapshot).hexdigest(),
    }
    export_native_forecasts(predictor, directory, report)
    report["forecast_evaluation"] = predictor.report
    report["anomaly_evaluation"] = {"status": "not_evaluated"}
    (directory / "evaluation.json").write_text(json.dumps(report), encoding="utf-8")
    current = fixture_records(training[-1].timestamp + timedelta(minutes=1), 16)
    return directory, predictor, current


def predict(directory, rows, **changes):
    return predict_from_run(directory, rows, **{
        "project": "fixture-project", "region": "asia-south1", "service": "fixture-service",
        "now": rows[-1].timestamp + timedelta(minutes=3), **changes,
    })


def test_native_round_trip_matches_pipeline_predictions_and_keeps_baseline_evidence(native_run):
    directory, predictor, rows = native_run
    result = predict(directory, rows)
    expected = predictor.predict(regularize_history(pd.DataFrame([row.model_dump() for row in rows])))
    assert len(result) == 9
    for actual, reference in zip(result, expected):
        assert actual["prediction"] == pytest.approx(reference["prediction"])
        assert actual["confidence"] is None
        assert actual["method"] == "xgboost_offline_candidate"
        assert actual["training_profile"] == "exploratory"
        assert actual["evaluation_status"] == "preliminary_exploratory"
        assert actual["lead_time_from_assessment_seconds"] == (actual["horizon_minutes"] - 3) * 60
        assert actual["forecast_in_past"] is False
        assert actual["beats_persistence_mae"] == (
            actual["test_mae"] < actual["persistence_test_mae"]
        )


@pytest.mark.parametrize("change", ["model_hash", "history_hash", "version", "scope", "unknown_model", "old_horizons", "profile"])
def test_invalid_run_fails_before_inference(native_run, tmp_path, change):
    source, _, rows = native_run
    directory = tmp_path / "synthetic-clone"
    shutil.copytree(source, directory)
    manifest_path = directory / "forecast_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if change == "model_hash":
        path = directory / "cpu_utilization_15m.json"
        path.write_bytes(path.read_bytes() + b" ")
    elif change == "history_hash":
        path = directory / "history.ndjson"
        path.write_bytes(path.read_bytes() + b"\n")
    elif change == "version":
        manifest["xgboost_version"] = "invalid-version"
    elif change == "scope":
        manifest["project"] = "different-project"
    elif change == "unknown_model":
        manifest["models"]["../../unexpected"] = next(iter(manifest["models"].values()))
    elif change == "old_horizons":
        manifest["horizons_minutes"] = [15, 30, 60]
    else:
        manifest["training_profile"] = "conservative"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        predict(directory, rows)


def test_stale_gap_missing_target_and_in_sample_origins_are_rejected(native_run):
    directory, _, rows = native_run
    with pytest.raises(ValueError, match="fresh"):
        predict(directory, rows, now=rows[-1].timestamp + timedelta(hours=1))
    with pytest.raises(ValueError, match="sixteen"):
        predict(directory, rows[:5] + rows[6:])
    missing = [*rows[:-1], rows[-1].model_copy(update={"request_count": None})]
    with pytest.raises(ValueError, match="sixteen"):
        predict(directory, missing)
    past = fixture_records(rows[0].timestamp - timedelta(minutes=16), 16)
    with pytest.raises(ValueError, match="later than"):
        predict(directory, past)


def test_native_export_refuses_unready_training(native_run, tmp_path):
    _, predictor, _ = native_run
    with pytest.raises(ValueError, match="readiness"):
        export_native_forecasts(predictor, tmp_path, {"trained": False})


def test_future_evidence_path_escape_and_oversize_files_are_rejected(native_run, tmp_path):
    directory, _, rows = native_run
    future = [*rows[:-1], rows[-1].model_copy(update={
        "collected_at": rows[-1].timestamp + timedelta(hours=1),
    })]
    with pytest.raises(ValueError, match="future"):
        predict(directory, future)
    inner = tmp_path / "inner"
    inner.mkdir()
    (tmp_path / "outside.json").write_text("{}")
    with pytest.raises(ValueError, match="escapes"):
        checked_file(inner, "../outside.json", 100)
    (inner / "large.json").write_text("{}")
    with pytest.raises(ValueError, match="size limit"):
        checked_file(inner, "large.json", 1)


def test_short_horizon_expiry_is_measured_from_observation_not_wall_clock(native_run):
    directory, _, rows = native_run
    result = predict(directory, rows, now=rows[-1].timestamp + timedelta(minutes=8))
    for item in result:
        assert item["lead_time_from_assessment_seconds"] == (item["horizon_minutes"] - 8) * 60
        assert item["forecast_in_past"] == (item["horizon_minutes"] == 5)


def test_dashboard_evaluation_and_forecasts_are_separate_from_current_readiness(native_run):
    from app.services.model_dashboard import model_panel

    directory, _, rows = native_run
    result = model_panel([row.model_dump() for row in rows], str(directory),
                         project="fixture-project", region="asia-south1", service="fixture-service",
                         now=rows[-1].timestamp + timedelta(minutes=3))
    assert result["status"] == "candidate_evaluated"
    assert result["readiness"]["ready"] is False  # only 16 new inference minutes
    assert result["forecast_status"] == "candidate_available"
    assert len(result["evaluation"]["forecast_evaluation"]) == 9
    assert len(result["forecasts"]) == 9
    assert result["evaluation"]["evaluation_status"] == "preliminary_exploratory"
    comparison = result["evaluation"]["baseline_comparison"]
    evaluations = result["evaluation"]["forecast_evaluation"]
    assert comparison["models_evaluated"] == 9
    assert comparison["models_beating_persistence_mae"] == sum(
        row["test_mae"] < row["persistence_test_mae"] for row in evaluations)
    assert result["evaluation"]["training_quality"]["ready"] is True
    assert result["anomaly_results"] is None
    assert result["deployment_allowed"] is False


def test_dashboard_keeps_recorded_evaluation_when_forecast_origin_is_stale(native_run):
    from app.services.model_dashboard import model_panel

    directory, _, rows = native_run
    result = model_panel([row.model_dump() for row in rows], str(directory),
                         project="fixture-project", region="asia-south1", service="fixture-service",
                         now=rows[-1].timestamp + timedelta(hours=1))
    assert result["evaluation"] is not None
    assert result["forecast_status"] == "unavailable"
    assert result["forecasts"] is None


@pytest.mark.parametrize("change", ["scope", "score", "nonfinite", "samples"])
def test_dashboard_rejects_conflicting_or_nonfinite_evaluation(native_run, tmp_path, change):
    from app.models.inference import inspect_run

    source, _, rows = native_run
    directory = tmp_path / "evaluation-clone"
    shutil.copytree(source, directory)
    report = json.loads((directory / "evaluation.json").read_text())
    scores = next(iter(report["forecast_evaluation"].values()))["test"]
    if change == "scope":
        report["project"] = "wrong-project"
    elif change == "score":
        scores["mae"] += 1
    elif change == "nonfinite":
        scores["rmse"] = float("nan")
    else:
        scores["samples"] = 1
    (directory / "evaluation.json").write_text(json.dumps(report))
    with pytest.raises(ValueError):
        inspect_run(directory, project="fixture-project", region="asia-south1",
                    service="fixture-service", now=rows[-1].timestamp + timedelta(minutes=3))


def test_dashboard_never_selects_a_model_implicitly(native_run):
    from app.services.model_dashboard import model_panel

    _, _, rows = native_run
    result = model_panel([row.model_dump() for row in rows], None,
                         project="fixture-project", region="asia-south1", service="fixture-service",
                         now=rows[-1].timestamp + timedelta(minutes=3))
    assert result["status"] == "not_selected"
    assert result["evaluation"] is None
    assert result["forecasts"] is None


def test_inspect_run_validates_evaluated_anomaly_metrics(native_run, tmp_path):
    from app.models.inference import BinaryEvalScores, inspect_run

    source, _, rows = native_run
    directory = tmp_path / "evaluated-clone"
    shutil.copytree(source, directory)
    report = json.loads((directory / "evaluation.json").read_text())
    report["anomaly_evaluation"] = {
        "status": "evaluated_preliminary",
        "anomaly_detected": {
            "precision": 1.0,
            "recall": 0.95,
            "f1": 38 / 39,
            "confusion_matrix": [[20, 0], [1, 19]],
            "false_positive_rate": 0.0,
            "evaluated_samples": 40,
        },
        "threshold_baseline": {
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "confusion_matrix": [[20, 0], [20, 0]],
            "false_positive_rate": 0.0,
            "evaluated_samples": 40,
        },
    }
    (directory / "evaluation.json").write_text(json.dumps(report))
    inspected = inspect_run(
        directory,
        project="fixture-project",
        region="asia-south1",
        service="fixture-service",
        now=rows[-1].timestamp + timedelta(minutes=3),
    )
    assert inspected["anomaly_evaluation_status"] == "evaluated_preliminary"
    assert inspected["anomaly_evaluation"]["anomaly_detected"]["recall"] == 0.95

    # Zero-positive operational audit passes with defined FPR and 0 precision/recall/F1.
    BinaryEvalScores.model_validate({
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "confusion_matrix": [[40, 0], [0, 0]],
        "false_positive_rate": 0.0,
        "evaluated_samples": 40,
    })

    # Zero-negative case requires false_positive_rate=None.
    BinaryEvalScores.model_validate({
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
        "confusion_matrix": [[0, 0], [0, 5]],
        "false_positive_rate": None,
        "evaluated_samples": 5,
    })

    # Contradictory claimed metrics against [[0, 10], [10, 0]] must be rejected.
    for bad_scores in (
        {
            "precision": 1.0,
            "recall": 1.0,
            "f1": 1.0,
            "confusion_matrix": [[0, 10], [10, 0]],
            "false_positive_rate": 0.0,
            "evaluated_samples": 20,
        },
        {
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "confusion_matrix": [[20, 0], [0, 0]],
            "false_positive_rate": None,
            "evaluated_samples": 20,
        },
    ):
        with pytest.raises(ValueError):
            BinaryEvalScores.model_validate(bad_scores)

    # Reject non-finite, malformed, or contradictory confusion matrix in inspect_run.
    bad_report = json.loads((directory / "evaluation.json").read_text())
    bad_report["anomaly_evaluation"]["anomaly_detected"]["confusion_matrix"] = [[1, 0], [0, 1]]
    (directory / "evaluation.json").write_text(json.dumps(bad_report))
    with pytest.raises(ValueError):
        inspect_run(
            directory,
            project="fixture-project",
            region="asia-south1",
            service="fixture-service",
            now=rows[-1].timestamp + timedelta(minutes=3),
        )


def test_recorded_production_evaluation_artifact_contract():
    """Verify packaged config/dashboard-evaluation.json passes schema, scope, and checksum checks."""
    from pathlib import Path
    from app.services.recorded_evaluation import load_recorded_evaluation

    eval_path = Path(__file__).resolve().parents[1] / "config" / "dashboard-evaluation.json"
    digest = hashlib.sha256(eval_path.read_bytes()).hexdigest()
    loaded = load_recorded_evaluation(
        str(eval_path), digest, "astute-sign-506809-j8", "asia-south1", "autocloud-api",
    )
    assert loaded["deployment_allowed"] is False
    assert loaded["anomaly_evaluation_status"] == "evaluated_preliminary"
    assert loaded["anomaly_evaluation"]["anomaly_detected"]["evaluated_samples"] == 47
    assert loaded["anomaly_evaluation"]["shared_observable_comparison"]["evaluated_samples"] == 41
    assert loaded["anomaly_evaluation"]["operational_fault_audit"]["fault_sensitivity_measured"] is False
    assert loaded["forecast_diagnostics"]["models_evaluated"] == 9
    assert loaded["forecast_diagnostics"]["models_beating_persistence_mae"] == 0
    assert loaded["forecast_diagnostics"]["data_characteristics"]["grid_minutes"] == 232


def test_streamlit_models_tab_renders_fixture_evaluation_and_expired_forecasts(native_run, monkeypatch, tmp_path):
    """UI-only synthetic fixture; makes no HTTP/cloud requests and proves no real accuracy."""
    from pathlib import Path
    from unittest.mock import Mock
    import tempfile
    import httpx
    from app.services.dashboard_service import overview
    from app.services.model_dashboard import model_panel

    AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    directory, _, rows = native_run
    now = rows[-1].timestamp + timedelta(minutes=8)
    payload = overview(tmp_path, "fixture-project", "asia-south1", "fixture-service", now,
                       records=[row.model_dump() for row in rows])
    payload["source"] = "bigquery"  # Mock response for the default source selector.
    payload["models"] = model_panel(payload["records"], str(directory), project="fixture-project",
                                    region="asia-south1", service="fixture-service", now=now)
    response = Mock()
    response.json.return_value = payload
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.get.return_value = response
    monkeypatch.setattr(httpx, "Client", Mock(return_value=client))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app/dashboard/home.py")).run(timeout=30)
    assert not app.exception
    assert any("Some forecast times have already passed" in item.value for item in app.warning)
    assert len(app.dataframe) == 2
    future_count = sum(f["forecast_in_past"] is False for f in payload["models"]["forecasts"])
    assert len(app.dataframe[0].value) == future_count
    assert "Model estimate" in app.dataframe[0].value.columns
    assert len(app.dataframe[1].value) == 9
    assert any(item.label == "Original test: forecasts with lower error" for item in app.metric)


def test_saved_real_run_observation_only_xgboost_and_isolation_forest_parity(tmp_path):
    """Saved pure-JSON XGBoost + Isolation Forest work observation-only without joblib/pickle."""
    from pathlib import Path
    import numpy as np
    from app.models.dataset import lag_features, regularize_history
    from app.models.inference import (
        AnomalyManifest,
        _score_isolation_forest_pure,
        predict_anomalies_from_run,
        predict_from_run,
    )
    from app.services.model_dashboard import model_panel

    run_dir = Path(__file__).resolve().parents[1] / "models" / "runs" / "20261116T051914Z_48d41482"
    manifest = AnomalyManifest.model_validate_json((run_dir / "anomaly_manifest.json").read_text())
    payload_trees = json.loads((run_dir / "anomaly_detector.json").read_text())
    trees = payload_trees["trees"]
    assert len(trees) == manifest.n_estimators

    # Verify exact numerical parity against scikit-learn on the real saved training cohort.
    history_rows = [
        MetricRecord.model_validate_json(line)
        for line in (run_dir / "history.ndjson").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    hist_df = regularize_history(
        pd.DataFrame([r.model_dump() for r in history_rows])
    )
    feats = hist_df[list(manifest.feature_names)].dropna()
    pure_scores = _score_isolation_forest_pure(feats.to_numpy(dtype=float), manifest, trees)

    import joblib

    sk_model = joblib.load(run_dir / "anomaly_detector.joblib")
    sk_scores = sk_model.pipeline.decision_function(feats)
    assert np.allclose(pure_scores, sk_scores, atol=1e-12)

    # Shift recent slice to a fresh post-cutoff timestamp window to exercise live observation-only gating.
    base_now = max(datetime.now(timezone.utc).replace(second=0, microsecond=0),
                   manifest.training_history_end + timedelta(hours=1))
    sample_slice = history_rows[182:212]
    fresh_rows = []
    for idx, row in enumerate(sample_slice):
        ts = base_now - timedelta(minutes=len(sample_slice) - 1 - idx + 2)
        payload = row.model_dump()
        payload["timestamp"] = ts
        payload["collected_at"] = base_now
        # Leave optional latency field missing on one middle row to check missingness reporting.
        if idx == len(sample_slice) - 2:
            payload["average_latency"] = None
        fresh_rows.append(MetricRecord.model_validate(payload))

    forecasts = predict_from_run(
        run_dir, fresh_rows,
        project="astute-sign-506809-j8", region="asia-south1", service="autocloud-api", now=base_now,
    )
    assert len(forecasts) == 9
    for item in forecasts:
        assert item["experimental"] is True
        assert item["observation_only"] is True
        assert item["execution_allowed"] is False
        assert "persistence_prediction" in item
        assert "delta_from_persistence" in item
        assert item["recent_observed_minutes"] == 16

    anomalies = predict_anomalies_from_run(
        run_dir, fresh_rows,
        project="astute-sign-506809-j8", region="asia-south1", service="autocloud-api", now=base_now,
    )
    assert anomalies["experimental"] is True
    assert anomalies["observation_only"] is True
    assert anomalies["execution_allowed"] is False
    assert anomalies["deployment_allowed"] is False
    assert "42.55%" in anomalies["limitations"]
    assert "95.24%" in anomalies["limitations"]
    assert anomalies["missing_feature_cells"] >= 1
    assert len(anomalies["rows"]) == len(fresh_rows)

    fresh_panel = model_panel(
        [r.model_dump() for r in fresh_rows],
        str(run_dir),
        project="astute-sign-506809-j8",
        region="asia-south1",
        service="autocloud-api",
        now=base_now,
    )
    assert fresh_panel["execution_allowed"] is False
    assert fresh_panel["deployment_allowed"] is False
    assert fresh_panel["forecast_status"] == "candidate_available"
    assert fresh_panel["anomaly_status"] == "experimental_observation_only"

    # Freshness gate: >15m stale -> both forecast & anomaly become explicitly unavailable.
    stale_panel = model_panel(
        [r.model_dump() for r in fresh_rows],
        str(run_dir),
        project="astute-sign-506809-j8",
        region="asia-south1",
        service="autocloud-api",
        now=fresh_rows[-1].timestamp + timedelta(minutes=16),
    )
    assert stale_panel["forecast_status"] == "unavailable"
    assert stale_panel["anomaly_status"] == "unavailable"
    assert stale_panel["forecasts"] is None
    assert stale_panel["anomaly_results"] is None

    # Wrong service scope: autocloud-dashboard cannot reuse autocloud-api model run.
    wrong_scope = model_panel(
        [r.model_copy(update={"service_name": "autocloud-dashboard"}).model_dump() for r in fresh_rows],
        str(run_dir),
        project="astute-sign-506809-j8",
        region="asia-south1",
        service="autocloud-dashboard",
        now=base_now,
    )
    assert wrong_scope["status"] == "unavailable_for_target"
    assert wrong_scope["forecast_status"] == "unavailable"
    assert wrong_scope["anomaly_status"] == "unavailable"
