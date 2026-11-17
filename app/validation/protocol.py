"""Frozen, bounded pilot design. Creating a plan does not run cloud traffic."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random

PROJECT = "astute-sign-506809-j8"
REGION = "asia-south1"
SERVICE = "autocloud-validation-lab"
RUN = Path("models/runs/20261116T051914Z_48d41482")
FAULTS = ("cpu_stress", "memory_growth", "latency", "http_503")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def make_plan(duration_minutes=120):
    if duration_minutes not in (30, 120):
        raise ValueError("Only the reviewed 30- or 120-minute designs are supported")
    phases = [dict(name="warmup_steady", minutes=20, rpm=12),
              dict(name="idle", minutes=10, rpm=0),
              dict(name="low", minutes=10, rpm=6),
              dict(name="ramp", minutes=10, rpm=6),
              dict(name="bursty", minutes=10, rpm=6)]
    order = list(FAULTS)*3
    random.Random(20261116).shuffle(order)
    for i, fault in enumerate(order):
        phases += [dict(name=f"episode_{i:02d}", minutes=2, rpm=12, fault=fault),
                   dict(name=f"recovery_{i:02d}", minutes=3, rpm=12)]
    if duration_minutes == 30:
        phases = [dict(name="warmup_steady", minutes=16, rpm=12),
                  dict(name="idle", minutes=1, rpm=0), dict(name="low", minutes=1, rpm=6),
                  dict(name="ramp", minutes=1, rpm=6), dict(name="bursty", minutes=1, rpm=24)]
        order = list(FAULTS)
        random.Random(20261117).shuffle(order)
        for i, fault in enumerate(order):
            phases += [dict(name=f"episode_{i:02d}", minutes=1, rpm=12, fault=fault),
                       dict(name=f"recovery_{i:02d}", minutes=1, rpm=12)]
        phases.append(dict(name="final_steady", minutes=2, rpm=12))
    offset = 0
    for phase in phases:
        phase["start_minute"] = offset
        offset += phase["minutes"]
    return {
        "schema_version": 1, "project": PROJECT, "region": REGION, "service": SERVICE,
        "registered_at": datetime.now(timezone.utc).isoformat(), "duration_minutes": offset,
        "maximum_requests": 450 if duration_minutes == 30 else 1800, "maximum_rpm": 24, "maximum_concurrency": 1,
        "latency_slo_seconds": 1.0, "phases": phases,
        "model_run": str(RUN),
        "model_files_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted(RUN.glob("*.json"))},
        "history_sha256": hashlib.sha256((RUN/"history.ndjson").read_bytes()).hexdigest(),
        "validation_code_sha256": {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in (
            "app/validation/protocol.py", "app/validation/lab_app.py", "app/validation/evaluate.py",
            "infrastructure/validation_campaign.py", "infrastructure/validation_lab_cloud.py",
            "infrastructure/validation_supervisor.py", "infrastructure/validation-lab.Dockerfile")},
        "deployment": {"cpu": "1", "memory": "512Mi", "min_instances": 0,
                       "max_instances": 1, "concurrency": 1, "timeout_seconds": 10,
                       "private": True, "service_account_roles": [], "max_age_minutes": duration_minutes+15},
        "fault_bounds": {"cpu_seconds_per_request": 3, "cpu_wall_seconds": 4,
                         "memory_bytes": 64*1024*1024, "memory_ttl_seconds": 120,
                         "latency_seconds": 2},
        "evaluation": {
            "fit_models": False, "tune_on_campaign": False, "execution_allowed": False,
            "scope": "Cross-service controlled pilot, outside the model's trained service domain; no operational approval.",
            "labels": "Actuator receipts establish exposure only. External HTTP 5xx or measured request latency >1s establish availability/latency impact. Missing receipts, transport failures and unobserved intervals remain unknown. CPU/memory exposure alone is not an operational fault.",
            "metrics": "All nine frozen forecasts versus persistence; complete sixteen-minute measured origins and actual future targets. Raw anomaly recall by repeated episode, false alarms on measured control requests, latency to first signal, and missingness. Report each workload/fault separately. No timestamp shifts or fake zero targets.",
            "promotion": "None. Pilot results cannot certify reliability. Multiple days, real workload traces and independently reviewed incident families remain required before a separate operational promotion review.",
        },
    }


def phase_at(plan, elapsed):
    for phase in plan["phases"]:
        if phase["start_minute"]*60 <= elapsed < (phase["start_minute"]+phase["minutes"])*60:
            return phase
    return None


def rpm_at(phase, elapsed):
    minute = int(elapsed//60)-phase["start_minute"]
    if phase["name"] == "ramp":
        return min(24, 6+2*minute)
    if phase["name"] == "bursty" and phase["minutes"] == 1:
        return 24 if int(elapsed % 60) < 30 else 6
    if phase["name"] == "bursty":
        return 24 if minute % 2 else 6
    return phase["rpm"]


def verify_plan(plan):
    """Refuse edited resource caps, schedule or frozen models at execution time."""
    expected = make_plan(plan["duration_minutes"])
    expected["registered_at"] = plan["registered_at"]
    if expected != plan:
        raise ValueError("Plan differs from the reviewed design or frozen model files")
