"""User sign-in, authorized resource listing, and keyless per-user GCP onboarding."""

from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.services.resource_registry import list_authorized_resources, resolve_tenant_store
from app.services.tenant_store import (
    ForbiddenCredentialInput,
    OnboardedProject,
    OnboardProjectRequest,
    REQUIRED_USER_PERMISSIONS,
    contains_forbidden_key_material,
    gcp_discover_run_services,
    gcp_test_iam_permissions,
    keyless_iam_commands,
    validate_project_target,
)
from app.services.user_auth import (
    AuthenticatedUser,
    build_google_oauth_request,
    exchange_google_oauth_code,
    extract_optional_user,
    require_authenticated_user,
    resolve_session_secret,
    sign_user_session,
    unseal_oauth_state,
    verify_google_user_id_token,
)

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])
resources_router = APIRouter(prefix="/api", tags=["resources"])
projects_router = APIRouter(
    prefix="/api/projects",
    tags=["projects"],
    dependencies=[Depends(require_authenticated_user)],
)


class DevLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    email: str = Field(min_length=3, max_length=320)
    name: str | None = Field(default=None, max_length=120)


class OAuthCallbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    code: str = Field(min_length=4, max_length=2048)
    state: str = Field(min_length=8, max_length=4096)


class GoogleTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id_token: str = Field(min_length=20, max_length=8192)


def _reject_browser_origin(request: Request) -> None:
    if request.headers.get("origin") is not None:
        raise HTTPException(403, "Use the authenticated dashboard control.")


def _reader_service_account(request: Request) -> str:
    custom = getattr(request.app.state, "reader_service_account", None)
    if custom:
        return custom
    settings = request.app.state.settings
    if settings.gcp_project_id:
        return f"autocloud-api-reader@{settings.gcp_project_id}.iam.gserviceaccount.com"
    return "autocloud-api-reader@autocloud-project.iam.gserviceaccount.com"


def _check_sa_delegation(request: Request, project_id: str) -> tuple[str, ...]:
    checker = getattr(request.app.state, "sa_permission_checker", None)
    if checker is not None:
        return tuple(checker(project_id, REQUIRED_USER_PERMISSIONS))
    try:
        import google.auth
        from google.auth.transport.requests import Request as AuthRequest

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(AuthRequest())
        return tuple(gcp_test_iam_permissions(project_id, creds.token, REQUIRED_USER_PERMISSIONS))
    except Exception:
        return ()


def _check_user_ownership(request: Request, project_id: str, user: AuthenticatedUser) -> tuple[str, ...]:
    user_gcp_token = request.headers.get("x-autocloud-gcp-access-token", "").strip()
    verifier = getattr(request.app.state, "user_project_verifier", None)
    if verifier is not None:
        perms = tuple(verifier(user, project_id, user_gcp_token, REQUIRED_USER_PERMISSIONS))
        if not set(REQUIRED_USER_PERMISSIONS).issubset(perms):
            raise HTTPException(
                403,
                "Signed-in user could not be verified as having GCP Monitoring/Run permissions on this project.",
            )
        return perms
    if not user_gcp_token:
        raise HTTPException(
            403,
            "Sign in with Google OAuth read-only Cloud permissions to verify project ownership (no keys accepted).",
        )
    from app.services.user_auth import verify_access_token_subject
    try:
        verify_access_token_subject(user_gcp_token, user)
    except Exception:
        raise HTTPException(403, "Cloud token must belong to the signed-in Google account.") from None
    perms = tuple(gcp_test_iam_permissions(project_id, user_gcp_token, REQUIRED_USER_PERMISSIONS))
    if not set(REQUIRED_USER_PERMISSIONS).issubset(perms):
        raise HTTPException(
            403,
            "Signed-in user lacks Monitoring/Run viewer permission on the target GCP project.",
        )
    return perms


def _discover_project_services(request: Request, project_id: str, region: str) -> tuple[str, ...]:
    discoverer = getattr(request.app.state, "project_service_discoverer", None)
    user_gcp_token = request.headers.get("x-autocloud-gcp-access-token", "").strip()
    if discoverer is not None:
        return tuple(discoverer(project_id, region, user_gcp_token))
    if user_gcp_token:
        found = gcp_discover_run_services(project_id, region, user_gcp_token)
        if found:
            return tuple(found)
    try:
        import google.auth
        from google.auth.transport.requests import Request as AuthRequest

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(AuthRequest())
        return tuple(gcp_discover_run_services(project_id, region, creds.token))
    except Exception:
        return ()


@auth_router.get("/session")
def auth_session(request: Request) -> dict:
    _reject_browser_origin(request)
    settings = request.app.state.settings
    user = extract_optional_user(request)
    return {
        "signed_in": user is not None,
        "user": user.model_dump() if user is not None else None,
        "user_auth_required": settings.dashboard_user_auth_required,
        "google_oauth_enabled": bool(settings.google_oauth_client_id and settings.dashboard_oauth_redirect_uri),
        "dev_login_enabled": bool(settings.environment != "production" and settings.dashboard_allow_dev_login),
    }


@auth_router.get("/login")
def oauth_login_url(request: Request) -> dict:
    _reject_browser_origin(request)
    settings = request.app.state.settings
    if not settings.google_oauth_client_id or not settings.dashboard_oauth_redirect_uri:
        raise HTTPException(409, "Google OAuth client ID and redirect URI are not configured.")
    secret = resolve_session_secret(request.app)
    return build_google_oauth_request(
        client_id=settings.google_oauth_client_id,
        redirect_uri=settings.dashboard_oauth_redirect_uri,
        secret=secret,
    )


@auth_router.post("/callback")
def oauth_callback(body: OAuthCallbackRequest, request: Request) -> dict:
    _reject_browser_origin(request)
    settings = request.app.state.settings
    if not settings.google_oauth_client_id or not settings.dashboard_oauth_redirect_uri:
        raise HTTPException(409, "Google OAuth is not configured.")
    secret = resolve_session_secret(request.app)
    store = resolve_tenant_store(request)
    try:
        verifier_pkce, expected_nonce = unseal_oauth_state(
            body.state,
            secret=secret,
            expected_redirect_uri=settings.dashboard_oauth_redirect_uri,
            consumed_jti_checker=store.consume_oauth_nonce,
        )
        exchanger = getattr(request.app.state, "oauth_code_exchanger", None) or exchange_google_oauth_code
        result = exchanger(
            code=body.code,
            code_verifier=verifier_pkce,
            client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret,
            redirect_uri=settings.dashboard_oauth_redirect_uri,
            expected_nonce=expected_nonce,
        )
    except Exception:
        raise HTTPException(403, "Google OAuth callback could not be verified.") from None
    user: AuthenticatedUser = result["user"]
    session_token = sign_user_session(
        sub=user.sub,
        email=user.email,
        name=user.name,
        auth_provider="google_oauth",
        secret=secret,
        ttl_seconds=min(int(result.get("expires_in", 3600)), 3600),
    )
    return {
        "session_token": session_token,
        "user": user.model_dump(),
        "gcp_access_token": result.get("gcp_access_token"),
        "expires_in": int(result.get("expires_in", 3600)),
        "storage_note": "Session token only proves signed-in identity; no service-account keys are stored.",
    }


@auth_router.post("/google-token")
def google_id_token_login(body: GoogleTokenRequest, request: Request) -> dict:
    _reject_browser_origin(request)
    settings = request.app.state.settings
    if not settings.google_oauth_client_id:
        raise HTTPException(409, "Google OAuth client ID is not configured.")
    verifier = getattr(request.app.state, "google_id_token_verifier", None) or verify_google_user_id_token
    try:
        user = verifier(body.id_token, settings.google_oauth_client_id)
    except Exception:
        raise HTTPException(403, "Invalid or unverified Google ID token.") from None
    secret = resolve_session_secret(request.app)
    session_token = sign_user_session(
        sub=user.sub,
        email=user.email,
        name=user.name,
        auth_provider="google_oidc",
        secret=secret,
    )
    return {"session_token": session_token, "user": user.model_dump()}


@auth_router.post("/dev-login")
def dev_login(body: DevLoginRequest, request: Request) -> dict:
    _reject_browser_origin(request)
    settings = request.app.state.settings
    if settings.environment == "production" or not settings.dashboard_allow_dev_login:
        raise HTTPException(403, "Local development sign-in is disabled.")
    email = body.email.strip().lower()
    if "@" not in email or "." not in email.split("@", 1)[-1]:
        raise HTTPException(422, "Valid email address required.")
    secret = resolve_session_secret(request.app)
    sub = f"dev:{email}"
    session_token = sign_user_session(
        sub=sub,
        email=email,
        name=body.name or email.split("@", 1)[0],
        auth_provider="dev_local",
        secret=secret,
    )
    user = AuthenticatedUser(
        sub=sub,
        email=email,
        name=body.name or email.split("@", 1)[0],
        auth_provider="dev_local",
        exp=int(datetime.now(timezone.utc).timestamp()) + 3600,
    )
    return {"session_token": session_token, "user": user.model_dump()}


@resources_router.get("/resources")
def list_resources(request: Request) -> dict:
    _reject_browser_origin(request)
    settings = request.app.state.settings
    user = extract_optional_user(request)
    if settings.dashboard_user_auth_required and user is None:
        raise HTTPException(401, "User sign-in is required.")
    return {
        "user": user.model_dump() if user is not None else None,
        "reader_service_account": _reader_service_account(request),
        "execution_allowed": False,
        "key_uploads_accepted": False,
        "resources": list_authorized_resources(request, user),
    }


@projects_router.get("")
def list_user_projects(request: Request, user: AuthenticatedUser = Depends(require_authenticated_user)) -> dict:
    _reject_browser_origin(request)
    store = resolve_tenant_store(request)
    reader_sa = _reader_service_account(request)
    projects = store.list_projects(user.sub)
    return {
        "owner_sub": user.sub,
        "owner_email": user.email,
        "reader_service_account": reader_sa,
        "key_uploads_accepted": False,
        "execution_allowed": False,
        "projects": [
            {
                **p.model_dump(),
                "setup_commands": keyless_iam_commands(p.project_id, reader_sa)
                if p.status != "verified_active" else [],
            }
            for p in projects
        ],
    }


@projects_router.post("/onboard")
async def onboard_project(request: Request, user: AuthenticatedUser = Depends(require_authenticated_user)) -> dict:
    _reject_browser_origin(request)
    try:
        raw_body = await request.json()
    except Exception:
        raise HTTPException(400, "Valid JSON body required.") from None
    if contains_forbidden_key_material(raw_body):
        raise HTTPException(
            400,
            "Service-account private keys or credential JSONs are never accepted; use keyless IAM delegation.",
        )
    try:
        body = OnboardProjectRequest.model_validate(raw_body)
    except Exception as err:
        raise HTTPException(422, str(err)) from None

    settings = request.app.state.settings
    if settings.gcp_project_id and body.project_id == settings.gcp_project_id:
        raise HTTPException(409, "Host project resources are managed automatically by server configuration.")

    user_perms = _check_user_ownership(request, body.project_id, user)
    sa_perms = _check_sa_delegation(request, body.project_id)
    discovered = list(_discover_project_services(request, body.project_id, body.region))
    if body.cloud_run_service and body.cloud_run_service not in discovered:
        discovered.append(body.cloud_run_service)
    services = tuple(sorted(set(discovered)))

    status = "verified_active" if set(REQUIRED_USER_PERMISSIONS).issubset(sa_perms) else "pending_iam_delegation"
    now = datetime.now(timezone.utc).isoformat()
    store = resolve_tenant_store(request)
    existing = store.get_project(user.sub, body.project_id)
    record = OnboardedProject(
        owner_sub=user.sub,
        owner_email=user.email,
        project_id=body.project_id,
        region=body.region,
        display_name=body.display_name or body.project_id,
        auth_method="keyless_iam_delegation",
        status=status,
        verified_permissions=user_perms,
        sa_delegated_permissions=sa_perms,
        services=services,
        created_at=existing.created_at if existing else now,
        updated_at=now,
        verified_at=now if status == "verified_active" else None,
    )
    store.upsert_project(record)
    reader_sa = _reader_service_account(request)
    return {
        "project": record.model_dump(),
        "setup_commands": keyless_iam_commands(record.project_id, reader_sa)
        if status != "verified_active" else [],
        "key_uploads_accepted": False,
        "execution_allowed": False,
    }


@projects_router.post("/{project_id}/verify")
def verify_onboarded_project(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_authenticated_user),
) -> dict:
    _reject_browser_origin(request)
    try:
        validate_project_target(project_id, "asia-south1")
    except ValueError as err:
        raise HTTPException(422, str(err)) from None
    store = resolve_tenant_store(request)
    existing = store.get_project(user.sub, project_id)
    if existing is None:
        raise HTTPException(404, "Onboarded project not found for signed-in user.")
    user_perms = _check_user_ownership(request, project_id, user)
    sa_perms = _check_sa_delegation(request, project_id)
    discovered = tuple(sorted(set([*existing.services, *_discover_project_services(request, project_id, existing.region)])))
    status = "verified_active" if set(REQUIRED_USER_PERMISSIONS).issubset(sa_perms) else "pending_iam_delegation"
    now = datetime.now(timezone.utc).isoformat()
    updated = existing.model_copy(update={
        "status": status,
        "verified_permissions": user_perms,
        "sa_delegated_permissions": sa_perms,
        "services": discovered,
        "updated_at": now,
        "verified_at": now if status == "verified_active" else existing.verified_at,
    })
    store.upsert_project(updated)
    reader_sa = _reader_service_account(request)
    return {
        "project": updated.model_dump(),
        "setup_commands": keyless_iam_commands(updated.project_id, reader_sa)
        if status != "verified_active" else [],
        "execution_allowed": False,
    }


@projects_router.delete("/{project_id}")
def revoke_onboarded_project(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_authenticated_user),
) -> dict:
    _reject_browser_origin(request)
    try:
        validate_project_target(project_id, "asia-south1")
    except ValueError as err:
        raise HTTPException(422, str(err)) from None
    store = resolve_tenant_store(request)
    if not store.revoke_project(user.sub, project_id, datetime.now(timezone.utc)):
        raise HTTPException(404, "Onboarded project not found for signed-in user.")
    return {"project_id": project_id, "status": "revoked"}
