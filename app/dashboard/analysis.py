"""Manual LangGraph/Gemini analysis controls, separate from ordinary refresh."""

import httpx
import streamlit as st


def render_analysis(
    api_url,
    headers,
    capabilities,
    hours,
    *,
    project: str | None = None,
    region: str | None = None,
    service: str | None = None,
    metric_source: str = "bigquery",
):
    st.subheader("LangGraph + Gemini analysis")
    if not capabilities.get("ai_workflow", False):
        st.info("The connected API does not have the dashboard AI workflow enabled.")
        return
    source_label = "Cloud Monitoring" if metric_source == "monitoring" else "BigQuery"
    st.caption(
        f"Reads measured {source_label} history for the authorized resource. Gemini can prioritize supported "
        "investigations; it cannot change infrastructure. Experimental ML signals do not trigger automatic actions."
    )
    with st.form("ai_analysis"):
        use_gemini = st.checkbox("Use Gemini (one potentially billable request)",
                                   disabled=not capabilities.get("gemini_enabled", False))
        include_billing = st.checkbox("Include the last day of exported Cloud Run costs",
                                      disabled=not capabilities.get("billing_configured", False))
        submit = st.form_submit_button("Run AI analysis")
        check = st.form_submit_button("Check Gemini connection", disabled=not capabilities.get("gemini_enabled", False))
    st.caption("Check Gemini connection sends one small request with no monitoring records; it does not assess the infrastructure.")
    st.caption("Gemini is skipped for stale, insufficient or incomplete observations. Repeated identical requests are cached for 60 seconds per API worker; this is not a project-wide spending cap.")
    if not capabilities.get("gemini_enabled", False):
        st.info("Gemini is not configured in this API. LangGraph can still run its evidence and policy checks.")
    if submit or check:
        body = {
            "hours": hours,
            "use_gemini": True if check else use_gemini,
            "include_billing": False if check else include_billing,
            "connectivity_check": check,
        }
        if project:
            body["project"] = project
        if region:
            body["region"] = region
        if service:
            body["service"] = service
        if metric_source in {"bigquery", "monitoring"} and (project or metric_source != "bigquery"):
            body["source"] = metric_source
        try:
            with httpx.Client(timeout=110, trust_env=False, follow_redirects=False) as client:
                response = client.post(f"{api_url}/api/analysis", headers=headers, json=body)
                response.raise_for_status()
                st.session_state["ai_analysis_result"] = response.json()
        except (httpx.HTTPError, ValueError):
            st.session_state.pop("ai_analysis_result", None)
            st.error("AI analysis could not be completed. Wait 60 seconds before retrying; no successful Gemini result is assumed.")
    payload = st.session_state.get("ai_analysis_result")
    if not payload:
        return
    if payload["status"] != "completed":
        st.warning("Analysis is unavailable. Check monitoring/billing access; the failure was sanitized.")
        return
    result = payload["result"]
    st.caption(f"Assessed: {result['assessed_at']} | Cached: {payload['cache_hit']} | Evidence: {result['data_status']}")
    st.write("Workflow:", result["workflow_status"], "| Gemini:", result["gemini"]["status"])
    st.write(result["summary"])
    if result["gemini"]["status"] == "failed_or_rejected":
        st.warning("Gemini failed or returned an invalid selection. The displayed result uses deterministic policy checks.")
    st.caption("This is the recorded analysis at the displayed time. Reload measurements and explicitly rerun to reassess current evidence.")
    for item in result["recommendations"]:
        with st.expander(item["problem"]):
            st.write(item["explanation"])
            st.json(item)
    with st.expander("AI analysis evidence, model readiness and cost status"):
        st.json(result)
