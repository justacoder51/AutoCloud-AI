"""Local and authenticated Cloud Storage review workflow; never authorizes an executor."""

import sqlite3
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.agents.recommendation_agent import RecommendationPlan
from app.services.dashboard_service import overview
from app.services.resource_registry import authorize_target
from app.services.review_store import CloudReviewStore, ReviewConflict, ReviewStore

try:
    from google.api_core.exceptions import GoogleAPIError
except ImportError:  # pragma: no cover - minimal API-only installs without GCS/BQ SDKs
    GoogleAPIError = ()


def verify_oidc_principal(token: str, audience: str | None = None) -> str:
    """Cryptographically verify a Google OIDC ID token and return its verified email claim."""
    from google.auth.transport.requests import Request as AuthRequest
    from google.oauth2 import id_token

    if not isinstance(token, str) or not token.strip():
        raise ValueError("Missing OIDC token")
    parts = token.split(".")
    if len(parts) != 3 or not parts[2] or token.endswith(".SIGNATURE_REMOVED_BY_GOOGLE"):
        raise ValueError("Unsigned or redacted token rejected")
    if not audience:
        raise ValueError("Review audience is required for OIDC verification")
    claims = id_token.verify_oauth2_token(
        token, AuthRequest(), audience=audience, clock_skew_in_seconds=30,
    )
    if claims.get("iss") not in {"https://accounts.google.com", "accounts.google.com"}:
        raise ValueError("Unexpected token issuer")
    if claims.get("aud") != audience:
        raise ValueError("Unexpected token audience")
    if claims.get("email_verified") is not True:
        raise ValueError("Unverified token email")
    email = claims.get("email")
    if not isinstance(email, str) or "@" not in email:
        raise ValueError("Missing principal email claim")
    return email


def _parse_bearer(header_value: str) -> str:
    parts = header_value.strip().split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return ""


def extract_application_bearer_token(request: Request) -> str:
    """Resolve the intact application OIDC token and reject ambiguous or redacted edge headers."""
    has_serverless_auth = request.headers.get("x-serverless-authorization") is not None
    app_header = request.headers.get("x-autocloud-authorization", "")
    std_header = request.headers.get("authorization", "")
    app_token = _parse_bearer(app_header)
    std_token = _parse_bearer(std_header)

    if app_header.strip() and not app_token:
        raise HTTPException(403, "Invalid X-AutoCloud-Authorization header.")
    if has_serverless_auth:
        if not app_token:
            raise HTTPException(
                403,
                "Authenticated application identity token required in X-AutoCloud-Authorization.",
            )
        if std_token and (
            std_token.endswith(".SIGNATURE_REMOVED_BY_GOOGLE") or std_token != app_token
        ):
            raise HTTPException(403, "Ambiguous authorization headers.")
        return app_token
    if app_token:
        if std_token:
            if std_token.endswith(".SIGNATURE_REMOVED_BY_GOOGLE"):
                if "." in app_token and std_token.rsplit(".", 1)[0] != app_token.rsplit(".", 1)[0]:
                    raise HTTPException(403, "Mismatched authorization headers.")
            elif std_token != app_token:
                raise HTTPException(403, "Mismatched authorization headers.")
        return app_token
    if std_token:
        if std_token.endswith(".SIGNATURE_REMOVED_BY_GOOGLE"):
            raise HTTPException(
                403,
                "Redacted edge token cannot verify application identity; send X-AutoCloud-Authorization.",
            )
        return std_token
    raise HTTPException(403, "Authenticated Cloud Run identity token required.")


def review_access(request: Request) -> str | None:
    """Enforce either authenticated Cloud Run OIDC access or loopback-only local access."""
    if request.headers.get("origin") is not None:
        raise HTTPException(403, "Reviews are available only through the dashboard.")
    settings = request.app.state.settings
    if settings.dashboard_review_bucket:
        token = extract_application_bearer_token(request)
        verifier = getattr(request.app.state, "review_token_verifier", None) or verify_oidc_principal
        try:
            principal = verifier(token, settings.dashboard_review_audience)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(403, "Invalid or unverified identity token.") from None
        if not isinstance(principal, str) or "@" not in principal:
            raise HTTPException(403, "Invalid or unverified identity token.")
        request.state.calling_service_principal = principal
        request.state.authenticated_principal = principal
        return principal
    if (settings.environment == "production"
            or not request.client or request.client.host not in {"127.0.0.1", "::1", "testclient"}):
        raise HTTPException(403, "Reviews are available only through the local dashboard.")
    request.state.calling_service_principal = None
    request.state.authenticated_principal = None
    return None


router = APIRouter(prefix="/api/reviews", tags=["reviews"], dependencies=[Depends(review_access)])


class Capture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["local", "bigquery", "monitoring"]
    hours: int = Field(default=24, ge=1, le=24)
    evidence_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    project: str | None = None
    region: str | None = None
    service: str | None = None


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    decision: Literal["approved", "rejected"]
    reviewer: str = Field(min_length=1, max_length=80)
    note: str = Field(min_length=1, max_length=1000)


def store_and_scope(
    request,
    *,
    project: str | None = None,
    region: str | None = None,
    service: str | None = None,
):
    settings = request.app.state.settings
    target = authorize_target(request, project=project, region=region, service=service)
    if not target.project_id:
        raise HTTPException(409, "Configure or onboard a project before recording reviews.")
    principal = (
        getattr(request.state, "calling_service_principal", None)
        or getattr(request.state, "authenticated_principal", None)
    )
    if settings.dashboard_review_bucket:
        if not principal:
            raise HTTPException(403, "Authenticated Cloud Run identity token required.")
        store = CloudReviewStore(
            settings.gcp_project_id or target.project_id,
            settings.gcp_region or target.region,
            settings.dashboard_review_bucket,
            client=getattr(request.app.state, "review_storage_client", None),
        )
    else:
        store = ReviewStore(request.app.state.analytics_data_root / "reviews.sqlite3")
    scope = ReviewStore.scope(
        target.project_id,
        target.region,
        target.service_name,
        owner_sub=target.owner_sub,
    )
    return store, scope, principal, target


@router.get("")
def history(
    request: Request,
    project: str | None = None,
    region: str | None = None,
    service: str | None = None,
):
    store, scope, principal, target = store_and_scope(
        request, project=project, region=region, service=service,
    )
    try:
        response = {
            "items": store.history(scope, datetime.now(timezone.utc)),
            "limit": 200,
            "scope_target": {
                "project_id": target.project_id,
                "region": target.region,
                "service_name": target.service_name,
                "kind": target.kind,
                "user_isolated": target.owner_sub is not None,
            },
            "execution_allowed": False,
            "reviewer_identity": (
                "service_authenticated_self_reported_label"
                if principal else "self_reported_local_label"
            ),
            "human_reviewer_verified": False,
        }
        if principal:
            response["calling_service_principal"] = principal
            response["authenticated_principal"] = principal
        return response
    except (OSError, sqlite3.Error, GoogleAPIError, ValueError):
        raise HTTPException(503, "Review history is unavailable.") from None


@router.post("/capture")
def capture(body: Capture, request: Request):
    store, _, principal, target = store_and_scope(
        request, project=body.project, region=body.region, service=body.service,
    )
    if target.kind == "onboarded" and body.source not in target.allowed_sources:
        raise HTTPException(403, "External onboarded projects support live source=monitoring reads only.")
    now = datetime.now(timezone.utc)
    user_gcp_token = request.headers.get("x-autocloud-gcp-access-token", "").strip() or None
    query = None
    if body.source in {"bigquery", "monitoring"}:
        query = request.app.state.dashboard_history.read(
            target.project_id,
            target.region,
            target.service_name,
            body.hours,
            source=body.source,
            owner_key=target.owner_sub,
            bearer_token=user_gcp_token if target.kind == "onboarded" else None,
        )
    snapshot = overview(
        request.app.state.analytics_data_root,
        target.project_id,
        target.region,
        target.service_name,
        now,
        records=query["records"] if query else None,
        query=query,
    )
    plan = snapshot.get("recommendation_plan")
    if not plan or plan["evidence_fingerprint"] != body.evidence_fingerprint:
        raise HTTPException(409, "Evidence changed or is unavailable; refresh measurements.")
    try:
        validated = RecommendationPlan.model_validate(plan)
        capture_kwargs: dict = {}
        if principal:
            capture_kwargs["authenticated_principal"] = principal
        if target.owner_sub is not None:
            capture_kwargs["owner_sub"] = target.owner_sub
        ids = store.capture(validated, now, **capture_kwargs)
        if principal:
            return {
                "saved_ids": ids,
                "execution_allowed": False,
                "reviewer_identity": "service_authenticated_self_reported_label",
                "calling_service_principal": principal,
                "authenticated_principal": principal,
            }
        return {"saved_ids": ids, "execution_allowed": False}
    except ReviewConflict as error:
        raise HTTPException(409, str(error)) from None
    except (OSError, sqlite3.Error, GoogleAPIError, ValueError):
        raise HTTPException(503, "Recommendations could not be saved.") from None


@router.post("/{identifier}/decision")
def decide(
    identifier: str,
    body: Decision,
    request: Request,
    project: str | None = None,
    region: str | None = None,
    service: str | None = None,
):
    store, scope, principal, _ = store_and_scope(
        request, project=project, region=region, service=service,
    )
    try:
        if principal:
            store.decide(
                scope, identifier, body.decision, body.reviewer, body.note,
                datetime.now(timezone.utc), authenticated_principal=principal,
            )
            return {
                "status": body.decision,
                "execution_allowed": False,
                "reviewer_identity": "service_authenticated_self_reported_label",
                "calling_service_principal": principal,
                "authenticated_principal": principal,
            }
        store.decide(scope, identifier, body.decision, body.reviewer, body.note, datetime.now(timezone.utc))
        return {"status": body.decision, "execution_allowed": False}
    except KeyError:
        raise HTTPException(404, "Saved recommendation not found.") from None
    except ReviewConflict as error:
        raise HTTPException(409, str(error)) from None
    except (OSError, sqlite3.Error, GoogleAPIError, ValueError):
        raise HTTPException(503, "Decision could not be saved.") from None
