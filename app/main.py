"""First deployment milestone: a small, measurable FastAPI service."""

import logging
import time
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
    async def index() -> dict[str, str]:
        return {
            "service": settings.app_name,
            "version": "0.1.0",
            "stage": "environment-setup",
            "message": "Initial service; monitoring and analytics are not enabled.",
        }

    @application.get("/health/live", response_model=HealthResponse)
    async def liveness() -> HealthResponse:
        return HealthResponse(status="ok")

    @application.get("/health/ready", response_model=HealthResponse)
    async def readiness() -> HealthResponse:
        # There are no external runtime dependencies in this milestone.
        return HealthResponse(status="ready")

    return application


app = create_app()
