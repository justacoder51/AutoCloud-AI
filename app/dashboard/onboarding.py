"""User sign-in, authorized resource selector, and keyless GCP project onboarding controls."""

from __future__ import annotations

import httpx
import hmac
import streamlit as st


def build_request_headers(base_headers: dict[str, str]) -> dict[str, str]:
    """Combine Cloud Run service headers with in-memory signed-in user headers."""
    headers = dict(base_headers)
    user_token = st.session_state.get("user_session_token")
    if isinstance(user_token, str) and user_token:
        headers["X-AutoCloud-User-Session"] = user_token
    gcp_token = st.session_state.get("user_gcp_access_token")
    if isinstance(gcp_token, str) and gcp_token:
        headers["X-AutoCloud-GCP-Access-Token"] = gcp_token
    return headers


def _handle_oauth_query_params(api_url: str, base_headers: dict[str, str]) -> None:
    try:
        qp = st.query_params
        code = qp.get("code")
        state = qp.get("state")
    except Exception:
        return
    if not code or not state or st.session_state.get("oauth_handled_state") == state:
        return
    pending = st.session_state.get("oauth_pending_request") or {}
    if not isinstance(pending.get("state"), str) or not hmac.compare_digest(str(state), pending["state"]):
        st.sidebar.error("OAuth callback does not match sign-in started in this browser session.")
        st.query_params.clear()
        return
    st.session_state["oauth_handled_state"] = state
    try:
        with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
            resp = client.post(
                f"{api_url}/api/auth/callback",
                headers=base_headers,
                json={"code": str(code), "state": str(state)},
            )
            resp.raise_for_status()
            payload = resp.json()
        st.session_state["user_session_token"] = payload["session_token"]
        st.session_state["user_profile"] = payload.get("user")
        if payload.get("gcp_access_token"):
            st.session_state["user_gcp_access_token"] = payload["gcp_access_token"]
        st.query_params.clear()
        st.rerun()
    except (httpx.HTTPError, ValueError, KeyError):
        st.sidebar.error("Google OAuth sign-in callback could not be verified.")


def _fetch_session_info(api_url: str, headers: dict[str, str]) -> dict | None:
    try:
        with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
            resp = client.get(f"{api_url}/api/auth/session", headers=headers)
            if resp.status_code != 200:
                return None
            payload = resp.json()
            if isinstance(payload, dict) and "user_auth_required" in payload:
                return payload
    except (httpx.HTTPError, ValueError):
        return None
    return None


def _fetch_resources_info(api_url: str, headers: dict[str, str]) -> dict | None:
    try:
        with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
            resp = client.get(f"{api_url}/api/resources", headers=headers)
            if resp.status_code != 200:
                return None
            payload = resp.json()
            if isinstance(payload, dict) and isinstance(payload.get("resources"), list):
                return payload
    except (httpx.HTTPError, ValueError):
        return None
    return None


def _sign_out() -> None:
    for key in (
        "user_session_token",
        "user_gcp_access_token",
        "user_profile",
        "review_history",
        "ai_analysis_result",
        "billing_result",
        "oauth_pending_request",
        "onboarded_projects_cache",
    ):
        st.session_state.pop(key, None)


def _render_sign_in_controls(api_url: str, base_headers: dict[str, str], session_info: dict) -> None:
    if session_info.get("signed_in") and session_info.get("user"):
        user = session_info["user"]
        st.sidebar.success(f"Signed in: {user['email']}")
        st.sidebar.caption(f"Isolation: strict per-user · Method: {user.get('auth_provider', 'oidc')}")
        if st.sidebar.button("Sign out"):
            _sign_out()
            st.rerun()
        return

    if st.session_state.get("user_session_token"):
        _sign_out()

    if session_info.get("google_oauth_enabled"):
        if st.sidebar.button("Start Google OAuth Sign-In"):
            try:
                with httpx.Client(timeout=20, trust_env=False, follow_redirects=False) as client:
                    resp = client.get(f"{api_url}/api/auth/login", headers=base_headers)
                    resp.raise_for_status()
                    st.session_state["oauth_pending_request"] = resp.json()
            except (httpx.HTTPError, ValueError):
                st.sidebar.error("Could not start Google OAuth flow.")
        pending = st.session_state.get("oauth_pending_request")
        if pending and pending.get("authorization_url"):
            st.sidebar.link_button("Continue with Google OAuth", pending["authorization_url"])
        with st.sidebar.expander("Complete OAuth callback manually", expanded=False):
            oauth_code = st.text_input("Authorization code", key="oauth_manual_code")
            oauth_state = st.text_input("State parameter", key="oauth_manual_state")
            if st.button("Verify OAuth code") and oauth_code and oauth_state:
                expected = (st.session_state.get("oauth_pending_request") or {}).get("state")
                if not isinstance(expected, str) or not hmac.compare_digest(oauth_state.strip(), expected):
                    st.error("OAuth state does not match this browser's pending sign-in.")
                    return
                try:
                    with httpx.Client(timeout=20, trust_env=False, follow_redirects=False) as client:
                        resp = client.post(
                            f"{api_url}/api/auth/callback",
                            headers=base_headers,
                            json={"code": oauth_code.strip(), "state": oauth_state.strip()},
                        )
                        resp.raise_for_status()
                        payload = resp.json()
                    st.session_state["user_session_token"] = payload["session_token"]
                    st.session_state["user_profile"] = payload.get("user")
                    if payload.get("gcp_access_token"):
                        st.session_state["user_gcp_access_token"] = payload["gcp_access_token"]
                    st.rerun()
                except (httpx.HTTPError, ValueError, KeyError):
                    st.error("Google OAuth verification failed.")

    if session_info.get("dev_login_enabled"):
        with st.sidebar.expander("Local dev sign-in (non-production only)", expanded=False):
            with st.form("dev_login_form"):
                email = st.text_input("Work or Google email", placeholder="engineer@example.com")
                display_name = st.text_input("Display name", placeholder="Cloud Engineer")
                submit_dev = st.form_submit_button("Sign in locally")
            if submit_dev and email.strip():
                try:
                    with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
                        resp = client.post(
                            f"{api_url}/api/auth/dev-login",
                            headers=base_headers,
                            json={"email": email.strip(), "name": display_name.strip() or None},
                        )
                        resp.raise_for_status()
                        payload = resp.json()
                    st.session_state["user_session_token"] = payload["session_token"]
                    st.session_state["user_profile"] = payload.get("user")
                    st.rerun()
                except (httpx.HTTPError, ValueError):
                    st.error("Local dev sign-in was rejected by the API.")


def _render_keyless_onboarding_expander(
    api_url: str,
    headers: dict[str, str],
    reader_sa: str,
) -> None:
    with st.sidebar.expander("Onboard GCP project (keyless)", expanded=False):
        st.caption(
            "Keyless IAM delegation only. Service-account private keys or credential JSON files are NEVER requested or accepted."
        )
        with st.form("keyless_project_onboarding"):
            proj_id = st.text_input("GCP Project ID", placeholder="my-app-prod-123")
            region = st.text_input("Cloud Run region", value="asia-south1")
            service_name = st.text_input("Cloud Run service name (optional)", placeholder="my-service")
            display_name = st.text_input("Display label (optional)", placeholder="Payments API")
            onboard_submit = st.form_submit_button("Verify & register project")
        if onboard_submit:
            if not proj_id.strip():
                st.warning("Provide a valid GCP Project ID.")
            else:
                body = {
                    "project_id": proj_id.strip(),
                    "region": region.strip() or "asia-south1",
                    "display_name": display_name.strip() or None,
                    "cloud_run_service": service_name.strip() or None,
                }
                try:
                    with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
                        resp = client.post(f"{api_url}/api/projects/onboard", headers=headers, json=body)
                    if resp.status_code >= 400:
                        detail = resp.json().get("detail", "Project onboarding rejected.")
                        st.error(detail)
                    else:
                        result = resp.json()
                        st.session_state["last_onboarded_project"] = result
                        st.success(f"Registered {result['project']['project_id']} ({result['project']['status']}).")
                        st.rerun()
                except (httpx.HTTPError, ValueError):
                    st.error("Onboarding API request failed.")

        if reader_sa:
            st.caption(f"Reader service account (read-only IAM only): `{reader_sa}`")
        if st.button("List my onboarded projects"):
            try:
                with httpx.Client(timeout=20, trust_env=False, follow_redirects=False) as client:
                    resp = client.get(f"{api_url}/api/projects", headers=headers)
                    resp.raise_for_status()
                    st.session_state["onboarded_projects_cache"] = resp.json()
            except (httpx.HTTPError, ValueError):
                st.error("Could not load onboarded projects.")

        cached = st.session_state.get("onboarded_projects_cache") or {}
        for proj in cached.get("projects", []):
            pid = proj["project_id"]
            st.write(f"**{proj.get('display_name', pid)}** (`{pid}`) — `{proj['status']}`")
            if proj.get("setup_commands"):
                st.code("\n".join(proj["setup_commands"]), language="bash")
            col_a, col_b = st.columns(2)
            if col_a.button("Re-verify IAM", key=f"verify_{pid}"):
                try:
                    with httpx.Client(timeout=25, trust_env=False, follow_redirects=False) as client:
                        resp = client.post(f"{api_url}/api/projects/{pid}/verify", headers=headers)
                        resp.raise_for_status()
                    st.session_state.pop("onboarded_projects_cache", None)
                    st.rerun()
                except (httpx.HTTPError, ValueError):
                    st.error(f"Verification failed for {pid}.")
            if col_b.button("Revoke", key=f"revoke_{pid}"):
                try:
                    with httpx.Client(timeout=20, trust_env=False, follow_redirects=False) as client:
                        resp = client.delete(f"{api_url}/api/projects/{pid}", headers=headers)
                        resp.raise_for_status()
                    st.session_state.pop("onboarded_projects_cache", None)
                    st.rerun()
                except (httpx.HTTPError, ValueError):
                    st.error(f"Revocation failed for {pid}.")


def render_sidebar_auth_and_resources(
    api_url: str,
    base_headers: dict[str, str],
) -> tuple[dict[str, str], dict | None, dict | None]:
    """Render sidebar sign-in, authorized resource picker, and keyless onboarding."""
    _handle_oauth_query_params(api_url, base_headers)
    headers = build_request_headers(base_headers)
    session_info = _fetch_session_info(api_url, headers)
    if session_info is not None:
        st.sidebar.header("Account & resource scope")
        _render_sign_in_controls(api_url, base_headers, session_info)

    headers = build_request_headers(base_headers)
    resources_payload = _fetch_resources_info(api_url, headers)
    selected_resource: dict | None = None
    if resources_payload is not None:
        items = [r for r in resources_payload.get("resources", []) if r.get("service_name")]
        if items:
            idx = st.sidebar.selectbox(
                "Authorized project / service",
                options=list(range(len(items))),
                format_func=lambda i: items[i].get(
                    "display_name",
                    f"{items[i]['project_id']} · {items[i]['service_name']}",
                ),
            )
            selected_resource = items[idx]
        if session_info and session_info.get("signed_in"):
            _render_keyless_onboarding_expander(
                api_url,
                headers,
                resources_payload.get("reader_service_account", ""),
            )
    elif session_info and session_info.get("signed_in"):
        _render_keyless_onboarding_expander(api_url, headers, "")

    return headers, selected_resource, session_info
