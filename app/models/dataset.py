"""Regular time grids and chronological split rules shared by ML models."""

from typing import Literal

import numpy as np
import pandas as pd

from app.data.schema import METRIC_FIELDS

FEATURES = tuple(METRIC_FIELDS)
TARGETS = ("cpu_utilization", "memory_utilization", "request_count")
HORIZONS = (5, 10, 15)
TrainingProfile = Literal["exploratory", "conservative"]
MIN_OBSERVED_MINUTES = {"exploratory": 200, "conservative": 1440}


def regularize_history(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep one target service, deduplicate observations, and expose real gaps."""
    required = {"timestamp", "collected_at", "project_id", "region", "service_name", *FEATURES}
    if not required.issubset(frame.columns):
        raise ValueError("History is empty or lacks required metric/provenance columns")
    data = frame.copy()
    for field in ("project_id", "region", "service_name"):
        if data[field].isna().any() or data[field].nunique() != 1:
            raise ValueError("Train one project/region/service at a time")
    for field in ("timestamp", "collected_at"):
        parsed = pd.DatetimeIndex(pd.to_datetime(data[field]))
        if parsed.tz is None or parsed.isna().any():
            raise ValueError("History timestamps must be timezone-aware")
        data[field] = parsed.tz_convert("UTC")
    if (
        (data["timestamp"].dt.second != 0).any()
        or (data["timestamp"].dt.microsecond != 0).any()
    ):
        raise ValueError("History must use minute boundaries")
    data = data.sort_values(["timestamp", "collected_at"]).drop_duplicates(
        "timestamp", keep="last",
    )
    data = data.set_index("timestamp")
    if data.empty or data.index[-1] - data.index[0] > pd.Timedelta(30, unit="D"):
        raise ValueError("Use nonempty history spanning at most 30 days")
    data["observed"] = True
    data = data.reindex(pd.date_range(data.index[0], data.index[-1], freq="min"))
    data["observed"] = data["observed"].eq(True)
    for field in FEATURES:
        values = pd.to_numeric(data[field], errors="coerce")
        valid = np.isfinite(values) & (values >= 0)
        if field in ("cpu_utilization", "memory_utilization", "error_rate"):
            valid &= values <= 1
        if field in ("request_count", "network_ingress", "network_egress"):
            valid &= values.eq(np.floor(values))
        data[field] = values.where(valid)
    return data


def quality_report(data: pd.DataFrame, profile: TrainingProfile = "exploratory") -> dict:
    """Development readiness checks; passing is not proof of scientific adequacy."""
    if profile not in MIN_OBSERVED_MINUTES:
        raise ValueError("Unknown training profile")
    minimum = MIN_OBSERVED_MINUTES[profile]
    missing = {field: float(data[field].isna().mean()) for field in FEATURES}
    reasons = []
    if len(data) < minimum or int(data["observed"].sum()) < minimum:
        reasons.append(f"Need at least {minimum:,} observed service-minutes for the {profile} profile")
    sparse = [field for field, fraction in missing.items() if fraction > .2]
    if sparse:
        reasons.append("More than 20% missing in: " + ", ".join(sparse))
    constant = [field for field in TARGETS if data[field].dropna().nunique() < 2]
    if constant:
        reasons.append("Insufficient target variation in: " + ", ".join(constant))
    split_samples = {}
    if len(data) >= 10:
        for horizon in HORIZONS:
            for target in TARGETS:
                masks = forecast_split_masks(data, target, horizon)
                split_samples[f"{target}_{horizon}m"] = {
                    name: int(mask.sum()) for name, mask in masks.items()
                }
        inadequate = [key for key, counts in split_samples.items() if (
            counts["train"] < 100 or counts["validation"] < 20 or counts["test"] < 20
        )]
        if inadequate:
            reasons.append("Need measured 100 train/20 validation/20 test labels: " + ", ".join(inadequate))
    return {
        "profile": profile, "minimum_observed_minutes": minimum,
        "horizons_minutes": list(HORIZONS), "forecast_split_samples": split_samples,
        "deployment_ready": False,
        "ready": not reasons, "reasons": reasons, "grid_minutes": len(data),
        "observed_minutes": int(data["observed"].sum()),
        "gap_minutes": int((~data["observed"]).sum()), "missing_fraction": missing,
        "first_timestamp": data.index[0].isoformat(),
        "last_timestamp": data.index[-1].isoformat(),
        "note": (
            "Preliminary exploratory results only; not deployment evidence"
            if profile == "exploratory" else
            "Conservative development gates only; workload representativeness needs separate review"
        ),
    }


def chronological_masks(index: pd.DatetimeIndex, horizon: int = 0) -> dict[str, np.ndarray]:
    """Split 60/20/20, purging labels that would cross the next split boundary."""
    if len(index) < 10 or not index.is_monotonic_increasing or not index.is_unique:
        raise ValueError("Need at least ten ordered, unique time points")
    if horizon < 0:
        raise ValueError("Horizon must be nonnegative")
    validation_start, test_start = index[int(len(index) * .6)], index[int(len(index) * .8)]
    label_time = index + pd.Timedelta(horizon, unit="min")
    return {
        "train": np.asarray((index < validation_start) & (label_time < validation_start)),
        "validation": np.asarray(
            (index >= validation_start) & (index < test_start) & (label_time < test_start)
        ),
        "test": np.asarray((index >= test_start) & (label_time <= index[-1])),
    }


def forecast_split_masks(data: pd.DataFrame, target: str, horizon: int) -> dict[str, np.ndarray]:
    """Use the same measured-origin/label pairs for readiness and actual fitting."""
    future = data[target].shift(-horizon)
    return {
        name: mask & future.notna().to_numpy() & data[target].notna().to_numpy()
        for name, mask in chronological_masks(data.index, horizon).items()
    }


def lag_features(data: pd.DataFrame) -> pd.DataFrame:
    """Features available at the forecast origin; no future/backward filling."""
    features = data[list(FEATURES)].copy()
    for field in TARGETS + ("network_ingress", "network_egress"):
        for lag in (1, 5, 15):
            features[f"{field}_lag_{lag}"] = data[field].shift(lag)
        features[f"{field}_past_15_mean"] = data[field].shift(1).rolling(15).mean()
    minute = data.index.hour * 60 + data.index.minute
    features["time_sin"] = np.sin(2 * np.pi * minute / 1440)
    features["time_cos"] = np.cos(2 * np.pi * minute / 1440)
    features["weekday"] = data.index.dayofweek
    return features
