"""Validation math and label provenance, with no model training or cloud calls."""
import numpy as np
import pandas as pd
import pytest

from app.models.real_validation import event_scores, interval, label_minutes, paired_hour_bootstrap


def test_all_positive_classifier_cannot_appear_precise_on_negative_minutes():
    scores=event_scores([0,0,1],[1,1,1])
    assert scores["recall"]==1
    assert scores["precision"]==pytest.approx(1/3)
    assert scores["false_positive_rate"]==1
    assert scores["confusion_matrix"]==[[0,2],[0,1]]


def test_absent_positive_faults_do_not_establish_recall():
    scores=event_scores([0,0],[0,0])
    assert scores["recall"] is None and scores["recall_wilson_95"] is None
    assert scores["precision"] is None
    assert scores["support_status"]=="single_or_no_class"
    assert interval(4,4)[0]<.6
    with pytest.raises(ValueError): event_scores([0,2],[0,1])


def test_log_labels_are_separate_outcomes_and_unknown_minutes_stay_unknown():
    entries=[{"timestamp":"2026-11-16T12:00:05Z","status":503,"entry_hash":"one"},
             {"timestamp":"2026-11-16T12:00:05Z","status":503,"entry_hash":"one"},
             {"timestamp":"2026-11-16T12:01:05Z","status":200,"entry_hash":"two"},
             {"timestamp":"2026-11-16T12:02:05Z","status":403,"entry_hash":"three"}]
    labels=label_minutes(entries)
    assert labels[pd.Timestamp("2026-11-16T12:01:00Z")]["label"]==1
    assert labels[pd.Timestamp("2026-11-16T12:01:00Z")]["requests"]==1
    assert labels[pd.Timestamp("2026-11-16T12:02:00Z")]["label"]==0
    assert labels[pd.Timestamp("2026-11-16T12:03:00Z")]["label"] is None


def test_block_interval_handles_dependence_and_small_block_counts():
    index=pd.date_range("2026-11-16",periods=180,freq="min",tz="UTC")
    assert paired_hour_bootstrap(index,np.ones(180),np.zeros(180))["delta_mae_95"] is None
    index=pd.date_range("2026-11-16",periods=300,freq="min",tz="UTC")
    result=paired_hour_bootstrap(index,np.ones(300),np.zeros(300))
    assert result["delta_mae_95"]==[1.,1.]
    assert result["nine_comparison_bonferroni_interval"]==[1.,1.]


def test_packaged_evidence_is_scoped_and_matches_unchanged_models(monkeypatch):
    from app.services import validation_evidence
    from pathlib import Path
    run=Path(__file__).resolve().parents[1]/"models/runs/20261116T051914Z_48d41482"
    kwargs=dict(project="astute-sign-506809-j8",region="asia-south1",service="autocloud-api")
    assert validation_evidence.load_measured_validation(run,**kwargs)["observed_minutes"]==438
    assert validation_evidence.load_measured_validation(run,**{**kwargs,"project":"other-project"}) is None
    monkeypatch.setattr(validation_evidence,"SUMMARY_SHA256","0"*64)
    assert validation_evidence.load_measured_validation(run,**kwargs) is None
