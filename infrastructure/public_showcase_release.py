"""Explicit stages for the user-approved public read-only Cloud Run release.

Uses ADC without printing tokens. Only the dashboard receives public invocation.
Run from the repository root: python infrastructure/public_showcase_release.py STAGE [RELEASE_DIR]
"""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import time

import google.auth
from google.auth.transport.requests import AuthorizedSession, Request
import requests

PROJECT = "astute-sign-506809-j8"
REGION = "asia-south1"
RUN = f"https://run.googleapis.com/v2/projects/{PROJECT}/locations/{REGION}"
BUILD = f"https://cloudbuild.googleapis.com/v1/projects/{PROJECT}/locations/{REGION}/builds"
IMAGE = f"{REGION}-docker.pkg.dev/{PROJECT}/autocloud/autocloud-dashboard"
ROOT = Path(__file__).resolve().parents[1]
HANDOFF = "598af1c6370583c993a4b381d7d96902c8832ae106b4b9b111a202055d1dce2e"


def save(directory, name, data):
    (directory / name).write_text(json.dumps(data, indent=2), encoding="utf-8")


def read(directory, name):
    return json.loads((directory / name).read_text(encoding="utf-8"))


def checked(response):
    if not response.ok:
        raise RuntimeError(f"Cloud request failed: HTTP {response.status_code}")
    return response.json()


def wait_operation(session, operation):
    while not operation.get("done"):
        print("Waiting for Cloud Run operation", flush=True)
        time.sleep(10)
        operation = checked(session.get("https://run.googleapis.com/v2/" + operation["name"], timeout=45))
    if operation.get("error"):
        raise RuntimeError("Cloud Run operation failed; inspect the cloud operation privately.")


def main():
    stage = sys.argv[1]
    assert hashlib.sha256((ROOT / "ANTIGRAVITY_HANDOFF.md").read_bytes()).hexdigest() == HANDOFF
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    session = AuthorizedSession(creds)
    if stage == "prepare":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        directory = ROOT / "data" / "releases" / (stamp + "-public")
        directory.mkdir(parents=True, exist_ok=False)
        old = checked(session.get(BUILD + "/65c4c64f-f186-4434-bb8e-04979ea436d2", timeout=45))
        files = read(ROOT / "data/releases/20261116T140549Z", "build-input.json")["files"]
        files = sorted(set(files + [str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "app").rglob("*.py")]))
        if (ROOT / "config/measured-validation.json").exists():
            files = sorted(set(files + ["config/measured-validation.json"]))
        archive = directory / "source.tgz"
        with tarfile.open(archive, "w:gz") as tar:
            for file in files:
                assert not file.endswith((".pkl", ".joblib"))
                tar.add(ROOT / file, arcname=file, recursive=False)
        for name in ("autocloud-api", "autocloud-dashboard"):
            service = checked(session.get(RUN + "/services/" + name, timeout=45))
            save(directory, name + "-before.json", service)
            policy = checked(session.get(RUN + "/services/" + name + ":getIamPolicy", timeout=45))
            save(directory, name + "-iam-before.json", policy)
            if name == "autocloud-api":
                assert not any("allUsers" in b.get("members", []) for b in policy.get("bindings", []))
        obj = f"source/{stamp}-public-source.tgz"
        bucket = old["source"]["storageSource"]["bucket"]
        with archive.open("rb") as data:
            checked(session.post(f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o",
                                 params={"uploadType": "media", "name": obj, "ifGenerationMatch": "0"},
                                 headers={"Content-Type": "application/gzip"}, data=data, timeout=120))
        tag = IMAGE + ":" + stamp.lower() + "-public"
        steps = [{"name": s["name"], "args": [a.replace(old["images"][0], tag) for a in s["args"]]}
                 for s in old["steps"]]
        build = {"source": {"storageSource": {"bucket": bucket, "object": obj}},
                 "steps": steps, "images": [tag], "timeout": "1200s",
                 "options": {"logging": "CLOUD_LOGGING_ONLY"}, "serviceAccount": old["serviceAccount"]}
        result = checked(session.post(BUILD, json=build, timeout=60))
        build_id = result["metadata"]["build"]["id"]
        save(directory, "release.json", {"status": "building", "build_id": build_id,
             "source_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "tag": tag,
             "public_mode": "read-only", "handoff_sha256": HANDOFF})
        print(json.dumps({"release_dir": str(directory), "build_id": build_id}), flush=True)
        return
    directory = Path(sys.argv[2]).resolve()
    assert directory.is_relative_to(ROOT / "data/releases")
    release = read(directory, "release.json")
    if stage == "rollback":
        # Withdraw public access before restoring the former private application.
        url = RUN + "/services/autocloud-dashboard"
        current = checked(session.get(url + ":getIamPolicy", timeout=45))
        original = read(directory, "autocloud-dashboard-iam-before.json")
        original["etag"] = current["etag"]
        checked(session.post(url + ":setIamPolicy", json={"policy": original}, timeout=45))
        for name in ("autocloud-api", "autocloud-dashboard"):
            before = read(directory, name + "-before.json")
            revision = before["latestReadyRevision"].split("/")[-1]
            if (directory / "rollback-plan.json").exists():
                revision = read(directory, "rollback-plan.json")["api" if name == "autocloud-api" else "dashboard"]
            current = checked(session.get(RUN + "/services/" + name, timeout=45))
            body = {"name": current["name"], "etag": current["etag"],
                    "traffic": [{"type": "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION", "revision": revision, "percent": 100}]}
            wait_operation(session, checked(session.patch(RUN + "/services/" + name,
                            params={"updateMask": "traffic"}, json=body, timeout=60)))
        release["status"] = "rolled_back"
        save(directory, "release.json", release)
        print("Restored previous access policy and verified revisions.", flush=True)
        return
    if stage == "build-status":
        build = checked(session.get(BUILD + "/" + release["build_id"], timeout=45))
        print("Build:", build["status"], flush=True)
        if build["status"] == "SUCCESS":
            digest = build["results"]["images"][0]["digest"]
            release.update(status="built", image=IMAGE + "@" + digest)
            save(directory, "release.json", release)
            save(directory, "build-result.json", {"id": build["id"], "status": build["status"], "image": release["image"]})
        return
    if stage in ("deploy-api", "deploy-dashboard"):
        name = "autocloud-api" if stage == "deploy-api" else "autocloud-dashboard"
        before = checked(session.get(RUN + "/services/" + name, timeout=45))
        containers = copy.deepcopy(before["template"]["containers"])
        containers[0]["image"] = release["image"]
        updates = {"DASHBOARD_PUBLIC_SHOWCASE": "true", "DASHBOARD_USER_AUTH_REQUIRED": "false",
                   "DASHBOARD_ALLOW_DEV_LOGIN": "false", "DASHBOARD_GEMINI_ENABLED": "true",
                   "DASHBOARD_ALLOWED_SERVICES": "autocloud-api",
                   "DASHBOARD_GEMINI_TESTING_UNLIMITED": next((e.get("value", "false") for e in containers[0].get("env", []) if e["name"] == "DASHBOARD_GEMINI_TESTING_UNLIMITED"), "false")}
        if name == "autocloud-api":
            updates["DASHBOARD_FORECAST_RUN"] = "/app/models/runs/20261116T051914Z_48d41482"
            updates["DASHBOARD_VALIDATION_LEDGER_ENABLED"] = next((e.get("value", "false") for e in containers[0].get("env", []) if e["name"] == "DASHBOARD_VALIDATION_LEDGER_ENABLED"), "true")
        if "--preserve-env" in sys.argv:
            updates = {}
        env = [e for e in containers[0].get("env", []) if e["name"] not in updates]
        containers[0]["env"] = env + [{"name": k, "value": v} for k, v in updates.items()]
        body = {"name": before["name"], "etag": before["etag"], "template": {"containers": containers}}
        operation = checked(session.patch(RUN + "/services/" + name,
                                          params={"updateMask": "template.containers"}, json=body, timeout=60))
        wait_operation(session, operation)
        after = checked(session.get(RUN + "/services/" + name, timeout=45))
        assert after["terminalCondition"]["state"] == "CONDITION_SUCCEEDED"
        assert after["scaling"] == before["scaling"]
        assert after["template"]["serviceAccount"] == before["template"]["serviceAccount"]
        save(directory, name + "-deployed.json", after)
        print(json.dumps({"service": name, "revision": after["latestReadyRevision"], "ready": True}), flush=True)
        return
    if stage == "verify-api":
        creds.refresh(Request())
        token = creds.id_token
        url = "https://autocloud-api-l25hfnltba-el.a.run.app"
        result = {}
        for path in ("/", "/health/ready", "/api/overview?source=bigquery&hours=24", "/api/costs", "/api/reviews", "/api/auth/session", "/api/resources"):
            r = requests.get(url + path, headers={"Authorization": "Bearer " + token}, timeout=90)
            result[path] = r.status_code
            assert r.status_code == (200 if path in ("/", "/health/ready", "/api/overview?source=bigquery&hours=24") else 403)
            if path == "/":
                assert r.json()["capabilities"]["public_read_only"]
                assert not r.json()["capabilities"]["autonomous_execution"]
            if path.startswith("/api/overview"):
                payload = r.json()
                save(directory, "live-overview.json", payload)
                result["models"] = {k: payload["models"].get(k) for k in ("status", "forecast_status", "forecast_reason", "anomaly_status", "anomaly_reason")}
                assert payload["capabilities"]["public_read_only"]
                assert payload["query"]["status"] == "succeeded"
        result["anonymous_api"] = requests.get(url + "/", timeout=45).status_code
        assert result["anonymous_api"] == 403
        save(directory, "verification-api.json", result)
        print(json.dumps(result), flush=True)
        return
    if stage == "publish-dashboard":
        assert (directory / "verification-api.json").is_file()
        assert (directory / "verification-dashboard-private.json").is_file()
        url = RUN + "/services/autocloud-dashboard"
        policy = checked(session.get(url + ":getIamPolicy", timeout=45))
        binding = next((b for b in policy.get("bindings", []) if b["role"] == "roles/run.invoker" and not b.get("condition")), None)
        if binding is None:
            binding = {"role": "roles/run.invoker", "members": []}
            policy.setdefault("bindings", []).append(binding)
        if "allUsers" not in binding["members"]:
            binding["members"].append("allUsers")
        checked(session.post(url + ":setIamPolicy", json={"policy": policy}, timeout=45))
        release["status"] = "published_pending_verification"
        save(directory, "release.json", release)
        print("Dashboard public invocation enabled; API IAM unchanged.", flush=True)
        return
    raise ValueError("Unknown stage")


if __name__ == "__main__":
    main()
