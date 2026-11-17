"""Manual read-only AI analysis; cloud authentication is enforced by Cloud Run IAM."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.services.analysis_service import AnalysisBusy
from app.services.resource_registry import authorize_target

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    hours: int = Field(default=24, ge=1, le=24)
    use_gemini: bool = False
    include_billing: bool = False
    connectivity_check: bool = False
    project: str | None = None
    region: str | None = None
    service: str | None = None
    source: Literal["bigquery", "monitoring"] = "bigquery"


@router.post("")
def analyse(body: AnalysisRequest, request: Request):
    if request.headers.get("origin") is not None:
        raise HTTPException(403, "Use the dashboard's server-side analysis control.")
    settings = request.app.state.settings
    target = authorize_target(
        request, project=body.project, region=body.region, service=body.service,
    )
    if not target.project_id:
        raise HTTPException(409, "Configure the project before running analysis.")
    if target.kind == "onboarded" and body.source not in target.allowed_sources:
        raise HTTPException(403, "External onboarded projects support source=monitoring analysis only.")
    if body.use_gemini and not settings.dashboard_gemini_enabled:
        raise HTTPException(409, "Gemini is not enabled for this API.")
    if body.connectivity_check and (not body.use_gemini or body.include_billing):
        raise HTTPException(422, "Connectivity checks require Gemini and no billing input.")
    if body.include_billing and not target.billing_applicable:
        raise HTTPException(409, "The billing export is not configured for this project.")
    user_gcp_token = request.headers.get("x-autocloud-gcp-access-token", "").strip() or None
    try:
        return request.app.state.dashboard_analysis.run(
            settings,
            request.app.state.dashboard_history,
            hours=body.hours,
            use_gemini=body.use_gemini,
            include_billing=body.include_billing,
            connectivity_check=body.connectivity_check,
            project_id=target.project_id,
            region=target.region,
            service_name=target.service_name,
            source=body.source,
            owner_key=target.owner_sub,
            bearer_token=user_gcp_token if target.kind == "onboarded" else None,
            billing_allowed=target.billing_applicable,
        )
    except AnalysisBusy as error:
        raise HTTPException(429, str(error), headers={"Retry-After": "60"}) from None
