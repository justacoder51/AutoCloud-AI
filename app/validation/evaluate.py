"""Descriptive held-out lab evaluation, never an operational promotion decision."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from app.data.schema import MetricRecord
from app.models.dataset import FEATURES, TARGETS, lag_features, regularize_history
from app.models.inference import validate_run, validate_anomaly_run, _score_isolation_forest_pure
from app.models.real_validation import event_scores
from app.models.resource_predictor import bound_predictions, regression_metrics
from app.validation.protocol import PROJECT, REGION, SERVICE, digest, phase_at, verify_plan


def request_labels(events, slo):
    """Outcome labels do not read a model score or a Monitoring feature value.

    A positive means client-observed HTTP/latency impact, not a causal diagnosis.
    An exposure without that impact remains a stress probe, not a fault-positive.
    """
    labels, episodes, seen = {}, {}, set()
    for event in events:
        if event["sequence"] in seen:
            raise ValueError("Duplicate request outcome")
        seen.add(event["sequence"])
        if not event.get("receipt_confirmed") or event.get("status") is None:
            continue
        minute = pd.Timestamp(event["received_at"]).ceil("min")
        impact = int(500 <= event["status"] < 600 or event["latency_seconds"] > slo)
        group = labels.setdefault(minute, {"impact": 0, "requests": 0, "control_only": True})
        group["requests"] += 1
        group["impact"] = max(group["impact"], impact)
        # Recovery is not healthy ground truth, and mixed minutes are excluded from controls.
        control = event["intended_fault"] == "none" and not event["phase"].startswith("recovery_")
        group["control_only"] &= control
        if event["intended_fault"] != "none":
            episode = episodes.setdefault(event["phase"], {"fault": event["intended_fault"],
                "confirmed_requests": 0, "impact_requests": 0, "minutes": set(),
                "first_actuation": event["receipt"]["started_at"]})
            if episode["fault"] != event["intended_fault"]:
                raise ValueError("One episode cannot contain different intended fault types")
            episode["confirmed_requests"] += 1
            episode["impact_requests"] += impact
            episode["minutes"].add(minute)
            episode["first_actuation"] = min(episode["first_actuation"], event["receipt"]["started_at"])
    return labels, episodes


def evaluate(folder):
    import xgboost as xgb
    folder = Path(folder)
    plan = json.loads((folder/"plan.json").read_text())
    verify_plan(plan)
    execution = json.loads((folder/"execution.json").read_text())
    if execution["plan_sha256"] != digest(plan):
        raise ValueError("Execution plan changed")
    payload = (folder/"observations.ndjson").read_bytes()
    source = json.loads((folder/"observations-source.json").read_text())
    request_payload = (folder/"requests.ndjson").read_bytes()
    if (hashlib.sha256(payload).hexdigest() != source["sha256"]
        or hashlib.sha256(request_payload).hexdigest() != source["requests_sha256"]
        or source["plan_sha256"] != digest(plan)):
        raise ValueError("Captured evidence changed")
    terminal = [json.loads(l) for l in (folder/"execution-events.ndjson").read_text().splitlines()][-1]
    rows = [MetricRecord.model_validate_json(l) for l in payload.splitlines() if l.strip()]
    start, end = pd.Timestamp(execution["started_at"]), pd.Timestamp(terminal["finished_at"])
    if any((row.project_id, row.region, row.service_name) != (PROJECT, REGION, SERVICE)
           or not start.floor("min") < row.timestamp <= end.ceil("min")
           or row.collected_at > datetime.fromisoformat(source["captured_at"]) for row in rows):
        raise ValueError("Observation target or time scope differs from the campaign")
    base = {"campaign_status": terminal["status"], "execution_allowed": False,
            "operational_promotion": "not_approved", "observed_minutes": len(rows),
            "evaluation_scope": "Frozen-model cross-service controlled pilot, outside trained target domain",
            "limitations": ["One artificial probe service is not representative production traffic.",
                "Client latency includes transport, cold starts and processing; >1s is a preregistered client SLO, not a causal infrastructure label.",
                "Fault exposure is separate from demonstrated HTTP/latency harm; CPU/memory exposure alone is not a true fault label.",
                "Contemporaneous error rate and latency are input features: detection is not early prediction.",
                "A short controlled pilot has insufficient independent repetitions for general accuracy claims.",
                "Retrospective frozen-model forecasts do not prove prospective prediction logging.",
                "Missing telemetry and unconfirmed requests are not healthy negative examples."],
            "plan_sha256": digest(plan), "model_files_sha256": plan["model_files_sha256"]}
    if not rows:
        return {**base, "status": "no_measured_telemetry", "forecasts": {}, "anomalies": None}
    history = regularize_history(pd.DataFrame([r.model_dump() for r in rows]))
    run = Path(plan["model_run"])
    original = json.loads((run/"forecast_manifest.json").read_text())
    # Validate original training-domain integrity; never relabel lab rows as autocloud-api.
    scope = {key: original[key] for key in ("project", "region", "service")}
    manifest = validate_run(run, **scope, now=datetime.now(timezone.utc))
    if not (manifest.training_history_end < start
            and pd.Timestamp(plan["registered_at"]) <= start < end
            and end < pd.Timestamp(source["captured_at"]) <= pd.Timestamp.now(tz="UTC")):
        raise ValueError("Campaign must be registered before execution, after training, and captured after execution")
    am, trees = validate_anomaly_run(run, **scope, now=datetime.now(timezone.utc))
    features = lag_features(history).reindex(columns=manifest.feature_names)
    origin_ok = (history["observed"] & history[list(TARGETS)].notna().all(axis=1)).rolling(16, min_periods=16).sum().eq(16)
    forecasts = {}
    for key, model in manifest.models.items():
        target, horizon = key.rsplit("_", 1)
        h = int(horizon[:-1])
        actual = history[target].shift(-h)
        valid = origin_ok & actual.notna()
        if not valid.any():
            forecasts[key] = {"status": "insufficient_measured_origins", "samples": 0}
            continue
        booster = xgb.Booster({"device": "cpu", "nthread": 1})
        booster.load_model(bytearray((run/(key+".json")).read_bytes()))
        raw = features.loc[valid].to_numpy(dtype=float)
        filled = np.where(np.isfinite(raw), raw, np.asarray(model.imputer_statistics))
        predicted = bound_predictions(booster.predict(xgb.DMatrix(filled)), target)
        realised = actual.loc[valid].to_numpy()
        persistence = history.loc[valid, target].to_numpy()
        model_metrics, baseline = regression_metrics(realised, predicted), regression_metrics(realised, persistence)
        strata = {}
        origins = history.index[valid]
        for i, origin in enumerate(origins):
            phase = phase_at(plan, (origin-start).total_seconds())
            category = (phase.get("fault") or phase["name"].split("_")[0]) if phase else "outside_phase"
            strata.setdefault(category, []).append(i)
        forecasts[key] = {"status": "evaluated_out_of_training_domain", "samples": len(realised),
            "xgboost": model_metrics, "persistence": baseline,
            "beats_persistence_mae": model_metrics["mae"] < baseline["mae"],
            "by_origin_regime": {k: {"samples": len(ix),
                "xgboost": regression_metrics(realised[ix], predicted[ix]),
                "persistence": regression_metrics(realised[ix], persistence[ix])} for k, ix in strata.items()},
            "note": "Targets can cross phases; origin regime does not label future target regime. No confidence claim from this short pilot."}
    measured = history[list(FEATURES)]
    known = measured.notna().any(axis=1)
    scores = pd.Series(np.nan, index=history.index)
    scores.loc[known] = _score_isolation_forest_pure(measured.loc[known].to_numpy(dtype=float), am, trees)
    events = [json.loads(l) for l in request_payload.splitlines() if l.strip()]
    labels, episodes = request_labels(events, plan["latency_slo_seconds"])
    eligible = [t for t, label in labels.items() if t in scores.index and pd.notna(scores.loc[t])
                and (label["impact"] or label["control_only"])]
    episode_results = []
    for name, episode in episodes.items():
        observed = sorted(t for t in episode["minutes"] if t in scores.index and pd.notna(scores.loc[t]))
        flags = [t for t in observed if scores.loc[t] < 0]
        episode_results.append({"episode": name, "fault": episode["fault"],
            "confirmed_requests": episode["confirmed_requests"], "impact_requests": episode["impact_requests"],
            "measured_minutes": len(observed), "raw_model_flagged": bool(flags) if observed else None,
            "has_independently_observed_impact": bool(episode["impact_requests"]),
            "latency_to_first_flag_seconds": max(0, (flags[0]-pd.Timestamp(episode["first_actuation"])).total_seconds()) if flags else None})
    per_type = {}
    for fault in ("cpu_stress", "memory_growth", "latency", "http_503"):
        group = [e for e in episode_results if e["fault"] == fault]
        impacted = [e for e in group if e["has_independently_observed_impact"]]
        measured_impact = [e for e in impacted if e["raw_model_flagged"] is not None]
        per_type[fault] = {"confirmed_episodes": len(group), "impact_episodes": len(impacted),
            "measured_impact_episodes": len(measured_impact),
            "detected_impact_episodes": sum(e["raw_model_flagged"] for e in measured_impact),
            "recall": sum(e["raw_model_flagged"] for e in measured_impact)/len(measured_impact) if measured_impact else None}
    negatives = [t for t in eligible if labels[t]["impact"] == 0]
    false_alarm_minutes = sum(scores.loc[t] < 0 for t in negatives)
    return {**base, "status": "evaluated_descriptive_pilot", "forecasts": forecasts,
        "missing_counts": {name: int(history[name].isna().sum()) for name in FEATURES},
        "anomalies": {"minute_metrics": event_scores([labels[t]["impact"] for t in eligible],
                                                     [int(scores.loc[t] < 0) for t in eligible]),
                      "episodes": episode_results, "by_probe_type": per_type,
                      "measured_control_minutes_without_observed_impact": len(negatives),
                      "false_alarm_minutes": int(false_alarm_minutes),
                      "false_alarm_minutes_per_measured_control_hour": float(false_alarm_minutes*60/len(negatives)) if negatives else None,
                      "planned_episodes": sum("fault" in phase for phase in plan["phases"]), "confirmed_episodes": len(episode_results),
                      "unconfirmed_request_outcomes": sum(not e.get("receipt_confirmed") for e in events),
                      "requests_without_outcome_record": max(0, terminal["requests"]-len(events)),
                      "measured_labelled_minutes": len(eligible)},
        "next_gate": "Independent multi-day real-workload incident validation; no automatic model promotion"}
