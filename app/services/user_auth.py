"""User sign-in, Google OAuth 2.0 PKCE / OIDC verification, and signed session tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Literal
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field


class AuthenticatedUser(BaseModel):
    """Verified signed-in user identity (separate from Cloud Run caller SA principal)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    sub: str = Field(min_length=1, max_length=256)
    email: str = Field(min_length=3, max_length=320)
    email_verified: Literal[True] = True
    name: str | None = Field(default=None, max_length=160)
    auth_provider: Literal["google_oauth", "google_oidc", "dev_local"]
    exp: int


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64u_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("ascii"))


def _sign_payload(payload: dict, secret: str) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = _b64u_encode(body)
    sig = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64u_encode(sig)}"


def _verify_payload(token: str, secret: str, *, now: float | None = None) -> dict:
    if not isinstance(token, str) or "." not in token:
        raise ValueError("Invalid signed token format")
    parts = token.split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("Invalid signed token structure")
    encoded, provided_sig = parts
    expected_sig = _b64u_encode(
        hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(provided_sig, expected_sig):
        raise ValueError("Invalid token signature")
    payload = json.loads(_b64u_decode(encoded).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Malformed token payload")
    exp = payload.get("exp")
    check_now = time.time() if now is None else now
    if not isinstance(exp, (int, float)) or exp <= check_now:
        raise ValueError("Token expired")
    return payload


def resolve_session_secret(app) -> str:
    """Return configured secret or an ephemeral CSPRNG per-process secret for dev/test."""
    settings = app.state.settings
    if settings.dashboard_session_secret:
        return settings.dashboard_session_secret
    cached = getattr(app.state, "ephemeral_session_secret", None)
    if not cached:
        cached = secrets.token_urlsafe(48)
        app.state.ephemeral_session_secret = cached
    return cached


def sign_user_session(
    *,
    sub: str,
    email: str,
    name: str | None = None,
    auth_provider: Literal["google_oauth", "google_oidc", "dev_local"],
    secret: str,
    ttl_seconds: int = 3600,
    now: float | None = None,
) -> str:
    if not isinstance(sub, str) or not sub.strip():
        raise ValueError("Subject claim is required")
    if not isinstance(email, str) or "@" not in email:
        raise ValueError("Verified email is required")
    issued = int(time.time() if now is None else now)
    payload = {
        "sub": sub.strip(),
        "email": email.strip().lower(),
        "email_verified": True,
        "name": name.strip() if isinstance(name, str) and name.strip() else None,
        "auth_provider": auth_provider,
        "iat": issued,
        "exp": issued + ttl_seconds,
        "typ": "autocloud_user_session",
    }
    return _sign_payload(payload, secret)


def verify_user_session(token: str, secret: str, *, now: float | None = None) -> AuthenticatedUser:
    payload = _verify_payload(token, secret, now=now)
    if payload.get("typ") != "autocloud_user_session" or payload.get("email_verified") is not True:
        raise ValueError("Invalid session claims")
    return AuthenticatedUser(
        sub=payload["sub"],
        email=payload["email"],
        email_verified=True,
        name=payload.get("name"),
        auth_provider=payload["auth_provider"],
        exp=int(payload["exp"]),
    )


def verify_google_user_id_token(token: str, client_id: str, *, nonce: str | None = None) -> AuthenticatedUser:
    """Cryptographically verify a Google OIDC user ID token."""
    from google.auth.transport.requests import Request as AuthRequest
    from google.oauth2 import id_token

    if not isinstance(token, str) or not client_id:
        raise ValueError("Missing Google ID token or OAuth client ID")
    if token.endswith(".SIGNATURE_REMOVED_BY_GOOGLE"):
        raise ValueError("Redacted OIDC token rejected")
    claims = id_token.verify_oauth2_token(
        token, AuthRequest(), audience=client_id, clock_skew_in_seconds=30,
    )
    if claims.get("iss") not in {"https://accounts.google.com", "accounts.google.com"}:
        raise ValueError("Unexpected OIDC issuer")
    if claims.get("aud") != client_id:
        raise ValueError("Unexpected OIDC audience")
    if claims.get("email_verified") is not True:
        raise ValueError("Google account email is not verified")
    if nonce is not None and claims.get("nonce") != nonce:
        raise ValueError("OIDC nonce mismatch")
    sub = claims.get("sub")
    email = claims.get("email")
    if not isinstance(sub, str) or not sub.strip() or not isinstance(email, str) or "@" not in email:
        raise ValueError("Missing verified user subject or email")
    return AuthenticatedUser(
        sub=sub.strip(),
        email=email.strip().lower(),
        email_verified=True,
        name=claims.get("name"),
        auth_provider="google_oauth",
        exp=int(claims.get("exp", time.time() + 3600)),
    )


def build_google_oauth_request(
    *,
    client_id: str,
    redirect_uri: str,
    secret: str,
    ttl_seconds: int = 600,
    now: float | None = None,
) -> dict:
    """Create a Google OAuth 2.0 + PKCE S256 authorization URL with signed single-use state."""
    code_verifier = secrets.token_urlsafe(48)
    code_challenge = _b64u_encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
    nonce = secrets.token_urlsafe(24)
    jti = secrets.token_hex(16)
    issued = int(time.time() if now is None else now)

    # Seal verifier with HMAC-derived keystream so state works across serverless instances.
    key = hashlib.sha256((secret + "|pkce|" + jti).encode("utf-8")).digest()
    verifier_bytes = code_verifier.encode("ascii")
    stream = (key * ((len(verifier_bytes) // len(key)) + 1))[: len(verifier_bytes)]
    sealed_verifier = _b64u_encode(bytes(a ^ b for a, b in zip(verifier_bytes, stream)))

    state = _sign_payload(
        {
            "typ": "oauth_pkce_state",
            "jti": jti,
            "nonce": nonce,
            "redirect_uri": redirect_uri,
            "sv": sealed_verifier,
            "exp": issued + ttl_seconds,
        },
        secret,
    )
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join([
            "openid",
            "email",
            "profile",
            "https://www.googleapis.com/auth/monitoring.read",
            "https://www.googleapis.com/auth/cloudplatformprojects.readonly",
            "https://www.googleapis.com/auth/cloud-platform.read-only",
        ]),
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "online",
        "prompt": "select_account",
    }
    return {
        "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params),
        "state": state,
        "expires_at": issued + ttl_seconds,
    }


def unseal_oauth_state(
    state: str,
    *,
    secret: str,
    expected_redirect_uri: str,
    consumed_jti_checker=None,
    now: float | None = None,
) -> tuple[str, str]:
    """Verify signed OAuth state, enforce single-use nonce if provided, and unseal PKCE verifier."""
    payload = _verify_payload(state, secret, now=now)
    if payload.get("typ") != "oauth_pkce_state" or payload.get("redirect_uri") != expected_redirect_uri:
        raise ValueError("Invalid OAuth state")
    jti = payload["jti"]
    if consumed_jti_checker is not None and not consumed_jti_checker(jti, int(payload["exp"])):
        raise ValueError("OAuth state already consumed")
    sealed = _b64u_decode(payload["sv"])
    key = hashlib.sha256((secret + "|pkce|" + jti).encode("utf-8")).digest()
    stream = (key * ((len(sealed) // len(key)) + 1))[: len(sealed)]
    code_verifier = bytes(a ^ b for a, b in zip(sealed, stream)).decode("ascii")
    return code_verifier, str(payload["nonce"])


def exchange_google_oauth_code(
    *,
    code: str,
    code_verifier: str,
    client_id: str,
    client_secret: str | None,
    redirect_uri: str,
    expected_nonce: str,
    token_verifier=None,
) -> dict:
    """Exchange OAuth authorization code for verified user identity and memory-only access token."""
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    if client_secret:
        form["client_secret"] = client_secret
    with httpx.Client(timeout=20.0, trust_env=False) as client:
        resp = client.post("https://oauth2.googleapis.com/token", data=form)
        if resp.status_code != 200:
            raise ValueError("Google OAuth token exchange failed")
        tokens = resp.json()
    raw_id_token = tokens.get("id_token")
    if not raw_id_token:
        raise ValueError("Google OAuth response did not include id_token")
    verifier = token_verifier or verify_google_user_id_token
    user = verifier(raw_id_token, client_id, nonce=expected_nonce)
    return {
        "user": user,
        "gcp_access_token": tokens.get("access_token"),
        "expires_in": int(tokens.get("expires_in", 3600)),
    }


def extract_optional_user(request: Request) -> AuthenticatedUser | None:
    """Verify X-AutoCloud-User-Session if sent; reject invalid or tampered tokens cleanly."""
    header = request.headers.get("x-autocloud-user-session", "").strip()
    if not header:
        return None
    token = header[7:].strip() if header.lower().startswith("bearer ") else header
    custom_verifier = getattr(request.app.state, "user_session_verifier", None)
    try:
        if custom_verifier is not None:
            return custom_verifier(token)
        secret = resolve_session_secret(request.app)
        return verify_user_session(token, secret)
    except Exception:
        raise HTTPException(401, "Invalid or expired user session.") from None


def require_authenticated_user(request: Request) -> AuthenticatedUser:
    """Require a cryptographically verified user session."""
    user = extract_optional_user(request)
    if user is None:
        raise HTTPException(401, "User sign-in is required.")
    return user


def verify_access_token_subject(token: str, user: AuthenticatedUser) -> None:
    """Bind the caller's Google resource token to their verified login identity."""
    with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
        response = client.get("https://openidconnect.googleapis.com/v1/userinfo",
                              headers={"Authorization": "Bearer " + token})
    if response.status_code != 200:
        raise ValueError("Cloud token identity could not be verified")
    info = response.json()
    if (info.get("sub") != user.sub or info.get("email_verified") is not True
            or str(info.get("email", "")).lower() != user.email.lower()):
        raise ValueError("Cloud token does not belong to the signed-in user")
