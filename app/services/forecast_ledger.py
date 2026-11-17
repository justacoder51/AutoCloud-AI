"""Opt-in immutable records of already-computed, genuinely future forecasts."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from threading import Lock
from time import monotonic


class ForecastLedger:
    def __init__(self, client=None, clock=monotonic):
        self.client=client
        self.clock=clock
        self.lock=Lock()
        self.cached=None

    def record(self, settings, overview):
        if not settings.dashboard_validation_ledger_enabled:
            return {"status":"disabled"}
        if not settings.dashboard_review_bucket or not settings.dashboard_forecast_run:
            return {"status":"not_configured"}
        forecasts=(overview.get("models") or {}).get("forecasts") or []
        now=datetime.now(timezone.utc)
        try:
            future=[f for f in forecasts if datetime.fromisoformat(f["timestamp"].replace("Z","+00:00"))>now]
            if not future:
                return {"status":"no_eligible_future_forecasts"}
            manifest=hashlib.sha256((Path(settings.dashboard_forecast_run)/"forecast_manifest.json").read_bytes()).hexdigest()
            origin=future[0]["origin"]
            day=datetime.fromisoformat(origin.replace("Z","+00:00")).astimezone(timezone.utc).strftime("%Y%m%d")
        except (OSError,ValueError,TypeError,KeyError):
            return {"status":"unavailable"}
        key=hashlib.sha256((manifest+origin).encode()).hexdigest()
        with self.lock:
            if self.cached and self.cached[0]==key and self.clock()-self.cached[1]<60:
                return self.cached[2]
            from google.api_core.exceptions import PreconditionFailed
            try:
                if self.client is None:
                    from google.cloud import storage
                    self.client=storage.Client(project=settings.gcp_project_id)
                name=f"validation-ledger/{manifest}/{day}/{key}.json"
                blob=self.client.bucket(settings.dashboard_review_bucket).blob(name)
                payload={"schema_version":1,"recorded_at":now.isoformat(),"project":settings.gcp_project_id,
                    "region":settings.gcp_region,"service":"autocloud-api","manifest_sha256":manifest,
                    "origin":origin,"forecasts":[{k:f.get(k) for k in ("target","horizon_minutes","timestamp","prediction","persistence_prediction","model_history_sha256")} for f in future],
                    "purpose":"Prospective validation only; score only targets later than immutable GCS creation time."}
                blob.upload_from_string(json.dumps(payload,allow_nan=False),content_type="application/json",
                                        if_generation_match=0,timeout=10,retry=None)
                result={"status":"archived","future_forecasts":len(future),"object":name}
            except PreconditionFailed:
                result={"status":"already_archived","object":name}
            except Exception:
                result={"status":"unavailable"}
            self.cached=(key,self.clock(),result)
            return result
