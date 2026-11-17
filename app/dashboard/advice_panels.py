"""Explain existing recommendations without changing policy or calling models."""

import streamlit as st

from app.dashboard.model_panels import display_time


GUIDANCE = {
    "restore_measurements": ("Get recent monitoring data", "Check the scheduled collector's last execution and any ingestion errors. Refresh after new measurements arrive."),
    "investigate_observed_errors": ("Check the requests that returned server errors", "Open application logs for the affected minutes and identify the failing routes. Investigate the cause before changing capacity."),
    "inspect_anomaly": ("Check an unusual pattern", "Compare the flagged minute with CPU, memory, traffic and application logs. Check whether the service was simply idle."),
    "forecast_coverage": ("Restore the inputs needed for predictions", "Look for 16 consecutive measured minutes of CPU, memory and requests. Check collection gaps; do not replace missing readings with invented values."),
    "check_coverage": ("Check missing measurements", "Compare gaps with instance count and collector logs. Scaling to zero may explain absent CPU and memory measurements."),
    "continue_monitoring": ("Keep monitoring before changing capacity", "Watch a longer period, including busy times. No sustained threshold breach is established; missing data still prevents a health guarantee."),
    "review_utilisation": ("Review resource size using a longer history", "Compare peak usage, response-time requirements and minimum-instance settings. Low use in a quiet window alone does not prove waste or savings."),
    "watch_forecast": ("Watch the predicted usage increase", "Compare the experimental estimate with the keep-current-value baseline and subsequent measurements. Do not scale from this signal alone."),
}
SOURCES = {
    "experimental": "Experimental model signal — needs confirmation",
    "data_quality": "Monitoring data quality",
    "monitoring": "Measured monitoring rules",
    "observed_availability": "Measured server-error responses",
    "capacity_review": "Measured usage history",
    "investigation": "Measured monitoring rules",
}


def gemini_status_message(status):
    return {
        "skipped_stale": "Gemini was not called because the monitoring evidence was not fresh enough. Check collection and load fresh measurements first.",
        "failed": "No accepted Gemini explanation was returned. The request may have failed, timed out or failed the response checks. The measured recommendations above remain available.",
        "disabled": "Gemini explanations are switched off for this service. The measured recommendations above still work.",
        "budget_unavailable": "Gemini was not called because its shared request-budget storage was unavailable. The measured recommendations above still work.",
        "hourly_limit": "The shared hourly Gemini allowance has been used. The measured recommendations above remain available without another model request.",
    }.get(status, "No accepted Gemini explanation is available for this request. Use the measured recommendations above; the returned status does not establish a specific cause.")


def render_advice(data):
    st.subheader("What should I check next?")
    st.write("These suggestions help you investigate the loaded measurements. They do not execute changes or establish cost savings.")
    advice = data.get("public_advice") or {}
    items = advice.get("items") or []
    plan = data.get("recommendation_plan") or {}
    status = advice.get("data_status") or plan.get("data_status")
    if status == "fresh":
        st.caption("Recent evidence is available. Recent does not mean complete: check coverage and missing values too.")
    else:
        st.warning("Monitoring evidence is not confirmed fresh. Restore usable measurements before making capacity decisions.")
    st.caption(f"Advice assessed: {display_time(advice.get('assessed_at') or data.get('assessed_at'))}")
    if not items:
        st.info("No investigation guidance was returned for this snapshot. This is not a confirmation that the service is healthy.")
    for index, item in enumerate(items, 1):
        title, next_step = GUIDANCE.get(item.get("id"), (item["title"], item["explanation"]))
        with st.container(border=True):
            st.write(f"**{index}. {title}**")
            st.caption(SOURCES.get(item.get("kind"), "Recorded evidence"))
            st.write("**Why this appears:** " + item["explanation"])
            st.write("**Next step:** " + next_step)
            with st.expander("Supporting measurements — " + title):
                st.json(item.get("evidence", {}))
    st.caption("The numbered list follows the recorded recommendation order. Gemini can provide a separate explanation and investigation order when explicitly requested.")
