"""Assess real history by default; train/save only with explicit --train."""

import argparse
import hashlib
import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import joblib
import numpy as np
import pandas as pd

from app.config import load_settings
from app.data.schema import MetricRecord
from app.models.anomaly_detector import AnomalyDetector, Thresholds, classification_metrics
from app.models.dataset import (
    HORIZONS, MIN_OBSERVED_MINUTES, TARGETS, chronological_masks,
    forecast_split_masks, lag_features, quality_report, regularize_history,
)
from app.models.resource_predictor import ResourcePredictor, bound_predictions, regression_metrics
from app.services.gcp_monitoring import validate_target


def _to_binary_array(series: pd.Series) -> np.ndarray:
    """Convert non-null boolean or 0/1 series values to integer numpy arrays without dtype warnings."""
    return np.asarray([1 if bool(value) else 0 for value in series], dtype=int)


def evaluate_anomalies(results: list[dict], label_path: Path | None) -> dict:
    """Never substitute model flags or heuristic thresholds for ground truth."""
    if label_path is None:
        return {
            "schema_version": 1,
            "status": "not_evaluated",
            "reason": "No independent ground-truth labels supplied",
        }
    labels = pd.read_csv(label_path)
    if not {"timestamp", "anomaly_label"}.issubset(labels.columns):
        raise ValueError("Labels CSV requires timestamp and anomaly_label (0 or 1)")
    index = pd.DatetimeIndex(pd.to_datetime(labels["timestamp"]))
    if index.tz is None or index.has_duplicates or index.isna().any():
        raise ValueError("Labels need unique timezone-aware timestamps")
    if not labels["anomaly_label"].isin([0, 1]).all():
        raise ValueError("Anomaly labels must be 0 or 1")
    truth = pd.Series(labels["anomaly_label"].to_numpy(), index=index.tz_convert("UTC"))
    if not results:
        return {
            "schema_version": 1,
            "status": "not_evaluated",
            "reason": "No matching measured test rows",
            "label_source": str(label_path),
        }

    test_index = pd.to_datetime([row["timestamp"] for row in results], utc=True)
    frame = pd.DataFrame(
        {
            "truth": truth.reindex(test_index).to_numpy(),
            "anomaly_detected": [row.get("anomaly_detected") for row in results],
            "threshold_baseline": [row.get("threshold_baseline") for row in results],
        },
        index=test_index,
    )
    labelled = frame[frame["truth"].notna()]
    if len(labelled) == 0:
        return {
            "schema_version": 1,
            "status": "not_evaluated",
            "reason": "No matching measured test rows",
            "label_source": str(label_path),
        }

    aligned_model = labelled[["truth", "anomaly_detected"]].dropna()
    aligned_baseline = labelled[["truth", "threshold_baseline"]].dropna()
    if len(aligned_model) == 0 or len(aligned_baseline) == 0:
        return {
            "schema_version": 1,
            "status": "not_evaluated",
            "reason": "No matching measured test rows",
            "label_source": str(label_path),
            "anomaly_detected": (
                classification_metrics(
                    _to_binary_array(aligned_model["truth"]),
                    _to_binary_array(aligned_model["anomaly_detected"]),
                )
                if len(aligned_model) else {"status": "not_evaluated", "reason": "No matching measured test rows"}
            ),
            "threshold_baseline": (
                classification_metrics(
                    _to_binary_array(aligned_baseline["truth"]),
                    _to_binary_array(aligned_baseline["threshold_baseline"]),
                )
                if len(aligned_baseline) else {"status": "not_evaluated", "reason": "No matching measured test rows"}
            ),
        }

    shared = labelled[["truth", "anomaly_detected", "threshold_baseline"]].dropna()
    shared_comparison = None
    if len(shared) > 0:
        shared_truth = _to_binary_array(shared["truth"])
        shared_comparison = {
            "evaluated_samples": int(len(shared)),
            "anomaly_detected": classification_metrics(
                shared_truth, _to_binary_array(shared["anomaly_detected"]),
            ),
            "threshold_baseline": classification_metrics(
                shared_truth, _to_binary_array(shared["threshold_baseline"]),
            ),
        }

    return {
        "schema_version": 1,
        "status": "evaluated",
        "label_source": str(label_path),
        "anomaly_detected": classification_metrics(
            _to_binary_array(aligned_model["truth"]),
            _to_binary_array(aligned_model["anomaly_detected"]),
        ),
        "threshold_baseline": classification_metrics(
            _to_binary_array(aligned_baseline["truth"]),
            _to_binary_array(aligned_baseline["threshold_baseline"]),
        ),
        "coverage": {
            "total_test_rows": len(results),
            "labelled_test_rows": int(len(labelled)),
            "model_evaluated_rows": int(len(aligned_model)),
            "baseline_evaluated_rows": int(len(aligned_baseline)),
            "baseline_abstained_rows": int(len(labelled) - len(aligned_baseline)),
            "shared_observable_rows": int(len(shared)),
        },
        "shared_observable_comparison": shared_comparison,
    }


def _load_verified_run_history(run_dir: Path) -> tuple[dict, pd.DataFrame]:
    """Load evaluation.json and verify history.ndjson matches its recorded SHA-256."""
    report = json.loads((run_dir / "evaluation.json").read_text(encoding="utf-8"))
    snapshot_bytes = (run_dir / "history.ndjson").read_bytes()
    if hashlib.sha256(snapshot_bytes).hexdigest() != report.get("history_sha256"):
        raise ValueError("Saved history checksum does not match evaluation.json")
    records = [
        MetricRecord.model_validate_json(line)
        for line in snapshot_bytes.decode("utf-8").splitlines()
        if line.strip()
    ]
    data = regularize_history(pd.DataFrame([record.model_dump() for record in records]))
    return report, data


def evaluate_saved_run_anomalies(
    run_dir: Path,
    label_path: Path,
    *,
    operational_fault_label_path: Path | None = None,
    provenance: dict | None = None,
) -> dict:
    """Evaluate a saved Isolation Forest artifact on its verified held-out test split."""
    _, data = _load_verified_run_history(run_dir)
    split = chronological_masks(data.index)
    detector = joblib.load(run_dir / "anomaly_detector.joblib")
    test_frame = data.loc[split["test"]]
    results = detector.predict(test_frame)
    primary = evaluate_anomalies(results, label_path)
    start_iso = test_frame.index[0].isoformat()
    end_iso = test_frame.index[-1].isoformat()
    partition_minutes = int(split["test"].sum())
    if primary.get("status") == "not_evaluated":
        return {
            **primary,
            "test_window_start": start_iso,
            "test_window_end": end_iso,
            "test_partition_minutes": partition_minutes,
        }
    protocol = (provenance or {}).get("evaluation_protocol", "held_out_test_partition_post_hoc_labels")
    default_note = (
        f"Primary metrics evaluate {start_iso}..{end_iso} ({partition_minutes} test-partition minutes) "
        "using supplied post-hoc labels; operational_fault_audit (if provided) measures specificity "
        "under the assumption that test minutes without fault injection represent normal operation."
    )
    enriched = {
        **primary,
        "status": "evaluated_preliminary",
        "evaluation_protocol": protocol,
        "test_window_start": start_iso,
        "test_window_end": end_iso,
        "test_partition_minutes": partition_minutes,
        "note": (provenance or {}).get("methodology_note", default_note),
    }
    if provenance and "label_provenance" in provenance:
        enriched["label_provenance"] = provenance["label_provenance"]
    if operational_fault_label_path is not None:
        audit = evaluate_anomalies(results, operational_fault_label_path)
        if audit.get("status") != "not_evaluated":
            matrix = audit["anomaly_detected"]["confusion_matrix"]
            positive_faults = int(matrix[1][0] + matrix[1][1])
            audit["assumption"] = (
                "all_test_rows_assumed_operationally_healthy_without_fault_injection"
            )
            audit["positive_fault_examples"] = positive_faults
            audit["fault_sensitivity_measured"] = positive_faults > 0
        enriched["operational_fault_audit"] = audit
    return enriched


def evaluate_saved_run_forecasts(run_dir: Path, *, active_cutoff: str | None = None) -> dict:
    """Evaluate saved XGBoost forecasts against persistence, historical average, and regime windows."""
    _, data = _load_verified_run_history(run_dir)
    predictor = joblib.load(run_dir / "resource_predictor.joblib")
    features = lag_features(data)
    cutoff_ts = None
    if active_cutoff is not None:
        cutoff_ts = pd.Timestamp(active_cutoff)
        if cutoff_ts.tzinfo is None:
            raise ValueError("active_cutoff must be timezone-aware")
        cutoff_ts = cutoff_ts.tz_convert("UTC")

    per_model = {}
    for horizon in HORIZONS:
        for target in TARGETS:
            key = f"{target}_{horizon}m"
            future = data[target].shift(-horizon)
            split = forecast_split_masks(data, target, horizon)
            training, testing = split["train"], split["test"]
            train_mean = float(future.loc[training].mean())

            def _eval_mask(mask: np.ndarray) -> dict | None:
                count = int(mask.sum())
                if count == 0:
                    return None
                actual = future.loc[mask].to_numpy()
                xgb_preds = bound_predictions(predictor.models[key].predict(features.loc[mask]), target)
                pers_preds = data.loc[mask, target].to_numpy()
                hist_preds = np.full(count, train_mean)
                return {
                    "samples": count,
                    "xgboost": regression_metrics(actual, xgb_preds),
                    "persistence": regression_metrics(actual, pers_preds),
                    "historical_average": regression_metrics(actual, hist_preds),
                }

            full = _eval_mask(testing)
            if full is None:
                raise ValueError(f"Empty test split for {key}")
            entry = {
                "target": target,
                "horizon_minutes": horizon,
                "xgboost_test": full["xgboost"],
                "persistence_test": full["persistence"],
                "historical_average_test": full["historical_average"],
                "beats_persistence_mae": full["xgboost"]["mae"] < full["persistence"]["mae"],
                "beats_historical_average_mae": full["xgboost"]["mae"] < full["historical_average"]["mae"],
                "beats_or_tying_historical_average_mae": (
                    full["xgboost"]["mae"] <= full["historical_average"]["mae"] + 1e-12
                ),
            }
            if cutoff_ts is not None:
                label_times = data.index + pd.Timedelta(horizon, unit="min")
                entry["active_in_regime"] = _eval_mask(testing & np.asarray(label_times <= cutoff_ts))
                entry["post_cutoff_idle"] = _eval_mask(testing & np.asarray(label_times > cutoff_ts))
            per_model[key] = entry

    base_split = chronological_masks(data.index)
    base_train = data.loc[base_split["train"]]
    base_test = data.loc[base_split["test"]]
    active_test = base_test.loc[base_test.index <= cutoff_ts] if cutoff_ts is not None else base_test
    idle_test = base_test.loc[base_test.index > cutoff_ts] if cutoff_ts is not None else data.iloc[0:0]

    grid_minutes = int(len(data))
    observed_minutes = int(data["observed"].sum())
    span_hours = round(grid_minutes / 60.0, 2)
    sub_diurnal_span = bool(grid_minutes < 1440)
    target_summaries = {}
    zero_var_active_targets = []
    shifted_post_cutoff_targets = []
    for target in TARGETS:
        tr_vals = base_train[target].dropna()
        te_vals = base_test[target].dropna()
        act_vals = active_test[target].dropna()
        idle_vals = idle_test[target].dropna()
        tr_min = float(tr_vals.min()) if len(tr_vals) else None
        tr_max = float(tr_vals.max()) if len(tr_vals) else None
        act_std = float(act_vals.std(ddof=0)) if len(act_vals) else None
        if act_std is not None and act_std < 1e-6 and len(act_vals) > 1:
            zero_var_active_targets.append(target)
        idle_min = float(idle_vals.min()) if len(idle_vals) else None
        idle_max = float(idle_vals.max()) if len(idle_vals) else None
        out_of_train_range = bool(
            tr_min is not None and tr_max is not None and (
                (idle_min is not None and idle_min < tr_min - 1e-9)
                or (idle_max is not None and idle_max > tr_max + 1e-9)
            )
        )
        if out_of_train_range:
            shifted_post_cutoff_targets.append(target)
        target_summaries[target] = {
            "train_range": [tr_min, tr_max] if tr_min is not None else None,
            "test_range": [float(te_vals.min()), float(te_vals.max())] if len(te_vals) else None,
            "active_test_std": act_std,
            "post_cutoff_range": [idle_min, idle_max] if idle_min is not None else None,
            "post_cutoff_outside_train_range": out_of_train_range,
        }

    hypotheses = []
    if sub_diurnal_span:
        hypotheses.append(
            f"Sub-diurnal {span_hours}-hour window ({grid_minutes} grid minutes, {observed_minutes} observed) "
            "covers less than one 24-hour cycle for time_sin/time_cos features."
        )
    if zero_var_active_targets:
        window_desc = (
            f"active test window (<= {cutoff_ts.isoformat()})" if cutoff_ts is not None else "test window"
        )
        hypotheses.append(
            f"Measured {window_desc} had near-zero variance on {', '.join(zero_var_active_targets)}, "
            "giving last-value persistence ~0.0 MAE on those targets."
        )
    if cutoff_ts is not None and shifted_post_cutoff_targets:
        hypotheses.append(
            f"Post-cutoff test observations after {cutoff_ts.isoformat()} shifted outside the training range "
            f"on {', '.join(shifted_post_cutoff_targets)}."
        )

    return {
        "status": "evaluated",
        "models_evaluated": len(per_model),
        "models_beating_persistence_mae": sum(1 for v in per_model.values() if v["beats_persistence_mae"]),
        "models_beating_historical_average_mae": sum(
            1 for v in per_model.values() if v["beats_historical_average_mae"]
        ),
        "models_beating_or_tying_historical_average_mae": sum(
            1 for v in per_model.values() if v["beats_or_tying_historical_average_mae"]
        ),
        "active_cutoff": cutoff_ts.isoformat() if cutoff_ts is not None else None,
        "data_characteristics": {
            "grid_minutes": grid_minutes,
            "observed_minutes": observed_minutes,
            "span_hours": span_hours,
            "sub_diurnal_span": sub_diurnal_span,
            "test_window_start": base_test.index[0].isoformat(),
            "test_window_end": base_test.index[-1].isoformat(),
            "targets": target_summaries,
        },
        "per_model": per_model,
        "diagnostic_hypotheses": hypotheses,
        "root_causes": hypotheses,
    }


def save_json(path: Path, value: dict) -> None:
    """Write portable evaluation metadata without nonstandard NaN values."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def main() -> int:
    """Use local observations or bounded BigQuery history, never implicit synthetic data."""
    settings = load_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--input", type=Path, default=Path("data/processed/metrics.ndjson"))
    source.add_argument("--from-bigquery", action="store_true")
    parser.add_argument("--project", default=settings.gcp_project_id)
    parser.add_argument("--region", default=settings.gcp_region)
    parser.add_argument("--service", default="autocloud-api")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--output-dir", type=Path, default=Path("models"))
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--profile", choices=("exploratory", "conservative"), default="exploratory")
    parser.add_argument("--labels-csv", type=Path)
    arguments = parser.parse_args()
    try:
        # The experiment starts this CLI as a fresh process after collection.
        # A per-input hold is therefore respected even by an already-running worker.
        if arguments.train and not arguments.from_bigquery and (arguments.input.parent / "HOLD_TRAINING").exists():
            print(json.dumps({
                "status": "training_paused", "trained": False,
                "reason": "Training is on hold by user request; collected evidence is preserved.",
                "readiness_assessed": False, "deployment_allowed": False,
            }))
            return 2
        if arguments.from_bigquery:
            if not arguments.project:
                parser.error("--project is required for BigQuery history")
            from app.services.bigquery_service import BigQueryService

            validate_target(arguments.project, arguments.region, arguments.service)
            rows = BigQueryService(
                arguments.project, arguments.region, "autocloud", "latest_metrics",
            ).read_history(arguments.service, arguments.days)
            records = [MetricRecord.model_validate(row) for row in rows]
        else:
            records = [
                MetricRecord.model_validate_json(line)
                for line in arguments.input.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        if not records:
            report = {"source": "gcp-monitoring", "quality": {
                "ready": False, "reasons": ["No measured observations"],
                "profile": arguments.profile, "horizons_minutes": list(HORIZONS),
                "minimum_observed_minutes": MIN_OBSERVED_MINUTES[arguments.profile],
                "deployment_ready": False,
            }, "trained": False}
            save_json(arguments.output_dir / "assessment.json", report)
            print(json.dumps(report))
            return 2 if arguments.train else 0
        frame = pd.DataFrame([record.model_dump() for record in records])
        data = regularize_history(frame)
        report = {
            "source": "gcp-monitoring", "quality": quality_report(data, arguments.profile), "trained": False,
            "project": records[0].project_id, "region": records[0].region,
            "service": records[0].service_name,
        }
        if not arguments.train or not report["quality"]["ready"]:
            save_json(arguments.output_dir / "assessment.json", report)
            print(json.dumps(report))
            return 2 if arguments.train else 0

        split = chronological_masks(data.index)
        detector = AnomalyDetector().fit(data.loc[split["train"]])
        results = detector.predict(data.loc[split["test"]])
        predictor = ResourcePredictor()
        report["forecast_evaluation"] = predictor.fit(data)
        report["anomaly_evaluation"] = evaluate_anomalies(results, arguments.labels_csv)
        report["threshold_baseline_assumptions"] = vars(Thresholds())
        if data.iloc[-1][["cpu_utilization", "memory_utilization", "request_count"]].notna().all():
            report["forecast_preview"] = predictor.predict(data)
        else:
            report["forecast_preview"] = []
            report["forecast_preview_unavailable"] = "Latest origin lacks measured targets"
        report["trained"] = True
        report["deployment_status"] = "offline_candidate_not_deployed"
        report["evaluation_status"] = (
            "preliminary_exploratory" if arguments.profile == "exploratory" else "offline_candidate"
        )
        report["versions"] = {
            package: importlib.metadata.version(package)
            for package in ("scikit-learn", "xgboost-cpu", "pandas", "numpy", "joblib")
        }
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
        directory = arguments.output_dir / "runs" / run_id
        directory.mkdir(parents=True, exist_ok=False)
        snapshot = "".join(
            json.dumps(record.model_dump(mode="json"), sort_keys=True, allow_nan=False) + "\n"
            for record in records
        )
        report["history_sha256"] = hashlib.sha256(snapshot.encode()).hexdigest()
        # Preserve the exact hashed bytes on Windows as well as Unix.
        (directory / "history.ndjson").write_bytes(snapshot.encode("utf-8"))
        from app.models.inference import export_native_forecasts

        export_native_forecasts(predictor, directory, report)
        joblib.dump(detector, directory / "anomaly_detector.joblib")
        joblib.dump(predictor, directory / "resource_predictor.joblib")
        save_json(directory / "evaluation.json", report)
        print(json.dumps({
            "trained": True, "directory": str(directory),
            "report": str(directory / "evaluation.json"),
        }))
        return 0
    except Exception as error:
        # Do not print cloud response bodies, authentication details or raw rows.
        message = (
            str(error) if type(error) in (ValueError, FileNotFoundError) else type(error).__name__
        )
        print(json.dumps({
            "trained": False, "error_type": type(error).__name__, "reason": message,
        }))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
