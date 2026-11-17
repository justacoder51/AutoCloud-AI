"""Validated environment configuration; no credentials are stored here."""

import os
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


_ALLOWED_SERVICE_RE = re.compile(r"^(?:[a-z][a-z0-9-]{0,48}[a-z0-9]|[a-z])$")


class Settings(BaseModel):
    """Keep runtime configuration separate from application logic."""

    model_config = ConfigDict(frozen=True)
    app_name: str = "AutoCloud AI"
    environment: Literal["development", "test", "production"] = "development"
    port: int = Field(default=8080, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    gcp_project_id: str | None = None
    gcp_region: str = "asia-south1"
    min_instances: int = Field(default=0, ge=0, le=2)
    max_instances: int = Field(default=2, ge=1, le=2)
    dashboard_forecast_run: str | None = None
    dashboard_billing_table: str | None = None
    dashboard_evaluation_file: str | None = None
    dashboard_evaluation_sha256: str | None = None
    dashboard_gemini_enabled: bool = False
    dashboard_gemini_testing_unlimited: bool = False
    dashboard_validation_ledger_enabled: bool = False
    dashboard_gemini_model: Literal["gemini-3.5-flash-lite", "gemini-3.5-flash"] = "gemini-3.5-flash-lite"
    dashboard_review_bucket: str | None = None
    dashboard_review_audience: str | None = None
    dashboard_allowed_services: str | None = None
    dashboard_discover_run_services: bool = False
    dashboard_user_auth_required: bool = False
    dashboard_public_showcase: bool = False
    dashboard_allow_dev_login: bool = False
    dashboard_allowed_users: str | None = None
    dashboard_session_secret: str | None = None
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    dashboard_oauth_redirect_uri: str | None = None

    @property
    def resolved_allowed_services(self) -> tuple[str, ...]:
        if self.dashboard_allowed_services:
            items = tuple(s.strip() for s in self.dashboard_allowed_services.split(",") if s.strip())
            if items:
                return items
        if self.gcp_project_id:
            return ("autocloud-api", "autocloud-dashboard")
        return ("autocloud-api",)

    @property
    def allowed_user_emails(self) -> tuple[str, ...]:
        if not self.dashboard_allowed_users:
            return ()
        return tuple(u.strip().lower() for u in self.dashboard_allowed_users.split(",") if u.strip())

    @model_validator(mode="after")
    def validate_instance_limits(self) -> "Settings":
        """Reject contradictory scaling limits before startup."""
        if self.min_instances > self.max_instances:
            raise ValueError("MIN_INSTANCES must not exceed MAX_INSTANCES")
        if self.environment == "production" and not self.gcp_project_id:
            raise ValueError("GCP_PROJECT_ID is required in production")
        if self.environment == "production" and self.dashboard_allow_dev_login:
            raise ValueError("DASHBOARD_ALLOW_DEV_LOGIN is forbidden in production")
        if self.environment == "production" and self.dashboard_user_auth_required:
            if not self.dashboard_session_secret or len(self.dashboard_session_secret) < 32:
                raise ValueError("DASHBOARD_SESSION_SECRET (>= 32 chars) is required when user auth is enabled in production")
        if self.dashboard_session_secret and len(self.dashboard_session_secret) < 32:
            raise ValueError("DASHBOARD_SESSION_SECRET must be at least 32 characters")
        if self.dashboard_allowed_services:
            for item in (s.strip() for s in self.dashboard_allowed_services.split(",") if s.strip()):
                if _ALLOWED_SERVICE_RE.fullmatch(item) is None:
                    raise ValueError(f"Invalid service name in DASHBOARD_ALLOWED_SERVICES: {item}")
        if self.dashboard_oauth_redirect_uri:
            parsed = urlsplit(self.dashboard_oauth_redirect_uri)
            valid_local = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
            valid_cloud = parsed.scheme == "https" and parsed.hostname and parsed.hostname.endswith(".run.app")
            if not (valid_local or valid_cloud) or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("Invalid OAuth redirect URI")
        if self.dashboard_billing_table:
            from app.services.billing_service import validate_billing_table

            validate_billing_table(self.dashboard_billing_table)
        if bool(self.dashboard_evaluation_file) != bool(self.dashboard_evaluation_sha256):
            raise ValueError("Recorded evaluation requires a file and checksum")
        if self.dashboard_review_bucket:
            if (not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]", self.dashboard_review_bucket)
                    or self.dashboard_review_bucket.startswith("goog")
                    or "google" in self.dashboard_review_bucket):
                raise ValueError("Invalid Cloud Storage review bucket")
        if self.dashboard_review_audience:
            parsed = urlsplit(self.dashboard_review_audience)
            if (parsed.scheme != "https" or not parsed.hostname
                    or not parsed.hostname.endswith(".run.app") or parsed.username
                    or parsed.password or parsed.port or parsed.path not in ("", "/")
                    or parsed.query or parsed.fragment):
                raise ValueError("Invalid Cloud Run review audience")
        return self


def load_settings() -> Settings:
    """Read only explicitly supported variables from the environment."""
    fields = {
        "APP_NAME": "app_name",
        "APP_ENV": "environment",
        "PORT": "port",
        "LOG_LEVEL": "log_level",
        "GCP_PROJECT_ID": "gcp_project_id",
        "GCP_REGION": "gcp_region",
        "MIN_INSTANCES": "min_instances",
        "MAX_INSTANCES": "max_instances",
        "DASHBOARD_FORECAST_RUN": "dashboard_forecast_run",
        "DASHBOARD_BILLING_TABLE": "dashboard_billing_table",
        "DASHBOARD_EVALUATION_FILE": "dashboard_evaluation_file",
        "DASHBOARD_EVALUATION_SHA256": "dashboard_evaluation_sha256",
        "DASHBOARD_GEMINI_ENABLED": "dashboard_gemini_enabled",
        "DASHBOARD_GEMINI_MODEL": "dashboard_gemini_model",
        "DASHBOARD_GEMINI_TESTING_UNLIMITED": "dashboard_gemini_testing_unlimited",
        "DASHBOARD_VALIDATION_LEDGER_ENABLED": "dashboard_validation_ledger_enabled",
        "DASHBOARD_REVIEW_BUCKET": "dashboard_review_bucket",
        "DASHBOARD_REVIEW_AUDIENCE": "dashboard_review_audience",
        "DASHBOARD_ALLOWED_SERVICES": "dashboard_allowed_services",
        "DASHBOARD_DISCOVER_RUN_SERVICES": "dashboard_discover_run_services",
        "DASHBOARD_USER_AUTH_REQUIRED": "dashboard_user_auth_required",
        "DASHBOARD_PUBLIC_SHOWCASE": "dashboard_public_showcase",
        "DASHBOARD_ALLOW_DEV_LOGIN": "dashboard_allow_dev_login",
        "DASHBOARD_ALLOWED_USERS": "dashboard_allowed_users",
        "DASHBOARD_SESSION_SECRET": "dashboard_session_secret",
        "GOOGLE_OAUTH_CLIENT_ID": "google_oauth_client_id",
        "GOOGLE_OAUTH_CLIENT_SECRET": "google_oauth_client_secret",
        "DASHBOARD_OAUTH_REDIRECT_URI": "dashboard_oauth_redirect_uri",
    }
    return Settings(**{
        field: os.environ[variable]
        for variable, field in fields.items()
        if variable in os.environ
    })
