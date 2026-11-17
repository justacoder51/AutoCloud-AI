"""Explicit local review controls and durable history."""

import httpx
import streamlit as st


def _api_source_name(source: str) -> str:
    if source == "BigQuery":
        return "bigquery"
    if source == "Cloud Monitoring":
        return "monitoring"
    return "local"


def render_reviews(
    api_url,
    plan,
    source,
    hours,
    headers=None,
    cloud_reviews=False,
    *,
    project: str | None = None,
    region: str | None = None,
    service: str | None = None,
):
    st.subheader("Recommendation review history")
    if cloud_reviews:
        st.caption("Approve means accept an investigation recommendation for manual follow-up. It never executes or authorizes infrastructure changes. Cloud reviews cryptographically verify the calling dashboard service identity and store immutable records in Cloud Storage; human reviewer labels are self-reported.")
    else:
        st.caption("Approve means accept an investigation recommendation for manual follow-up. It never executes or authorizes infrastructure changes. Reviewer names are self-reported local labels.")

    target_params = {k: v for k, v in (("project", project), ("region", region), ("service", service)) if v}

    def request(method, path, body=None):
        extra: dict = {"headers": headers} if headers else {}
        if target_params and method != "POST" or (target_params and path.endswith("/decision")):
            extra["params"] = target_params
        elif target_params and path == "":
            extra["params"] = target_params
        with httpx.Client(timeout=45, trust_env=False, follow_redirects=False) as client:
            response = client.request(method, f"{api_url}/api/reviews{path}", json=body, **extra)
            if response.status_code == 409:
                st.warning(response.json()["detail"])
                return None
            response.raise_for_status()
            return response.json()

    def load():
        st.session_state["review_history"] = request("GET", "")

    try:
        if st.button("Save current recommendations for review", disabled=not (
                plan and plan["data_status"] == "fresh" and plan["recommendations"])):
            capture_body = {
                "source": _api_source_name(source),
                "hours": hours,
                "evidence_fingerprint": plan["evidence_fingerprint"],
            }
            if project:
                capture_body["project"] = project
            if region:
                capture_body["region"] = region
            if service:
                capture_body["service"] = service
            result = request("POST", "/capture", capture_body)
            if result is not None:
                st.success(f"Saved {len(result['saved_ids'])} recommendations. Repeated saves do not duplicate evidence.")
                load()
        if st.button("Load review history"):
            load()
        history = st.session_state.get("review_history")
        if history is None:
            st.info("Load review history to see saved recommendations and decisions.")
            return
        if not history["items"]:
            st.info("No saved recommendations yet. Recommendations appear only when measured evidence supports them.")
        st.caption("Latest 200 saved recommendations. Refresh history to retrieve decisions from disk.")
        for entry in history["items"]:
            identifier = entry["id"]
            candidate = entry["snapshot"]["recommendations"][0]
            with st.expander(f"{candidate['problem']} — {entry['status']} — {entry['created_at']}"):
                st.caption(f"Review ID: {identifier}")
                st.json(entry["snapshot"])
                st.caption(f"Evidence approval deadline: {entry['expires_at']}")
                if entry["decision"]:
                    svc_principal = entry.get("calling_service_principal") or entry.get("authenticated_principal")
                    principal_text = f" | Service principal: {svc_principal} (self-reported reviewer label)" if svc_principal else ""
                    reviewer_label = entry.get("reviewer_label") or entry["reviewer"]
                    st.write(f"Decision: {entry['decision']} | Reviewer label: {reviewer_label}{principal_text} | At: {entry['decided_at']}")
                    st.text(entry["note"])
                else:
                    if entry["evidence_expired"]:
                        st.warning("Evidence expired. Approval is blocked; rejection remains available.")
                    with st.form("review_" + identifier):
                        reviewer = st.text_input("Reviewer label", max_chars=80)
                        note = st.text_area("Reason for decision", max_chars=1000)
                        choice = st.selectbox("Decision", ["rejected"] if entry["evidence_expired"] else ["approved", "rejected"])
                        confirm = st.checkbox("I reviewed the evidence and understand this records a decision only.")
                        submit = st.form_submit_button("Record decision")
                    if submit:
                        if not reviewer.strip() or not note.strip() or not confirm:
                            st.warning("Provide your label, a reason and the review acknowledgement.")
                        else:
                            result = request("POST", f"/{identifier}/decision", {
                                "decision": choice, "reviewer": reviewer, "note": note,
                            })
                            if result is not None:
                                load()
                                st.rerun()
    except (httpx.HTTPError, ValueError, KeyError):
        st.session_state.pop("review_history", None)
        st.error("Review API is unavailable. Restart the updated local API and load history again. No successful save is assumed.")
