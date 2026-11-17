"""Evidence-grounded public investigations and a durable, shared Gemini budget."""
import re
import hashlib
import json
from datetime import datetime, timezone


def recommendations(overview):
    plan = overview.get("recommendation_plan") or {}
    models = overview.get("models") or {}
    items = []

    def add(code, title, explanation, evidence, kind="investigation"):
        items.append(dict(id=code, title=title, explanation=explanation, evidence=evidence,
                          kind=kind, execution_allowed=False, estimated_savings=None))

    if plan.get("data_status") != "fresh":
        add("restore_measurements", "Restore fresh monitoring evidence",
            "Check scheduled collector executions and ingestion before making resource changes.",
            {"data_status": plan.get("data_status", "unavailable"),
             "latest_observation": plan.get("latest_observation")}, "data_quality")
    else:
        recent_errors = [r for r in overview.get("records", [])[-5:]
                         if r.get("error_rate") is not None and r["error_rate"] > 0
                         and r.get("request_count") is not None and r["request_count"] > 0]
        # Require recency relative to the actual latest observation; sparse
        # rows must never pull an old incident into a fresh recommendation.
        try:
            latest = datetime.fromisoformat(plan["latest_observation"].replace("Z", "+00:00"))
            recent_errors = [r for r in recent_errors if 0 <= (latest-datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00"))).total_seconds() < 300]
        except (KeyError, ValueError, TypeError):
            recent_errors = []
        if recent_errors:
            add("investigate_observed_errors", "Investigate observed server-error responses",
                "Server errors were measured in the recent window. Inspect failing routes and application logs; this establishes an availability symptom, not its cause or a need to scale. This warning uses measured errors rather than an experimental model flag.",
                [{k:r.get(k) for k in ("timestamp","error_rate","request_count")} for r in recent_errors], "observed_availability")
        rows = overview.get("records", [])[-30:]
        if len(rows) == 30:
            try:
                times = [datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")) for r in rows]
                contiguous = all((b-a).total_seconds() == 60 for a,b in zip(times,times[1:]))
                fields = ("cpu_utilization", "memory_utilization", "request_count", "error_rate", "instance_count")
                complete = all(all(r.get(k) is not None for k in fields) for r in rows)
                if contiguous and complete and all(r["cpu_utilization"] < .1 and r["memory_utilization"] < .6 and r["error_rate"] <= .01 and r["instance_count"] > 0 for r in rows):
                    add("review_utilisation", "Review sizing against this low-utilisation window",
                        "Resource use was consistently low in this measured window. Compare longer peak-period history, latency objectives, minimum-instance settings and allocation before considering a smaller size. A quiet window alone does not establish overprovisioning or savings.",
                        {"window_start":rows[0]["timestamp"], "window_end":rows[-1]["timestamp"], "observed_minutes":30,
                         "maximum_cpu":max(r["cpu_utilization"] for r in rows), "maximum_memory":max(r["memory_utilization"] for r in rows),
                         "total_requests":sum(r["request_count"] for r in rows)}, "capacity_review")
            except (ValueError, TypeError, KeyError):
                pass
        for item in plan.get("recommendations", []):
            add(item["action"], item["problem"], item["proposed_action"], item["evidence"])
        anomaly = models.get("anomaly_results") or {}
        if models.get("anomaly_status") == "experimental_observation_only" and anomaly.get("latest_anomaly_detected"):
            add("inspect_anomaly", "Review the experimental signal against measured pressure",
                "Review recent measurements and application logs. This experimental detector often flags idle periods; its flag does not establish a fault or justify scaling.",
                {k: anomaly.get(k) for k in ("window_end", "latest_decision_score", "latest_threshold_baseline", "latest_threshold_triggers", "latest_missing_fields", "latest_operational_status", "limitations")}, "experimental")
        forecasts = models.get("forecasts") or []
        pressure = [f for f in forecasts if not f.get("forecast_in_past", True)
                    and f.get("target") in ("cpu_utilization", "memory_utilization")
                    and f.get("prediction", 0) > .9]
        if pressure:
            add("watch_forecast", "Watch the candidate forecast for resource pressure",
                "Compare the candidate with persistence and new measurements. These forecasts failed the saved persistence benchmark; do not change capacity from this signal alone.",
                [{k: f.get(k) for k in ("target", "timestamp", "prediction", "persistence_prediction", "assessed_at")} for f in pressure], "experimental")
        if models.get("forecast_status") == "unavailable":
            add("forecast_coverage", "Check the missing forecast inputs",
                "Inspect measurement gaps and normal service activity. Keep missing targets unknown; do not generate traffic just to fill the chart.",
                {"reason": models.get("forecast_reason")}, "data_quality")
        summary = overview.get("summary") or {}
        missing = {k: v for k, v in summary.get("missing_counts", {}).items() if v and k in ("cpu_utilization", "memory_utilization", "request_count")}
        if missing:
            add("check_coverage", "Review gaps in the monitoring window",
                "Compare missing buckets with instance count and collection logs. A service scaling to zero can legitimately have no CPU or memory measurements.",
                {"missing_counts": missing, "observed_minutes": summary.get("observed_minutes")}, "data_quality")
        if not plan.get("recommendations") and not recent_errors:
            add("continue_monitoring", "Keep observing before changing capacity",
                "No sustained CPU, memory or server-error threshold breach is established in the latest window. This does not prove health or sufficient capacity.",
                {"latest_observation": plan.get("latest_observation"), "data_status": "fresh"}, "monitoring")
    return {"assessed_at": overview.get("assessed_at"), "data_status": plan.get("data_status", "unavailable"),
            "items": items, "execution_allowed": False, "estimated_savings": None}


def explain(settings, advice, *, client=None, selector=None, now=None):
    """At most one Gemini attempt per UTC hour across workers, instances and restarts.

    GCS generation=0 is the atomic reservation. Failures consume the hourly slot.
    Gemini only orders server-approved IDs; all factual explanations remain checked text.
    """
    if not settings.dashboard_gemini_enabled:
        return {"status": "disabled", "advice": advice}
    if advice["data_status"] != "fresh":
        return {"status": "skipped_stale", "advice": advice}

    def select_response():
        select = selector
        if select is None:
            from app.services.vertex_service import VertexService, VertexSettings
            select = VertexService(VertexSettings(project_id=settings.gcp_project_id,
                region=settings.gcp_region, model=settings.dashboard_gemini_model)).explain_advice
        response = select(advice)
        # List selectors remain supported for internal ordering tests/older integrations.
        if isinstance(response, list):
            ids, explanations, summary = response, {}, None
        else:
            from pydantic import BaseModel, ConfigDict, Field
            class GeneratedItem(BaseModel):
                model_config = ConfigDict(extra="forbid", strict=True)
                id: str
                explanation: str = Field(min_length=20, max_length=1400)
            class GeneratedResponse(BaseModel):
                model_config = ConfigDict(extra="forbid", strict=True)
                summary: str = Field(min_length=20, max_length=700)
                items: list[GeneratedItem] = Field(min_length=1, max_length=12)
            checked = GeneratedResponse.model_validate(response)
            ids = [i.id for i in checked.items]
            explanations = {i.id: i.explanation for i in checked.items}
            summary = checked.summary
            templates = {i["id"]: i["explanation"] for i in advice["items"]}
            if any(text.strip().casefold() == templates.get(code, "").strip().casefold() for code,text in explanations.items()):
                raise ValueError("Generated explanations copied checked text")
            for text in [summary, *explanations.values()]:
                if re.search(r"[0-9]|https?://|`|\b(?:gcloud|kubectl|terraform|guaranteed|definitely)\b", text, re.I):
                    raise ValueError("Generated text contains unsupported quantities or instructions")
        expected = [i["id"] for i in advice["items"]]
        if len(ids) != len(expected) or set(ids) != set(expected):
            raise ValueError("Invalid advice selection")
        return {"ordered_ids": ids, "explanations": explanations, "summary": summary,
                "text_source": "gemini" if explanations else "checked_templates"}

    if settings.dashboard_gemini_testing_unlimited:
        # Explicit testing mode: every click may call Gemini, without a GCS budget
        # reservation or result cache. Existing reservations remain untouched.
        try:
            return {"status": "completed", **select_response(), "advice": advice,
                    "budget_mode": "testing_unlimited"}
        except Exception as error:
            return {"status": "failed", "error_type": type(error).__name__, "advice": advice,
                    "budget_mode": "testing_unlimited"}
    if not settings.dashboard_review_bucket:
        return {"status": "budget_unavailable", "advice": advice}
    now = now or datetime.now(timezone.utc)
    fingerprint = hashlib.sha256(json.dumps({k: v for k, v in advice.items() if k != "assessed_at"}, sort_keys=True).encode()).hexdigest()
    if client is None:
        from google.cloud import storage
        client = storage.Client(project=settings.gcp_project_id)
    blob = client.bucket(settings.dashboard_review_bucket).blob("public-advice-budget/" + now.strftime("%Y%m%d/%H") + ".json")
    result_blob = client.bucket(settings.dashboard_review_bucket).blob("public-advice-results/" + now.strftime("%Y%m%d/%H") + ".json")
    from google.api_core.exceptions import PreconditionFailed
    try:
        blob.upload_from_string(json.dumps({"status": "reserved", "at": now.isoformat()}),
                                content_type="application/json", if_generation_match=0, timeout=10, retry=None)
    except PreconditionFailed:
        try:
            cached = json.loads(result_blob.download_as_text(timeout=10, retry=None))
            # Never return old measurements as a current explanation.
            if cached.get("fingerprint") == fingerprint and cached.get("status") == "completed":
                return {"status": "cached", "advice": advice, **{k: cached.get(k) for k in ("ordered_ids", "explanations", "summary", "text_source")}}
        except Exception:
            pass
        return {"status": "hourly_limit", "advice": advice}
    except Exception:
        return {"status": "budget_unavailable", "advice": advice}
    try:
        generated = select_response()
        result_blob.upload_from_string(json.dumps({"status": "completed", "fingerprint": fingerprint,
            **generated, "at": now.isoformat()}), content_type="application/json",
            if_generation_match=0, timeout=10, retry=None)
        return {"status": "completed", **generated, "advice": advice}
    except Exception as error:
        return {"status": "failed", "error_type": type(error).__name__, "advice": advice}
