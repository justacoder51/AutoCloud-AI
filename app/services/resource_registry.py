"""Authorized host and per-user onboarded project/service resolution."""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict

from app.services.tenant_store import (
    CloudTenantStore,
    LocalTenantStore,
    SERVICE_PATTERN,
    gcp_discover_run_services,
    validate_project_target,
)
from app.services.user_auth import AuthenticatedUser, extract_optional_user


class AuthorizedTarget(BaseModel):
    """Server-validated (project, region, service) bound to the authenticated caller."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    project_id: str | None
    region: str
    service_name: str
    kind: Literal["host", "onboarded", "unconfigured"]
    owner_sub: str | None = None
    billing_applicable: bool = False
    allowed_sources: tuple[Literal["local", "bigquery", "monitoring"], ...] = ("local",)
    delegation_status: str | None = None


def resolve_tenant_store(request: Request):
    """Return configured LocalTenantStore (dev/test) or CloudTenantStore (cloud)."""
    custom = getattr(request.app.state, "tenant_store", None)
    if custom is not None:
        return custom
    settings = request.app.state.settings
    if settings.dashboard_review_bucket:
        return CloudTenantStore(
            settings.gcp_project_id,
            settings.gcp_region,
            settings.dashboard_review_bucket,
            client=getattr(request.app.state, "review_storage_client", None),
        )
    return LocalTenantStore(request.app.state.analytics_data_root / "tenants.sqlite3")


def _caller_host_allowed(settings, user: AuthenticatedUser | None) -> bool:
    if settings.dashboard_user_auth_required and user is None:
        return False
    allowed_emails = settings.allowed_user_emails
    if allowed_emails:
        return user is not None and user.email.lower() in allowed_emails
    return True


def _discover_host_services(request: Request) -> tuple[str, ...]:
    settings = request.app.state.settings
    base = list(settings.resolved_allowed_services)
    discoverer = getattr(request.app.state, "host_service_discoverer", None)
    discovered: list[str] = []
    if discoverer is not None:
        discovered = list(discoverer(settings.gcp_project_id, settings.gcp_region))
    elif settings.dashboard_discover_run_services and settings.gcp_project_id:
        try:
            import google.auth
            from google.auth.transport.requests import Request as AuthRequest

            creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            creds.refresh(AuthRequest())
            discovered = gcp_discover_run_services(settings.gcp_project_id, settings.gcp_region, creds.token)
        except Exception:
            discovered = []
    if settings.dashboard_allowed_services:
        # Strict allowlist configured -> filter discovered services against allowlist.
        allowed_set = set(base)
        ordered = [s for s in discovered if s in allowed_set]
        for s in base:
            if s not in ordered:
                ordered.append(s)
        return tuple(ordered)
    combined = list(dict.fromkeys([*base, *(s for s in discovered if SERVICE_PATTERN.fullmatch(s))]))
    return tuple(combined)


def list_authorized_resources(request: Request, user: AuthenticatedUser | None) -> list[dict]:
    """Enumerate ONLY host resources authorized for caller plus user's own onboarded projects."""
    settings = request.app.state.settings
    items: list[dict] = []
    if settings.gcp_project_id and _caller_host_allowed(settings, user):
        services = _discover_host_services(request)
        for svc in services:
            items.append({
                "project_id": settings.gcp_project_id,
                "region": settings.gcp_region,
                "service_name": svc,
                "kind": "host",
                "display_name": f"{settings.gcp_project_id} · {svc} (host)",
                "allowed_sources": ["bigquery", "monitoring", "local"],
                "billing_applicable": bool(settings.dashboard_billing_table),
                "models_scoped": svc == "autocloud-api",
                "status": "authorized_host",
            })

    if user is not None:
        store = resolve_tenant_store(request)
        for proj in store.list_projects(user.sub):
            svc_list = proj.services or ()
            if svc_list:
                for svc in svc_list:
                    items.append({
                        "project_id": proj.project_id,
                        "region": proj.region,
                        "service_name": svc,
                        "kind": "onboarded",
                        "display_name": f"{proj.display_name} ({proj.project_id}) · {svc}",
                        "allowed_sources": ["monitoring"],
                        "billing_applicable": False,
                        "models_scoped": False,
                        "status": proj.status,
                    })
            else:
                items.append({
                    "project_id": proj.project_id,
                    "region": proj.region,
                    "service_name": "",
                    "kind": "onboarded",
                    "display_name": f"{proj.display_name} ({proj.project_id}) · pending service discovery",
                    "allowed_sources": ["monitoring"],
                    "billing_applicable": False,
                    "models_scoped": False,
                    "status": proj.status,
                })
    return items


def authorize_target(
    request: Request,
    *,
    project: str | None = None,
    region: str | None = None,
    service: str | None = None,
) -> AuthorizedTarget:
    """Validate target access; deny cross-tenant, arbitrary project, or unallowed service access."""
    settings = request.app.state.settings
    user = extract_optional_user(request)
    if settings.dashboard_user_auth_required and user is None:
        raise HTTPException(401, "User sign-in is required.")

    # Backward-compatible unconfigured dev/test fallback when project is unset and none requested.
    if not settings.gcp_project_id and project is None:
        return AuthorizedTarget(
            project_id=None,
            region=region or settings.gcp_region,
            service_name=service or "autocloud-api",
            kind="unconfigured",
            owner_sub=user.sub if user else None,
            billing_applicable=False,
            allowed_sources=("local",),
        )

    target_project = project or settings.gcp_project_id
    target_region = region or settings.gcp_region
    target_service = service or "autocloud-api"

    if not target_project:
        raise HTTPException(409, "Configure or onboard a project before querying resources.")
    try:
        validate_project_target(target_project, target_region, target_service)
    except ValueError as err:
        raise HTTPException(422, str(err)) from None

    # Branch 1: Shared host GCP project.
    if settings.gcp_project_id and target_project == settings.gcp_project_id:
        if not _caller_host_allowed(settings, user):
            raise HTTPException(403, "Signed-in account is not authorized for the host project.")
        if target_region != settings.gcp_region:
            raise HTTPException(403, "Requested region is not configured for the host project.")
        allowed_services = _discover_host_services(request)
        if target_service not in allowed_services:
            raise HTTPException(403, "Requested service is not in the authorized host allowlist.")
        return AuthorizedTarget(
            project_id=target_project,
            region=target_region,
            service_name=target_service,
            kind="host",
            owner_sub=user.sub if user else None,
            billing_applicable=bool(settings.dashboard_billing_table),
            allowed_sources=("bigquery", "monitoring", "local"),
            delegation_status="host_project",
        )

    # Branch 2: Per-user onboarded project -> requires signed-in user AND exact owner match.
    if user is None:
        raise HTTPException(401, "User sign-in is required to access onboarded cloud projects.")
    store = resolve_tenant_store(request)
    record = store.get_project(user.sub, target_project)
    if record is None:
        raise HTTPException(403, "Requested GCP project is not onboarded for the signed-in user.")
    if target_region != record.region:
        raise HTTPException(403, "Requested region does not match the onboarded project region.")
    if record.services and target_service not in record.services:
        raise HTTPException(403, "Requested service is not registered for this onboarded project.")
    # A stored delegation record is not ongoing user authorisation. Check the
    # user's identity and live IAM again before serving even cached observations.
    from app.api.auth_projects import _check_user_ownership
    _check_user_ownership(request, target_project, user)
    if not request.headers.get("x-autocloud-gcp-access-token", "").strip():
        raise HTTPException(403, "A current user-bound Google access token is required.")
    return AuthorizedTarget(
        project_id=target_project,
        region=target_region,
        service_name=target_service,
        kind="onboarded",
        owner_sub=user.sub,
        billing_applicable=False,
        allowed_sources=("monitoring",),
        delegation_status=record.status,
    )
