"""Isolated synthetic presentation data. No cloud reads, training, or model calls."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

DEMO_SOURCE = "synthetic-demo"


def example_metrics():
    """Generate a fixed fictional six-hour window with visible workload variation."""
    rng = np.random.default_rng(42)
    t = np.arange(360)
    traffic = np.maximum(8, np.round(90+45*np.sin(t/23)+22*np.sin(t/7)+rng.normal(0,8,len(t))))
    cpu = np.clip(.2+traffic/340+rng.normal(0,.025,len(t)),.05,.78)
    memory = np.clip(.42+.08*np.sin(t/55)+traffic/1400,.25,.8)
    latency = 65+traffic*.65+rng.normal(0,8,len(t))
    error = np.zeros(len(t))
    # Scripted presentation incident, explicitly fictional rather than fault evidence.
    incident = (t>=330)&(t<343)
    cpu[incident] = np.clip(.91+rng.normal(0,.02,incident.sum()),0,1)
    memory[incident] = .88
    latency[incident] += 700
    error[incident] = .06
    start = datetime(2026,11,17,tzinfo=timezone.utc)
    return pd.DataFrame({
        "timestamp":[start+timedelta(minutes=int(i)) for i in t],
        "source":DEMO_SOURCE,"service_name":"synthetic-example","synthetic":True,
        "cpu_utilization":cpu,"memory_utilization":memory,"request_count":traffic.astype(int),
        "network_ingress":(traffic*1800).astype(int),"network_egress":(traffic*6500).astype(int),
        "average_latency":np.maximum(1,latency),"error_rate":error,
        "instance_count":np.where(traffic>115,2,1),"scripted_incident":incident,
    })


def example_projections(frame):
    """An illustrative bounded trend, never presented as trained XGBoost output."""
    rows=[]
    for target in ("cpu_utilization","memory_utilization","request_count"):
        last=float(frame[target].iloc[-1])
        slope=float((frame[target].iloc[-5:].mean()-frame[target].iloc[-15:-10].mean())/10)
        for horizon in (5,10,15):
            value=max(0.,last+slope*horizon)
            if target!="request_count":
                value=min(1.,value)
            rows.append({"target":target,"horizon_minutes":horizon,"illustrative_projection":value,
                "persistence_example":last,"timestamp":frame["timestamp"].iloc[-1]+timedelta(minutes=horizon),
                "source":DEMO_SOURCE,"execution_allowed":False})
    return pd.DataFrame(rows)


def example_alerts(frame):
    rows=frame.tail(60).copy()
    rows["example_alert"]=(rows["cpu_utilization"]>.8)|(rows["memory_utilization"]>.85)|(rows["error_rate"]>.02)|(rows["average_latency"]>600)
    return rows


def render_demo():
    import streamlit as st

    st.warning("SYNTHETIC DEMO: generated examples, not measured cloud activity.")
    st.caption("Simulated service: synthetic-example. This view does not query BigQuery, train models, call Gemini or execute cloud changes.")
    frame=example_metrics()
    st.caption("Fixed example window: 17 November 2026, 00:00–05:59 UTC. Example timestamps do not indicate live activity.")
    usage,projections,alerts,guidance=st.tabs(["Demo usage","Demo projections","Demo alert examples","Demo guidance"])
    indexed=frame.set_index("timestamp")
    with usage:
        st.subheader("Synthetic usage statistics")
        cols=st.columns(4)
        last=frame.iloc[-1]
        for col,label,value in (
            (cols[0],"Demo CPU",f"{last.cpu_utilization:.1%}"),
            (cols[1],"Demo memory",f"{last.memory_utilization:.1%}"),
            (cols[2],"Demo requests / minute",str(int(last.request_count))),
            (cols[3],"Demo server latency (ms)",f"{last.average_latency:.1f}")):
            col.metric(label,value)
        for title,fields in (("Demo CPU and memory",["cpu_utilization","memory_utilization"]),
                ("Demo requests per minute",["request_count"]),
                ("Demo network bytes per minute",["network_ingress","network_egress"]),
                ("Demo instances",["instance_count"]),("Demo latency in milliseconds",["average_latency"]),
                ("Demo server-error fraction",["error_rate"])):
            st.subheader(title)
            st.line_chart(indexed[fields])
    with projections:
        st.subheader("Illustrative trend projections")
        st.info("These are synthetic trend examples, not XGBoost predictions. They do not establish model accuracy or operational readiness.")
        projected=example_projections(frame)
        st.dataframe(projected[["target","horizon_minutes","illustrative_projection","persistence_example"]],hide_index=True)
        for target in ("cpu_utilization","memory_utilization","request_count"):
            recent=indexed[[target]].tail(45).rename(columns={target:"Synthetic history"})
            future=projected[projected.target==target].set_index("timestamp")
            chart=recent.join(future[["illustrative_projection","persistence_example"]],how="outer")
            st.subheader("Demo projection: "+target.replace("_"," "))
            st.line_chart(chart)
        st.caption("The real Models tab keeps its freshness, scope and measured-input gates. Demo examples are excluded from the forecast ledger and accuracy studies.")
    with alerts:
        st.subheader("Scripted alert examples")
        st.info("Threshold flags on fictional inputs, not Isolation Forest scores or independent fault validation.")
        examples=example_alerts(frame)
        st.metric("Demo alert minutes in the last hour",int(examples.example_alert.sum()))
        st.dataframe(examples[["timestamp","cpu_utilization","memory_utilization","average_latency","error_rate","example_alert"]],hide_index=True)
        st.line_chart(examples.set_index("timestamp")[["cpu_utilization","memory_utilization","error_rate"]])
    with guidance:
        st.subheader("Illustrative investigation guidance")
        st.caption("Demo rule examples only. No Gemini request, capacity recommendation or savings claim.")
        st.write("**Simulated CPU pressure:** inspect the scripted high-CPU interval and compare request volume with response time.")
        st.write("**Simulated server errors:** the generated incident includes error responses and higher latency. In a real service, inspect request logs to identify the cause.")
        st.write("**Recovery example:** compare the fictional incident with the later return to ordinary values. Recovery in a demo does not establish reliability.")
    st.caption("Synthetic data stays in this demo view. Measured monitoring and BigQuery history remain separate.")
