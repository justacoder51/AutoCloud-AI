"""Prospective recording cannot backfill expired predictions or overwrite an origin."""
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock
import json

from google.api_core.exceptions import PreconditionFailed

from app.config import Settings
from app.services.forecast_ledger import ForecastLedger


def test_only_future_forecasts_are_archived_once_without_overwrite(tmp_path):
    (tmp_path/"forecast_manifest.json").write_text('{}')
    config=Settings(gcp_project_id="test-project",dashboard_review_bucket="test-bucket",
        dashboard_forecast_run=str(tmp_path),dashboard_validation_ledger_enabled=True)
    now=datetime.now(timezone.utc)
    def forecast(minutes):
        return {"origin":now.isoformat(),"timestamp":(now+timedelta(minutes=minutes)).isoformat(),
                "prediction":.2,"persistence_prediction":.1,"target":"cpu_utilization","horizon_minutes":5}
    overview={"models":{"forecasts":[forecast(-1),forecast(5)]}}
    storage=Mock(); blob=storage.bucket.return_value.blob.return_value
    ledger=ForecastLedger(client=storage)
    assert ledger.record(config,overview)["status"]=="archived"
    assert ledger.record(config,overview)["status"]=="archived"
    assert blob.upload_from_string.call_count==1
    call=blob.upload_from_string.call_args
    assert call.kwargs["if_generation_match"]==0
    assert len(json.loads(call.args[0])["forecasts"])==1
    blob.upload_from_string.side_effect=PreconditionFailed("exists")
    assert ForecastLedger(client=storage).record(config,overview)["status"]=="already_archived"


def test_storage_failures_do_not_break_metrics_and_disabled_mode_never_writes(tmp_path):
    storage=Mock();config=Settings()
    assert ForecastLedger(client=storage).record(config,{})["status"]=="disabled"
    storage.bucket.assert_not_called()


def test_gcs_creation_time_prevents_backdated_forecast_accuracy_claim():
    import pandas as pd
    from infrastructure.score_prospective_ledger import eligible_predictions
    actuals=pd.DataFrame({"cpu_utilization":[.3]},index=pd.to_datetime(["2026-11-16T17:05:00Z"]))
    record={"manifest_sha256":"fixed","origin":"2026-11-16T17:00:00Z","recorded_at":"2026-11-16T17:01:00Z",
        "forecasts":[{"target":"cpu_utilization","horizon_minutes":5,"timestamp":"2026-11-16T17:05:00Z","prediction":.2,"persistence_prediction":.1}]}
    assert len(eligible_predictions(record,"2026-11-16T17:02:00Z",actuals,"fixed"))==1
    assert eligible_predictions(record,"2026-11-16T17:06:00Z",actuals,"fixed")==[]
    assert eligible_predictions(record,None,actuals,"fixed")==[]
    assert eligible_predictions(record,"2026-11-16T17:02:00Z",actuals,"different")==[]
