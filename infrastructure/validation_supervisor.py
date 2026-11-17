"""Run the approved finite lab, delete it promptly, then collect delayed telemetry."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from infrastructure.validation_campaign import ROOT, read_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--approved-plan-sha", required=True)
    args = parser.parse_args()
    folder = args.directory.resolve()
    if not folder.is_relative_to(ROOT/"data/validation_campaigns"):
        raise ValueError("Invalid campaign directory")
    plan = read_plan(folder, args.approved_plan_sha)
    if plan["duration_minutes"] != 30:
        raise ValueError("This execution is authorised for at most thirty minutes")
    if (folder/"supervisor.json").exists():
        raise ValueError("Supervisor already started; inspect saved state")
    state = {"pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat(),
             "plan_sha256": args.approved_plan_sha, "traffic_duration_limit_minutes": 30}
    def update(stage, **extra):
        state.update(stage=stage, updated_at=datetime.now(timezone.utc).isoformat(), **extra)
        temporary = folder/"supervisor-next.json"
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temporary.replace(folder/"supervisor.json")
        print(datetime.now(timezone.utc).isoformat(), stage, flush=True)
    def command(module, stage, mutating=False, timeout=700):
        cmd = [sys.executable, "-B", "-u", "-m", module, stage, str(folder)]
        if mutating:
            cmd += ["--execute", "--approved-plan-sha", args.approved_plan_sha]
        subprocess.run(cmd, cwd=ROOT, check=True, timeout=timeout)
    cloud = "infrastructure.validation_lab_cloud"
    campaign = "infrastructure.validation_campaign"
    traffic_error = None
    try:
        update("building")
        command(cloud, "build", True)
        deadline = time.monotonic()+1300
        while time.monotonic() < deadline:
            command(cloud, "build-status")
            build = json.loads((folder/"cloud-build.json").read_text())
            if build["status"] == "SUCCESS":
                break
            if build["status"] not in ("QUEUED", "WORKING", "PENDING"):
                raise RuntimeError("Dedicated lab build failed")
            time.sleep(15)
        else:
            raise RuntimeError("Build deadline exceeded; no service was created")
        try:
            update("deploying")
            command(cloud, "deploy", True)
            update("running_traffic", expected_traffic_finish=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat())
            deployment = json.loads((folder/"deployment.json").read_text())
            subprocess.run([sys.executable,"-B","-u","-m",campaign,"run",str(folder),
                "--approved-plan-sha",args.approved_plan_sha], cwd=ROOT, check=True, timeout=1830)
        except Exception as error:
            traffic_error = type(error).__name__
            update("traffic_or_deployment_failed", error_type=traffic_error)
        finally:
            # Deletion occurs before waiting for Monitoring ingestion, including failures.
            if (folder/"lab-identity.json").exists():
                update("deleting_lab")
                command(cloud, "cleanup", True)
                update("lab_deleted")
        if not (folder/"execution-events.ndjson").exists():
            raise RuntimeError("No terminal traffic record; completion cannot be established")
        terminal = json.loads((folder/"execution-events.ndjson").read_text().splitlines()[-1])
        available = datetime.fromisoformat(terminal["finished_at"]).replace(second=0,microsecond=0)+timedelta(minutes=16)
        update("waiting_for_measurements_lab_deleted", collection_not_before=available.isoformat())
        while datetime.now(timezone.utc) < available:
            time.sleep(min(15, (available-datetime.now(timezone.utc)).total_seconds()))
            update("waiting_for_measurements_lab_deleted")
        update("collecting_measurements_lab_deleted")
        command(campaign, "collect", timeout=600)
        update("evaluating_lab_deleted")
        command(campaign, "evaluate", timeout=120)
        update("completed" if traffic_error is None else "partial_results_after_failure", traffic_error_type=traffic_error)
    except Exception as error:
        update("failed", error_type=type(error).__name__, cleanup_recorded=(folder/"cleanup.json").exists())
        raise


if __name__ == "__main__":
    main()
