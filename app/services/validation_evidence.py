"""Immutable measured validation evidence, bound to the evaluated model manifests."""
import hashlib
import json
from pathlib import Path

SUMMARY_SHA256 = "e6343427e600067be71ea492427fae14bd52d0ddf8868e8e6fa5f2900955fdea"


def load_measured_validation(run, *, project, region, service):
    if not run:
        return None
    try:
        path = Path(__file__).resolve().parents[2] / "config/measured-validation.json"
        if path.stat().st_size > 250_000:
            return None
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != SUMMARY_SHA256:
            return None
        data = json.loads(raw)
        if (data["project"],data["region"],data["service"]) != (project,region,service):
            return None
        for name in ("forecast_manifest", "anomaly_manifest"):
            contents=(Path(run)/(name+".json")).read_bytes()
            if hashlib.sha256(contents).hexdigest()!=data[name+"_sha256"]:
                return None
            manifest=json.loads(contents)
            if name=="forecast_manifest":
                for key, model in manifest["models"].items():
                    if "/" in key or "\\" in key:
                        return None
                    if hashlib.sha256((Path(run)/(key+".json")).read_bytes()).hexdigest()!=model["sha256"]:
                        return None
            elif hashlib.sha256((Path(run)/"anomaly_detector.json").read_bytes()).hexdigest()!=manifest["model_sha256"]:
                return None
        return data
    except (OSError,ValueError,KeyError,TypeError):
        return None
