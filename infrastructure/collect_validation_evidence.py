"""Read-only, bounded collection for frozen-model and cost validation.

No traffic generation, training, deployments, IAM or billing configuration changes.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.cloud import bigquery

from app.data.schema import MetricRecord

PROJECT = "astute-sign-506809-j8"
REGION = "asia-south1"
RUN = Path("models/runs/20261116T051914Z_48d41482")
BILLING = PROJECT + ".autocloud_billing.gcp_billing_export_v1_011640_0793FF_B5C560"


def save(folder, name, value):
    (folder / name).write_text(json.dumps(value, indent=2, default=str, allow_nan=False), encoding="utf-8")


def main():
    now = datetime.now(timezone.utc)
    manifest = json.loads((RUN / "forecast_manifest.json").read_text())
    start = datetime.fromisoformat(manifest["training_history_end"].replace("Z", "+00:00"))
    end = (now-timedelta(minutes=10)).replace(second=0, microsecond=0)
    folder = Path("data/validation_studies") / now.strftime("%Y%m%dT%H%M%SZ")
    folder.mkdir(parents=True)
    protocol = {
        "registered_at": now.isoformat(), "project": PROJECT, "region": REGION,
        "service": "autocloud-api", "model_run": str(RUN),
        "model_files_sha256": {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in RUN.glob("*.json")},
        "history_sha256": hashlib.sha256((RUN / "history.ndjson").read_bytes()).hexdigest(),
        "start_exclusive": start.isoformat(), "end_inclusive": end.isoformat(),
        "forecast_protocol": "Frozen native models; no fitting or selection on this post-training temporal cohort. All nine targets/horizons; same sixteen-minute observed-origin gate as live inference. Compare MAE/RMSE with persistence and train-only historical average. Hour-block paired bootstrap is descriptive, not independent multi-workload proof.",
        "label_protocol": "HTTP availability-event detection only. Positive: at least one logged 5xx; negative: at least one logged 2xx and no logged 5xx. Other minutes unknown. Logs are separate from model flags/thresholds. Contemporaneous error_rate is a feature, so this is detection, not early warning or general causal infrastructure-fault accuracy. Require complete pagination and separately report Monitoring/log count mismatch.",
        "cost_protocol": "Read exported gross costs, signed credits and net costs separately by currency and service. Do not infer causal savings without resource-attributed comparable baseline/treatment windows and a verified optimisation. No new infrastructure experiment authorised by this collection.",
        "bounds": {"maximum_bytes_per_query":100_000_000, "maximum_log_entries":10000, "billing_lookback_days":7},
    }
    save(folder, "protocol.json", protocol)
    print("Protocol registered:", folder, flush=True)
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    session = AuthorizedSession(creds)
    client = bigquery.Client(project=PROJECT, location=REGION, credentials=creds)
    config = bigquery.QueryJobConfig(maximum_bytes_billed=100_000_000, query_parameters=[
        bigquery.ScalarQueryParameter("start","TIMESTAMP",start),
        bigquery.ScalarQueryParameter("end","TIMESTAMP",end),
        bigquery.ScalarQueryParameter("captured","TIMESTAMP",now),
    ])
    sql = f"""SELECT * FROM `{PROJECT}.autocloud.latest_metrics`
        WHERE timestamp > @start AND timestamp <= @end AND collected_at <= @captured
        AND project_id='{PROJECT}' AND region='{REGION}' AND service_name='autocloud-api'
        AND source='gcp-monitoring' ORDER BY timestamp LIMIT 5001"""
    job = client.query(sql, job_config=config, location=REGION, timeout=15)
    rows = [MetricRecord.model_validate(dict(r)) for r in job.result(timeout=60)]
    assert len(rows) <= 5000
    payload = "".join(r.model_dump_json()+"\n" for r in rows).encode()
    (folder / "observations.ndjson").write_bytes(payload)
    save(folder, "observations-source.json", {"job_id":job.job_id, "bytes_processed":job.total_bytes_processed,
         "rows":len(rows), "sha256":hashlib.sha256(payload).hexdigest()})
    print("Post-training observations:", len(rows), flush=True)

    filter_text = (f'resource.type="cloud_run_revision" AND resource.labels.service_name="autocloud-api" '
        f'AND resource.labels.location="{REGION}" AND logName="projects/{PROJECT}/logs/run.googleapis.com%2Frequests" '
        f'AND timestamp>"{start.isoformat()}" AND timestamp<="{end.isoformat()}"')
    entries, token, complete = [], None, False
    for page in range(10):
        body = {"resourceNames":["projects/"+PROJECT], "filter":filter_text, "orderBy":"timestamp asc", "pageSize":1000}
        if token: body["pageToken"] = token
        response = session.post("https://logging.googleapis.com/v2/entries:list", json=body, timeout=45)
        if not response.ok:
            save(folder,"request-logs-source.json",{"status":"unavailable","http_status":response.status_code,"complete":False})
            break
        data = response.json()
        for e in data.get("entries", []):
            request = e.get("httpRequest", {})
            if "status" not in request: continue
            from urllib.parse import urlsplit
            entries.append({"timestamp":e["timestamp"], "status":int(request["status"]),
                "revision":e.get("resource",{}).get("labels",{}).get("revision_name"),
                "path":urlsplit(request.get("requestUrl", "")).path,
                "entry_hash":hashlib.sha256(str(e.get("insertId", e["timestamp"])).encode()).hexdigest()})
        token = data.get("nextPageToken")
        if not token:
            complete = True
            break
    else:
        save(folder,"request-logs-source.json",{"status":"truncated","complete":False})
    save(folder,"request-logs.json",entries)
    if complete:
        save(folder,"request-logs-source.json",{"status":"collected","complete":True,"entries":len(entries),
            "label_limitations":"Request logs may arrive late. No observed 5xx is not proof of general infrastructure health."})
    print("Request logs:",len(entries),"complete:",complete,flush=True)

    table = client.get_table(BILLING, timeout=15)
    save(folder, "billing-schema.json", {"location":table.location,"fields":[f.name for f in table.schema],
        "resource_field_present":any(f.name=="resource" for f in table.schema)})
    config = bigquery.QueryJobConfig(maximum_bytes_billed=100_000_000, query_parameters=[
        bigquery.ScalarQueryParameter("start","TIMESTAMP",now-timedelta(days=7)),
        bigquery.ScalarQueryParameter("end","TIMESTAMP",now),
        bigquery.ScalarQueryParameter("project","STRING",PROJECT)])
    sql = f"""SELECT DATE(usage_start_time,'UTC') usage_date, currency, service.description service,
        cost_type, SUM(CAST(cost AS NUMERIC)) gross_cost,
        SUM(IFNULL((SELECT SUM(CAST(c.amount AS NUMERIC)) FROM UNNEST(credits)c),0)) credits,
        SUM(CAST(cost AS NUMERIC)+IFNULL((SELECT SUM(CAST(c.amount AS NUMERIC)) FROM UNNEST(credits)c),0)) net_cost,
        MIN(usage_start_time) earliest_usage, MAX(usage_start_time) latest_usage, MAX(export_time) latest_export
        FROM `{BILLING}` WHERE usage_start_time>=@start AND usage_start_time<@end AND project.id=@project
        GROUP BY usage_date,currency,service,cost_type ORDER BY usage_date,service,currency LIMIT 1001"""
    job = client.query(sql,job_config=config,location=table.location,timeout=15)
    costs = [dict(r) for r in job.result(timeout=60)]
    assert len(costs)<=1000
    save(folder,"billing-export.json",{"status":"exported_usage_costs" if costs else "no_exported_rows",
        "project":PROJECT,"source_table":BILLING,"job_id":job.job_id,"bytes_processed":job.total_bytes_processed,
        "rows":costs,"measured_savings":None,"note":"Project/service aggregates; export can lag or be adjusted. No invoice or causal savings claim."})
    print("Billing aggregate rows:",len(costs),"Evidence directory:",folder,flush=True)


if __name__ == "__main__":
    main()
