"""Validated environment configuration; no credentials are stored here."""

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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

    @model_validator(mode="after")
    def validate_instance_limits(self) -> "Settings":
        """Reject contradictory scaling limits before startup."""
        if self.min_instances > self.max_instances:
            raise ValueError("MIN_INSTANCES must not exceed MAX_INSTANCES")
        if self.environment == "production" and not self.gcp_project_id:
            raise ValueError("GCP_PROJECT_ID is required in production")
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
    }
    return Settings(**{
        field: os.environ[variable]
        for variable, field in fields.items()
        if variable in os.environ
    })
