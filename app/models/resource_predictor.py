"""Purged chronological XGBoost forecasting with persistence comparisons."""

from typing import Callable

import numpy as np
import pandas as pd

from app.models.dataset import HORIZONS, TARGETS, forecast_split_masks, lag_features


def regression_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict:
    """MAPE excludes near-zero actuals and reports its evaluated sample count."""
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    if actual.size == 0 or actual.shape != predicted.shape:
        raise ValueError("Need equally sized nonempty arrays")
    if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError("Metrics require finite targets and predictions")
    errors = actual - predicted
    nonzero = np.abs(actual) > 1e-6
    mape = (
        float(np.mean(np.abs(errors[nonzero] / actual[nonzero])) * 100)
        if nonzero.any() else None
    )
    return {
        "mae": float(np.abs(errors).mean()), "rmse": float(np.sqrt(np.mean(errors ** 2))),
        "mape": mape,
        "mape_samples": int(nonzero.sum()), "samples": int(actual.size),
    }


def bound_predictions(values: np.ndarray, target: str) -> np.ndarray:
    """Keep reported utilisation in [0,1] and expected request counts nonnegative."""
    return np.clip(values, 0, None if target == "request_count" else 1)


def xgboost_factory(depth: int):
    """Lazy CPU-only dependency: data checks do not require XGBoost installed."""
    from xgboost import XGBRegressor

    return XGBRegressor(
        objective="reg:squarederror", n_estimators=100, max_depth=depth,
        learning_rate=.05, tree_method="hist", device="cpu", n_jobs=1, random_state=42,
    )


class ResourcePredictor:
    """Select depth using validation only, then evaluate the untouched test split."""

    def __init__(self, factory: Callable = xgboost_factory, depths: tuple[int, ...] = (2, 3)):
        if not depths:
            raise ValueError("At least one model candidate is required")
        self.factory = factory
        self.depths = depths
        self.models = {}
        self.report = {}
        self.feature_names = []

    def fit(self, data: pd.DataFrame) -> dict:
        """Fit each target/horizon with a gap preventing future-label leakage."""
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import Pipeline

        self.models = {}
        self.report = {}
        features = lag_features(data)
        self.feature_names = list(features.columns)
        for horizon in HORIZONS:
            for target in TARGETS:
                future = data[target].shift(-horizon)
                split = forecast_split_masks(data, target, horizon)
                counts = {name: int(mask.sum()) for name, mask in split.items()}
                if counts["train"] < 100 or min(counts["validation"], counts["test"]) < 20:
                    raise ValueError(
                        f"Insufficient measured train/validation/test labels: {target}/{horizon}"
                    )
                training, validation, testing = (
                    split[name] for name in ("train", "validation", "test")
                )
                if data.loc[training, target].nunique() < 2:
                    raise ValueError(f"Training target lacks variation: {target}/{horizon}")
                best, best_mae, best_depth = None, float("inf"), None
                for depth in self.depths:
                    model = Pipeline([
                        ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
                        ("model", self.factory(depth)),
                    ])
                    model.fit(features.loc[training], future.loc[training])
                    predicted = bound_predictions(model.predict(features.loc[validation]), target)
                    mae = regression_metrics(future.loc[validation], predicted)["mae"]
                    if mae < best_mae:
                        best, best_mae, best_depth = model, mae, depth
                predicted = bound_predictions(best.predict(features.loc[testing]), target)
                persistence = data.loc[testing, target].to_numpy()
                train_mean = float(future.loc[training].mean())
                validation_baselines = {
                    "xgboost": best_mae,
                    "persistence": regression_metrics(future.loc[validation], data.loc[validation, target])["mae"],
                    "historical_average": regression_metrics(future.loc[validation], np.full(int(validation.sum()), train_mean))["mae"],
                }
                # Baseline wins ties; model selection never examines test errors.
                selected_method = min(("persistence", "historical_average", "xgboost"), key=validation_baselines.get)
                historical_average = np.full(int(testing.sum()), train_mean)
                measured = regression_metrics(future.loc[testing], predicted)
                baseline = regression_metrics(future.loc[testing], persistence)
                hist_avg = regression_metrics(future.loc[testing], historical_average)
                key = f"{target}_{horizon}m"
                self.models[key] = best
                self.report[key] = {
                    "target": target, "horizon_minutes": horizon, "split_samples": counts,
                    "selected_depth": best_depth, "validation_mae": best_mae,
                    "validation_mae_by_method": validation_baselines,
                    "preferred_method": selected_method,
                    "preferred_test": regression_metrics(future.loc[testing], {
                        "xgboost": predicted, "persistence": persistence,
                        "historical_average": historical_average,
                    }[selected_method]),
                    "selection_scope": "chronological validation only; test untouched by selection",
                    "test": measured, "persistence_test": baseline,
                    "beats_persistence_mae": measured["mae"] < baseline["mae"],
                    "historical_average_test": hist_avg,
                    "beats_historical_average_mae": measured["mae"] < hist_avg["mae"],
                    "max_training_label_time": (
                        data.index[training][-1] + pd.Timedelta(horizon, unit="min")
                    ).isoformat(),
                    "first_validation_origin": data.index[validation][0].isoformat(),
                    "max_validation_label_time": (
                        data.index[validation][-1] + pd.Timedelta(horizon, unit="min")
                    ).isoformat(),
                    "first_test_origin": data.index[testing][0].isoformat(),
                }
        return self.report

    def predict(self, history: pd.DataFrame) -> list[dict]:
        """Forecast only at an observed final origin; no gap filling is implied."""
        if not self.models:
            raise ValueError("Fit the resource predictor before inference")
        if not history.iloc[-1][list(TARGETS)].notna().all():
            raise ValueError("Forecast origin needs observed CPU, memory and request count")
        features = lag_features(history).reindex(columns=self.feature_names).iloc[[-1]]
        results = []
        for key, model in self.models.items():
            info = self.report[key]
            future_time = history.index[-1] + pd.Timedelta(info["horizon_minutes"], unit="min")
            results.append({
                "origin": history.index[-1].isoformat(),
                "timestamp": future_time.isoformat(),
                "target": info["target"], "horizon_minutes": info["horizon_minutes"],
                "prediction": float(bound_predictions(model.predict(features), info["target"])[0]),
                "confidence": None,
                "uncertainty": (
                    "No calibrated interval; assess held-out errors "
                    "and workload representativeness"
                ),
            })
        return results
