"""Isolation Forest and an explicit heuristic threshold baseline."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.models.dataset import FEATURES


@dataclass(frozen=True)
class Thresholds:
    """Baseline assumptions, not universal operational SLOs."""

    cpu_utilization: float = .9
    memory_utilization: float = .9
    error_rate: float = .05
    average_latency: float = 1000.0


def operational_interpretation(row, model_flag, threshold_flag):
    """Separate raw model flags from corroborated investigations, preserving unknowns."""
    if model_flag is None:
        return "unknown"
    if threshold_flag is True:
        return "investigate_measured_pressure"
    if row.get("request_count") == 0 and row.get("instance_count") == 0:
        return "observed_scaled_to_zero"
    if model_flag:
        return "uncorroborated_model_signal"
    return "no_model_signal"


def threshold_flags(data: pd.DataFrame, thresholds: Thresholds | None = None) -> pd.Series:
    """Return unknown when no thresholded feature is observed."""
    thresholds = thresholds or Thresholds()
    limits = vars(thresholds)
    known = data[list(limits)].notna().any(axis=1)
    flags = pd.Series(False, index=data.index, dtype="boolean")
    for field, limit in limits.items():
        flags |= data[field].gt(limit)
    return flags.where(known, pd.NA)


def classification_metrics(labels: np.ndarray, predictions: np.ndarray) -> dict:
    """Evaluate externally labelled samples: 1=anomaly, 0=normal."""
    from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

    labels, predictions = np.asarray(labels), np.asarray(predictions)
    if labels.size == 0 or labels.shape != predictions.shape:
        raise ValueError("Need equally sized, nonempty labels and predictions")
    if not np.isin(labels, [0, 1]).all() or not np.isin(predictions, [0, 1]).all():
        raise ValueError("Evaluation labels and predictions must be binary")
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels, predictions, average="binary", zero_division=0,
    )
    matrix = confusion_matrix(labels, predictions, labels=[0, 1])
    tn, fp, fn, tp = matrix.ravel()
    return {
        "precision": float(precision), "recall": float(recall), "f1": float(f1),
        "confusion_matrix": matrix.tolist(),
        "false_positive_rate": float(fp / (fp + tn)) if fp + tn else None,
        "evaluated_samples": int(labels.size),
    }


class AnomalyDetector:
    """Train-only imputation and reproducible isolation scoring on CPU."""

    def __init__(self):
        from sklearn.ensemble import IsolationForest
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import Pipeline

        self.pipeline = Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("model", IsolationForest(
                n_estimators=100, contamination="auto", random_state=42, n_jobs=1,
            )),
        ])
        self.median = None
        self.spread = None

    def fit(self, training: pd.DataFrame) -> "AnomalyDetector":
        """Fit only the chronological training partition."""
        features = training[list(FEATURES)].dropna(how="all")
        if len(features) < 100 or features.notna().sum().min() < 20:
            raise ValueError("Need 100 training rows and 20 measured values per anomaly feature")
        self.pipeline.fit(features)
        self.median = features.median()
        self.spread = (features.quantile(.75) - features.quantile(.25)).replace(0, 1)
        return self

    def predict(self, observations: pd.DataFrame) -> list[dict]:
        """Return raw scores with null confidence; missing rows are not classified."""
        if self.median is None:
            raise ValueError("Fit the anomaly detector before prediction")
        features = observations[list(FEATURES)]
        known = features.notna().any(axis=1)
        scores = pd.Series(np.nan, index=features.index)
        if known.any():
            scores.loc[known] = self.pipeline.decision_function(features.loc[known])
        baseline = threshold_flags(features)
        results = []
        for index, row in features.iterrows():
            score = scores.loc[index]
            anomaly = bool(score < 0) if np.isfinite(score) else None
            deviation = ((row - self.median).abs() / self.spread).dropna()
            reason = (
                "No observed features" if anomaly is None else "Within learned isolation boundary"
            )
            if anomaly:
                reason = (
                    "Largest deviation from training baseline: " + str(deviation.idxmax())
                )
            results.append({
                "timestamp": index.isoformat(), "anomaly_detected": anomaly,
                "severity": "unknown" if anomaly is None else (
                    "high" if anomaly and pd.notna(baseline.loc[index]) and baseline.loc[index]
                    else "medium" if anomaly else "none"
                ),
                "reason": reason, "confidence": None,
                "decision_score": float(score) if np.isfinite(score) else None,
                "threshold_baseline": (
                    bool(baseline.loc[index]) if pd.notna(baseline.loc[index]) else None
                ),
                "missing_fields": row.index[row.isna()].tolist(),
                "uncertainty": (
                    "Score is not a probability; baseline deviation is not causal attribution"
                ),
            })
        return results
