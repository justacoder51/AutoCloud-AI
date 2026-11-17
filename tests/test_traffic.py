"""Traffic caps and token handling are checked without sending real requests."""

import json
from urllib.error import HTTPError
from unittest.mock import Mock

import pytest

from app.data.traffic import NoRedirects, SERVICE_URL, TrafficPlan, run_traffic


class FakeClock:
    def __init__(self):
        self.now = 0.

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.mark.parametrize("values", [
    {"duration_seconds": 3601}, {"requests_per_minute": 0},
    {"requests_per_minute": 121}, {"max_requests": 1001},
])
def test_invalid_plans_are_rejected(values):
    with pytest.raises(ValueError):
        TrafficPlan(**values)


def test_traffic_has_hard_count_and_duration_limits_without_token_logging():
    clock = FakeClock()
    token = "test-token-never-save"
    transport = Mock(return_value=200)
    result = run_traffic(
        TrafficPlan(duration_seconds=120, requests_per_minute=30, max_requests=3),
        lambda: token, transport, clock, clock.sleep,
    )
    assert result["attempted_requests"] == result["successful_requests"] == 3
    assert result["elapsed_seconds"] == 4
    assert result["url"] == SERVICE_URL
    assert token not in json.dumps(result)
    assert transport.call_args.args[0] == token


def test_traffic_stops_on_unauthorized_response():
    clock = FakeClock()
    transport = Mock(side_effect=HTTPError(SERVICE_URL, 403, "denied", {}, None))
    result = run_traffic(TrafficPlan(), lambda: "test", transport, clock, clock.sleep)
    assert result["attempted_requests"] == 1
    assert result["status"] == "stopped_http_error"


def test_traffic_does_not_follow_redirects_or_burst_on_failures():
    assert NoRedirects().redirect_request(None, None, 302, "", {}, "https://example.com") is None
    clock = FakeClock()
    transport = Mock(side_effect=TimeoutError("fixture"))
    result = run_traffic(TrafficPlan(), lambda: "test", transport, clock, clock.sleep)
    assert result["attempted_requests"] == 3
    assert result["status"] == "stopped_repeated_failures"
    assert result["elapsed_seconds"] == 4


def test_slow_requests_do_not_start_new_requests_after_deadline():
    clock = FakeClock()

    def slow_transport(token, experiment):
        clock.now += 10
        return 200

    result = run_traffic(
        TrafficPlan(duration_seconds=12), lambda: "test", slow_transport, clock, clock.sleep,
    )
    assert result["attempted_requests"] == 2
    # A request already in flight may complete beyond the scheduling deadline.
    assert result["elapsed_seconds"] == 20


def test_developer_adc_identity_token_is_refreshed_with_bounded_transport_and_not_saved(monkeypatch):
    from app.data.traffic import adc_identity_token

    credentials = Mock(id_token="fixture-id-token")
    request = Mock()
    credentials.refresh.side_effect = lambda transport: transport("https://fixture.invalid", timeout=999)
    monkeypatch.setattr("google.auth.default", lambda: (credentials, "fixture-project"))
    monkeypatch.setattr("google.auth.transport.requests.Request", lambda: request)
    assert adc_identity_token() == "fixture-id-token"
    assert request.call_args.kwargs["timeout"] == 30
    request.session.close.assert_called_once()


def test_httpx_training_transport_keeps_fixed_target_redirect_refusal_and_private_header(monkeypatch):
    from app.data.traffic import send_request_httpx

    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.get.return_value.status_code = 200
    constructor = Mock(return_value=client)
    monkeypatch.setattr("httpx.Client", constructor)
    assert send_request_httpx("fixture-id-token", "fixture-experiment") == 200
    assert constructor.call_args.kwargs == {"timeout": 10, "follow_redirects": False}
    assert client.get.call_args.args == (SERVICE_URL,)
    assert client.get.call_args.kwargs["headers"]["Authorization"] == "Bearer fixture-id-token"
