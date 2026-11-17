"""Cloud dashboard boundaries without cloud calls or model inference."""

import hashlib
import json
import httpx
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.dashboard.authentication import api_headers
from app.main import create_app
from app.services.recorded_evaluation import load_recorded_evaluation


def test_recorded_summary_is_scoped_and_checksummed(tmp_path):
    record = {'project': 'test-project', 'region': 'asia-south1', 'service': 'autocloud-api',
              'evaluation': {'deployment_allowed': False, 'run_name': 'test'}}
    path = tmp_path / 'evaluation.json'
    path.write_bytes(json.dumps(record).encode())
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    assert load_recorded_evaluation(str(path), checksum, 'test-project', 'asia-south1', 'autocloud-api')['run_name'] == 'test'
    with pytest.raises(ValueError):
        load_recorded_evaluation(str(path), checksum, 'other-project', 'asia-south1', 'autocloud-api')
    with pytest.raises(ValueError):
        load_recorded_evaluation(str(path), '0'*64, 'test-project', 'asia-south1', 'autocloud-api')
    app = create_app(Settings(environment='production', gcp_project_id='test-project',
                              dashboard_evaluation_file=str(path), dashboard_evaluation_sha256=checksum))
    app.state.analytics_data_root = tmp_path
    with TestClient(app) as client:
        payload = client.get('/api/overview').json()
        assert payload['models']['status'] == 'recorded_evaluation_only'
        assert payload['models']['forecasts'] is None
        assert payload['models']['forecast_status'] == 'not_deployed'
        assert payload['capabilities']['local_reviews'] is False
        assert client.get('/api/reviews').status_code == 403


@pytest.mark.parametrize('url', ['http://example.run.app', 'https://example.com',
                               'https://example.run.app/path', 'https://user@example.run.app',
                               'https://example.run.app?query=1'])
def test_identity_token_is_not_sent_to_unapproved_destinations(url):
    with pytest.raises(ValueError):
        api_headers(url, 'cloudrun')


def test_identity_token_uses_configured_origin(monkeypatch):
    from google.oauth2 import id_token
    calls = []
    def fetch(request, audience):
        calls.append(audience)
        return 'fixture-token'
    monkeypatch.setattr(id_token, 'fetch_id_token', fetch)
    assert api_headers('https://example.run.app', 'cloudrun') == {
        'Authorization': 'Bearer fixture-token',
        'X-AutoCloud-Authorization': 'Bearer fixture-token',
    }
    assert calls == ['https://example.run.app']
    assert api_headers('http://127.0.0.1:8080') == {}


def test_private_proxy_rejects_cross_origin_before_using_identity():
    from app.dashboard.private_proxy import create_proxy
    calls = []
    app = create_proxy('https://example.run.app', token_provider=lambda: calls.append(True))
    with TestClient(app) as client:
        assert client.get('/', headers={'origin': 'https://evil.example'}).status_code == 403
        assert client.get('/', headers={'sec-fetch-site': 'cross-site'}).status_code == 403
    assert calls == []
    with pytest.raises(ValueError):
        create_proxy('https://example.com')


def test_private_proxy_forwards_identity_only_upstream(monkeypatch):
    from app.dashboard.private_proxy import create_proxy
    from unittest.mock import AsyncMock, Mock
    response = httpx.Response(200, content=b'<html>private dashboard</html>',
                              headers={'content-type': 'text/html'})
    upstream = AsyncMock()
    upstream.request.return_value = response
    context = Mock()
    context.__aenter__ = AsyncMock(return_value=upstream)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(httpx, 'AsyncClient', Mock(return_value=context))
    with TestClient(create_proxy('https://example.run.app', token_provider=lambda: 'fixture-token')) as client:
        result = client.get('/')
    assert result.status_code == 200
    assert 'fixture-token' not in result.text and 'authorization' not in result.headers
    assert upstream.request.call_args.kwargs['headers']['Authorization'] == 'Bearer fixture-token'
