# Phase 3: real Cloud Run monitoring

The initial deployment is verified from user-provided evidence: authenticated
readiness returned 200, direct unauthenticated readiness returned 403, and Cloud
Logging recorded both. Phase 3 now adds a standalone collection pipeline; the
currently deployed v1 FastAPI service is unchanged.

## Modules

- `services/gcp_monitoring.py`: read-only Cloud Monitoring adapter, filtering
  `cloud_run_revision` by project/service/region and consuming all SDK pages.
- `data/schema.py`: validated, source-labelled samples and observation records.
- `data/processor.py`: Pandas/NumPy window aggregation and missingness tracking.
- `data/collector.py`: one-shot CLI orchestration using ADC; exits nonzero on
  API, credentials, validation or storage errors.
- `services/bigquery_service.py`: batch append to an existing regional table.
- `data/storage.py`: NDJSON snapshots and optional immutable Cloud Storage archive.

No ML, forecast, cost estimate or automatic scaling is introduced in this phase.

## Metric contract

All metric paths have prefix `run.googleapis.com/`. Each record's UTC timestamp
is the end of a complete 60-second aligned window. The collector queries only
through three minutes before now, allowing for the documented sampling and
visibility delay. Availability can still vary; rerun overlapping windows later.

| Record field | Metric suffix | Aggregation / unit |
| --- | --- | --- |
| cpu_utilization | container/cpu/utilizations | Distribution count-weighted mean; fraction, 1 = 100% |
| memory_utilization | container/memory/utilizations | Distribution count-weighted mean; fraction |
| request_count | request_count | DELTA sum across revisions and response labels; requests/window |
| network_ingress | container/network/received_bytes_count | DELTA sum across revisions/network kinds; bytes/window |
| network_egress | container/network/sent_bytes_count | DELTA sum across revisions/network kinds; bytes/window |
| average_latency | request_latencies | Distribution count-weighted mean; milliseconds |
| instance_count | container/instance_count | Sum of per-series temporal means across states/revisions; average instances |
| error_rate | request_count | Observed 5xx requests / total classified requests; fraction |

Distribution metrics use `ALIGN_SUM`, retaining count and mean; they do not use
numeric-only `ALIGN_MEAN`. Counts use `ALIGN_SUM`; the instance gauge uses
`ALIGN_MEAN`. The processor combines actual sample weights across series.
It does not average revision means equally or manufacture missing measurements.

Missing values remain JSON null, with `missing_fields` listing affected fields.
There is no interpolation or forward fill. A window with no measurements is not
created. A zero request count has undefined error rate (null); observed requests
with known non-5xx codes yield a measured error rate of zero. Incomplete/missing
response-code labels yield null. Invalid/nonfinite/negative points are rejected;
out-of-range utilisation or fractional integer counters are dropped. Exact
series-point duplicates are removed before service aggregation.

These metrics describe traffic reaching Cloud Run revisions. Requests denied
by upstream IAM may appear in request logs without reaching the container or
appearing as application errors. CPU/memory series can be sparse for a lightly
used service that scales to zero. Null does not mean healthy or zero usage.
Network metrics are observed bytes, not billable egress cost.

## First read-only cloud collection

Run in your own **Command Prompt**, which has working cloud/network access:

```cmd
cd /d "C:\Users\sihan\Desktop\cloud sem end project"
.venv\Scripts\python.exe -m pip install -r requirements-monitoring.txt
gcloud auth application-default login
.venv\Scripts\python.exe -m app.data.collector --project=astute-sign-506809-j8 --region=asia-south1 --service=autocloud-api --minutes=60
```

Python client libraries need Application Default Credentials separately from
`gcloud auth login`. Complete sign-in in the browser; do not paste tokens or
download service account keys. If the `.venv` lacks pip, run its Python with
`-m ensurepip --upgrade` before installing. This command reads real Monitoring
metrics and writes only `data/processed/metrics.ndjson` locally. It does not
create cloud storage or modify infrastructure. A successful empty response is
reported as `no_observations`, not synthetic data. API failures return exit 1.

Generate a small number of authenticated requests using the existing local
proxy if needed, wait for Monitoring's ingestion delay, then collect again.
Inspect the NDJSON values and missingness before enabling historical storage.

## BigQuery provisioning and historical ingestion (approval required)

Review `infrastructure/bigquery.sql` before running it. It creates the regional
`autocloud` dataset, a day-partitioned service-clustered table with 30-day
partition retention, and the `latest_metrics` deduplication view. Partition
expiry deletes old observations, so change the retention before ingestion if
your experiment requires longer history. The SQL does not modify an already
existing table's schema/options; inspect existing resources before reuse.

In **Command Prompt**, after approval:

```cmd
bq --project_id=astute-sign-506809-j8 --location=asia-south1 query --use_legacy_sql=false < infrastructure\bigquery.sql
.venv\Scripts\python.exe -m app.data.collector --project=astute-sign-506809-j8 --region=asia-south1 --service=autocloud-api --minutes=60 --write-bigquery
```

Collection never auto-creates the dataset/table. Missing storage, wrong location,
permissions errors and failed load jobs cause failure. Batch job IDs are derived
from the target and exact payload, so retrying that exact batch reuses the job
while BigQuery retains its job metadata. A fresh collection or overlapping poll
can append the same logical window again. **Read `latest_metrics` to deduplicate
by record_id and latest collected_at; do not sum the append table directly.**

Budgeted verification query (Command Prompt):

```cmd
bq --project_id=astute-sign-506809-j8 --location=asia-south1 query --use_legacy_sql=false --maximum_bytes_billed=100000000 "SELECT timestamp, service_name, cpu_utilization, request_count, missing_fields FROM `astute-sign-506809-j8.autocloud.latest_metrics` WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR) ORDER BY timestamp DESC LIMIT 10"
```

The backticks in this query are for Command Prompt; PowerShell treats them as
escape characters. Use Command Prompt as shown or adapt quoting explicitly.
Batch writes and analytics have cloud usage implications; no monetary price or
free-tier availability is assumed here.

## Optional archive and cloud collector identity

An existing regional Cloud Storage bucket can receive immutable NDJSON using
`--archive-bucket=BUCKET_NAME`. The collector does not create buckets. This is an
optional archive of processed observations, not raw distribution histograms.
Only one writer's success is needed; content-derived names and create-only
preconditions make exact archive retries safe. BigQuery and archive writes are
not transactional; on failure inspect local output and retry the failed sink.

For a later Cloud Run Job collector, use a separate service account with:

- Monitoring Viewer on the monitored project.
- BigQuery Job User on the ingestion project.
- BigQuery Data Editor scoped to the metrics table (the prepared loader does
  not create tables and does not need dataset-wide write access).
- Storage Object Creator scoped to the optional archive bucket, if used.

The v1 API runtime needs none of these roles. Real collection, historical loading
and view readback are now verified. The cloud collector packaging and staged
deployment helper are ready in [scheduled-collection.md](scheduled-collection.md).
The user has now created scoped collector IAM grants, deployed the Cloud Run Job,
and enabled Cloud Scheduler. Manual cloud ingestion and an on-demand invocation
through Scheduler are verified. Pub/Sub integration is not implemented.

## Validation and official references

Offline tests use labelled fixtures and mock SDK clients. They verify weighted
aggregation, missing values, labels, duplicate handling, error rates, target
filtering, ingestion lag, API failures, load retries and regional storage checks.
They do not substitute for an actual successful collection/load in this project.

- [Cloud Run monitoring](https://docs.cloud.google.com/run/docs/monitoring)
- [Metric kinds, types and units](https://docs.cloud.google.com/monitoring/api/metrics_gcp_p_z)
- [Monitoring aggregation](https://docs.cloud.google.com/python/docs/reference/monitoring/latest/summary_class)
- [Batch JSON load API](https://docs.cloud.google.com/python/docs/reference/bigquery/latest/google.cloud.bigquery.client.Client#google_cloud_bigquery_client_Client_load_table_from_json)

Checked 2026-11-15. Numeric pricing integration remains Phase 5 work.
