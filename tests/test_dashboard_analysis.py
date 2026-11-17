"""Actual LangGraph execution with fixture evidence and mocked Gemini calls."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.data.schema import MetricRecord
from app.main import create_app
from app.services.analysis_service import AnalysisBusy, DashboardAnalysis


def history(stale=False):
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    rows = [MetricRecord(timestamp=now-timedelta(minutes=i+(60 if stale else 0)),
                         collected_at=now, project_id='test-project', region='asia-south1',
                         service_name='autocloud-api', cpu_utilization=.99, memory_utilization=.2,
                         error_rate=0, request_count=10).model_dump(mode='json') for i in (4,3,2)]
    return Mock(read=Mock(return_value={'status':'succeeded','records':rows}))


def test_one_explicit_gemini_selection_and_cooldown():
    clock = [0]
    service = DashboardAnalysis(clock=lambda: clock[0])
    source = history()
    selector = Mock(return_value={'summary_code':'investigate_observed_pressure', 'ordered_actions':['review_capacity']})
    settings = Settings(gcp_project_id='test-project', dashboard_gemini_enabled=True)
    first = service.run(settings, source, hours=24, use_gemini=True, include_billing=False, selector=selector)
    assert first['result']['gemini']['status'] == 'succeeded'
    assert first['result']['recommendations'][0]['action'] == 'review_capacity'
    assert first['result']['execution_allowed'] is False
    cached = service.run(settings, source, hours=24, use_gemini=True, include_billing=False, selector=selector)
    assert cached['cache_hit']
    selector.assert_called_once()
    source.read.assert_called_once()
    with pytest.raises(AnalysisBusy):
        service.run(settings, source, hours=1, use_gemini=True, include_billing=False)
    clock[0] = 61
    service.run(settings, source, hours=24, use_gemini=True, include_billing=False, selector=selector)
    assert selector.call_count == 2


def test_stale_evidence_skips_gemini_and_failures_do_not_leak():
    settings = Settings(gcp_project_id='test-project', dashboard_gemini_enabled=True)
    selector = Mock(side_effect=RuntimeError('credential-detail'))
    result = DashboardAnalysis().run(settings, history(stale=True), hours=24, use_gemini=True, include_billing=False, selector=selector)
    assert result['result']['workflow_status'] == 'blocked_evidence'
    assert result['result']['gemini']['status'] == 'skipped_unusable_evidence'
    selector.assert_not_called()
    result = DashboardAnalysis().run(settings, history(), hours=24, use_gemini=True, include_billing=False, selector=selector)
    assert result['result']['gemini']['status'] == 'failed_or_rejected'
    assert 'credential-detail' not in str(result)


def test_api_requires_configuration_and_refuses_browser_or_untrusted_inputs(tmp_path):
    app = create_app(Settings(environment='test', gcp_project_id='test-project'))
    app.state.analytics_data_root = tmp_path
    app.state.dashboard_history = history()
    with TestClient(app) as client:
        assert client.get('/api/analysis').status_code == 405
        assert client.post('/api/analysis', json={'use_gemini':True}).status_code == 409
        assert client.post('/api/analysis', json={'include_billing':True}).status_code == 409
        assert client.post('/api/analysis', json={'hours':25}).status_code == 422
        assert client.post('/api/analysis', json={'connectivity_check':True}).status_code == 422
        assert client.post('/api/analysis', json={'records':[]}).status_code == 422
        assert client.post('/api/analysis', json={'use_gemini':'true'}).status_code == 422
        assert client.post('/api/analysis', json={}, headers={'Origin':'https://example.com'}).status_code == 403
        result = client.post('/api/analysis', json={})
        assert result.status_code == 200
        assert result.json()['result']['gemini']['status'] == 'disabled'
        assert client.post('/api/analysis', json={}).json()['cache_hit'] is True
        assert client.post('/api/analysis', json={'hours':1}).status_code == 429


def test_analysis_ui_does_not_call_until_form_submit(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    payload = DashboardAnalysis().run(Settings(gcp_project_id='test-project'), history(stale=True),
                                     hours=24, use_gemini=True, include_billing=False,
                                     selector=Mock(side_effect=AssertionError('Stale evidence must not call Gemini')))
    response = Mock(json=Mock(return_value=payload))
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.post.return_value = response
    monkeypatch.setattr(httpx, 'Client', Mock(return_value=client))
    path = tmp_path/'analysis_app.py'
    path.write_text("from app.dashboard.analysis import render_analysis\nrender_analysis('http://localhost:8080', {}, {'ai_workflow':True,'gemini_enabled':True}, 24)")
    app = AppTest.from_file(str(path)).run()
    assert not app.exception
    client.post.assert_not_called()
    app.checkbox[0].check()
    app.button[0].click().run()
    assert not app.exception
    client.post.assert_called_once()
    assert client.post.call_args.kwargs['json']['use_gemini'] is True
    assert any('skipped_unusable_evidence' in m.value for m in app.markdown)


def test_connectivity_probe_never_reads_or_fabricates_monitoring():
    source = Mock()
    selector = Mock(return_value={'summary_code':'insufficient_recent_evidence','ordered_actions':[]})
    result = DashboardAnalysis().run(Settings(gcp_project_id='test-project'), source,
        hours=24, use_gemini=True, include_billing=False, connectivity_check=True, selector=selector)
    assert result['status'] == 'completed'
    assert result['result']['mode'] == 'connectivity_probe_only'
    assert result['result']['recommendations'] == []
    source.read.assert_not_called()
    selector.assert_called_once()
    assert selector.call_args.args[0]['candidates'] == []
