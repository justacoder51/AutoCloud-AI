"""Preview or explicitly run bounded, labelled real HTTP test traffic."""

import argparse
import json
import math
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

import numpy as np

# Do not forward the user's identity token to arbitrary configurable URLs.
SERVICE_URL = "https://autocloud-api-437897070681.asia-south1.run.app/"


@dataclass(frozen=True)
class TrafficPlan:
    """Fixed target and conservative resource limits, including a hard request cap."""

    duration_seconds: int = 120
    requests_per_minute: int = 30
    max_requests: int = 60

    def __post_init__(self):
        if not 1 <= self.duration_seconds <= 3600:
            raise ValueError("Duration must be 1..3600 seconds")
        if not 1 <= self.requests_per_minute <= 120:
            raise ValueError("Rate must be 1..120 requests/minute")
        if not 1 <= self.max_requests <= 1000:
            raise ValueError("Request cap must be 1..1000")

    @property
    def request_budget(self) -> int:
        return min(
            self.max_requests,
            math.ceil(self.duration_seconds * self.requests_per_minute / 60),
        )


class NoRedirects(HTTPRedirectHandler):
    """Stop redirects so an identity token cannot follow to a different target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def identity_token() -> str:
    """Read the active CLI identity token into memory; never log or save it."""
    executable = shutil.which("gcloud.cmd" if os.name == "nt" else "gcloud")
    if executable is None:
        raise RuntimeError("Google Cloud CLI was not found")
    result = subprocess.run(
        [executable, "auth", "print-identity-token"], capture_output=True,
        text=True, check=True, timeout=30,
    )
    token = result.stdout.strip()
    if not token or any(character.isspace() for character in token):
        raise RuntimeError("CLI did not return a usable identity token")
    return token


def send_request(token: str, experiment_id: str) -> int:
    """Send one request to the fixed private API; retain no response body."""
    request = Request(SERVICE_URL, headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": f"AutoCloud-Controlled-Traffic/{experiment_id}",
    })
    with build_opener(NoRedirects()).open(request, timeout=10) as response:
        response.read(1024)
        return response.status


def adc_identity_token() -> str:
    """Refresh an already authorised developer ADC identity token in memory."""
    import google.auth
    from google.auth.transport.requests import Request as AuthRequest

    credentials, _ = google.auth.default()
    request = AuthRequest()

    def bounded_request(*args, **kwargs):
        kwargs["timeout"] = 30
        return request(*args, **kwargs)

    try:
        credentials.refresh(bounded_request)
        token = getattr(credentials, "id_token", None)
        if not isinstance(token, str) or not token or any(char.isspace() for char in token):
            raise RuntimeError("Developer ADC did not provide an identity token")
        return token
    finally:
        request.session.close()


def send_request_httpx(token: str, experiment_id: str) -> int:
    """Fixed-target transport supporting the managed session's SOCKS proxy."""
    import httpx

    try:
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            response = client.get(SERVICE_URL, headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": f"AutoCloud-Controlled-Traffic/{experiment_id}",
            })
            return response.status_code
    except httpx.HTTPError as error:
        # The traffic runner handles transport failures without logging tokens/URLs.
        raise URLError(type(error).__name__) from None


def run_traffic(
    plan: TrafficPlan, token_provider: Callable = identity_token,
    transport: Callable = send_request, clock: Callable = time.monotonic,
    sleep: Callable = time.sleep,
) -> dict:
    """Run sequentially within caps; do not catch up by bursting delayed requests."""
    experiment_id = uuid4().hex
    events = []
    start = clock()
    deadline = start + plan.duration_seconds
    token, token_time = "", float("-inf")
    status = "completed"
    failures = 0
    try:
        for number in range(plan.request_budget):
            if clock() >= deadline:
                break
            if clock() - token_time >= 2700:
                token = token_provider()
                token_time = clock()
            if clock() >= deadline:
                break
            request_start = clock()
            code, error_type = None, None
            try:
                code = transport(token, experiment_id)
            except HTTPError as error:
                code = error.code
                error_type = "HTTPError"
            except (URLError, TimeoutError, OSError) as error:
                error_type = type(error).__name__
            events.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status_code": code, "error_type": error_type,
                "client_roundtrip_ms": round((clock() - request_start) * 1000, 3),
            })
            failures = failures + 1 if code is None or code >= 500 else 0
            if code in (401, 403, 429) or (code is not None and 300 <= code < 400):
                status = "stopped_http_error"
                break
            if failures >= 3:
                status = "stopped_repeated_failures"
                break
            if number + 1 < plan.request_budget:
                pause = max(0, min(
                    request_start + 60 / plan.requests_per_minute - clock(),
                    deadline - clock(),
                ))
                if pause:
                    sleep(pause)
    except KeyboardInterrupt:
        status = "interrupted"
    except Exception as error:
        # CLI errors can contain sensitive command output; retain only its type.
        status = "failed_" + type(error).__name__
    latencies = [event["client_roundtrip_ms"] for event in events]
    return {
        "experiment_id": experiment_id, "source": "controlled-real-http-traffic",
        "url": SERVICE_URL, "plan": asdict(plan), "status": status,
        "attempted_requests": len(events),
        "successful_requests": sum(
            event["status_code"] is not None and 200 <= event["status_code"] < 300
            for event in events
        ),
        "elapsed_seconds": round(clock() - start, 3),
        "client_roundtrip_percentiles_ms": {
            f"p{percentile}": float(np.percentile(latencies, percentile))
            for percentile in (50, 95, 99)
        } if latencies else None,
        "note": "Client timings are not server latency; experiment is not anomaly ground truth",
        "events": events,
    }


def main() -> int:
    """Preview by default; only --execute authenticates or sends any requests."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--requests-per-minute", type=int, default=30)
    parser.add_argument("--max-requests", type=int, default=60)
    parser.add_argument("--execute", action="store_true")
    arguments = parser.parse_args()
    try:
        plan = TrafficPlan(
            arguments.duration_seconds, arguments.requests_per_minute, arguments.max_requests,
        )
    except ValueError as error:
        parser.error(str(error))
    if not arguments.execute:
        print(json.dumps({
            "mode": "preview", "url": SERVICE_URL, "plan": asdict(plan),
            "requests_upper_bound": plan.request_budget,
        }))
        return 0
    result = run_traffic(plan)
    output = Path("data/experiments") / (result["experiment_id"] + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    summary = {key: value for key, value in result.items() if key != "events"}
    summary["output"] = str(output)
    print(json.dumps(summary))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
