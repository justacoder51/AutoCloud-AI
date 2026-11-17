"""Bounded operator-controlled minimum-instance trial with durable checkpoints.

Not connected to recommendation approvals, dashboard buttons or an AI agent.
"""

import json
import os
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path


def fingerprint(resource):
    # Hash sensitive configuration without writing its plaintext into the journal.
    fields = {key: resource.get(key) for key in (
        "name", "uid", "template", "traffic", "ingress", "invokerIamDisabled",
        "binaryAuthorization", "defaultUriDisabled", "iapEnabled", "labels", "annotations",
    )}
    scaling = dict(resource.get("scaling", {}))
    scaling.pop("minInstanceCount", None)
    fields["scaling"] = scaling
    return sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def check_ready(resource):
    if resource.get("reconciling") or resource.get("terminalCondition", {}).get("state") != "CONDITION_SUCCEEDED":
        raise ValueError("Service must be reconciled and ready")
    scaling = resource.get("scaling", {})
    revision = resource.get("template", {}).get("scaling", {})
    if scaling.get("scalingMode", "AUTOMATIC") not in ("AUTOMATIC", "SCALING_MODE_UNSPECIFIED"):
        raise ValueError("Manual scaling is unsupported")
    if revision.get("minInstanceCount", 0) != 0:
        raise ValueError("Revision minimum must be zero")
    if not (scaling.get("maxInstanceCount") in (1, 2)
            or revision.get("maxInstanceCount") in (1, 2)):
        raise ValueError("An existing service or revision maximum of one or two is required")
    if scaling.get("maxInstanceCount", 0) not in (0, 1, 2):
        raise ValueError("Service maximum exceeds the trial limit")


class ScalingTrial:
    """One journal per service; unfinished trials block additional writes.

    Uncertain requests are never retried automatically. Reconcile or recover using
    the recorded checkpoint; stale etags and configuration drift fail closed.
    """

    def __init__(self, adapter, data_root: Path):
        self.adapter = adapter
        self.root = data_root
        self.directory = data_root / "scaling_trials" / sha256(adapter.name.encode()).hexdigest()

    def idle_experiment(self):
        marker = self.root / "training_runs/active.json"
        if marker.exists():
            run = json.loads(marker.read_text(encoding="utf-8"))["run_id"]
            if not isinstance(run, str) or len(run) != 32 or any(c not in "0123456789abcdef" for c in run):
                raise ValueError("Invalid active experiment marker")
            status = json.loads((marker.parent / run / "status.json").read_text(encoding="utf-8"))
            if status.get("stage") not in {"completed", "training_not_ready", "training_paused", "stopped", "failed"}:
                raise ValueError("Existing collection experiment is active; defer scaling trial")

    def prepare(self):
        resource = self.adapter.read()
        check_ready(resource)
        if resource.get("scaling", {}).get("minInstanceCount", 0) != 0:
            raise ValueError("Trial requires existing service minimum zero")
        plan = {"target": self.adapter.name, "before": 0, "during": 1,
                "etag": resource["etag"], "configuration_hash": fingerprint(resource),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "purpose": "operator minimum-instance and rollback test; not an optimisation"}
        plan["approval_digest"] = sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        return plan

    def checkpoint(self, entry):
        path = self.directory / "events.jsonl"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), **entry}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def apply(self, plan, approved_digest):
        expected = dict(plan)
        digest = expected.pop("approval_digest", None)
        if digest != approved_digest or sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest() != digest:
            raise ValueError("Explicit approval must match the exact plan")
        if plan["target"] != self.adapter.name or plan["before"] != 0 or plan["during"] != 1:
            raise ValueError("Unsupported trial plan")
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(plan["created_at"])).total_seconds()
        if not 0 <= age <= 300:
            raise ValueError("Plan expired; prepare and review again")
        self.idle_experiment()
        current = self.adapter.read()
        check_ready(current)
        if current["etag"] != plan["etag"] or fingerprint(current) != plan["configuration_hash"]:
            raise ValueError("Configuration changed after planning")
        self.directory.mkdir(parents=True, exist_ok=True)
        # Exclusive marker persists until verified rollback; no automatic retries.
        with (self.directory / "active.json").open("x", encoding="utf-8") as stream:
            json.dump(plan, stream)
            stream.flush()
            os.fsync(stream.fileno())
        self.checkpoint({"stage": "apply_submitting", "plan": plan})
        operation = self.adapter.minimum(current, 1, validate_only=False)
        self.checkpoint({"stage": "apply_submitted", "operation": operation.get("name"), "done": operation.get("done", False)})
        return operation

    def rollback(self):
        path = self.directory / "active.json"
        plan = json.loads(path.read_text(encoding="utf-8"))
        current = self.adapter.read()
        check_ready(current)
        if plan["target"] != self.adapter.name or fingerprint(current) != plan["configuration_hash"]:
            raise ValueError("Configuration drift; manual reconciliation required")
        value = current.get("scaling", {}).get("minInstanceCount", 0)
        if value == 0:
            self.checkpoint({"stage": "rollback_verified", "etag": current["etag"]})
            path.unlink()
            return {"done": True, "restored": True}
        if value != 1:
            raise ValueError("Unexpected minimum; manual reconciliation required")
        self.checkpoint({"stage": "rollback_submitting", "etag": current["etag"]})
        operation = self.adapter.minimum(current, 0, validate_only=False)
        self.checkpoint({"stage": "rollback_submitted", "operation": operation.get("name"), "done": operation.get("done", False)})
        return operation  # Invoke rollback again after reconciliation to verify.
