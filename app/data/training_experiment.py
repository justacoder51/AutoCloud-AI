"""Bounded background collection experiment, followed by readiness-gated training."""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.data.schema import MetricRecord
from app.data.storage import save_records
from app.data.traffic import TrafficPlan, adc_identity_token, run_traffic, send_request_httpx

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "data" / "training_runs"
PROJECT = "astute-sign-506809-j8"
REGION = "asia-south1"
SERVICE = "autocloud-api"
RATES = (6, 10, 14, 6, 10, 14, 10)
PHASE_SECONDS = 1800
TERMINAL = {"completed", "training_not_ready", "stopped", "failed"}


def planned_phases() -> tuple[TrafficPlan, ...]:
    """Seven existing-cap-compliant blocks; 210 minutes and 2,100 requests maximum."""
    return tuple(TrafficPlan(PHASE_SECONDS, rate, rate * 30) for rate in RATES)


def active_directory() -> Path | None:
    """Resolve only a valid locally generated run identifier."""
    marker = RUNS / "active.json"
    if not marker.exists():
        return None
    run_id = json.loads(marker.read_text(encoding="utf-8"))["run_id"]
    if not isinstance(run_id, str) or re.fullmatch(r"[a-f0-9]{32}", run_id) is None:
        raise ValueError("Invalid active run identifier")
    return RUNS / run_id


def read_status(directory: Path | None) -> dict:
    if directory is None:
        return {"stage": "no_run"}
    return json.loads((directory / "status.json").read_text(encoding="utf-8"))


def write_status(directory: Path, status: dict, **changes) -> None:
    """Atomic progress writes contain no credentials, headers or provider bodies."""
    status.update(changes, updated_at=datetime.now(timezone.utc).isoformat())
    temporary = directory / "status.tmp"
    for attempt in range(10):
        try:
            temporary.write_text(json.dumps(status, indent=2, allow_nan=False), encoding="utf-8")
            temporary.replace(directory / "status.json")
            return
        except PermissionError:
            # Brief Windows scanner/read locks must not abort an hours-long run.
            if attempt == 9:
                raise
            time.sleep(.2)


def select_cohort(records: list[MetricRecord], start: datetime, end: datetime) -> list[MetricRecord]:
    """Exclude earlier sparse history and partially exposed boundary minutes."""
    lower = start.replace(second=0, microsecond=0) + timedelta(minutes=2)
    upper = end.replace(second=0, microsecond=0)
    return [row for row in records if lower <= row.timestamp <= upper]


def run_command(arguments: list[str], timeout: int) -> dict:
    """Run only fixed project modules; do not expose stderr or raw command errors."""
    result = subprocess.run(
        [sys.executable, "-m", *arguments], cwd=ROOT, capture_output=True,
        text=True, timeout=timeout,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    payload = json.loads(lines[-1]) if lines else {}
    return {"exit_code": result.returncode, "result": payload}


def execute() -> int:
    RUNS.mkdir(parents=True, exist_ok=True)
    previous = active_directory()
    if previous is not None:
        if read_status(previous)["stage"] not in TERMINAL:
            raise ValueError("A training experiment is already active; inspect or stop it first")
        (RUNS / "active.json").unlink()
    run_id = uuid4().hex
    directory = RUNS / run_id
    directory.mkdir()
    # Exclusive claim prevents duplicate background jobs.
    with (RUNS / "active.json").open("x", encoding="utf-8") as marker:
        json.dump({"run_id": run_id}, marker)
    started = datetime.now(timezone.utc)
    status = {
        "run_id": run_id, "pid": os.getpid(), "stage": "starting",
        "source": "controlled-real-http-traffic", "started_at": started.isoformat(),
        "expected_finish": (started + timedelta(minutes=215)).isoformat(),
        "duration_minutes": 210, "requests_upper_bound": 2100,
        "attempted_requests": 0, "successful_requests": 0, "completed_phases": 0,
        "trained": False, "deployment_allowed": False,
        "note": "Normal-workload collection experiment; not anomaly ground truth or production evaluation.",
    }
    write_status(directory, status)
    totals = {"attempted_requests": 0, "successful_requests": 0}

    def stopped():
        if (directory / "STOP").exists():
            raise KeyboardInterrupt

    def wait(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            stopped()
            time.sleep(min(5, max(0, deadline - time.monotonic())))

    try:
        for index, plan in enumerate(planned_phases(), start=1):
            stopped()
            write_status(directory, status, stage="sending_traffic", phase=index,
                         requests_per_minute=plan.requests_per_minute)
            phase_start = time.monotonic()
            last_progress = phase_start
            counters = {"attempted_requests": 0, "successful_requests": 0}

            def transport(token, experiment_id):
                nonlocal last_progress
                stopped()
                counters["attempted_requests"] += 1
                code = send_request_httpx(token, experiment_id)
                counters["successful_requests"] += int(200 <= code < 300)
                if time.monotonic() - last_progress >= 60 or counters["attempted_requests"] == 1:
                    write_status(directory, status, **{
                        key: totals[key] + counters[key] for key in totals
                    })
                    last_progress = time.monotonic()
                return code

            result = run_traffic(
                plan, token_provider=adc_identity_token, transport=transport, sleep=wait,
            )
            (directory / f"phase_{index}.json").write_text(
                json.dumps(result, indent=2, allow_nan=False), encoding="utf-8",
            )
            for key in totals:
                totals[key] += result[key]
            write_status(directory, status, **totals, completed_phases=index)
            if result["status"] != "completed":
                write_status(directory, status, stage=(
                    "stopped" if result["status"] == "interrupted" else "failed"
                ), traffic_status=result["status"])
                return 1
            wait(max(0, PHASE_SECONDS - (time.monotonic() - phase_start)))
        ended = datetime.now(timezone.utc)
        write_status(directory, status, stage="waiting_for_monitoring", traffic_ended_at=ended.isoformat())
        wait(300)
        stopped()
        write_status(directory, status, stage="collecting")
        snapshot = directory / "collected.ndjson"
        collection = run_command([
            "app.data.collector", f"--project={PROJECT}", f"--region={REGION}",
            f"--service={SERVICE}", "--minutes=240", f"--output={snapshot}", "--write-bigquery",
        ], timeout=180)
        write_status(directory, status, collection=collection)
        if collection["exit_code"] != 0:
            raise RuntimeError("Collection failed")
        records = [MetricRecord.model_validate_json(line) for line in snapshot.read_text(encoding="utf-8").splitlines() if line.strip()]
        cohort = select_cohort(records, started, ended)
        baseline = directory / "baseline.ndjson"
        save_records(cohort, baseline)
        write_status(directory, status, stage="assessing_and_training", cohort_records=len(cohort))
        stopped()
        training = run_command([
            "app.models.train", f"--input={baseline}", "--profile=exploratory", "--train",
        ], timeout=180)
        trained = training["exit_code"] == 0 and training["result"].get("trained") is True
        write_status(directory, status, stage="completed" if trained else "training_not_ready",
                     trained=trained, training=training)
        return 0 if trained else 2
    except KeyboardInterrupt:
        write_status(directory, status, stage="stopped")
        return 1
    except Exception as error:
        write_status(directory, status, stage="failed", error_type=type(error).__name__)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    try:
        if args.execute:
            return execute()
        if args.status or args.stop:
            directory = active_directory()
            current = read_status(directory)
            if args.stop and directory is not None and current["stage"] not in TERMINAL:
                (directory / "STOP").touch()
                current["stop_requested"] = True
            print(json.dumps(current, indent=2))
            return 0
        print(json.dumps({
            "mode": "preview", "duration_minutes": 210, "monitoring_wait_minutes": 5,
            "requests_upper_bound": sum(plan.request_budget for plan in planned_phases()),
            "rates_per_minute": list(RATES), "phase_minutes": 30,
            "automatic_training": "Only if real cohort passes exploratory readiness",
            "deployment_allowed": False,
        }, indent=2))
        return 0
    except Exception as error:
        print(json.dumps({"stage": "failed", "error_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
