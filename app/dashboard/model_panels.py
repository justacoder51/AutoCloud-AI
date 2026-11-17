"""Plain-language views of recorded evidence; no inference or cloud calls."""

import pandas as pd
import streamlit as st


TARGETS = {"cpu_utilization": "CPU", "memory_utilization": "Memory", "request_count": "Requests / minute"}


def measured_value(target, value):
    if value is None:
        return "Not available"
    return f"{value * 100:.1f}%" if target in ("cpu_utilization", "memory_utilization") else f"{value:,.1f}"


def display_time(value):
    if not value:
        return "Not available"
    return pd.Timestamp(value).tz_convert("Asia/Kolkata").strftime("%d %b %Y, %I:%M %p IST")


def comparison_count(wins, total):
    return "Not evaluated" if wins is None or total is None else f"{wins} / {total}"


def anomaly_message(anomalies):
    if not anomalies or not anomalies.get("rows"):
        return "No current anomaly assessment", "There is not enough usable recent evidence to assess unusual activity. Missing data does not mean healthy operation."
    if anomalies.get("age_seconds", 0) > 900:
        return "Historical assessment", "These measurements are more than 15 minutes old. Load fresh evidence before interpreting them as current activity."
    flag = anomalies.get("latest_anomaly_detected")
    if flag is None:
        scored = [r for r in anomalies["rows"] if r.get("decision_score") is not None]
        flag = scored[-1].get("anomaly_detected") if scored else None
    threshold = anomalies.get("latest_threshold_baseline")
    if threshold is True and flag is True:
        return "Review this measured activity", "Both the model and a fixed monitoring limit flagged the latest observation. Check the measurements and application logs; agreement does not prove a fault."
    if threshold is True:
        return "A monitoring limit was crossed", "A fixed limit flagged the latest observation. Investigate the measured trigger even if the experimental model did not flag it."
    if flag is True:
        return "Unusual pattern — needs checking", "The model flagged the latest observation, but no supporting threshold breach is established. Normal idle periods can trigger this detector. This is not a confirmed fault."
    if flag is False and threshold is False:
        return "No flag in the latest scored minute", "Neither method flagged that observation. This does not establish that the service is healthy, especially where measurements are missing."
    return "Assessment incomplete", "Some signals are unavailable. Check the missing measurements before interpreting this result."


def render_models(data):
    panel = data.get("models") or {}
    st.subheader("Understand the models")
    st.write("XGBoost estimates future usage. Isolation Forest looks for unusual patterns. Both are experimental and only provide information; they cannot change your cloud resources.")

    st.subheader("1. Can I see usage predictions now?")
    forecasts = panel.get("forecasts") or []
    future = [f for f in forecasts if f.get("forecast_in_past") is False]
    if any(f.get("forecast_in_past") is True for f in forecasts):
        st.warning("Some forecast times have already passed because monitoring measurements arrive after a delay. Those predictions are historical and are excluded from the table and charts below; they remain in prediction details.")
    if future:
        st.info("Experimental forecasts are available. Compare them with new measurements before drawing conclusions.")
        table = [{"Resource": TARGETS.get(f["target"], f["target"]),
                  "Minutes after observation": f["horizon_minutes"],
                  "Prediction for": display_time(f["timestamp"]),
                  "Model estimate": measured_value(f["target"], f.get("prediction")),
                  "Keep current value": measured_value(f["target"], f.get("persistence_prediction"))} for f in future]
        st.dataframe(pd.DataFrame(table), hide_index=True)
        st.caption("Keep current value is the persistence baseline: it assumes the last measured usage will stay unchanged. Horizons start at the observation time, which can lag behind now.")
        st.caption(f"Based on observations at {display_time(future[0].get('origin'))}. Assessed at {display_time(future[0].get('assessed_at'))}.")
        if any(f.get("imputed_feature_count", 0) for f in future):
            st.info("Some older input features were missing and filled by the saved preprocessing rules. Review prediction details before interpreting these estimates.")
        if data.get("records"):
            history = pd.DataFrame(data["records"])
            history["timestamp"] = pd.to_datetime(history["timestamp"], utc=True)
            history = history.set_index("timestamp").asfreq("min").tail(60)
            for target, title in TARGETS.items():
                points = [f for f in future if f["target"] == target]
                if not points:
                    continue
                projected = pd.DataFrame(points)
                projected["timestamp"] = pd.to_datetime(projected["timestamp"], utc=True)
                projected = projected.set_index("timestamp")
                chart = pd.concat([history[target].rename("Measured"),
                                   projected["prediction"].rename("Experimental estimate"),
                                   projected["persistence_prediction"].rename("Keep current value")], axis=1)
                if target != "request_count":
                    chart = chart * 100
                st.write(title + (" (%)" if target != "request_count" else ""))
                st.line_chart(chart)
    elif panel.get("forecast_status") == "not_deployed":
        st.info("Live forecasting is not enabled. Recorded model evaluations are available below.")
    elif forecasts:
        st.warning("The saved forecast times have already passed. They are historical predictions, not estimates of what happens next.")
    else:
        st.warning("Usage predictions are not available for this snapshot.")
        st.write("Forecasts need fresh data and 16 consecutive minutes of measured CPU, memory and request counts. Gaps can prevent a forecast even when model files exist.")
        st.caption("Next step: check measurement coverage and scheduled collection. Refresh loads stored data; it does not train a model or collect new measurements.")
    with st.expander("Prediction details and reasons"):
        st.write(panel.get("forecast_reason") or "No additional unavailability reason was supplied.")
        if forecasts:
            st.json(forecasts)
        st.caption("Missing inputs and model-integrity checks remain enforced. Earlier or expired forecasts are excluded from the charts.")

    st.subheader("2. Does anything need investigation?")
    anomalies = panel.get("anomaly_results") or {}
    title, message = anomaly_message(anomalies)
    st.warning(title)
    st.write(message)
    if anomalies.get("rows"):
        columns = st.columns(3)
        columns[0].metric("Minutes flagged by the model", anomalies.get("anomaly_flagged_minutes", "Unavailable"))
        columns[1].metric("Minutes crossing fixed limits", anomalies.get("threshold_flagged_minutes", "Unavailable"))
        columns[2].metric("Minutes with model scores", f"{anomalies.get('scored_minutes', '?')} / {anomalies.get('window_minutes', '?')}")
        st.caption(f"Window: {display_time(anomalies.get('window_start'))} to {display_time(anomalies.get('window_end'))}. Counts are minutes, not separate incidents.")
        st.write("A threshold is a fixed monitoring limit. Isolation Forest instead compares patterns with its training data. An unusual pattern is not necessarily a fault.")
        st.caption(f"Missing input values: {anomalies.get('missing_feature_cells', 'unavailable')}. Entirely unobserved minutes: {anomalies.get('unobserved_minutes', 'unavailable')}. Missing values are not zeros or evidence of health.")
        with st.expander("Anomaly scores, fixed limits and individual minutes"):
            score = anomalies.get("latest_decision_score")
            st.write("Latest Isolation Forest score:", "Unavailable" if score is None else f"{score:.4f}")
            st.caption("A negative decision score is flagged as unusual. It is not a probability or percentage risk.")
            st.write("Latest threshold result:", {True: "Limit crossed", False: "No limit crossed", None: "Unavailable"}.get(anomalies.get("latest_threshold_baseline"), "Unavailable"))
            st.dataframe(pd.DataFrame(anomalies["rows"]), hide_index=True)
            scores = pd.DataFrame(anomalies["rows"])
            if "decision_score" in scores:
                scores["timestamp"] = pd.to_datetime(scores["timestamp"], utc=True)
                st.line_chart(scores.set_index("timestamp")[["decision_score"]].rename(columns={"decision_score": "Unusual-pattern score (below zero is flagged)"}))
            st.write(anomalies.get("limitations", "Independent fault labels are needed to establish detection accuracy."))
            st.json({k: v for k, v in anomalies.items() if k != "rows"})
    else:
        st.caption(panel.get("anomaly_reason") or "No usable recent anomaly scores were returned.")

    st.subheader("3. How reliable are these models?")
    st.write("We compare forecasts with actual future measurements and the simple keep-current-value baseline. Lower average error (MAE) is better. A count of winning forecasts is not an accuracy percentage.")
    evaluation = panel.get("evaluation") or {}
    comparison = evaluation.get("baseline_comparison") or {}
    validation = data.get("measured_validation") or {}
    columns = st.columns(2)
    columns[0].metric("Original test: forecasts with lower error", comparison_count(comparison.get('models_beating_persistence_mae'), comparison.get('models_evaluated')))
    columns[1].metric("Newer study: forecasts with lower error", comparison_count(validation.get('forecast_mae_wins'), validation.get('forecast_models_evaluated')))
    st.caption("These are different datasets, not a live accuracy score. Each comparison is one resource and one forecast horizon.")
    if comparison.get("models_beating_persistence_mae") == 0:
        st.warning("No forecast beat the simple baseline on the original test. That test does not support using these forecasts to scale resources.")
    if validation:
        st.write(f"The newer study used {validation.get('observed_minutes', '?')} measured minutes with the models unchanged. Point-error wins alone do not establish consistent improvement across workloads.")
        cpu_intervals = [result.get("paired_uncertainty", {}).get("nine_comparison_bonferroni_interval")
                         for key, result in validation.get("forecast_results", {}).items()
                         if key.startswith("cpu_utilization_") and result.get("status") == "evaluated"]
        if cpu_intervals and all(interval and interval[0] <= 0 <= interval[1] for interval in cpu_intervals):
            st.caption("The recorded CPU improvement intervals include zero, so general superiority has not been established.")
    if not evaluation:
        if panel.get("status") == "run_rejected":
            st.error("The model run failed validation. Its evaluation and forecasts were not accepted.")
        else:
            st.info("No accepted recorded model evaluation is available.")
    with st.expander("Recorded model evaluation — original test"):
        if evaluation:
            st.caption(f"Run: {evaluation.get('run_name')} | History ends: {display_time(evaluation.get('training_history_end'))}")
            st.dataframe(pd.DataFrame(evaluation.get("forecast_evaluation", [])), hide_index=True)
            st.caption("MAE is average absolute error. RMSE gives larger misses more weight. Utilisation errors use fractions: 0.01 equals one percentage point; request errors use requests per minute.")
            st.json(evaluation)
        else:
            st.write("No recorded evaluation supplied.")
    if validation:
        comparisons = validation.get("anomaly_event_comparisons", {}).get("matching_request_counts", {})
        raw = comparisons.get("raw_flag") or {}
        if raw:
            matrix = raw.get("confusion_matrix")
            st.write("**Anomaly validation: false alarms remain a concern.**")
            if matrix:
                st.write(f"In the recorded HTTP-error study, the model flagged {matrix[1][1]} of {raw.get('positive_minutes', '?')} error-labelled minutes and {matrix[0][1]} of {raw.get('negative_minutes', '?')} minutes without observed server errors.")
            st.caption("No observed server error does not prove complete service health. This small, correlated incident sample does not establish general fault detection or early warning.")
        with st.expander("Newer forecast study and HTTP-error detection validation"):
            st.caption(f"Study {validation.get('study_id')} | {display_time(validation.get('period_start_exclusive'))} to {display_time(validation.get('period_end_inclusive'))}")
            st.write("The server-error counter detects errors that already happened. Its agreement with request logs is not predictive ML accuracy.")
            st.json(validation)
    st.info("Automatic resource changes are disabled. Verified cost savings have not been established.")

    st.subheader("4. Is the selected data ready for another training run?")
    readiness = panel.get("readiness")
    if readiness:
        st.write("Enough usable data for exploratory training" if readiness.get("ready") else "More usable monitoring data is needed")
        st.caption("This checks the selected dashboard window, not the earlier dataset used to train the saved models. Passing this check does not start training or approve deployment.")
        with st.expander("Data coverage, missing values and training requirements"):
            for reason in readiness.get("reasons", []):
                st.write(reason)
            st.write("Coverage counts measured minutes. Missingness counts absent metric values. Training, validation and test examples are ordered by time so that future observations do not leak into earlier training.")
            st.json(readiness)
    else:
        st.info("Training-data readiness has not been assessed for this snapshot.")
    ledger = data.get("prospective_validation")
    if ledger:
        with st.expander("Forecast audit trail"):
            st.write("Eligible forecasts are saved before their outcomes occur so they can be evaluated later. Saving a forecast does not prove it is accurate.")
            if ledger.get("status") == "no_eligible_future_forecasts":
                st.write("No eligible future forecasts were available to record in this snapshot.")
            st.json(ledger)
