"""Prepare or run a bounded PRIVATE lab campaign; no production mutations.

prepare is entirely local. run requires the exact approved plan SHA, an already
deployed private dedicated service, and its immutable image digest.
"""
import argparse
from collections import deque
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tarfile
import time
from uuid import uuid4

import httpx

from app.validation.protocol import PROJECT, REGION, SERVICE, digest, make_plan, phase_at, rpm_at, verify_plan

ROOT = Path(__file__).resolve().parents[1]


def save(folder, name, value):
    (folder/name).write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def append(folder, name, value):
    with (folder/name).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, allow_nan=False)+"\n")
        stream.flush()


def read_plan(folder, approved=None):
    plan = json.loads((folder/"plan.json").read_text(encoding="utf-8"))
    verify_plan(plan)
    if approved is not None and digest(plan) != approved:
        raise ValueError("Approved plan checksum does not match")
    return plan


def prepare(minutes=30):
    now = datetime.now(timezone.utc)
    folder = ROOT/"data/validation_campaigns"/now.strftime("%Y%m%dT%H%M%SZ")
    folder.mkdir(parents=True, exist_ok=False)
    plan = make_plan(minutes)
    save(folder, "plan.json", plan)
    archive = folder/"source.tgz"
    files = ["infrastructure/validation-lab.Dockerfile", "app/validation/lab_app.py"]
    with tarfile.open(archive, "w:gz") as tar:
        for filename in files:
            tar.add(ROOT/filename, arcname=filename, recursive=False)
    tag = f"{REGION}-docker.pkg.dev/{PROJECT}/autocloud/autocloud-validation-lab:{folder.name.lower()}"
    save(folder, "build.json", {
        "steps": [{"name": "gcr.io/cloud-builders/docker", "args": ["build", "-f", files[0], "-t", tag, "."]},
                  {"name": "gcr.io/cloud-builders/docker", "args": ["run", "--rm", tag, "python", "-c",
                     "from app.validation.lab_app import app; assert len(app.routes)==1; print('isolated lab import passed')"]},
                  {"name": "gcr.io/cloud-builders/docker", "args": ["run", "--rm", tag, "pip", "check"]}],
        "images": [tag], "timeout": "1200s", "options": {"logging": "CLOUD_LOGGING_ONLY"},
        "serviceAccount": f"projects/{PROJECT}/serviceAccounts/437897070681-compute@developer.gserviceaccount.com"})
    save(folder, "preparation.json", {"status": "prepared_not_built_or_deployed", "plan_sha256": digest(plan),
         "source_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "image_tag": tag,
         "build_config_sha256": hashlib.sha256((folder/"build.json").read_bytes()).hexdigest(),
         "production_changes": False, "traffic_started": False})
    print(json.dumps({"directory": str(folder), "plan_sha256": digest(plan), "image_tag": tag}), flush=True)


def authorised_session():
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return AuthorizedSession(credentials)


def checked(response):
    if not response.ok:
        raise RuntimeError(f"Google API request failed: HTTP {response.status_code}")
    return response.json()


def check_target(session, run_id, image_digest, duration_minutes=120):
    """Discover the URL from fixed Google API, never accept a token destination URL."""
    import re
    if re.fullmatch(r"sha256:[a-f0-9]{64}", image_digest) is None:
        raise ValueError("An immutable digest is required")
    base = f"https://run.googleapis.com/v2/projects/{PROJECT}/locations/{REGION}/services/{SERVICE}"
    service = checked(session.get(base, timeout=30))
    policy = checked(session.get(base+":getIamPolicy", timeout=30))
    if service.get("invokerIamDisabled") or any(
        m in ("allUsers", "allAuthenticatedUsers") for b in policy.get("bindings", []) for m in b.get("members", [])
    ):
        raise ValueError("Laboratory must require private IAM invocation")
    template = service["template"]
    container = template["containers"][0]
    env = {e["name"]: e.get("value") for e in container.get("env", [])}
    expected_image = f"{REGION}-docker.pkg.dev/{PROJECT}/autocloud/autocloud-validation-lab@{image_digest}"
    limits = container["resources"]["limits"]
    scaling = template.get("scaling", {})
    service_scaling = service.get("scaling", {})
    expiry = datetime.fromisoformat(env.get("LAB_EXPIRES_AT", ""))
    now = datetime.now(timezone.utc)
    if not (container["image"] == expected_image and env.get("LAB_RUN_ID") == run_id
            and env.get("AUTOCLOUD_COMPONENT") == "validation_lab"
            and env.get("LAB_PLAN_SHA256") and limits.get("cpu") == "1"
            and limits.get("memory") == "512Mi" and scaling.get("maxInstanceCount") == 1
            and scaling.get("minInstanceCount", 0) == 0
            and service_scaling.get("minInstanceCount", 0) == 0
            and template["maxInstanceRequestConcurrency"] == 1 and template["timeout"] == "10s"
            and template["serviceAccount"] == f"{SERVICE}@{PROJECT}.iam.gserviceaccount.com"
            and container["resources"].get("cpuIdle", True)
            and expiry.tzinfo and now+timedelta(minutes=duration_minutes) < expiry <= now+timedelta(minutes=duration_minutes+15)):
        raise ValueError("Lab deployment differs from the approved bounds, image or lifetime")
    url = service["uri"]
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname.endswith(".run.app") or parts.path or parts.query or parts.fragment:
        raise ValueError("Unexpected canonical Cloud Run URL")
    return url, service, env


def valid_receipt(body, run_id, sequence, fault, sent_at, received_at):
    """Expose intent separately from confirmed actuation and observed HTTP effects."""
    try:
        start, end = datetime.fromisoformat(body["started_at"]), datetime.fromisoformat(body["finished_at"])
        return (body["run_id"] == run_id and body["sequence"] == sequence and body["fault"] == fault
                and start.tzinfo and end.tzinfo and sent_at-timedelta(seconds=10) <= start <= end
                and end <= received_at+timedelta(seconds=10))
    except (KeyError, TypeError, ValueError):
        return False


def run(folder, approved, image_digest, run_id):
    import re
    from app.data.traffic import adc_identity_token
    if not approved or re.fullmatch(r"[a-f0-9]{32}", run_id or "") is None:
        raise ValueError("Explicit approved plan checksum and deployment run ID are required")
    plan = read_plan(folder, approved)
    if (folder/"execution.json").exists():
        raise ValueError("This campaign has already started; do not restart or resume into the same evidence")
    session = authorised_session()
    url, service, env = check_target(session, run_id, image_digest, plan["duration_minutes"])
    if env["LAB_PLAN_SHA256"] != approved:
        raise ValueError("Deployed plan differs from the approved plan")
    # Opening exclusively before any traffic prevents concurrent/double runs.
    started_at = datetime.now(timezone.utc)
    with (folder/"execution.json").open("x", encoding="utf-8") as stream:
        json.dump({"status": "running", "run_id": run_id, "plan_sha256": approved,
                   "started_at": started_at.isoformat(), "image_digest": image_digest,
                   "revision": service["latestReadyRevision"]}, stream, indent=2)
    start = time.monotonic()
    sent = 0
    recent = deque()
    token, token_at = None, -1e10
    last_phase = None
    status = "failed"
    try:
        with httpx.Client(timeout=9, follow_redirects=False) as client:
            while time.monotonic()-start < plan["duration_minutes"]*60:
                elapsed = time.monotonic()-start
                if elapsed >= plan["duration_minutes"]*60-10:
                    # Leave room for the last in-flight request; never start beyond the deadline.
                    break
                phase = phase_at(plan, elapsed)
                if not phase:
                    break
                if phase["name"] != last_phase:
                    append(folder, "phase-intent.ndjson", {"recorded_at": datetime.now(timezone.utc).isoformat(), "phase": phase})
                    last_phase = phase["name"]
                    print("Phase:", last_phase, "requests:", sent, flush=True)
                rpm = rpm_at(phase, elapsed)
                if not rpm:
                    time.sleep(min(5, (phase["start_minute"]+phase["minutes"])*60-elapsed))
                    continue
                while recent and time.monotonic()-recent[0] >= 60:
                    recent.popleft()
                if len(recent) >= plan["maximum_rpm"]:
                    time.sleep(min(5, max(.01, 60-(time.monotonic()-recent[0]))))
                    continue
                if sent >= plan["maximum_requests"]:
                    raise RuntimeError("Hard request cap reached")
                if time.monotonic()-token_at > 1800:
                    token = adc_identity_token()
                    token_at = time.monotonic()
                # Recheck phase after token refresh so a slow refresh cannot inject into recovery.
                elapsed = time.monotonic()-start
                phase = phase_at(plan, elapsed)
                if phase is None or rpm_at(phase, elapsed) == 0:
                    continue
                fault = phase.get("fault", "none")
                sequence = sent
                sent_at = datetime.now(timezone.utc)
                recent.append(time.monotonic())
                sent += 1
                event = {"sequence": sequence, "sent_at": sent_at.isoformat(), "phase": phase["name"],
                         "intended_fault": fault, "status": None, "latency_seconds": None,
                         "receipt_confirmed": False}
                append(folder, "request-intent.ndjson", event)
                request_start = time.monotonic()
                try:
                    response = client.post(url+"/work", headers={"Authorization": "Bearer "+token},
                        json={"run_id": run_id, "sequence": sequence, "fault": fault})
                    received_at = datetime.now(timezone.utc)
                    event.update(status=response.status_code, latency_seconds=time.monotonic()-request_start,
                                 received_at=received_at.isoformat())
                    if len(response.content) <= 4096:
                        try:
                            receipt = response.json()
                        except ValueError:
                            receipt = {}
                        if valid_receipt(receipt, run_id, sequence, fault, sent_at, received_at):
                            event.update(receipt_confirmed=True, receipt=receipt)
                    append(folder, "requests.ndjson", event)
                    if response.status_code in (401,403,410,429) or (response.status_code != 200 and not (
                        fault == "http_503" and response.status_code == 503 and event["receipt_confirmed"])):
                        raise RuntimeError("Unexpected service response; campaign stopped")
                    if not event["receipt_confirmed"]:
                        raise RuntimeError("Actuation receipt missing; campaign stopped")
                except httpx.HTTPError:
                    event.update(transport_failure=True, received_at=datetime.now(timezone.utc).isoformat())
                    append(folder, "requests.ndjson", event)
                    raise RuntimeError("Transport failed; uncertain outcome recorded, campaign stopped") from None
                # Sequential rate limiting; never catch up with a delayed burst.
                rpm = rpm_at(phase, elapsed)
                wait = max(0, 60/rpm-(time.monotonic()-request_start))
                if wait:
                    time.sleep(min(wait, 10))
        status = "completed"
    finally:
        append(folder, "execution-events.ndjson", {"status": status, "requests": sent,
            "finished_at": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": time.monotonic()-start})
        session.close()
        print("Campaign", status, "requests", sent, "— delete the dedicated lab service after evidence collection.", flush=True)


def collect(folder):
    """Read real Monitoring telemetry with no BQ writes or production target changes."""
    from app.data.processor import process_samples
    from app.services.gcp_monitoring import CloudMonitoringService
    plan = read_plan(folder)
    execution = json.loads((folder/"execution.json").read_text())
    events = [json.loads(line) for line in (folder/"execution-events.ndjson").read_text().splitlines()]
    end = datetime.fromisoformat(events[-1]["finished_at"]).replace(second=0, microsecond=0)+timedelta(minutes=1)
    start = datetime.fromisoformat(execution["started_at"]).replace(second=0, microsecond=0)
    now = datetime.now(timezone.utc)
    if now < end+timedelta(minutes=15):
        raise ValueError("Wait fifteen minutes after the final complete minute for metric/log ingestion")
    if not start < end <= start+timedelta(minutes=plan["duration_minutes"]+2):
        raise ValueError("Invalid campaign collection interval")
    samples = CloudMonitoringService().collect(PROJECT, REGION, SERVICE, start, end)
    records = process_samples(samples, PROJECT, REGION, SERVICE, start, end, now)
    payload = "".join(row.model_dump_json()+"\n" for row in records).encode()
    # Refuse to replace the first captured evidence snapshot.
    with (folder/"observations.ndjson").open("xb") as stream:
        stream.write(payload)
    save(folder, "observations-source.json", {"source": "gcp-monitoring", "captured_at": now.isoformat(),
         "start": start.isoformat(), "end": end.isoformat(), "rows": len(records),
         "sha256": hashlib.sha256(payload).hexdigest(), "plan_sha256": digest(plan),
         "requests_sha256": hashlib.sha256((folder/"requests.ndjson").read_bytes()).hexdigest()})
    print("Actual measured service-minutes:", len(records), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "run", "collect", "evaluate"])
    parser.add_argument("directory", nargs="?", type=Path)
    parser.add_argument("--approved-plan-sha")
    parser.add_argument("--image-digest")
    parser.add_argument("--run-id")
    parser.add_argument("--minutes", type=int, choices=[30,120], default=30)
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare(args.minutes)
        return
    if args.directory is None:
        parser.error("A prepared campaign directory is required")
    folder = args.directory.resolve()
    if not folder.is_relative_to(ROOT/"data/validation_campaigns"):
        parser.error("Use the project's validation_campaigns directory")
    if args.stage == "run":
        deployment = json.loads((folder/"deployment.json").read_text()) if (folder/"deployment.json").exists() else {}
        run(folder, args.approved_plan_sha, args.image_digest or deployment.get("image_digest"),
            args.run_id or deployment.get("run_id"))
    elif args.stage == "collect":
        collect(folder)
    else:
        from app.validation.evaluate import evaluate
        save(folder, "evaluation.json", evaluate(folder))
        print("Saved evaluation.json; no model or operational gate changed.")


if __name__ == "__main__":
    main()
