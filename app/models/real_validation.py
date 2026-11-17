"""Frozen-model evaluation on measured, post-training temporal data.

No fitting, production inference-gate changes, or synthetic fault labels.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd

from app.data.schema import MetricRecord
from app.models.anomaly_detector import operational_interpretation, threshold_flags
from app.models.dataset import FEATURES, TARGETS, chronological_masks, lag_features, regularize_history
from app.models.inference import checked_file, validate_run, validate_anomaly_run, _score_isolation_forest_pure
from app.models.resource_predictor import bound_predictions, regression_metrics


def interval(successes, total):
    """Wilson descriptive interval; dependence between minutes is a limitation."""
    if total == 0:
        return None
    if not 0 <= successes <= total:
        raise ValueError("Invalid binomial counts")
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z*z/total
    centre = (p + z*z/(2*total))/denominator
    width = z*sqrt(p*(1-p)/total+z*z/(4*total*total))/denominator
    return [max(0., centre-width), min(1., centre+width)]


def event_scores(labels, flags):
    y, p = np.asarray(labels), np.asarray(flags)
    if y.shape != p.shape or y.ndim != 1 or not np.isin(y,[0,1]).all() or not np.isin(p,[0,1]).all():
        raise ValueError("Binary equally sized vectors required")
    tp, fp = int(((y==1)&(p==1)).sum()), int(((y==0)&(p==1)).sum())
    tn, fn = int(((y==0)&(p==0)).sum()), int(((y==1)&(p==0)).sum())
    return {"samples":len(y), "positive_minutes":tp+fn, "negative_minutes":tn+fp,
        "confusion_matrix":[[tn,fp],[fn,tp]],
        "precision":tp/(tp+fp) if tp+fp else None,
        "recall":tp/(tp+fn) if tp+fn else None,
        "false_positive_rate":fp/(fp+tn) if fp+tn else None,
        "recall_wilson_95":interval(tp,tp+fn), "fpr_wilson_95":interval(fp,fp+tn),
        "support_status":"both_classes" if tp+fn and tn+fp else "single_or_no_class",
        "limitations":"Minutes can be correlated; these intervals are descriptive, not independent incident-level confidence."}


def paired_hour_bootstrap(index, model_errors, baseline_errors):
    """Resample paired hour blocks instead of pretending minutes are independent."""
    frame = pd.DataFrame({"model":model_errors,"baseline":baseline_errors,"n":1}, index=index)
    blocks = frame.groupby(frame.index.floor("h")).sum().to_numpy()
    if len(blocks)<4:
        return {"status":"insufficient_hour_blocks", "blocks":len(blocks), "delta_mae_95":None}
    rng = np.random.default_rng(42)
    samples = blocks[rng.integers(0,len(blocks),size=(2000,len(blocks)))].sum(axis=1)
    delta = (samples[:,0]-samples[:,1])/samples[:,2]
    return {"status":"descriptive", "blocks":len(blocks), "replicates":2000,
        "delta_mae_95":[float(v) for v in np.quantile(delta,[.025,.975])],
        "nine_comparison_bonferroni_interval":[float(v) for v in np.quantile(delta,[.05/(2*9),1-.05/(2*9)])],
        "interpretation":"Negative favours model; adjacent hour blocks and one workload can still be dependent."}


def label_minutes(entries):
    """Labels originate only from logged HTTP outcomes, never model/threshold flags."""
    groups = {}
    seen = set()
    for e in entries:
        identity = e["entry_hash"]
        if identity in seen:
            continue
        seen.add(identity)
        end = pd.Timestamp(e["timestamp"]).ceil("min")
        group = groups.setdefault(end,{"requests":0,"server_errors":0,"successes":0})
        group["requests"] += 1
        group["server_errors"] += int(500<=e["status"]<600)
        group["successes"] += int(200<=e["status"]<300)
    for group in groups.values():
        group["label"] = 1 if group["server_errors"] else 0 if group["successes"] else None
    return groups


def evaluate(folder):
    import xgboost as xgb
    folder = Path(folder)
    protocol = json.loads((folder/"protocol.json").read_text())
    run = Path(protocol["model_run"])
    for name,digest in protocol["model_files_sha256"].items():
        if hashlib.sha256((run/name).read_bytes()).hexdigest()!=digest:
            raise ValueError("Model changed after protocol registration")
    snapshot = (folder/"observations.ndjson").read_bytes()
    if hashlib.sha256(snapshot).hexdigest()!=json.loads((folder/"observations-source.json").read_text())["sha256"]:
        raise ValueError("Observation snapshot changed")
    rows = [MetricRecord.model_validate_json(l) for l in snapshot.decode().splitlines() if l.strip()]
    start,end = pd.Timestamp(protocol["start_exclusive"]),pd.Timestamp(protocol["end_inclusive"])
    if any(not start<r.timestamp<=end for r in rows):
        raise ValueError("Holdout overlaps training or exceeds fixed end")
    history = regularize_history(pd.DataFrame([r.model_dump() for r in rows]))
    manifest = validate_run(run,project=protocol["project"],region=protocol["region"],service=protocol["service"],now=datetime.now(timezone.utc))
    if start < manifest.training_history_end or any(
        (r.project_id,r.region,r.service_name)!=(protocol["project"],protocol["region"],protocol["service"])
        or r.collected_at>datetime.fromisoformat(protocol["registered_at"]) for r in rows):
        raise ValueError("Invalid temporal holdout scope or future-collected evidence")
    training_bytes = (run/"history.ndjson").read_bytes()
    if hashlib.sha256(training_bytes).hexdigest()!=protocol["history_sha256"]:
        raise ValueError("Training evidence changed")
    training = regularize_history(pd.DataFrame([MetricRecord.model_validate_json(l).model_dump() for l in training_bytes.decode().splitlines() if l.strip()]))
    features = lag_features(history).reindex(columns=manifest.feature_names)
    origin_ok = (history["observed"] & history[list(TARGETS)].notna().all(axis=1)).rolling(16,min_periods=16).sum().eq(16)
    forecasts = {}
    for key, model in manifest.models.items():
        target,horizon = key.rsplit("_",1); h=int(horizon[:-1])
        future = history[target].shift(-h)
        valid = origin_ok & future.notna()
        if not valid.any():
            forecasts[key] = {"status":"no_eligible_origins"}
            continue
        contents = checked_file(run,key+".json",4_000_000)
        if hashlib.sha256(contents).hexdigest()!=model.sha256:
            raise ValueError("Model checksum mismatch")
        booster=xgb.Booster({"device":"cpu","nthread":1});booster.load_model(bytearray(contents))
        raw=features.loc[valid].to_numpy(dtype=float)
        filled=np.where(np.isfinite(raw),raw,np.asarray(model.imputer_statistics))
        predicted=bound_predictions(booster.predict(xgb.DMatrix(filled)),target)
        actual=future.loc[valid].to_numpy(); persistence=history.loc[valid,target].to_numpy()
        train_mask=chronological_masks(training.index,h)["train"]
        mean=float(training[target].shift(-h).loc[train_mask].mean())
        m,b=regression_metrics(actual,predicted),regression_metrics(actual,persistence)
        forecasts[key]={"status":"evaluated", "samples":len(actual),"origin_start":history.index[valid][0].isoformat(),
            "origin_end":history.index[valid][-1].isoformat(),"xgboost":m,"persistence":b,
            "historical_average":regression_metrics(actual,np.full(len(actual),mean)),
            "beats_persistence_mae":m["mae"]<b["mae"],
            "paired_uncertainty":paired_hour_bootstrap(history.index[valid],np.abs(actual-predicted),np.abs(actual-persistence))}

    am,trees=validate_anomaly_run(run,project=protocol["project"],region=protocol["region"],service=protocol["service"],now=datetime.now(timezone.utc))
    measured=history[list(FEATURES)]; known=measured.notna().any(axis=1)
    scores=pd.Series(np.nan,index=history.index)
    scores.loc[known]=_score_isolation_forest_pure(measured.loc[known].to_numpy(dtype=float),am,trees)
    thresholds=threshold_flags(measured)
    log_source=json.loads((folder/"request-logs-source.json").read_text())
    logs=json.loads((folder/"request-logs.json").read_text())
    labels=label_minutes(logs) if log_source.get("complete") else {}
    paired=[]
    for minute,outcome in labels.items():
        if outcome["label"] is None or minute not in history.index or not known.loc[minute]:
            continue
        threshold=bool(thresholds.loc[minute]) if pd.notna(thresholds.loc[minute]) else None
        flag=bool(scores.loc[minute]<0)
        paired.append({"timestamp":minute.isoformat(),**outcome,"raw_flag":int(flag),
            "observed_error_signal":int(history.loc[minute,"error_rate"]>0) if pd.notna(history.loc[minute,"error_rate"]) else None,
            "threshold_flag":int(threshold) if threshold is not None else None,
            "operational_investigation":int(operational_interpretation(measured.loc[minute],flag,threshold)=="investigate_measured_pressure"),
            "request_count_matches":pd.notna(history.loc[minute,"request_count"]) and float(history.loc[minute,"request_count"])==outcome["requests"]})
    comparisons={}
    for scope, cohort in [("all_separately_logged_outcomes",paired),("matching_request_counts",[r for r in paired if r["request_count_matches"]])]:
        comparisons[scope]={}
        for field in ("raw_flag","threshold_flag","operational_investigation","observed_error_signal"):
            eligible=[r for r in cohort if r[field] is not None]
            comparisons[scope][field]=event_scores([r["label"] for r in eligible],[r[field] for r in eligible])
    billing=json.loads((folder/"billing-export.json").read_text())
    result={"source":"real_post_training_monitoring_and_request_logs", "study":str(folder),
        "model_run":str(run),"training_end":manifest.training_history_end.isoformat(),
        "period_start_exclusive":start.isoformat(),"period_end_inclusive":end.isoformat(),
        "observed_minutes":len(rows),"calendar_minutes":len(history), "forecast_results":forecasts,
        "forecast_mae_wins":sum(r.get("beats_persistence_mae",False) for r in forecasts.values()),
        "forecast_models_evaluated":sum(r["status"]=="evaluated" for r in forecasts.values()),
        "anomaly_event_comparisons":comparisons,"labelled_pairs":paired,
        "logged_server_error_requests":sum(500<=e["status"]<600 for e in logs),
        "fault_label_scope":"Observed HTTP availability errors only, not operator-certified general infrastructure faults. Error rate is an input feature: contemporaneous detection, not prediction.",
        "general_fault_accuracy_established":False,
        "cost_evidence":{"billing_status":billing["status"],"aggregate_rows":len(billing["rows"]),
            "measured_savings":None,"savings_established":False,
            "reasons":["No verified matched optimisation baseline/treatment experiment", "No matching exported billing rows" if not billing["rows"] else "Export aggregates do not by themselves establish causal savings"]},
        "limitations":["One project/service and changing revisions; no broad workload generalisation.",
            "Labelled request minutes are selected by logged traffic and can be correlated.",
            "No observed server error is not proof of infrastructure health.",
            "Log/Monitoring minute alignment and delivery may differ; matching-count comparison is provided.",
            "No hyperparameters, weights, deployment, traffic or cloud configuration changed by this evaluation."]}
    (folder/"evaluation.json").write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf-8")
    print(json.dumps({k:result[k] for k in ("forecast_mae_wins","forecast_models_evaluated","observed_minutes","logged_server_error_requests","cost_evidence")}),flush=True)
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("study",type=Path)
    evaluate(parser.parse_args().study)
