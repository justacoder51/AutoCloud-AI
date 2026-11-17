"""Transparent Cloud Run estimates; measured savings are never inferred."""

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, model_validator

DEFAULT_PRICING = Path(__file__).resolve().parents[2] / "config" / "pricing.json"
EXCLUSIONS = [
    "free-tier credits", "negotiated/CUD discounts", "taxes", "currency conversion",
    "network transfer", "builds", "image storage", "BigQuery", "Monitoring", "Scheduler",
]


class CostModel(BaseModel):
    """Reject unexpected fields and nonfinite financial values."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class RateCard(CostModel):
    active_cpu_per_vcpu_second: Decimal = Field(ge=0)
    active_memory_per_gib_second: Decimal = Field(ge=0)
    idle_cpu_per_vcpu_second: Decimal = Field(ge=0)
    idle_memory_per_gib_second: Decimal = Field(ge=0)
    requests_per_million: Decimal = Field(ge=0)


class Pricing(CostModel):
    schema_version: Literal[1]
    currency: Literal["USD"]
    regions: list[str] = Field(min_length=1)
    verified_on: date
    expires_on: date
    sources: list[HttpUrl] = Field(min_length=1)
    cards: dict[Literal["request_based", "instance_based", "jobs"], RateCard]

    @model_validator(mode="after")
    def validate_dates(self) -> "Pricing":
        if self.expires_on < self.verified_on:
            raise ValueError("Pricing expiry must not precede verification")
        if set(self.cards) != {"request_based", "instance_based", "jobs"}:
            raise ValueError("All supported billing profiles need explicit rates")
        return self


class UsageContext(CostModel):
    project_id: str = Field(pattern=r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
    region: str
    service_name: str = Field(min_length=1)
    period_start: AwareDatetime
    period_end: AwareDatetime
    source: Literal["verified_metering", "user_assumptions", "synthetic_demo"]
    evidence_reference: str | None = None

    @model_validator(mode="after")
    def validate_context(self) -> "UsageContext":
        if self.period_start >= self.period_end:
            raise ValueError("Usage period must be nonempty")
        if self.source == "verified_metering" and not self.evidence_reference:
            raise ValueError("Metered usage needs an evidence reference")
        return self


class ServiceUsage(UsageContext):
    """Allocated billable units, not utilization percentages or request latency."""

    billing_mode: Literal["request_based", "instance_based"]
    active_vcpu_seconds: Decimal = Field(ge=0)
    active_gib_seconds: Decimal = Field(ge=0)
    requests: int = Field(ge=0)
    idle_vcpu_seconds: Decimal = Field(default=Decimal(0), ge=0)
    idle_gib_seconds: Decimal = Field(default=Decimal(0), ge=0)

    @model_validator(mode="after")
    def validate_idle(self) -> "ServiceUsage":
        if self.billing_mode == "instance_based" and (
            self.idle_vcpu_seconds or self.idle_gib_seconds
        ):
            raise ValueError("Instance-based lifetime usage belongs in active units")
        return self


class JobAttempt(CostModel):
    """One started instance attempt, including startup/shutdown and any retries."""

    instance_lifetime_seconds: Decimal = Field(ge=0)
    vcpu: Decimal = Field(gt=0)
    memory_gib: Decimal = Field(gt=0)


class JobUsage(UsageContext):
    billing_mode: Literal["jobs"] = "jobs"
    attempts: list[JobAttempt] = Field(min_length=1, max_length=10000)


class CostEstimate(CostModel):
    status: Literal["illustrative_estimate", "estimated_not_billed"]
    currency: Literal["USD"]
    estimated_cost: Decimal
    components: dict[str, Decimal]
    billing_mode: str
    project_id: str
    service_name: str
    region: str
    period_start: AwareDatetime
    period_end: AwareDatetime
    input_source: str
    evidence_reference: str | None
    pricing_verified_on: date
    pricing_sources: list[str]
    exclusions: list[str]
    actual_billed_cost: None = None
    measured_savings: None = None


def load_usage(path: Path) -> ServiceUsage | JobUsage:
    """Load a clearly labelled usage document, refusing unknown/missing units."""
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    model = JobUsage if payload.get("billing_mode") == "jobs" else ServiceUsage
    return model.model_validate(payload)


class CostAnalyser:
    """Decimal arithmetic with versioned, dated, region-scoped pricing."""

    def __init__(self, pricing: Pricing, as_of: date | None = None):
        self.pricing = pricing
        as_of = as_of or datetime.now(timezone.utc).date()
        if not pricing.verified_on <= as_of <= pricing.expires_on:
            raise ValueError("Pricing is future-dated or expired; verify and refresh it")

    @classmethod
    def from_file(cls, path: Path = DEFAULT_PRICING, as_of: date | None = None):
        return cls(Pricing.model_validate_json(path.read_text(encoding="utf-8")), as_of)

    def estimate(self, usage: ServiceUsage | JobUsage) -> CostEstimate:
        """Estimate list-rate components without assuming free-tier availability."""
        if usage.region not in self.pricing.regions:
            raise ValueError("No verified rate card for this region")
        rate = self.pricing.cards[usage.billing_mode]
        if isinstance(usage, JobUsage):
            cpu, memory = Decimal(0), Decimal(0)
            for attempt in usage.attempts:
                seconds = (
                    max(attempt.instance_lifetime_seconds, Decimal(60)) / Decimal("0.1")
                ).to_integral_value(rounding=ROUND_CEILING) * Decimal("0.1")
                cpu += seconds * attempt.vcpu
                memory += seconds * attempt.memory_gib
            idle_cpu, idle_memory, requests = Decimal(0), Decimal(0), 0
        else:
            cpu, memory = usage.active_vcpu_seconds, usage.active_gib_seconds
            idle_cpu, idle_memory = usage.idle_vcpu_seconds, usage.idle_gib_seconds
            requests = usage.requests
        components = {
            "active_cpu": cpu * rate.active_cpu_per_vcpu_second,
            "active_memory": memory * rate.active_memory_per_gib_second,
            "idle_cpu": idle_cpu * rate.idle_cpu_per_vcpu_second,
            "idle_memory": idle_memory * rate.idle_memory_per_gib_second,
            "requests": Decimal(requests) * rate.requests_per_million / Decimal(1_000_000),
        }
        return CostEstimate(
            status="estimated_not_billed" if usage.source == "verified_metering"
            else "illustrative_estimate",
            currency=self.pricing.currency, estimated_cost=sum(components.values()),
            components=components, billing_mode=usage.billing_mode,
            project_id=usage.project_id, service_name=usage.service_name, region=usage.region,
            period_start=usage.period_start, period_end=usage.period_end,
            input_source=usage.source, evidence_reference=usage.evidence_reference,
            pricing_verified_on=self.pricing.verified_on,
            pricing_sources=[str(source) for source in self.pricing.sources],
            exclusions=EXCLUSIONS,
        )

    def compare(
        self, current: ServiceUsage | JobUsage, alternative: ServiceUsage | JobUsage,
    ) -> dict:
        """Counterfactual savings require comparable scope and never count as measured."""
        for field in ("project_id", "region", "service_name", "period_start", "period_end"):
            if getattr(current, field) != getattr(alternative, field):
                raise ValueError("Cost comparison must use the same service, region and period")
        if isinstance(current, JobUsage) != isinstance(alternative, JobUsage):
            raise ValueError("Job and service workloads are not directly comparable")
        before, after = self.estimate(current), self.estimate(alternative)
        savings = before.estimated_cost - after.estimated_cost
        return {
            "status": "counterfactual_estimate_not_measured", "currency": before.currency,
            "current_estimated_cost": str(before.estimated_cost),
            "recommended_estimated_cost": str(after.estimated_cost),
            "estimated_savings": str(savings),
            "savings_percentage": str(savings / before.estimated_cost * 100)
            if before.estimated_cost else None,
            "measured_savings": None,
            "performance_impact": "Not assessed; workload equivalence and SLOs need experiments",
            "current": before.model_dump(mode="json"),
            "alternative": after.model_dump(mode="json"),
        }
