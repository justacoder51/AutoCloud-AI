"""Read-only dashboard consuming the local FastAPI evidence endpoint."""

import os

import httpx
import pandas as pd
import streamlit as st

_SOURCE_TO_API = {
    "BigQuery": "bigquery",
    "Cloud Monitoring": "monitoring",
    "Local snapshot": "local",
}
_API_TO_SOURCE = {v: k for k, v in _SOURCE_TO_API.items()}

st.set_page_config(page_title="AutoCloud AI", page_icon="☁", layout="wide")
st.title("AutoCloud AI")
view_mode = st.sidebar.radio("Data mode", ["Measured monitoring", "Synthetic demo"], key="autocloud_data_mode")
if view_mode == "Synthetic demo":
    from app.dashboard.demo import render_demo
    render_demo()
    st.stop()
public_showcase = os.getenv("DASHBOARD_PUBLIC_SHOWCASE", "false").lower() == "true"
api_url = os.getenv("AUTOCLOUD_API_URL", "http://127.0.0.1:8080").rstrip("/")
try:
    from app.dashboard.authentication import api_headers
    from app.dashboard.onboarding import render_sidebar_auth_and_resources

    base_headers = api_headers(api_url, os.getenv("AUTOCLOUD_API_AUTH", "none"))
except Exception:
    st.error("Monitoring API authentication helper failed. Check dashboard configuration.")
    st.stop()

if public_showcase:
    headers, selected_resource, session_info = base_headers, None, None
    st.info("Public read-only showcase. Experimental predictions and anomaly scores never execute cloud changes.")
else:
    headers, selected_resource, session_info = render_sidebar_auth_and_resources(api_url, base_headers)
target_params: dict[str, str] = {}
if selected_resource:
    target_params = {
        "project": selected_resource["project_id"],
        "region": selected_resource["region"],
        "service": selected_resource["service_name"],
    }
    st.caption(
        f"Cloud Run monitoring · {selected_resource['project_id']} · "
        f"{selected_resource['service_name']} · {selected_resource['region']}"
    )
    allowed_labels = [
        _API_TO_SOURCE[s]
        for s in ("bigquery", "monitoring", "local")
        if s in selected_resource.get("allowed_sources", [])
    ] or ["BigQuery", "Cloud Monitoring", "Local snapshot"]
else:
    st.caption("Cloud Run monitoring · autocloud-api · asia-south1")
    allowed_labels = ["BigQuery", "Cloud Monitoring", "Local snapshot"]

st.sidebar.header("Monitoring")
source = "BigQuery" if public_showcase else st.sidebar.selectbox("Metrics source", allowed_labels)
hours = 24 if public_showcase else st.sidebar.selectbox("Lookback (hours)", [1, 6, 12, 24], index=3)
st.sidebar.button("Refresh measurements")
st.sidebar.caption("Reads are cached for 60 seconds. Refresh does not send traffic or run the collector.")
api_source = _SOURCE_TO_API[source]
@st.cache_data(ttl=60, max_entries=1, show_spinner=False)
def public_overview(url: str):
    # Tokens stay on the server and are never arguments or results of the cache.
    with httpx.Client(timeout=45, trust_env=False, follow_redirects=False) as client:
        response = client.get(f"{url}/api/overview", params={"source": "bigquery", "hours": 24},
                              headers=api_headers(url, os.getenv("AUTOCLOUD_API_AUTH", "none")))
        response.raise_for_status()
        return response.json()

stop_reason: tuple[str, str] | None = None
try:
    if public_showcase:
        data = public_overview(api_url)
    else:
        with httpx.Client(timeout=45, trust_env=False, follow_redirects=False) as client:
            response = client.get(
                f"{api_url}/api/overview",
                params={"source": api_source, "hours": hours, **target_params},
                headers=headers,
            )
            if response.status_code == 401:
                stop_reason = ("warning", "User sign-in is required to view authorized project metrics. Sign in via the sidebar.")
            elif response.status_code == 403:
                detail = response.json().get("detail", "Signed-in account is not authorized for this resource.")
                stop_reason = ("error", str(detail))
            else:
                response.raise_for_status()
                data = response.json()
except Exception:
    stop_reason = ("error", "Monitoring is temporarily unavailable. Please refresh in a minute.")
if stop_reason is not None:
    getattr(st, stop_reason[0])(stop_reason[1])
    st.stop()

summary = data["summary"]
plan = data["recommendation_plan"]
st.caption(f"Metrics source: {data['source']}")
if source == "BigQuery" and data["source"] != "bigquery":
    st.error("The API did not return BigQuery data. Restart the API with the updated code and GCP_PROJECT_ID configured.")
    st.stop()
if source == "Cloud Monitoring" and data["source"] != "monitoring":
    st.error("The API did not return live Cloud Monitoring data for the selected project and service.")
    st.stop()
query = data.get("query")
if query:
    if query["status"] != "succeeded":
        st.error("Metrics source is unavailable. Check ADC/OAuth permissions, project ID, and Cloud Monitoring/BigQuery access. No local fallback was used.")
    else:
        st.caption(f"Fetched: {query['fetched_at']} | Cached: {query['cache_hit']} | Window: {query['window_start']} to {query['window_end']}")
coverage = data.get("coverage")
if coverage:
    st.caption(f"Observation coverage: {coverage['observed_minutes']}/{coverage['expected_minutes']} minutes ({coverage['observed_fraction']:.1%}); {coverage['gap_minutes']} missing buckets. This is not training readiness.")
st.caption(f"Assessed at {data['assessed_at']} · Snapshot: {data['snapshot_status']}")
if plan:
    if plan["data_status"] != "fresh":
        st.warning(f"Evidence is {plan['data_status']}. Displayed measurements are historical.")
    else:
        st.success("Recent monitoring evidence is available.")

monitoring, training, models, recommendations, costs = st.tabs([
    "Infrastructure", "Training experiment", "Models", "Recommendations", "Costs & actions",
])
with monitoring:
    if not summary:
        st.info("No usable snapshot for the configured project and service. Configure GCP_PROJECT_ID and collect metrics separately.")
    else:
        values = summary["latest_values"]
        cols = st.columns(4)
        for column, label, key, percent in (
            (cols[0], "CPU", "cpu_utilization", True),
            (cols[1], "Memory", "memory_utilization", True),
            (cols[2], "Requests / latest minute", "request_count", False),
        ):
            value = values[key]
            column.metric(label, "Unknown" if value is None else f"{value * 100:.1f}%" if percent else f"{value:,.2f}")
        from app.dashboard.latency import latency_card

        latency = latency_card(data["records"], data["assessed_at"])
        cols[3].metric(latency["label"], latency["value"])
        cols[3].caption(latency["caption"])
        st.caption(f"Latest observation: {summary['latest_observation']} · {summary['observed_minutes']} observed minute buckets")
        st.write("Requests in measured buckets:", summary["observed_request_total"])
        st.caption(f"Request measurements exist in {summary['request_minutes_with_measurements']} buckets; missing buckets are excluded.")
        frame = pd.DataFrame(data["records"])
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame = frame[frame["timestamp"] >= frame["timestamp"].max() - pd.Timedelta(1, unit="D")]
        st.caption("Charts show up to 24 hours ending at the latest saved observation.")
        # Reindex to expose gaps; never interpolate or replace missing measurements.
        frame = frame.set_index("timestamp").asfreq("min")
        for title, fields in (
            ("CPU & memory (fraction)", ["cpu_utilization", "memory_utilization"]),
            ("Requests per minute", ["request_count"]),
            ("Network bytes per minute", ["network_ingress", "network_egress"]),
            ("Instances", ["instance_count"]),
            ("Server latency (ms)", ["average_latency"]),
        ):
            st.subheader(title)
            st.line_chart(frame[fields])
        with st.expander("Missing measurements"):
            st.json(summary["missing_counts"])
            st.caption("Counts cover observed buckets; wholly missing minute buckets appear as chart gaps.")

with training:
    experiment = data["experiment"]
    st.subheader("Collection and training progress")
    if experiment["progress_status"] == "may_have_stalled":
        st.warning("Progress is stale. The worker may have stalled; completion is unconfirmed.")
    st.json(experiment)
    st.caption("A recent heartbeat is not proof of worker liveness. Trained does not mean independently validated or deployed.")
with models:
    from app.dashboard.model_panels import render_models

    render_models(data)

with recommendations:
    from app.dashboard.advice_panels import render_advice, gemini_status_message

    render_advice(data)
    if public_showcase and data.get("capabilities", {}).get("public_explanations"):
        st.subheader("Optional: explain this with Gemini")
        st.caption("Gemini writes explanations from the cited evidence and prioritises investigations. Generated wording can be wrong; verify it against the measurements.")
        if data.get("capabilities", {}).get("gemini_testing_unlimited"):
            st.caption("Testing mode: application hourly and daily limits are disabled. Each button click can make a billable Gemini request. Google quotas still apply. Refresh does not call Gemini.")
        else:
            st.caption("Shared limit: one model attempt per UTC hour, at most 24 per day; failures also consume that hour. No automatic requests on refresh.")
        if st.button("Generate Gemini explanations"):
            try:
                with httpx.Client(timeout=100, trust_env=False, follow_redirects=False) as client:
                    explained = client.post(f"{api_url}/api/public-explanation", headers=api_headers(api_url, os.getenv("AUTOCLOUD_API_AUTH", "none")))
                    explained.raise_for_status()
                    st.session_state["public_explanation"] = explained.json()
            except Exception:
                st.session_state.pop("public_explanation", None)
                st.warning("Gemini is unavailable. Use the evidence-based recommendations above.")
        explained = st.session_state.get("public_explanation")
        if explained:
            status = explained.get("status")
            st.caption("Gemini returns an explanation of its recorded snapshot; it does not measure usage or change resources.")
            if status in ("completed", "cached"):
                st.caption(f"Recorded analysis at {explained['advice'].get('assessed_at')}. This ordering refers to that snapshot; the recommendations above reflect the latest loaded measurements.")
                if explained.get("summary"):
                    st.write(explained["summary"])
                by_id = {i["id"]: i for i in explained["advice"]["items"]}
                for index, code in enumerate(explained["ordered_ids"], 1):
                    item = by_id[code]
                    st.write(f"{index}. {item['title']}: {(explained.get('explanations') or {}).get(code, item['explanation'])}")
                    with st.expander("Cited measured evidence: " + code):
                        st.json(item["evidence"])
            elif status == "hourly_limit":
                st.info(gemini_status_message(status))
            else:
                st.info(gemini_status_message(status))
            with st.expander("Gemini request details"):
                st.write("Recorded status:", status)
    if not public_showcase:
        from app.dashboard.analysis import render_analysis
    
        render_analysis(
            api_url,
            headers,
            data.get("capabilities", {}),
            hours,
            project=target_params.get("project"),
            region=target_params.get("region"),
            service=target_params.get("service"),
            metric_source=api_source,
        )
    with st.expander("Detailed threshold checks"):
        st.caption("Deterministic threshold preview; no Gemini request is made by refreshing this page.")
        if plan:
            st.write(plan["diagnostic"])
            for item in plan["recommendations"]:
                st.write(item["problem"])
                st.json(item)
            if not plan["recommendations"]:
                st.info("No sustained threshold breach in the latest window. See the evidence-based guidance above; missing measurements do not establish health.")
        else:
            st.info("Monitoring evidence is unavailable.")
    from app.dashboard.reviews import render_reviews

    caps = data.get("capabilities", {})
    if not public_showcase and (caps.get("local_reviews", True) or caps.get("cloud_reviews", False)):
        render_reviews(
            api_url,
            plan,
            source,
            hours,
            headers=headers,
            cloud_reviews=caps.get("cloud_reviews", False),
            project=target_params.get("project"),
            region=target_params.get("region"),
            service=target_params.get("service"),
        )
    else:
        st.info("Review history and decision controls are not available in this read-only view.")
with costs:
    if public_showcase:
        st.info("Billing and infrastructure actions are private and unavailable in the public showcase.")
    else:
        st.subheader("Exported Cloud Run usage costs")
        st.caption("Project-wide Cloud Run costs across all resources and regions, including jobs. These are not the costs of autocloud-api alone or a final invoice.")
        with st.form("billing_query"):
            billing_days = st.selectbox("Billing lookback (days)", [1, 7, 30, 31])
            read_billing = st.form_submit_button("Read billing export")
        st.caption("Billing reads are requested explicitly and cached for five minutes. The selected period is a trailing UTC usage window; first/last days may be partial.")
        if read_billing:
            try:
                with httpx.Client(timeout=45, trust_env=False, follow_redirects=False) as client:
                    billing_response = client.get(
                        f"{api_url}/api/costs",
                        params={"days": billing_days, **target_params},
                        headers=headers,
                    )
                    billing_response.raise_for_status()
                    st.session_state["billing_result"] = billing_response.json()
            except (httpx.HTTPError, ValueError):
                st.session_state.pop("billing_result", None)
                st.error("Billing API is unavailable. Restart the updated local API and check its configuration/access.")
        billing = st.session_state.get("billing_result")
        if billing and billing.get("lookback_days") != billing_days:
            st.info("Click Read billing export to load the newly selected billing window.")
        elif billing:
            status = billing["status"]
            if status == "not_configured":
                st.info("Set DASHBOARD_BILLING_TABLE and GCP_PROJECT_ID in the API terminal, then restart the API.")
            elif status == "not_applicable_external_project":
                st.info(billing.get("note", "Host billing export is not applicable to external onboarded projects."))
            elif status == "unavailable":
                st.error("Billing export could not be read or validated. Costs remain unknown; check the table and BigQuery access.")
            else:
                st.caption(f"Usage period: {billing['period_start']} to {billing['period_end']} (end exclusive)")
                st.caption(f"Fetched: {billing['fetched_at']} | Cached: {billing['cache_hit']}")
                st.caption(f"Latest matching export delivery: {billing['latest_export_time']} | Latest matching usage start: {billing['latest_usage_start_time']}")
                st.caption(billing["scope"])
                if status == "no_exported_rows":
                    st.warning("No matching Cloud Run billing rows have arrived for this period. Cost is unknown, not zero.")
                else:
                    for total in billing["currency_totals"]:
                        st.write(total["currency"])
                        columns = st.columns(3)
                        columns[0].metric("Exported cost before credits", total["gross_cost"])
                        columns[1].metric("Signed credits", total["credits"])
                        columns[2].metric("Exported net cost", total["net_cost"])
                    st.subheader("Daily exported costs by currency (UTC)")
                    st.dataframe(pd.DataFrame(billing["daily_totals"]), hide_index=True)
                    with st.expander("Exported cost types and delivery timestamps"):
                        st.dataframe(pd.DataFrame(billing["rows"]), hide_index=True)
                st.caption(billing["note"])
        else:
            st.info("Click Read billing export to query the configured table.")
        st.info("Service estimates require verified billable usage inputs. Estimates and measured savings remain unavailable.")
        st.write("Recommendation decisions are recorded in the Recommendations tab. Infrastructure execution is not implemented.")
