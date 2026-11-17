"""Explicit native XGBoost candidate inference; never deserialize Python pickles."""

import hashlib
import importlib.metadata
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.data.schema import MetricRecord
from app.models.anomaly_detector import AnomalyDetector, Thresholds, threshold_flags
from app.models.dataset import (
    FEATURES, HORIZONS, TARGETS, TrainingProfile, lag_features, quality_report, regularize_history,
)
from app.models.resource_predictor import ResourcePredictor, bound_predictions


class NativeModel(BaseModel):
    """Bounded, finite metadata describing one fixed target/horizon model."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    imputer_statistics: tuple[float, ...] = Field(min_length=1, max_length=100)
    test_mae: float = Field(ge=0)
    persistence_test_mae: float = Field(ge=0)
    test_samples: int = Field(ge=20)


class NativeManifest(BaseModel):
    """Training evidence and file integrity, not an approval or authenticity signature."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[2] = 2
    training_profile: TrainingProfile
    horizons_minutes: tuple[int, ...] = HORIZONS
    source: Literal["gcp-monitoring"] = "gcp-monitoring"
    project: str
    region: str
    service: str
    training_history_end: AwareDatetime
    history_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    xgboost_version: str
    feature_names: tuple[str, ...] = Field(min_length=1, max_length=100)
    models: dict[str, NativeModel]

    @model_validator(mode="after")
    def validate_models(self):
        expected = {f"{target}_{horizon}m" for target in TARGETS for horizon in HORIZONS}
        if self.horizons_minutes != HORIZONS:
            raise ValueError("Unsupported forecast horizons; retrain this run")
        if set(self.models) != expected or len(set(self.feature_names)) != len(self.feature_names):
            raise ValueError("Need all supported target/horizon models and unique feature names")
        if any(len(item.imputer_statistics) != len(self.feature_names) for item in self.models.values()):
            raise ValueError("Imputation statistics must match the feature schema")
        return self


def checked_file(directory: Path, name: str, size_limit: int) -> bytes:
    """Refuse symlink escapes, missing files and unexpectedly large artifacts."""
    path = (directory / name).resolve(strict=True)
    if path.parent != directory.resolve() or not path.is_file() or path.stat().st_size > size_limit:
        raise ValueError("Model run file escapes the run directory or exceeds its size limit")
    return path.read_bytes()


def history_frame(records: list[MetricRecord], project: str, region: str, service: str):
    """Reuse the real-data schema and shared preprocessing for training evidence."""
    if not records or any((row.project_id, row.region, row.service_name) != (
        project, region, service,
    ) for row in records):
        raise ValueError("Model history must match one nonempty target")
    return regularize_history(pd.DataFrame([row.model_dump() for row in records]))


def export_native_forecasts(predictor: ResourcePredictor, directory: Path, report: dict) -> None:
    """Export trees plus train-fitted medians after the training CLI passes its gates."""
    if report.get("trained") is not True or report.get("quality", {}).get("ready") is not True:
        raise ValueError("Only a trained, readiness-checked run can export native forecasts")
    if report.get("source") != "gcp-monitoring":
        raise ValueError("Forecast model runs require Monitoring provenance")
    models = {}
    for key, pipeline in predictor.models.items():
        if key not in {f"{target}_{horizon}m" for target in TARGETS for horizon in HORIZONS}:
            raise ValueError("Unexpected native model key")
        path = directory / f"{key}.json"
        pipeline.named_steps["model"].save_model(path)
        info = predictor.report[key]
        models[key] = NativeModel(
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            imputer_statistics=tuple(pipeline.named_steps["imputer"].statistics_),
            test_mae=info["test"]["mae"], persistence_test_mae=info["persistence_test"]["mae"],
            test_samples=info["test"]["samples"],
        )
    manifest = NativeManifest(
        training_profile=report["quality"]["profile"],
        project=report["project"], region=report["region"], service=report["service"],
        training_history_end=report["quality"]["last_timestamp"],
        history_sha256=report["history_sha256"],
        xgboost_version=importlib.metadata.version("xgboost-cpu"),
        feature_names=tuple(predictor.feature_names), models=models,
    )
    (directory / "forecast_manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")


def validate_run(directory: Path, *, project: str, region: str,
                 service: str, now: datetime) -> NativeManifest:
    """Validate training evidence and all native model hashes without inference."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Inference clock must be timezone aware")
    manifest = NativeManifest.model_validate_json(checked_file(directory, "forecast_manifest.json", 1_000_000))
    if (manifest.project, manifest.region, manifest.service) != (project, region, service):
        raise ValueError("Model run scope does not match the requested service")
    if manifest.xgboost_version != importlib.metadata.version("xgboost-cpu"):
        raise ValueError("Use the recorded XGBoost version or re-evaluate the model")
    snapshot = checked_file(directory, "history.ndjson", 64_000_000)
    if hashlib.sha256(snapshot).hexdigest() != manifest.history_sha256:
        raise ValueError("Training snapshot integrity check failed")
    training = [MetricRecord.model_validate_json(line) for line in snapshot.decode("utf-8").splitlines() if line.strip()]
    if any(row.timestamp > now or row.collected_at > now for row in training):
        raise ValueError("Training evidence is future dated")
    trained_frame = history_frame(training, project, region, service)
    if not quality_report(trained_frame, manifest.training_profile)["ready"] or trained_frame.index[-1] != manifest.training_history_end:
        raise ValueError("Training evidence does not satisfy the recorded readiness gate")
    for key, info in manifest.models.items():
        contents = checked_file(directory, f"{key}.json", 4_000_000)
        if hashlib.sha256(contents).hexdigest() != info.sha256:
            raise ValueError("Native model integrity check failed")
    return manifest


class EvaluationScores(BaseModel):
    """Finite held-out errors and sample counts from the recorded evaluation."""

    model_config = ConfigDict(allow_inf_nan=False)
    mae: float = Field(ge=0)
    rmse: float = Field(ge=0)
    samples: int = Field(ge=20)


class BinaryEvalScores(BaseModel):
    """Finite held-out binary classification scores validated against confusion_matrix."""

    model_config = ConfigDict(allow_inf_nan=False)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1: float = Field(ge=0, le=1)
    confusion_matrix: list[list[int]]
    false_positive_rate: float | None = Field(default=None, ge=0, le=1)
    evaluated_samples: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_matrix(self) -> "BinaryEvalScores":
        if (len(self.confusion_matrix) != 2
                or any(len(row) != 2 or any(cell < 0 for cell in row) for row in self.confusion_matrix)
                or sum(sum(row) for row in self.confusion_matrix) != self.evaluated_samples):
            raise ValueError("Invalid 2x2 confusion matrix")
        tn, fp = self.confusion_matrix[0]
        fn, tp = self.confusion_matrix[1]
        exp_precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        exp_recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        exp_f1 = (2.0 * tp) / (2 * tp + fp + fn) if (2 * tp + fp + fn) > 0 else 0.0
        exp_fpr = (fp / (fp + tn)) if (fp + tn) > 0 else None
        tol = 1e-6
        if (
            abs(self.precision - exp_precision) > tol
            or abs(self.recall - exp_recall) > tol
            or abs(self.f1 - exp_f1) > tol
        ):
            raise ValueError("Classification metrics contradict confusion matrix")
        if exp_fpr is None:
            if self.false_positive_rate is not None:
                raise ValueError("false_positive_rate must be null when there are no negative labels")
        elif self.false_positive_rate is None or abs(self.false_positive_rate - exp_fpr) > tol:
            raise ValueError("false_positive_rate contradicts confusion matrix")
        return self


def _validate_anomaly_block(block: dict) -> None:
    if not isinstance(block, dict):
        raise ValueError("Anomaly evaluation block must be a mapping")
    for key in ("anomaly_detected", "threshold_baseline"):
        if key not in block:
            raise ValueError(f"Missing anomaly evaluation metrics for {key}")
        BinaryEvalScores.model_validate(block[key])
    shared = block.get("shared_observable_comparison")
    if shared is not None:
        if not isinstance(shared, dict) or not isinstance(shared.get("evaluated_samples"), int):
            raise ValueError("Invalid shared_observable_comparison block")
        for key in ("anomaly_detected", "threshold_baseline"):
            if key not in shared:
                raise ValueError(f"Missing shared_observable_comparison metrics for {key}")
            scores = BinaryEvalScores.model_validate(shared[key])
            if scores.evaluated_samples != shared["evaluated_samples"]:
                raise ValueError("shared_observable_comparison sample counts disagree")


def inspect_run(directory: Path, *, project: str, region: str,
                service: str, now: datetime) -> dict:
    """Read scoped candidate evaluation; integrity checks are not authentication."""
    manifest = validate_run(directory, project=project, region=region, service=service, now=now)
    report = json.loads(checked_file(directory, "evaluation.json", 2_000_000))
    if (report.get("source"), report.get("project"), report.get("region"), report.get("service"),
        report.get("history_sha256")) != (
        "gcp-monitoring", project, region, service, manifest.history_sha256,
    ) or report.get("trained") is not True:
        raise ValueError("Evaluation scope or history does not match the model run")
    if report.get("quality", {}).get("profile") != manifest.training_profile:
        raise ValueError("Evaluation training profile does not match")
    evaluations = report.get("forecast_evaluation", {})
    if set(evaluations) != set(manifest.models):
        raise ValueError("Evaluation lacks supported model results")
    rows = []
    for key, info in manifest.models.items():
        scores = EvaluationScores.model_validate(evaluations[key]["test"])
        baseline = EvaluationScores.model_validate(evaluations[key]["persistence_test"])
        if (scores.mae, baseline.mae, scores.samples) != (
            info.test_mae, info.persistence_test_mae, info.test_samples,
        ) or baseline.samples != scores.samples:
            raise ValueError("Evaluation and manifest metrics differ")
        target, horizon = key.rsplit("_", 1)
        rows.append({
            "target": target, "horizon_minutes": int(horizon[:-1]),
            "test_mae": scores.mae, "test_rmse": scores.rmse,
            "persistence_test_mae": baseline.mae, "persistence_test_rmse": baseline.rmse,
            "test_samples": scores.samples, "beats_persistence_mae": scores.mae < baseline.mae,
        })
    raw_anomaly = report.get("anomaly_evaluation") or {}
    anomaly_status = raw_anomaly.get("status", "not_evaluated")
    evaluated_anomaly = None
    if anomaly_status == "not_evaluated":
        evaluated_anomaly = None
    elif anomaly_status in {"evaluated", "evaluated_preliminary"}:
        _validate_anomaly_block(raw_anomaly)
        if "operational_fault_audit" in raw_anomaly:
            audit = raw_anomaly["operational_fault_audit"]
            if audit.get("status", "evaluated") != "not_evaluated":
                _validate_anomaly_block(audit)
        evaluated_anomaly = raw_anomaly
    else:
        raise ValueError("Unsupported anomaly evaluation status")
    forecast_diag = report.get("forecast_diagnostics")
    if forecast_diag is not None:
        if (not isinstance(forecast_diag, dict)
                or forecast_diag.get("models_evaluated") != len(rows)
                or not isinstance(forecast_diag.get("per_model"), dict)
                or set(forecast_diag["per_model"]) != set(manifest.models)):
            raise ValueError("Forecast diagnostics do not match the evaluated models")
    result = {
        "run_name": directory.name, "training_profile": manifest.training_profile,
        "evaluation_status": "preliminary_exploratory" if manifest.training_profile == "exploratory" else "offline_candidate",
        "training_history_end": manifest.training_history_end.isoformat(),
        "forecast_evaluation": rows,
        "baseline_comparison": {
            "models_evaluated": len(rows),
            "models_beating_persistence_mae": sum(row["beats_persistence_mae"] for row in rows),
            "comparison_metric": "held_out_test_mae",
        },
        "training_quality": report["quality"],
        "anomaly_evaluation_status": (
            "not_evaluated" if evaluated_anomaly is None
            else evaluated_anomaly["status"]
        ),
        "deployment_allowed": False,
        "note": "Recorded held-out results; workload representativeness and label quality require independent review.",
    }
    if evaluated_anomaly is not None:
        result["anomaly_evaluation"] = evaluated_anomaly
    if forecast_diag is not None:
        result["forecast_diagnostics"] = forecast_diag
    return result


def predict_from_run(
    directory: Path, records: list[MetricRecord], *, project: str, region: str,
    service: str, now: datetime,
) -> list[dict]:
    """Read only explicitly chosen trusted run files; report candidates, not deployment approval."""
    import xgboost as xgb

    manifest = validate_run(directory, project=project, region=region, service=service, now=now)
    if any(row.timestamp > now or row.collected_at > now for row in records):
        raise ValueError("Inference evidence is future dated")
    history = history_frame(records, project, region, service)
    origin = history.index[-1]
    if not timedelta(0) <= now - origin <= timedelta(minutes=15):
        raise ValueError("Forecast origin must be fresh")
    if origin <= manifest.training_history_end:
        raise ValueError("Inference origin must be later than the training/evaluation history")
    recent = history.iloc[-16:]
    if len(recent) < 16 or not recent["observed"].all() or recent[list(TARGETS)].isna().any().any():
        raise ValueError("Inference needs sixteen consecutive minutes of measured targets")
    features = lag_features(history)
    if tuple(features.columns) != manifest.feature_names:
        raise ValueError("Feature schema differs from the trained model")
    raw = features.iloc[-1].to_numpy(dtype=float)
    missing_features = [name for name, value in zip(manifest.feature_names, raw) if not np.isfinite(value)]
    recent_observed_count = int(history["observed"].tail(16).sum())
    results = []
    for key, info in manifest.models.items():
        target, horizon_text = key.rsplit("_", 1)
        horizon = int(horizon_text[:-1])
        contents = checked_file(directory, f"{key}.json", 4_000_000)
        if hashlib.sha256(contents).hexdigest() != info.sha256:
            raise ValueError("Native model integrity check failed")
        # Load verified bytes via native Booster (no scikit-learn runtime dependency).
        booster = xgb.Booster({"device": "cpu", "nthread": 1})
        booster.load_model(bytearray(contents))
        values = np.where(np.isfinite(raw), raw, np.asarray(info.imputer_statistics))
        prediction = float(bound_predictions(
            booster.predict(xgb.DMatrix(values.reshape(1, -1))), target,
        )[0])
        if not np.isfinite(prediction):
            raise ValueError("Model returned a non-finite prediction")
        persistence_value = float(history.loc[origin, target])
        results.append({
            "origin": origin.isoformat(), "timestamp": (origin + timedelta(minutes=horizon)).isoformat(),
            "target": target, "horizon_minutes": horizon, "prediction": prediction,
            "persistence_prediction": persistence_value,
            "persistence_origin": origin.isoformat(),
            "delta_from_persistence": prediction - persistence_value,
            "method": "xgboost_offline_candidate", "confidence": None,
            "experimental": True,
            "observation_only": True,
            "execution_allowed": False,
            "training_profile": manifest.training_profile,
            "evaluation_status": (
                "preliminary_exploratory" if manifest.training_profile == "exploratory" else "offline_candidate"
            ),
            "lead_time_from_assessment_seconds": (origin + timedelta(minutes=horizon) - now).total_seconds(),
            "forecast_in_past": origin + timedelta(minutes=horizon) <= now,
            "assessed_at": now.isoformat(),
            "observation_age_seconds": (now - origin).total_seconds(),
            "recent_observed_minutes": recent_observed_count,
            "model_history_sha256": manifest.history_sha256,
            "imputed_features": missing_features,
            "imputed_feature_count": len(missing_features),
            "test_mae": info.test_mae, "persistence_test_mae": info.persistence_test_mae,
            "beats_persistence_mae": info.test_mae < info.persistence_test_mae,
            "uncertainty": (
                "Experimental observation-only forecast alongside flat persistence; no calibrated "
                "interval, 0/9 real held-out MAE wins against persistence, autonomous changes disabled."
            ),
        })
    return results


class AnomalyManifest(BaseModel):
    """Checksummed metadata and statistics for pickle-free Isolation Forest evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    schema_version: Literal[1] = 1
    source: Literal["gcp-monitoring"] = "gcp-monitoring"
    project: str
    region: str
    service: str
    training_history_end: AwareDatetime
    history_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_joblib_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    feature_names: tuple[str, ...] = Field(min_length=1, max_length=50)
    n_estimators: int = Field(ge=1, le=500)
    max_samples: int = Field(ge=2)
    c_max_samples: float = Field(gt=0)
    offset: float
    imputer_statistics: tuple[float, ...] = Field(min_length=1, max_length=50)
    baseline_median: tuple[float, ...] = Field(min_length=1, max_length=50)
    baseline_spread: tuple[float, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_schema(self):
        expected_len = len(self.feature_names)
        if tuple(self.feature_names) != FEATURES:
            raise ValueError("Unsupported anomaly feature schema")
        if any(len(v) != expected_len for v in (self.imputer_statistics, self.baseline_median, self.baseline_spread)):
            raise ValueError("Anomaly statistics length must match feature schema")
        return self


def export_native_anomalies(
    detector: AnomalyDetector,
    directory: Path,
    *,
    project: str,
    region: str,
    service: str,
    training_history_end: datetime,
    history_sha256: str,
    source_joblib_sha256: str,
) -> AnomalyManifest:
    """Export fitted Isolation Forest trees and medians to pure JSON (no runtime pickle)."""
    from sklearn.ensemble._iforest import _average_path_length

    if detector.median is None or detector.spread is None:
        raise ValueError("Fit AnomalyDetector before exporting")
    imputer = detector.pipeline.named_steps["imputer"]
    model = detector.pipeline.named_steps["model"]
    trees = []
    for estimator, feat_idx, plens, apls in zip(
        model.estimators_,
        model.estimators_features_,
        model._decision_path_lengths,
        model._average_path_length_per_tree,
    ):
        tr = estimator.tree_
        leaf_depths = [
            float(plens[idx]) + float(apls[idx]) - 1.0 if int(tr.children_left[idx]) == -1 else 0.0
            for idx in range(int(tr.node_count))
        ]
        trees.append({
            "estimator_features": [int(i) for i in feat_idx],
            "children_left": [int(v) for v in tr.children_left],
            "children_right": [int(v) for v in tr.children_right],
            "feature": [int(v) for v in tr.feature],
            "threshold": [float(v) for v in tr.threshold],
            "leaf_depth": leaf_depths,
        })
    model_path = directory / "anomaly_detector.json"
    model_bytes = json.dumps({"trees": trees}, separators=(",", ":"), allow_nan=False).encode("utf-8")
    model_path.write_bytes(model_bytes)
    manifest = AnomalyManifest(
        project=project,
        region=region,
        service=service,
        training_history_end=training_history_end,
        history_sha256=history_sha256,
        model_sha256=hashlib.sha256(model_bytes).hexdigest(),
        source_joblib_sha256=source_joblib_sha256,
        feature_names=tuple(FEATURES),
        n_estimators=len(trees),
        max_samples=int(model._max_samples),
        c_max_samples=float(_average_path_length([model._max_samples])[0]),
        offset=float(model.offset_),
        imputer_statistics=tuple(float(v) for v in imputer.statistics_),
        baseline_median=tuple(float(detector.median[name]) for name in FEATURES),
        baseline_spread=tuple(float(detector.spread[name]) for name in FEATURES),
    )
    (directory / "anomaly_manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return manifest


def validate_anomaly_run(
    directory: Path, *, project: str, region: str, service: str, now: datetime,
) -> tuple[AnomalyManifest, list[dict]]:
    """Verify checksummed pure-JSON anomaly manifest and tree weights without pickle."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Inference clock must be timezone aware")
    manifest = AnomalyManifest.model_validate_json(checked_file(directory, "anomaly_manifest.json", 1_000_000))
    if (manifest.project, manifest.region, manifest.service) != (project, region, service):
        raise ValueError("Anomaly run scope does not match the requested service")
    snapshot = checked_file(directory, "history.ndjson", 64_000_000)
    if hashlib.sha256(snapshot).hexdigest() != manifest.history_sha256:
        raise ValueError("Anomaly training snapshot integrity check failed")
    model_bytes = checked_file(directory, "anomaly_detector.json", 16_000_000)
    if hashlib.sha256(model_bytes).hexdigest() != manifest.model_sha256:
        raise ValueError("Anomaly model integrity check failed")
    payload = json.loads(model_bytes.decode("utf-8"))
    trees = payload.get("trees")
    if not isinstance(trees, list) or len(trees) != manifest.n_estimators:
        raise ValueError("Anomaly tree payload does not match manifest")
    return manifest, trees


def _score_isolation_forest_pure(
    values: np.ndarray, manifest: AnomalyManifest, trees: list[dict],
) -> np.ndarray:
    stats = np.asarray(manifest.imputer_statistics, dtype=float)
    imp_x = np.where(np.isfinite(values), values, stats).astype(np.float32)
    depths = np.zeros(imp_x.shape[0], dtype=float)
    for tree in trees:
        children_left = tree["children_left"]
        children_right = tree["children_right"]
        feat_map = tree["estimator_features"]
        feat_arr = tree["feature"]
        thresh_arr = tree["threshold"]
        leaf_depth = tree["leaf_depth"]
        sub = imp_x[:, feat_map]
        for row_i in range(imp_x.shape[0]):
            node = 0
            while children_left[node] != -1:
                if float(sub[row_i, feat_arr[node]]) <= float(thresh_arr[node]):
                    node = children_left[node]
                else:
                    node = children_right[node]
            depths[row_i] += float(leaf_depth[node])
    denominator = float(manifest.n_estimators) * float(manifest.c_max_samples)
    return -np.power(2.0, -depths / denominator) - float(manifest.offset)


def predict_anomalies_from_run(
    directory: Path,
    records: list[MetricRecord],
    *,
    project: str,
    region: str,
    service: str,
    now: datetime,
    window_minutes: int = 30,
) -> dict:
    """Evaluate observation-only Isolation Forest scores alongside heuristic threshold checks."""
    manifest, trees = validate_anomaly_run(
        directory, project=project, region=region, service=service, now=now,
    )
    if any(row.timestamp > now or row.collected_at > now for row in records):
        raise ValueError("Inference evidence is future dated")
    history = history_frame(records, project, region, service)
    origin = history.index[-1]
    age_seconds = (now - origin).total_seconds()
    if not 0 <= age_seconds <= 900:
        raise ValueError("Anomaly observation origin must be fresh (<= 15 minutes)")
    if origin <= manifest.training_history_end:
        raise ValueError("Anomaly observation origin must be later than training history")

    from app.models.anomaly_detector import operational_interpretation

    recent = history.tail(max(1, min(window_minutes, 60)))
    features = recent[list(manifest.feature_names)]
    known_mask = features.notna().any(axis=1)
    if not known_mask.any():
        raise ValueError("No measured anomaly feature rows in recent window")

    scores = pd.Series(np.nan, index=features.index, dtype=float)
    scores.loc[known_mask] = _score_isolation_forest_pure(
        features.loc[known_mask].to_numpy(dtype=float), manifest, trees,
    )
    thresholds = Thresholds()
    limits = vars(thresholds)
    baseline = threshold_flags(features, thresholds)
    med_series = pd.Series(manifest.baseline_median, index=list(FEATURES))
    spread_series = pd.Series(manifest.baseline_spread, index=list(FEATURES))

    rows: list[dict] = []
    missing_cells = 0
    for ts, row in features.iterrows():
        score = scores.loc[ts]
        anomaly = bool(score < 0) if np.isfinite(score) else None
        base_flag = bool(baseline.loc[ts]) if pd.notna(baseline.loc[ts]) else None
        triggers = [
            f"{field}>{limit}"
            for field, limit in limits.items()
            if pd.notna(row[field]) and float(row[field]) > float(limit)
        ]
        missing_fields = [name for name in FEATURES if pd.isna(row[name])]
        missing_cells += len(missing_fields)
        deviation = ((row - med_series).abs() / spread_series).dropna()
        reason = "No observed features" if anomaly is None else "Within learned isolation boundary"
        if anomaly and not deviation.empty:
            reason = f"Largest deviation from active baseline: {deviation.idxmax()}"
        rows.append({
            "timestamp": ts.isoformat(),
            "operational_status": operational_interpretation(row, anomaly, base_flag),
            "observed": bool(known_mask.loc[ts]),
            "decision_score": float(score) if np.isfinite(score) else None,
            "anomaly_detected": anomaly,
            "threshold_baseline": base_flag,
            "threshold_triggers": triggers,
            "severity": (
                "unknown" if anomaly is None
                else ("high" if anomaly and base_flag else "medium" if anomaly else "none")
            ),
            "reason": reason,
            "missing_fields": missing_fields,
            "confidence": None,
            "experimental": True,
            "observation_only": True,
        })

    observed_rows = [r for r in rows if r["observed"]]
    latest_row = rows[-1]
    return {
        "status": "experimental_observation_only",
        "experimental": True,
        "observation_only": True,
        "execution_allowed": False,
        "deployment_allowed": False,
        "model_history_sha256": manifest.history_sha256,
        "model_sha256": manifest.model_sha256,
        "assessed_at": now.isoformat(),
        "latest_observation": origin.isoformat(),
        "age_seconds": age_seconds,
        "window_start": recent.index[0].isoformat(),
        "window_end": origin.isoformat(),
        "window_minutes": len(recent),
        "scored_minutes": len(observed_rows),
        "unobserved_minutes": len(recent) - len(observed_rows),
        "anomaly_flagged_minutes": sum(1 for r in observed_rows if r["anomaly_detected"] is True),
        "threshold_flagged_minutes": sum(1 for r in observed_rows if r["threshold_baseline"] is True),
        "missing_feature_cells": missing_cells,
        "latest_decision_score": latest_row["decision_score"],
        "latest_operational_status": latest_row["operational_status"],
        "corroborated_investigation_minutes": sum(r["operational_status"] == "investigate_measured_pressure" for r in rows),
        "latest_anomaly_detected": latest_row["anomaly_detected"],
        "latest_threshold_baseline": latest_row["threshold_baseline"],
        "latest_threshold_triggers": latest_row["threshold_triggers"],
        "latest_missing_fields": latest_row["missing_fields"],
        "thresholds": limits,
        "limitations": (
            "Experimental observation-only score (not a calibrated probability). Trained solely on "
            "active traffic; held-out operational-normality FPR was 42.55% (20/47 all rows; "
            "95.24% = 20/21 idle-only) with positive fault recall unmeasured."
        ),
        "rows": rows,
    }
