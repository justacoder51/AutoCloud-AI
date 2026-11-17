"""Source-labelled metric records with explicit units and missing values."""

from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

METRIC_FIELDS = (
    "cpu_utilization", "memory_utilization", "request_count", "network_ingress",
    "network_egress", "average_latency", "error_rate", "instance_count",
)


class MetricSample(BaseModel):
    """One aligned series point; distribution means retain sample weights."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    timestamp: AwareDatetime
    metric: str
    value: float = Field(ge=0)
    weight: int = Field(default=1, gt=0)
    series_key: str
    response_code: str = ""


class MetricRecord(BaseModel):
    """One observed service/minute; utilisation and error rate are fractions."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)
    timestamp: AwareDatetime
    collected_at: AwareDatetime
    project_id: str
    region: str
    service_name: str
    source: Literal["gcp-monitoring"] = "gcp-monitoring"
    interval_seconds: Literal[60] = 60
    record_id: str = ""
    cpu_utilization: float | None = Field(default=None, ge=0, le=1)
    memory_utilization: float | None = Field(default=None, ge=0, le=1)
    request_count: int | None = Field(default=None, ge=0)
    network_ingress: int | None = Field(default=None, ge=0)
    network_egress: int | None = Field(default=None, ge=0)
    average_latency: float | None = Field(default=None, ge=0)
    error_rate: float | None = Field(default=None, ge=0, le=1)
    instance_count: float | None = Field(default=None, ge=0)
    missing_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def populate_provenance(self) -> "MetricRecord":
        """Derive stable logical keys and missingness from measured fields."""
        timestamp = self.timestamp.astimezone(timezone.utc)
        if timestamp.second or timestamp.microsecond:
            raise ValueError("timestamp must be a UTC minute boundary")
        key = f"{self.project_id}|{self.region}|{self.service_name}|{timestamp.isoformat()}"
        object.__setattr__(self, "record_id", sha256(key.encode()).hexdigest())
        object.__setattr__(self, "missing_fields", [
            name for name in METRIC_FIELDS if getattr(self, name) is None
        ])
        return self
