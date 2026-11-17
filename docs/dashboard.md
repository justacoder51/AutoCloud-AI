# Local monitoring dashboard

Use **http://127.0.0.1:8501/** for the in-app browser. The app is bound to IPv4
loopback; the `localhost` address failed in this browser even while the numeric
loopback address worked. Browser-level verification now passed on 16 November
2026: the Models tab displayed run `20261116T051914Z_48d41482`, all nine evaluation
rows, the 0/9 baseline summary and 232-minute saved training readiness. Stale
monitoring correctly withheld live candidate forecasts. The launcher probes
the actual TCP ports and pins Streamlit to port 8501 to avoid silent port changes.

## Display the completed training run

The Models tab now summarizes the explicitly selected run's held-out comparison,
including models beating persistence, its saved training-cohort readiness and
anomaly evaluation status. The first real run reports 0/9 beating persistence.
This does not enable deployment or scaling. Current monitoring-window readiness
is displayed separately and may fail even when the saved training cohort passed.
Fresh out-of-sample input is still required for live candidate forecasts.

Start both local servers with the selected run from a PowerShell terminal:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File infrastructure/start-dashboard.ps1
```

The launcher selects `models/runs/20261116T051914Z_48d41482`, configures the existing
project/billing export, and starts loopback servers. It refuses occupied ports and
keeps the supervising terminal open. Logs and process IDs are under
`data/dashboard_logs/`. Use `-ForecastRun models/runs/ANOTHER_TRUSTED_RUN` only for
an explicitly reviewed native run. Alternatively set `DASHBOARD_FORECAST_RUN` in
the API terminal before starting Uvicorn. No `.env` file is implicitly loaded.

This Streamlit dashboard consumes `GET /api/overview` from FastAPI.
Its Recommendations tab now supports local saved reviews and decisions; see
[review workflow](recommendations.md#local-recommendation-reviews). Restart the
API after updating code, refresh Streamlit, then use Save current recommendations
for review or Load review history. Decisions never execute cloud actions.
The UI defaults to BigQuery with an explicit local-snapshot alternative. It shows
the configured service's Monitoring observations, missing measurements,
historical charts, deterministic threshold recommendations and the active training
run's recorded progress. It never starts traffic, trains models or calls Gemini.
It does not deploy or execute infrastructure actions.

The API filters by configured project, region and `autocloud-api`, deduplicates
by logical record ID and latest collection time, rejects conflicting/future
evidence and preserves nulls. Charts insert missing minute buckets without filling
them. The request total covers measured buckets only. Last-observed CPU, memory
and latency are historical when the freshness warning is shown.

Run these commands in separate Command Prompt windows in the project folder.
Leave the traffic experiment's terminal running.

Install optional dashboard dependencies (may take a few minutes):

```cmd
.venv\Scripts\python.exe -m pip install -r requirements-dashboard.txt
```

Start the local API:

```cmd
set GCP_PROJECT_ID=astute-sign-506809-j8
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Start the dashboard in another terminal:

```cmd
.venv\Scripts\python.exe -m streamlit run app/dashboard/home.py --server.address=127.0.0.1
```

Open http://localhost:8501. The sidebar offers BigQuery or local snapshot and
1/6/12/24-hour windows. Refresh reads BigQuery through the API, with a 60-second
per-worker cache. The scheduled collector writes BigQuery, not this computer's
snapshot, and new measurements appear only after Monitoring ingestion and the
collector's next successful write. Dashboard refresh does not run collection.

`GET /api/overview?source=bigquery&hours=24` reads the existing regional
`autocloud.latest_metrics` view. The local endpoint default remains unchanged
for compatibility. Queries filter project, region, service and measured source,
use timestamp parameters and at most 1,440 rows, and set a 100 MB billed-byte cap.
Query submission/result timeouts are 10/20 seconds with best-effort cancellation;
provider authentication/retries can add latency. The dashboard HTTP timeout is
45 seconds. Failures are sanitized and cached for 60 seconds; no local fallback
is performed. A local snapshot is used only when explicitly selected.

The API process uses existing ADC and needs permission to run BigQuery jobs and
read the existing dataset. No permissions are granted by this implementation.
Restart the local API after updating its code (Ctrl+C only in the API terminal,
then rerun the Uvicorn command above). Leave the traffic terminal untouched.
The dashboard reloads its script when saved; refresh the browser if needed.

Coverage shows observed buckets out of expected minute boundaries in the query
window, including leading/trailing gaps. It is not ML readiness. Query fetch
time, cache status and latest observation time are separate. The dashboard does
not automatically discover or load experiment/model artifacts.

An active heartbeat older than three minutes is flagged as possibly stalled.
A recent heartbeat does not verify process liveness. Terminal outcomes are the
runner's recorded statuses, not independent evaluation. Final invoice costs,
service estimates and measured savings remain unavailable. Local recommendation
reviews are available; infrastructure approval and execution remain unavailable.

## Billing dashboard

In the **API terminal**, configure the already-existing export, then restart only
Uvicorn. Keep the traffic terminal running; its training hold remains in place.

```cmd
set GCP_PROJECT_ID=astute-sign-506809-j8
set DASHBOARD_BILLING_TABLE=astute-sign-506809-j8.autocloud_billing.gcp_billing_export_v1_011640_0793FF_B5C560
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

The Costs & actions tab reads `GET /api/costs?days=1` only after **Read billing
export** is clicked. Ordinary monitoring refreshes do not query billing. The API
accepts 1..31 trailing days; table selection comes from server configuration,
not the browser. Successful and failed requests are cached per worker for five
minutes. The reader uses the export's location, project and Cloud Run filters,
parameterized timestamps, a 100 MB billed-byte cap, 10-second query submission
and 20-second result timeouts with best-effort cancellation. Authentication and
provider retries can add latency. No export setup, IAM or cloud changes occur.

Amounts are exact Decimal strings. Totals are kept separate by currency; signed
credits and negative adjustments are retained. Daily UTC rows and cost types
are shown without filling missing days with zero. First/last days can be partial.
Query fetch time, latest matching usage time and export delivery time are distinct.
No matching rows means unknown cost, while a recorded zero net cost remains zero.

The export covers all Cloud Run resources and regions in this project, including
jobs. It is not the cost of autocloud-api alone, a project-wide total across GCP
products, or a final invoice. Service estimates and measured savings stay null
without their separate verified inputs and experimental evidence. Billing
reporting remains independent of ML readiness and model selection.

## Models tab

The API assesses exploratory readiness for the selected dashboard observations
using the existing 200-minute, missingness, variation and purged split gates.
This window is not the isolated experiment cohort and can have different
readiness. The assessment never trains a model, selects artifacts automatically
or approves deployment.

After a real run completes, select its trusted native candidate directory in
the **API terminal** and restart Uvicorn:

```cmd
set DASHBOARD_FORECAST_RUN=models\runs\ACTUAL_COMPLETED_RUN_DIRECTORY
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Replace the directory placeholder with the actual successful training CLI result.
Do not run another Uvicorn process on the same port; stop only the existing API
process first. Leave collection running. This configuration is read at startup,
never accepted as a browser-supplied path. Leave it unset until a run completes.

The API validates the native manifest, scope, schema, XGBoost version, training
history and nine model hashes before accepting recorded evaluation. It compares
recorded MAE and sample counts to manifest metadata, rejects nonfinite scores and
shows held-out MAE/RMSE alongside persistence for each target/horizon. Integrity
hashes are not authenticity signatures; select only trusted local runs.

Candidate forecasts reuse the existing native inference checks: fresh origins
later than the full training/evaluation history, sixteen consecutive measured
CPU/memory/request minutes, matching feature schema and native model hashes.
Missing lag features are disclosed and imputed with training-only statistics.
Evaluation stays visible when inference is unavailable. Origin time, forecast
time, remaining lead time and expiry are separate; expired forecasts remain
labelled in the table and are omitted from charts. Utilization errors use
fractions, request errors use requests per minute. Exploratory results remain
preliminary, with no calibrated confidence or deployment authority.

The dashboard never deserializes the saved anomaly joblib file. Live anomaly
inference and anomaly accuracy displays remain pending; no independent labels
or evaluation quality are inferred from collection success. Future work includes
independently evaluated anomaly inference and approval persistence.

No cloud deployment is part of this increment. Keep local servers bound to
loopback; the deployed Cloud Run service continues using its existing revision.

References: [Streamlit charts](https://docs.streamlit.io/develop/api-reference/charts/st.line_chart)
and [launching Streamlit](https://docs.streamlit.io/develop/api-reference/cli/run).

## Sparse latency display

The latency card shows the last measured minute's mean latency in the selected
window, with its timestamp and age. A value from an earlier observation or more
than 15 minutes old is labelled historical. If no latency exists, the card says
"Not measured". A latest measured request count of zero is distinguished from
missing request/latency evidence. Charts, stored records, model inputs and
readiness gates retain their original nulls; this display does not forward-fill
data or generate traffic.

## Plain-language model and recommendation views (17 November 2026)

Models is organised around four questions: whether predictions are available,
whether recent activity needs investigation, what recorded evaluations establish,
and whether the selected data could support another exploratory training run.
Forecasts use percentage displays for CPU/memory and requests/minute for traffic.
Charts retain gaps and exclude expired horizons. The persistence comparison is
labelled "Keep current value" and explained alongside MAE; forecast wins are
explicitly not accuracy percentages. Original and newer cohorts remain separate.
Scores, evaluation records, readiness reasons and the audit trail remain available
in collapsed technical sections. Missing/stale assessments never imply health.

Recommendations show the reason, evidence source and next investigation step in
individual cards. Raw evidence and detailed threshold checks are collapsed.
Gemini is optional, runs only on explicit request, and its skipped/error states
explain the recorded reason without claiming an unverified root cause. Timestamps
in the new summaries use IST; underlying records retain their UTC timestamps.
These are presentation changes, with no retraining, gate relaxation, data writes,
new Gemini calls or infrastructure execution.


Verified cloud rollout: dashboard revision `autocloud-dashboard-00015-9cp` is live. All 314 tests passed; anonymous Streamlit rendering and measured/demo switching passed. API revision `autocloud-api-00016-7ph`, environment settings, identities, IAM and scaling were verified unchanged. Release evidence: `data/releases/20261117T094739Z-public/`. No Gemini verification request or BigQuery write was made.
