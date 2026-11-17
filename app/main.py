"""First deployment milestone: a small, measurable FastAPI service."""

import logging
import time
from pathlib import Path
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import Settings, load_settings
from app.utils.logging import configure_logging

logger = logging.getLogger("autocloud")


class HealthResponse(BaseModel):
    """Typed health response, deliberately independent of future integrations."""

    status: str


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an isolated application instance for runtime or testing."""
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        configure_logging(settings.log_level)
        logger.info("Application started")
        yield
        logger.info("Application stopped")

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.environment != "production" else None,
    )
    application.state.settings = settings
    application.state.analytics_data_root = Path(__file__).resolve().parents[1] / "data"
    from app.services.dashboard_service import DashboardHistory

    application.state.dashboard_history = DashboardHistory()
    from app.services.forecast_ledger import ForecastLedger
    application.state.forecast_ledger = ForecastLedger()
    from app.services.billing_dashboard import BillingDashboard

    application.state.dashboard_billing = BillingDashboard()

    from app.api.monitoring import router

    application.include_router(router)
    from app.api.reviews import router as reviews_router

    application.include_router(reviews_router)
    from app.api.analysis import router as analysis_router
    from app.services.analysis_service import DashboardAnalysis

    application.state.dashboard_analysis = DashboardAnalysis()
    application.include_router(analysis_router)
    from app.api.auth_projects import auth_router, projects_router, resources_router

    application.include_router(auth_router)
    application.include_router(resources_router)
    application.include_router(projects_router)

    @application.middleware("http")
    async def public_showcase_boundary(request: Request, call_next):
        if settings.dashboard_public_showcase:
            allowed = {"/", "/health/live", "/health/ready", "/api/overview"}
            explanation = request.method == "POST" and request.url.path == "/api/public-explanation"
            if not explanation and (request.method != "GET" or request.url.path not in allowed):
                return JSONResponse(status_code=403, content={"detail": "Unavailable in public read-only mode."})
            if request.url.path == "/api/overview":
                permitted = {
                    "source": "bigquery", "hours": "24",
                    "project": settings.gcp_project_id,
                    "region": settings.gcp_region, "service": "autocloud-api",
                }
                if (request.query_params.get("source") != "bigquery"
                    or any(key not in permitted or value != permitted[key]
                           for key, value in request.query_params.multi_items())):
                    return JSONResponse(status_code=403, content={"detail": "Public monitoring is restricted to the configured showcase."})
        return await call_next(request)

    @application.middleware("http")
    async def log_request(request: Request, call_next):
        request_id = uuid4().hex
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Do not log exception text, which may contain credentials or user input.
            logger.error("Unhandled request error", extra={"request_id": request_id})
            response = JSONResponse(
                status_code=500,
                content={"detail": "Internal server error", "request_id": request_id},
            )
        response.headers["X-Request-ID"] = request_id
        logger.info("Request completed", extra={
            "request_id": request_id,
            "method": request.method,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - start) * 1000, 3),
        })
        return response

    @application.get("/")
    async def index() -> dict[str, object]:
        if not settings.gcp_project_id:
            return {
                "service": settings.app_name,
                "version": "0.1.0",
                "stage": "environment-setup",
                "message": "Initial service; monitoring and analytics are not enabled.",
            }
        return {
            "service": settings.app_name,
            "version": "0.1.0",
            "stage": "configured",
            "capabilities": {
                "monitoring_overview": True,
                "recorded_evaluation": bool(settings.dashboard_evaluation_file),
                "observation_only_models": bool(settings.dashboard_forecast_run),
                "cloud_reviews": bool(settings.dashboard_review_bucket) and not settings.dashboard_public_showcase,
                "ai_workflow": not settings.dashboard_public_showcase,
                "gemini_enabled": settings.dashboard_gemini_enabled and not settings.dashboard_public_showcase,
                "billing_configured": bool(settings.dashboard_billing_table) and not settings.dashboard_public_showcase,
                "user_auth": (settings.dashboard_user_auth_required or bool(settings.google_oauth_client_id)) and not settings.dashboard_public_showcase,
                "project_onboarding": not settings.dashboard_public_showcase,
                "public_read_only": settings.dashboard_public_showcase,
                "public_recommendations": settings.dashboard_public_showcase,
                "autonomous_execution": False,
            },
            "message": (
                "Configured for scoped observability, recorded/experimental evaluation, and human-reviewed "
                "recommendations; autonomous infrastructure execution is disabled."
            ),
        }

    @application.get("/health/live", response_model=HealthResponse)
    async def liveness() -> HealthResponse:
        return HealthResponse(status="ok")

    @application.get("/health/ready", response_model=HealthResponse)
    async def readiness() -> HealthResponse:
        # Process readiness only; does not probe BigQuery, Vertex AI Gemini, or Cloud Storage.
        return HealthResponse(status="ready")

    return application


app = create_app()
