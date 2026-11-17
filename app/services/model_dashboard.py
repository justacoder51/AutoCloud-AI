"""Model readiness and explicit candidate results; never trains or loads pickle."""

from datetime import datetime
from pathlib import Path

from app.data.schema import MetricRecord


def _safe_forecast_reason(error: Exception) -> str:
    msg = str(error)
    if "fresh" in msg:
        return "Forecasts unavailable: latest monitoring observations are older than 15 minutes."
    if "later than" in msg:
        return "Forecasts unavailable: observations are not newer than the training cutoff."
    if "sixteen" in msg:
        return "Forecasts unavailable: need sixteen consecutive minutes of measured target metrics."
    return "Forecast checks did not pass. Need fresh, out-of-sample observations with sixteen consecutive measured target minutes."


def _safe_anomaly_reason(error: Exception) -> str:
    msg = str(error)
    if "fresh" in msg:
        return "Anomaly scoring unavailable: latest monitoring observations are older than 15 minutes."
    if "later than" in msg:
        return "Anomaly scoring unavailable: observations are not newer than the training cutoff."
    if "No measured" in msg:
        return "Anomaly scoring unavailable: no measured feature rows in the recent window."
    return "Anomaly scoring unavailable: recent measured observations do not satisfy integrity or freshness checks."


def model_panel(records: list[dict], selected_run: str | None, *, project: str | None,
                region: str, service: str, now: datetime) -> dict:
    """Keep observed-window readiness, training evaluation and observation-only inference separate."""
    result = {
        "status": "not_selected", "readiness": None, "evaluation": None,
        "forecast_status": "not_selected", "forecasts": None,
        "anomaly_status": "not_selected", "anomaly_results": None,
        "experimental": True, "observation_only": True,
        "deployment_allowed": False, "execution_allowed": False,
        "readiness_scope": "Selected dashboard observations, not the isolated training experiment cohort",
    }
    try:
        from app.models.dataset import quality_report, regularize_history
        import pandas as pd

        rows = [MetricRecord.model_validate(row) for row in records]
        if any((row.project_id, row.region, row.service_name) != (project, region, service)
               or row.timestamp > now or row.collected_at > now for row in rows):
            raise ValueError("Invalid observation scope")
        if rows:
            frame = regularize_history(pd.DataFrame([row.model_dump() for row in rows]))
            result["readiness"] = quality_report(frame, "exploratory")
        else:
            result["readiness"] = {"ready": False, "reasons": ["No usable measured observations"],
                                   "deployment_ready": False, "profile": "exploratory"}
    except Exception as error:
        result.update(status="readiness_unavailable", forecast_status="unavailable",
                      anomaly_status="unavailable", error_type=type(error).__name__)
        return result
    if not selected_run or not project:
        return result
    directory = Path(selected_run)
    try:
        from app.models.inference import inspect_run, predict_anomalies_from_run, predict_from_run

        result["evaluation"] = inspect_run(directory, project=project, region=region, service=service, now=now)
        result["status"] = "candidate_evaluated"
    except Exception as error:
        msg = str(error)
        if "scope" in msg.lower():
            result.update(
                status="unavailable_for_target",
                forecast_status="unavailable",
                anomaly_status="unavailable",
                forecast_reason="Candidate models apply only to the trained source service and region.",
                anomaly_reason="Anomaly detector applies only to the trained source service and region.",
            )
            return result
        result.update(status="run_rejected", forecast_status="run_rejected",
                      anomaly_status="run_rejected", error_type=type(error).__name__)
        return result
    try:
        forecasts = predict_from_run(directory, rows, project=project, region=region, service=service, now=now)
        result.update(forecast_status="candidate_available", forecasts=forecasts)
    except Exception as error:
        result.update(forecast_status="unavailable", forecast_error_type=type(error).__name__,
                      forecast_reason=_safe_forecast_reason(error))
    if (directory / "anomaly_manifest.json").is_file():
        try:
            anomalies = predict_anomalies_from_run(directory, rows, project=project, region=region, service=service, now=now)
            result.update(anomaly_status="experimental_observation_only", anomaly_results=anomalies)
        except Exception as error:
            result.update(anomaly_status="unavailable", anomaly_error_type=type(error).__name__,
                          anomaly_reason=_safe_anomaly_reason(error))
    else:
        result.update(anomaly_status="unavailable", anomaly_reason="No checksummed anomaly artifact in selected run.")
    return result
