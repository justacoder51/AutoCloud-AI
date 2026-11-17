"""Local evidence endpoint; never collects traffic, trains or executes actions."""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from app.services.dashboard_service import overview
from app.services.model_dashboard import model_panel
from app.services.resource_registry import authorize_target

router = APIRouter(prefix="/api", tags=["monitoring"])


@router.get("/costs")
def billing_costs(
    request: Request,
    days: int = Query(default=1, ge=1, le=31),
    project: str | None = None,
    region: str | None = None,
    service: str | None = None,
) -> dict:
    """Read the server-configured export for the host project only; never leak cross-tenant billing."""
    settings = request.app.state.settings
    target = authorize_target(request, project=project, region=region, service=service)
    if target.kind == "onboarded":
        return {
            "status": "not_applicable_external_project",
            "lookback_days": days,
            "project_id": target.project_id,
            "currency_totals": [],
            "daily_totals": [],
            "rows": [],
            "actual_billed_cost": None,
            "note": "Configured Cloud Billing export covers the host project only and is not exposed for external onboarded projects.",
        }
    return request.app.state.dashboard_billing.read(
        settings.gcp_project_id, settings.dashboard_billing_table, days,
    )


@router.get("/overview")
def monitoring_overview(
    request: Request,
    source: Literal["local", "bigquery", "monitoring"] = "local",
    hours: int = Query(default=24, ge=1, le=24),
    project: str | None = None,
    region: str | None = None,
    service: str | None = None,
) -> dict:
    """Return the authorized scoped service snapshot, observation-only ML signals, and limitations."""
    settings = request.app.state.settings
    target = authorize_target(request, project=project, region=region, service=service)
    if target.kind == "onboarded" and source not in target.allowed_sources:
        raise HTTPException(403, "External onboarded projects support live source=monitoring reads only.")

    user_gcp_token = request.headers.get("x-autocloud-gcp-access-token", "").strip() or None
    query = None
    if source in {"bigquery", "monitoring"} and target.project_id:
        query = request.app.state.dashboard_history.read(
            target.project_id,
            target.region,
            target.service_name,
            hours,
            source=source,
            owner_key=target.owner_sub,
            bearer_token=user_gcp_token if target.kind == "onboarded" else None,
        )
    result = overview(
        request.app.state.analytics_data_root,
        target.project_id,
        target.region,
        target.service_name,
        records=query["records"] if query else None,
        query=query,
    )
    result["models"] = model_panel(
        result["records"],
        settings.dashboard_forecast_run,
        project=target.project_id,
        region=target.region,
        service=target.service_name,
        now=datetime.now(timezone.utc),
    )
    result["target"] = target.model_dump()
    result["capabilities"] = {
        "local_reviews": settings.environment != "production",
        "cloud_reviews": bool(settings.dashboard_review_bucket),
        "ai_workflow": True,
        "gemini_enabled": settings.dashboard_gemini_enabled,
        "gemini_model": settings.dashboard_gemini_model,
        "billing_configured": target.billing_applicable,
        "user_auth_enabled": settings.dashboard_user_auth_required or bool(settings.google_oauth_client_id),
        "signed_in": target.owner_sub is not None,
        "keyless_onboarding": True,
        "observation_only_models": bool(settings.dashboard_forecast_run),
    }
    if settings.dashboard_evaluation_file and not settings.dashboard_forecast_run:
        if target.kind == "host" and target.service_name == "autocloud-api":
            try:
                from app.services.recorded_evaluation import load_recorded_evaluation

                evaluation = load_recorded_evaluation(
                    settings.dashboard_evaluation_file, settings.dashboard_evaluation_sha256,
                    settings.gcp_project_id, settings.gcp_region, "autocloud-api",
                )
                result["models"].update(
                    status="recorded_evaluation_only", evaluation=evaluation,
                    forecast_status="not_deployed", forecasts=None,
                )
            except Exception:
                result["models"].update(status="run_rejected", evaluation=None, forecasts=None,
                                         forecast_status="run_rejected")
        else:
            result["models"].update(
                status="unavailable_for_target",
                evaluation=None,
                forecasts=None,
                forecast_status="unavailable",
                anomaly_status="unavailable",
            )
    elif settings.dashboard_evaluation_file and result["models"].get("evaluation") is None and target.kind == "host" and target.service_name == "autocloud-api":
        try:
            from app.services.recorded_evaluation import load_recorded_evaluation

            evaluation = load_recorded_evaluation(
                settings.dashboard_evaluation_file, settings.dashboard_evaluation_sha256,
                settings.gcp_project_id, settings.gcp_region, "autocloud-api",
            )
            result["models"]["evaluation"] = evaluation
        except Exception:
            pass
    if settings.dashboard_public_showcase:
        for capability in ("local_reviews", "cloud_reviews", "ai_workflow", "gemini_enabled",
                           "billing_configured", "user_auth_enabled", "keyless_onboarding"):
            result["capabilities"][capability] = False
        result["capabilities"]["public_read_only"] = True
        result["experiment"] = {"progress_status": "not_applicable", "note": "Public read-only monitoring; no training is started by visiting."}
    from app.services.public_advice import recommendations
    result["public_advice"] = recommendations(result)
    result["capabilities"]["public_explanations"] = bool(settings.dashboard_public_showcase and settings.dashboard_gemini_enabled)
    result["capabilities"]["gemini_testing_unlimited"] = settings.dashboard_gemini_testing_unlimited
    from app.services.validation_evidence import load_measured_validation
    result["measured_validation"] = load_measured_validation(settings.dashboard_forecast_run,
        project=target.project_id, region=target.region, service=target.service_name)
    if target.kind=="host" and target.service_name=="autocloud-api":
        result["prospective_validation"] = request.app.state.forecast_ledger.record(settings, result)
    return result


@router.post("/public-explanation")
async def public_explanation(request: Request):
    """Fixed server-side evidence only; no arbitrary prompt, scope, or billing input."""
    settings = request.app.state.settings
    if not settings.dashboard_public_showcase or request.headers.get("origin") is not None:
        raise HTTPException(403, "Use the public dashboard control.")
    if request.query_params or await request.body():
        raise HTTPException(422, "This control accepts no input.")
    from starlette.concurrency import run_in_threadpool
    from app.services.public_advice import explain

    def run():
        evidence = monitoring_overview(request, source="bigquery", hours=24)
        return explain(settings, evidence["public_advice"])
    return await run_in_threadpool(run)
