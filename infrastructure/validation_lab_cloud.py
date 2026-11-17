"""Explicit approved lab-only build/deploy/cleanup. Does not target production.

Mutating stages require --execute and --approved-plan-sha. No invocation traffic
is generated here. The campaign runner is a separate, explicit command.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time
from uuid import uuid4

from app.validation.protocol import PROJECT, REGION, SERVICE
from infrastructure.validation_campaign import ROOT, authorised_session, checked, read_plan, save

BASE = f"https://run.googleapis.com/v2/projects/{PROJECT}/locations/{REGION}"
BUILDS = f"https://cloudbuild.googleapis.com/v1/projects/{PROJECT}/locations/{REGION}/builds"
IAM = f"https://iam.googleapis.com/v1/projects/{PROJECT}/serviceAccounts"
EMAIL = f"{SERVICE}@{PROJECT}.iam.gserviceaccount.com"


def wait(session, operation):
    limit = time.monotonic()+600
    while not operation.get("done"):
        if time.monotonic() > limit:
            raise RuntimeError("Deployment operation still pending; inspect recorded operation before retrying")
        print("Waiting for dedicated lab operation", flush=True)
        time.sleep(10)
        operation = checked(session.get("https://run.googleapis.com/v2/"+operation["name"], timeout=30))
    if operation.get("error"):
        raise RuntimeError("Lab operation failed; inspect its recorded operation privately")
    return operation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["build", "build-status", "deploy", "cleanup"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--approved-plan-sha")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    folder = args.directory.resolve()
    if not folder.is_relative_to(ROOT/"data/validation_campaigns"):
        parser.error("Use a prepared validation_campaigns directory")
    if args.stage != "build-status" and not (args.execute and args.approved_plan_sha):
        parser.error("Mutating stages require --execute and the explicitly approved plan checksum")
    # Cleanup must remain possible even if working code/models changed after a run.
    if args.stage != "cleanup":
        plan = read_plan(folder, args.approved_plan_sha)
    preparation = json.loads((folder/"preparation.json").read_text())
    if args.stage != "build-status" and preparation["plan_sha256"] != args.approved_plan_sha:
        parser.error("Approved plan checksum differs from the prepared campaign")
    session = authorised_session()
    try:
        if args.stage == "build":
            if (folder/"cloud-build.json").exists():
                raise ValueError("Build already submitted; use build-status")
            archive = (folder/"source.tgz").read_bytes()
            if hashlib.sha256(archive).hexdigest() != preparation["source_sha256"]:
                raise ValueError("Source archive changed")
            bucket = PROJECT+"_cloudbuild"
            obj = f"source/validation-lab-{folder.name}.tgz"
            checked(session.post(f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o",
                params={"uploadType": "media", "name": obj, "ifGenerationMatch": "0"},
                headers={"Content-Type": "application/gzip"}, data=archive, timeout=60))
            build = json.loads((folder/"build.json").read_text())
            if hashlib.sha256((folder/"build.json").read_bytes()).hexdigest() != preparation["build_config_sha256"]:
                raise ValueError("Build configuration changed")
            build["source"] = {"storageSource": {"bucket": bucket, "object": obj}}
            result = checked(session.post(BUILDS, json=build, timeout=60))
            save(folder, "cloud-build.json", {"id": result["metadata"]["build"]["id"], "status": "submitted"})
            print("Submitted dedicated lab image build; use build-status before deploying.", flush=True)
        elif args.stage == "build-status":
            build = json.loads((folder/"cloud-build.json").read_text())
            result = checked(session.get(BUILDS+"/"+build["id"], timeout=30))
            build["status"] = result["status"]
            if result["status"] == "SUCCESS":
                build["digest"] = result["results"]["images"][0]["digest"]
                build["image"] = preparation["image_tag"].split(":")[0]+"@"+build["digest"]
            save(folder, "cloud-build.json", build)
            print(json.dumps(build), flush=True)
        elif args.stage == "deploy":
            build = json.loads((folder/"cloud-build.json").read_text())
            if build.get("status") != "SUCCESS":
                raise ValueError("Verified successful lab image build required")
            if (folder/"lab-operation.json").exists() or (folder/"deployment.json").exists():
                raise ValueError("Deployment already attempted; inspect saved operation before retrying")
            # Refuse to update/reuse any pre-existing service or identity.
            if session.get(BASE+"/services/"+SERVICE, timeout=30).status_code != 404:
                raise ValueError("Lab service already exists or its absence cannot be confirmed")
            if session.get(IAM+"/"+EMAIL, timeout=30).status_code != 404:
                raise ValueError("Lab service account already exists or its absence cannot be confirmed")
            identity = checked(session.post(IAM, json={"accountId": SERVICE,
                "serviceAccount": {"displayName": "Temporary AutoCloud validation lab; no project roles"}}, timeout=30))
            save(folder, "lab-identity.json", {"email": EMAIL, "unique_id": identity["uniqueId"]})
            run_id = uuid4().hex
            expiry = datetime.now(timezone.utc)+timedelta(minutes=plan["deployment"]["max_age_minutes"])
            env = {"AUTOCLOUD_COMPONENT": "validation_lab", "LAB_RUN_ID": run_id,
                   "LAB_PLAN_SHA256": preparation["plan_sha256"], "LAB_EXPIRES_AT": expiry.isoformat()}
            body = {"ingress": "INGRESS_TRAFFIC_ALL", "invokerIamDisabled": False,
                "labels": {"purpose": "temporary-ml-validation"},
                "template": {"serviceAccount": EMAIL, "timeout": "10s", "maxInstanceRequestConcurrency": 1,
                    "scaling": {"minInstanceCount": 0, "maxInstanceCount": 1},
                    "containers": [{"image": build["image"], "ports": [{"containerPort": 8080}],
                        "resources": {"limits": {"cpu": "1", "memory": "512Mi"}, "cpuIdle": True,
                                      "startupCpuBoost": False},
                        "env": [{"name": k, "value": v} for k,v in env.items()]}]}}
            operation = checked(session.post(BASE+"/services", params={"serviceId": SERVICE}, json=body, timeout=60))
            save(folder, "lab-operation.json", operation)
            wait(session, operation)
            from infrastructure.validation_campaign import check_target
            url, service, _ = check_target(session, run_id, build["digest"], plan["duration_minutes"])
            save(folder, "deployment.json", {"run_id": run_id, "image_digest": build["digest"],
                 "service_uid": service["uid"], "uri": url, "expires_at": expiry.isoformat(),
                 "plan_sha256": preparation["plan_sha256"], "status": "private_lab_ready_not_started"})
            print("Private lab ready. Start promptly; expiry minutes:", plan["deployment"]["max_age_minutes"], flush=True)
        else:
            identity = json.loads((folder/"lab-identity.json").read_text())
            current = session.get(BASE+"/services/"+SERVICE, timeout=30)
            if current.status_code != 404:
                service = checked(current)
                env = {e["name"]: e.get("value") for e in service["template"]["containers"][0].get("env", [])}
                if env.get("LAB_PLAN_SHA256") != args.approved_plan_sha:
                    raise ValueError("Refuse to delete a service belonging to a different campaign")
                wait(session, checked(session.delete(BASE+"/services/"+SERVICE, timeout=60)))
            current = session.get(IAM+"/"+EMAIL, timeout=30)
            if current.status_code != 404:
                if checked(current)["uniqueId"] != identity["unique_id"]:
                    raise ValueError("Service account identity changed; deletion refused")
                response = session.delete(IAM+"/"+EMAIL, timeout=30)
                if not response.ok:
                    raise RuntimeError(f"Lab service account deletion failed: HTTP {response.status_code}")
            save(folder, "cleanup.json", {"status": "lab_service_and_identity_deleted",
                 "at": datetime.now(timezone.utc).isoformat(),
                 "note": "Build logs, source archive and Artifact Registry image remain for audit and can incur storage charges."})
            print("Deleted only the dedicated lab service and its recorded role-free service account.", flush=True)
    finally:
        session.close()


if __name__ == "__main__":
    main()
