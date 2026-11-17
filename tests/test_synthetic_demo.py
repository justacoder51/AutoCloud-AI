"""Demo provenance and UI isolation. Synthetic fixtures are not accuracy evidence."""
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from app.dashboard.demo import example_metrics, example_projections, example_alerts
from app.data.schema import MetricRecord


def test_demo_is_fixed_explicitly_synthetic_and_rejected_by_real_metric_schema():
    rows=example_metrics()
    pd.testing.assert_frame_equal(rows,example_metrics())
    assert len(rows)==360 and rows.synthetic.all()
    assert rows.source.eq("synthetic-demo").all()
    assert rows.service_name.eq("synthetic-example").all()
    assert rows.timestamp.diff().dropna().eq(pd.Timedelta(minutes=1)).all()
    with pytest.raises(ValidationError):
        MetricRecord.model_validate({**rows.iloc[0].to_dict(),"collected_at":rows.timestamp.iloc[-1],
            "project_id":"test-project","region":"asia-south1"})


def test_demo_projections_and_thresholds_are_finite_and_bounded():
    rows=example_metrics()
    future=example_projections(rows)
    assert len(future)==9 and not future.execution_allowed.any()
    assert np.isfinite(future.illustrative_projection).all()
    assert future.timestamp.gt(rows.timestamp.max()).all()
    assert future[future.target!="request_count"].illustrative_projection.between(0,1).all()
    alerts=example_alerts(rows)
    assert alerts.example_alert.sum()==13
    assert not alerts.iloc[-1].example_alert


def test_demo_renders_without_network_auth_or_model_calls(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import httpx
    monkeypatch.setenv("DASHBOARD_PUBLIC_SHOWCASE","true")
    client=Mock(side_effect=AssertionError("Demo must not make HTTP calls"))
    monkeypatch.setattr(httpx,"Client",client)
    app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app/dashboard/home.py"))
    app.session_state["autocloud_data_mode"]="Synthetic demo"
    app.run(timeout=30)
    assert not app.exception
    assert not client.called
    assert any("SYNTHETIC DEMO" in str(x.value) for x in app.warning)
    assert any("not XGBoost predictions" in str(x.value) for x in app.info)
    assert not app.button
    assert len(app.dataframe)==2
