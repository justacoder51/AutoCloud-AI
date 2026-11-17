"""ML checks use explicitly synthetic fixtures, never production measurements."""

import numpy as np
import pandas as pd
import pytest
from sklearn.tree import DecisionTreeRegressor

from app.models.anomaly_detector import AnomalyDetector, classification_metrics, threshold_flags
from app.models.dataset import (
    FEATURES, HORIZONS, chronological_masks, lag_features, quality_report, regularize_history,
)
from app.models.resource_predictor import ResourcePredictor, regression_metrics
from app.models.train import evaluate_anomalies


def synthetic_fixture(minutes=1800):
    """Deterministic fixture for checking algorithms and split mechanics only."""
    time = np.arange(minutes)
    timestamp = pd.date_range("2026-11-01", periods=minutes, freq="min", tz="UTC")
    return pd.DataFrame({
        "timestamp": timestamp, "collected_at": timestamp + pd.Timedelta(3, unit="min"),
        "project_id": "fixture-project", "region": "asia-south1", "service_name": "fixture",
        "source": "synthetic-fixture", "cpu_utilization": .4 + .1 * np.sin(time / 30),
        "memory_utilization": .3 + .03 * np.cos(time / 40),
        "request_count": 20 + np.floor(5 * np.sin(time / 20)),
        "network_ingress": 1000 + time % 100, "network_egress": 2000 + time % 200,
        "average_latency": 50 + 5 * np.cos(time / 10),
        "error_rate": .01 + .001 * np.sin(time / 20), "instance_count": 1.,
    })


def test_quality_rejects_tiny_or_sparse_history():
    tiny = regularize_history(synthetic_fixture(29))
    assert not quality_report(tiny)["ready"]
    complete = regularize_history(synthetic_fixture())
    assert quality_report(complete)["ready"]
    complete.loc[complete.index[100:], "average_latency"] = np.nan
    assert not quality_report(complete)["ready"]


def test_short_horizons_and_exploratory_gate_keep_conservative_profile_available():
    assert HORIZONS == (5, 10, 15)
    history = regularize_history(synthetic_fixture(200))
    exploratory = quality_report(history)
    assert exploratory["ready"]
    assert exploratory["profile"] == "exploratory"
    assert exploratory["minimum_observed_minutes"] == 200
    assert exploratory["deployment_ready"] is False
    for counts in exploratory["forecast_split_samples"].values():
        assert counts["train"] >= 100
        assert counts["validation"] >= 20
        assert counts["test"] >= 20
    conservative = quality_report(history, "conservative")
    assert not conservative["ready"]
    assert conservative["minimum_observed_minutes"] == 1440
    with pytest.raises(ValueError, match="profile"):
        quality_report(history, "unknown")


def test_200_minutes_does_not_override_sparse_labels_or_missingness():
    history = regularize_history(synthetic_fixture(200))
    history.loc[history.index[:20], "cpu_utilization"] = np.nan
    result = quality_report(history)
    assert result["missing_fraction"]["cpu_utilization"] == .1
    assert not result["ready"]
    assert any("100 train/20 validation/20 test" in reason for reason in result["reasons"])
    history = regularize_history(synthetic_fixture(200))
    history.loc[history.index[:50], "memory_utilization"] = np.nan
    assert not quality_report(history)["ready"]


def test_exploratory_200_minute_fit_preserves_all_nine_horizon_target_evaluations():
    history = regularize_history(synthetic_fixture(200))
    predictor = ResourcePredictor(factory=lambda depth: DecisionTreeRegressor(max_depth=depth, random_state=42))
    report = predictor.fit(history)
    assert set(report) == {f"{target}_{horizon}m" for target in ("cpu_utilization", "memory_utilization", "request_count") for horizon in (5, 10, 15)}
    assert {item["horizon_minutes"] for item in predictor.predict(history)} == {5, 10, 15}
    for key, info in report.items():
        assert info["split_samples"] == quality_report(history)["forecast_split_samples"][key]


def test_history_gaps_and_deduplication_remain_explicit():
    frame = synthetic_fixture(20)
    duplicate = frame.iloc[[0]].copy()
    duplicate["collected_at"] += pd.Timedelta(1, unit="min")
    duplicate["cpu_utilization"] = .8
    history = regularize_history(pd.concat([frame.drop(index=5), duplicate]))
    assert len(history) == 20
    assert not history.iloc[5]["observed"]
    assert history.iloc[5][list(FEATURES)].isna().all()
    assert history.iloc[0]["cpu_utilization"] == .8


def test_history_rejects_mixed_services_and_naive_timestamps():
    frame = synthetic_fixture(20)
    frame.loc[0, "service_name"] = "different"
    with pytest.raises(ValueError):
        regularize_history(frame)
    frame = synthetic_fixture(20)
    frame["timestamp"] = frame["timestamp"].dt.tz_localize(None)
    with pytest.raises(ValueError):
        regularize_history(frame)


@pytest.mark.parametrize("horizon", HORIZONS)
def test_forecast_labels_cannot_cross_split_boundaries(horizon):
    history = regularize_history(synthetic_fixture(900))
    index = history.index
    split = chronological_masks(index, horizon)
    gap = pd.Timedelta(horizon, unit="min")
    assert index[split["train"]][-1] + gap < index[split["validation"]][0]
    assert index[split["validation"]][-1] + gap < index[split["test"]][0]
    assert index[split["test"]][-1] + gap <= index[-1]
    assert not (split["train"] & split["test"]).any()


def test_future_values_do_not_change_past_features():
    history = regularize_history(synthetic_fixture(300))
    before = lag_features(history)
    altered = history.copy()
    altered.loc[altered.index[200:], list(FEATURES)] = 999
    after = lag_features(altered)
    pd.testing.assert_frame_equal(before.iloc[:200], after.iloc[:200])
    assert pd.isna(before.iloc[0]["cpu_utilization_lag_1"])


def test_regression_metrics_handle_zero_targets():
    result = regression_metrics(np.array([0., 2.]), np.array([1., 3.]))
    assert result["mae"] == 1
    assert result["rmse"] == 1
    assert result["mape"] == 50
    assert result["mape_samples"] == 1
    assert regression_metrics(np.zeros(2), np.ones(2))["mape"] is None
    with pytest.raises(ValueError):
        regression_metrics(np.array([np.nan]), np.array([0.]))


def test_threshold_baseline_and_binary_evaluation():
    data = regularize_history(synthetic_fixture(20))
    data.loc[data.index[0], "cpu_utilization"] = .99
    data.loc[data.index[1], list(FEATURES)] = np.nan
    flags = threshold_flags(data)
    assert flags.iloc[0]
    assert pd.isna(flags.iloc[1])
    result = classification_metrics(np.array([0, 0, 1, 1]), np.array([0, 1, 0, 1]))
    assert result["confusion_matrix"] == [[1, 1], [1, 1]]
    assert result["precision"] == result["recall"] == result["f1"] == .5
    assert result["false_positive_rate"] == .5


def test_isolation_training_imputation_and_unknown_predictions():
    history = regularize_history(synthetic_fixture(300))
    training = history.iloc[:200].copy()
    training.iloc[0, training.columns.get_loc("cpu_utilization")] = np.nan
    detector = AnomalyDetector().fit(training)
    expected = training[list(FEATURES)].median().to_numpy()
    np.testing.assert_allclose(detector.pipeline.named_steps["imputer"].statistics_, expected)
    observations = history.iloc[200:203].copy()
    observations.loc[observations.index[-1], list(FEATURES)] = np.nan
    result = detector.predict(observations)
    assert all(row["confidence"] is None for row in result)
    assert result[-1]["anomaly_detected"] is None
    assert result[-1]["decision_score"] is None
    assert result[-1]["severity"] == "unknown"


def test_anomaly_evaluation_needs_independent_labels(tmp_path):
    result = [{
        "timestamp": "2026-11-01T00:00:00+00:00",
        "anomaly_detected": True, "threshold_baseline": False,
    }]
    no_labels = evaluate_anomalies(result, None)
    assert no_labels["status"] == "not_evaluated"
    labels = tmp_path / "fixture-labels.csv"
    labels.write_text("timestamp,anomaly_label\n2026-11-01T00:00:00+00:00,1\n", encoding="utf-8")
    report = evaluate_anomalies(result, labels)
    assert report["status"] == "evaluated"
    assert report["schema_version"] == 1
    assert report["anomaly_detected"]["recall"] == 1
    assert report["threshold_baseline"]["recall"] == 0
    assert report["coverage"]["shared_observable_rows"] == 1
    assert report["shared_observable_comparison"]["evaluated_samples"] == 1

    # Non-overlapping label timestamps remain not_evaluated.
    disjoint = tmp_path / "disjoint-labels.csv"
    disjoint.write_text("timestamp,anomaly_label\n2026-11-02T00:00:00+00:00,1\n", encoding="utf-8")
    assert evaluate_anomalies(result, disjoint)["status"] == "not_evaluated"


def test_training_labelled_evaluation_survives_inspect_run(tmp_path):
    pytest.importorskip("xgboost", reason="Install requirements-ml.txt for native forecast export")
    import hashlib
    import json
    from datetime import timedelta
    from app.data.schema import MetricRecord
    from app.data.storage import serialize_records
    from app.models.inference import export_native_forecasts, inspect_run

    frame = synthetic_fixture(220)
    records = [
        MetricRecord.model_validate({
            **row,
            "source": "gcp-monitoring",
            "request_count": int(row["request_count"]),
            "network_ingress": int(row["network_ingress"]),
            "network_egress": int(row["network_egress"]),
        })
        for row in frame.to_dict(orient="records")
    ]
    data = regularize_history(pd.DataFrame([record.model_dump() for record in records]))
    split = chronological_masks(data.index)
    detector = AnomalyDetector().fit(data.loc[split["train"]])
    test_results = detector.predict(data.loc[split["test"]])
    test_index = data.loc[split["test"]].index
    labels = tmp_path / "train-cli-labels.csv"
    labels.write_text(
        "timestamp,anomaly_label\n"
        + "\n".join(f"{ts.isoformat()},{1 if i >= len(test_index) // 2 else 0}" for i, ts in enumerate(test_index))
        + "\n",
        encoding="utf-8",
    )

    predictor = ResourcePredictor(depths=(2,))
    forecast_report = predictor.fit(data)
    snapshot = serialize_records(records).encode("utf-8")
    run_dir = tmp_path / "labelled_train_run"
    run_dir.mkdir()
    (run_dir / "history.ndjson").write_bytes(snapshot)
    report = {
        "source": "gcp-monitoring",
        "trained": True,
        "quality": quality_report(data, "exploratory"),
        "project": "fixture-project",
        "region": "asia-south1",
        "service": "fixture",
        "history_sha256": hashlib.sha256(snapshot).hexdigest(),
        "forecast_evaluation": forecast_report,
        "anomaly_evaluation": evaluate_anomalies(test_results, labels),
    }
    export_native_forecasts(predictor, run_dir, report)
    (run_dir / "evaluation.json").write_text(json.dumps(report), encoding="utf-8")

    inspected = inspect_run(
        run_dir,
        project="fixture-project",
        region="asia-south1",
        service="fixture",
        now=data.index[-1] + timedelta(minutes=3),
    )
    assert inspected["anomaly_evaluation_status"] == "evaluated"
    assert inspected["anomaly_evaluation"]["shared_observable_comparison"]["evaluated_samples"] == len(test_index)
    assert json.loads(json.dumps(inspected))["anomaly_evaluation_status"] == "evaluated"

    # Disjoint label overlap stays unevaluated across inspect_run.
    disjoint = tmp_path / "disjoint.csv"
    disjoint.write_text("timestamp,anomaly_label\n2026-12-01T00:00:00+00:00,1\n", encoding="utf-8")
    report["anomaly_evaluation"] = evaluate_anomalies(test_results, disjoint)
    (run_dir / "evaluation.json").write_text(json.dumps(report), encoding="utf-8")
    inspected_disjoint = inspect_run(
        run_dir,
        project="fixture-project",
        region="asia-south1",
        service="fixture",
        now=data.index[-1] + timedelta(minutes=3),
    )
    assert inspected_disjoint["anomaly_evaluation_status"] == "not_evaluated"
    assert "anomaly_evaluation" not in inspected_disjoint


def test_forecast_protocol_with_small_cpu_test_estimator():
    # This checks split/selection/preprocessing mechanics, not XGBoost accuracy.
    history = regularize_history(synthetic_fixture(900))
    predictor = ResourcePredictor(
        factory=lambda depth: DecisionTreeRegressor(max_depth=depth, random_state=42),
    )
    report = predictor.fit(history)
    assert len(report) == 9
    for info in report.values():
        assert info["max_training_label_time"] < info["first_validation_origin"]
        assert info["max_validation_label_time"] < info["first_test_origin"]
        assert np.isfinite(info["test"]["mae"])
        assert info["persistence_test"]["samples"] == info["test"]["samples"]
        assert info["historical_average_test"]["samples"] == info["test"]["samples"]
        assert isinstance(info["beats_historical_average_mae"], bool)
    forecasts = predictor.predict(history)
    assert len(forecasts) == 9
    assert all(row["prediction"] >= 0 and row["confidence"] is None for row in forecasts)
    assert all(row["prediction"] <= 1 for row in forecasts if row["target"] != "request_count")
    history.loc[history.index[-1], "request_count"] = np.nan
    with pytest.raises(ValueError):
        predictor.predict(history)


def test_real_xgboost_cpu_integration(tmp_path):
    pytest.importorskip(
        "xgboost", reason="Install requirements-ml.txt for the real CPU integration",
    )
    history = regularize_history(synthetic_fixture(900))
    predictor = ResourcePredictor(depths=(2,))
    report = predictor.fit(history)
    assert len(report) == len(predictor.predict(history)) == 9
    import joblib

    artifact = tmp_path / "synthetic_fixture_predictor.joblib"
    joblib.dump(predictor, artifact)
    restored = joblib.load(artifact)
    assert restored.predict(history) == predictor.predict(history)


def test_input_training_hold_prevents_assessment_fitting_and_artifact_writes(tmp_path, monkeypatch, capsys):
    from app.models import train
    from unittest.mock import Mock
    import json

    (tmp_path / "HOLD_TRAINING").touch()
    fit = Mock()
    monkeypatch.setattr(train.AnomalyDetector, "fit", fit)
    output = tmp_path / "output"
    monkeypatch.setattr('sys.argv', ['train', '--train', '--input=' + str(tmp_path / 'nonexistent.ndjson'),
                                     '--output-dir=' + str(output)])
    assert train.main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "training_paused"
    assert result["trained"] is False
    assert result["readiness_assessed"] is False
    fit.assert_not_called()
    assert not output.exists()


def test_evaluate_saved_run_anomalies_round_trip(tmp_path):
    import hashlib
    import json
    import joblib
    from app.data.schema import MetricRecord
    from app.data.storage import serialize_records
    from app.models.train import evaluate_saved_run_anomalies

    frame = synthetic_fixture(200)
    records = [
        MetricRecord.model_validate({
            **row,
            "source": "gcp-monitoring",
            "request_count": int(row["request_count"]),
            "network_ingress": int(row["network_ingress"]),
            "network_egress": int(row["network_egress"]),
        })
        for row in frame.to_dict(orient="records")
    ]
    snapshot = serialize_records(records).encode("utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "history.ndjson").write_bytes(snapshot)
    data = regularize_history(pd.DataFrame([record.model_dump() for record in records]))
    split = chronological_masks(data.index)
    detector = AnomalyDetector().fit(data.loc[split["train"]])
    joblib.dump(detector, run_dir / "anomaly_detector.joblib")
    (run_dir / "evaluation.json").write_text(
        json.dumps({"history_sha256": hashlib.sha256(snapshot).hexdigest()}),
        encoding="utf-8",
    )

    test_index = data.loc[split["test"]].index
    regime_csv = tmp_path / "regime.csv"
    fault_csv = tmp_path / "fault.csv"
    regime_lines = ["timestamp,anomaly_label"] + [
        f"{ts.isoformat()},{1 if i >= len(test_index) // 2 else 0}"
        for i, ts in enumerate(test_index)
    ]
    fault_lines = ["timestamp,anomaly_label"] + [f"{ts.isoformat()},0" for ts in test_index]
    regime_csv.write_text("\n".join(regime_lines) + "\n", encoding="utf-8")
    fault_csv.write_text("\n".join(fault_lines) + "\n", encoding="utf-8")

    result = evaluate_saved_run_anomalies(
        run_dir, regime_csv, operational_fault_label_path=fault_csv,
    )
    assert result["status"] == "evaluated_preliminary"
    assert result["test_partition_minutes"] == len(test_index)
    assert result["anomaly_detected"]["evaluated_samples"] == len(test_index)
    assert result["threshold_baseline"]["evaluated_samples"] == len(test_index)
    assert result["shared_observable_comparison"]["evaluated_samples"] == len(test_index)
    assert result["operational_fault_audit"]["anomaly_detected"]["evaluated_samples"] == len(test_index)
    assert result["operational_fault_audit"]["fault_sensitivity_measured"] is False
    # Generic evaluation helper must not hardcode one specific experiment's timestamps.
    serialized = json.dumps(result)
    assert "21:38:59" not in serialized
    assert "232 minutes" not in serialized
    assert "11.13" not in serialized

    # Checksum mismatch must fail loudly.
    (run_dir / "evaluation.json").write_text(json.dumps({"history_sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        evaluate_saved_run_anomalies(run_dir, regime_csv)


def _small_tree(depth: int):
    return DecisionTreeRegressor(max_depth=depth, random_state=42)


def test_evaluate_saved_run_forecasts_and_regime_breakdown(tmp_path):
    import hashlib
    import json
    import joblib
    from app.data.schema import MetricRecord
    from app.data.storage import serialize_records
    from app.models.train import evaluate_saved_run_forecasts

    frame = synthetic_fixture(220)
    records = [
        MetricRecord.model_validate({
            **row,
            "source": "gcp-monitoring",
            "request_count": int(row["request_count"]),
            "network_ingress": int(row["network_ingress"]),
            "network_egress": int(row["network_ingress"]) if False else int(row["network_egress"]),
        })
        for row in frame.to_dict(orient="records")
    ]
    snapshot = serialize_records(records).encode("utf-8")
    run_dir = tmp_path / "run_fc"
    run_dir.mkdir()
    (run_dir / "history.ndjson").write_bytes(snapshot)
    data = regularize_history(pd.DataFrame([record.model_dump() for record in records]))
    predictor = ResourcePredictor(factory=_small_tree, depths=(2,))
    predictor.fit(data)
    joblib.dump(predictor, run_dir / "resource_predictor.joblib")
    (run_dir / "evaluation.json").write_text(
        json.dumps({"history_sha256": hashlib.sha256(snapshot).hexdigest()}),
        encoding="utf-8",
    )

    cutoff = data.index[-15].isoformat()
    diag = evaluate_saved_run_forecasts(run_dir, active_cutoff=cutoff)
    assert diag["status"] == "evaluated"
    assert diag["models_evaluated"] == 9
    assert diag["active_cutoff"] == cutoff
    assert diag["data_characteristics"]["grid_minutes"] == 220
    assert diag["data_characteristics"]["sub_diurnal_span"] is True
    diag_serialized = json.dumps(diag)
    assert "21:38:59" not in diag_serialized
    assert "232 minutes" not in diag_serialized
    assert "11.13" not in diag_serialized
    for entry in diag["per_model"].values():
        assert entry["active_in_regime"]["samples"] > 0
        assert entry["post_cutoff_idle"]["samples"] > 0
        assert np.isfinite(entry["historical_average_test"]["mae"])

    (run_dir / "evaluation.json").write_text(json.dumps({"history_sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        evaluate_saved_run_forecasts(run_dir)


def test_representative_benchmark_is_reproducible(tmp_path):
    pytest.importorskip(
        "xgboost", reason="Install requirements-ml.txt to verify the XGBoost representative benchmark",
    )
    from app.models.benchmark import BENCHMARK_SEED, run_representative_benchmark

    first = run_representative_benchmark(tmp_path / "bench1.json")
    second = run_representative_benchmark(tmp_path / "bench2.json")
    assert first["seed"] == BENCHMARK_SEED
    assert first["dataset_sha256"] == second["dataset_sha256"]
    assert first["models_evaluated"] == 9
    assert first["models_beating_persistence_mae"] == 9
    assert first["models_beating_historical_average_mae"] == 9
    assert first["deployment_allowed"] is False


def test_validation_method_selection_is_independent_of_test_targets():
    first = regularize_history(synthetic_fixture(240))
    changed = first.copy()
    changed.loc[changed.index[int(len(changed)*.8):], ["cpu_utilization", "memory_utilization", "request_count"]] *= .5
    factory = lambda depth: DecisionTreeRegressor(max_depth=depth, random_state=42)
    original = ResourcePredictor(factory=factory, depths=(2,)).fit(first)
    mutated = ResourcePredictor(factory=factory, depths=(2,)).fit(changed)
    for key in original:
        assert original[key]["preferred_method"] == mutated[key]["preferred_method"]
        assert original[key]["validation_mae_by_method"] == mutated[key]["validation_mae_by_method"]


def test_operational_interpretation_preserves_raw_uncertainty():
    from app.models.anomaly_detector import operational_interpretation
    assert operational_interpretation({"request_count":0,"instance_count":0},True,False) == "observed_scaled_to_zero"
    assert operational_interpretation({"request_count":0,"instance_count":None},True,False) == "uncorroborated_model_signal"
    assert operational_interpretation({},True,True) == "investigate_measured_pressure"
    assert operational_interpretation({},None,None) == "unknown"
