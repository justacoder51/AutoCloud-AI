# AutoCloud AI — handoff to Antigravity

Prepared 16 November 2026. This describes recorded verification, not a fresh
inventory of cloud state. The user paused further changes to move development
to Antigravity. Read this before continuing; do not restart completed work.

## Workspace and instructions

- Project: `C:\Users\sihan\Desktop\cloud sem end project`.
- Windows, PowerShell; Python: `.venv\Scripts\python.exe`.
- Read `CLAUDE.md` and authoritative `Cloud.md`, then this file and the linked docs.
- Git has substantial modified and untracked implementation files. Do not reset,
  clean, overwrite or assume they are committed/pushed. Review before committing.
- `data/` and `models/` are ignored by git and contain important evidence and
  trained artifacts. Opening this same folder preserves them; a git clone alone
  does not. Preserve these directories separately if moving machines.
- Use ADC and service accounts. Never print, copy into images, commit or share
  credentials. No service-account keys were created for this deployment.
- Do not start additional traffic, relax readiness gates, retrain to chase the
  inspected test set, deploy the experimental models or enable autonomous scaling.
  New cloud changes must stay within explicit user authorization.

## Completed implementation

- Real Cloud Monitoring collection and BigQuery ingestion/deduplication view.
- Local FastAPI/Streamlit monitoring, charts, missingness and stale-data handling.
- Billing export reader and dashboard; exact signed credits, separate currencies,
  bounded queries, explicit reads. Empty export is unknown cost, not zero.
- Isolation Forest and nine XGBoost forecasts trained on measured experiment data.
- Recorded model evaluation integrated into local and cloud Models tabs.
- Local SQLite recommendation snapshots, final approve/reject decisions and
  history. Investigation approval never authorizes a cloud change.
- LangGraph workflow and optional Vertex Gemini constrained selection adapter.
- Manual cloud Recommendations controls: Run AI analysis, optional Gemini and
  billing, and a separate Gemini connection probe. Refresh does not call Gemini.
- Private API/dashboard Cloud Run deployment and authenticated browser access.
- Bounded live operator minimum-instance trial 0 -> 1 -> 0, verified restored.
- Deleted the stopped `gemma-api` VM, disks `gemma-api` and `gemma-api-l4`, and
  reserved addresses `gemma-api-ip` and `gemma-api-l4-ip`; all five returned 404
  on verification. Do not recreate them. Artifact Registry repositories were
  not deleted as part of that cleanup.

## Exact current task and status

The user asked: "start to connect LangGraph + Gemini; also notify me when done."
**Completed on 16 November 2026:** Following explicit user approval of the
minimal grant in `data/releases/gemini-permission-plan.json`:

- Created custom role `projects/astute-sign-506809-j8/roles/autocloudGeminiPredict`
  with ONLY `aiplatform.endpoints.predict` (`stage: GA`) and bound it on project
  `astute-sign-506809-j8` to
  `serviceAccount:autocloud-api-reader@astute-sign-506809-j8.iam.gserviceaccount.com`.
- Saved pre-update service configuration to
  `data/releases/20261116T072454Z/autocloud-api-before-gemini.json` and patched
  `autocloud-api` to set `DASHBOARD_GEMINI_ENABLED=true` while retaining
  `DASHBOARD_GEMINI_MODEL=gemini-3.5-flash-lite`, the existing image digest,
  120s timeout, service account, scaling (`0 / 2`), and private IAM.
- Verified ready revision `autocloud-api-00004-bwt` (generation `6`):
  unauthenticated `/health` returned HTTP 403; authenticated `/api/overview`
  reported `gemini_enabled=true` and `gemini_model="gemini-3.5-flash-lite"`;
  explicit connectivity probe (`connectivity_check=true`) returned HTTP 200
  (`status=completed`, `mode=connectivity_probe_only`,
  `workflow_status=connectivity_checked`, `gemini.status=succeeded`,
  `execution_allowed=false`; saved in
  `data/releases/20261116T072454Z/gemini-connectivity-verification.json`).
- After respecting the 60-second cooldown, the measured LangGraph + Gemini
  workflow (`use_gemini=true`, `hours=24`, `include_billing=false`) returned
  HTTP 200 (`status=completed`, `data_status=fresh` with latest observation
  `2026-11-16T07:42:00+00:00`, `workflow_status=no_supported_action`,
  `gemini.status=succeeded`, `model_analysis.status=not_evaluated`,
  `cost_analysis.status=usage_or_billing_export_required`,
  `execution_allowed=false`; saved in
  `data/releases/20261116T072454Z/analysis-verification.json`).

## Cloud deployment

Project `astute-sign-506809-j8`, region `asia-south1`.

| Service | URL | Latest verified ready revision | Min / max |
| --- | --- | --- | --- |
| API | https://autocloud-api-l25hfnltba-el.a.run.app | `autocloud-api-00007-x5w` | 0 / 2 |
| Dashboard | https://autocloud-dashboard-l25hfnltba-el.a.run.app | `autocloud-dashboard-00006-fhw` | 0 / 1 |

Both are IAM-private; unauthenticated 403 is expected. Do not make them public.
API identity: `autocloud-api-reader@astute-sign-506809-j8.iam.gserviceaccount.com`.
Dashboard identity: `autocloud-dashboard@astute-sign-506809-j8.iam.gserviceaccount.com`.

Approved/applied IAM: API has project BigQuery Job User, project custom role
`projects/astute-sign-506809-j8/roles/autocloudGeminiPredict`
(`aiplatform.endpoints.predict` only), READER on the `autocloud` dataset, Data
Viewer on the exact billing export table below, and bucket-scoped
`roles/storage.legacyBucketReader`, `roles/storage.objectCreator`, and
`roles/storage.objectViewer` on `astute-sign-506809-j8-autocloud-reviews`.
Dashboard has Cloud Run Invoker on the API service. No Owner/Editor roles or
keys were granted to these runtime identities. Cloud Resource Manager API was
enabled as a prerequisite to the approved project-role grant; Vertex API was
already enabled.

API timeout 120 seconds; dashboard timeout 3600 seconds for WebSockets.
`PYTHONPATH=/app` fixes Streamlit console-entrypoint application imports.
The cloud image includes the checksummed recorded evaluation summary, not model
weights or local datasets. Cloud inference is explicitly `not_deployed`.

Cloud Run local disks are ephemeral: `autocloud-api` uses Cloud Storage bucket
`astute-sign-506809-j8-autocloud-reviews` (`ASIA-SOUTH1`, uniform bucket-level
access, public access prevention enforced) via `DASHBOARD_REVIEW_BUCKET` /
`DASHBOARD_REVIEW_AUDIENCE` for durable immutable cloud reviews, while local
SQLite history remains on the workstation for local runs.

Latest release: `data/releases/20261116T110246Z/` and
`data/releases/ai-current.json`. Build `a1be38c7-e86a-4694-b6f8-f0188aae27e4`
succeeded. Image digest:
`sha256:1e5195a7732da62f16de800cc2d10ae0437d7e2e63cefcd71b7a1b11f262d8f1`
(includes R1–R7 security/evaluation fixes and `config/dashboard-evaluation.json`
`sha256: 9461e93bd134b2650edc71166f09aefaf6a5fe29221560550f3dc3b8d5234841`).
Older releases `data/releases/20261116T090610Z/`, `data/releases/20261116T072454Z/`,
and `data/releases/20261116T055002Z/` retain prior service backups and verification.
Release metadata includes pre-update service state for rollback. Use current
etags for any future update; do not replay stale ones.

## Access from a browser

Port 8501 is the local dashboard. Port 8503 forwards to the private CLOUD
dashboard. Use numeric loopback `127.0.0.1`; `localhost` failed in the in-app
browser while numeric IPv4 worked. Proxy processes may no longer be running
after the previous agent session ends. From the project directory:

```cmd
.venv\Scripts\python.exe -m app.dashboard.private_proxy --url https://autocloud-dashboard-l25hfnltba-el.a.run.app --port 8503
```

Open http://127.0.0.1:8503/. Dependencies: `requirements-proxy.txt`. The proxy
uses existing developer ADC ID tokens in memory, rejects cross-origin requests,
and supports Streamlit WebSockets; no credentials are put in browser URLs.
Keep the proxy terminal running. Its outbound HTTP honors the environment's
network proxy; ordinary local dashboard-to-API calls use `trust_env=False`.
The Cloud SDK proxy binary failed in the prior managed environment; the Python
proxy was successfully browser-verified. On a normal terminal the official
alternative is `gcloud run services proxy autocloud-dashboard --project=astute-sign-506809-j8 --region=asia-south1 --port=8503`.

Cloud services and the collector/Scheduler remain enabled; no shutdown was
requested. Collector job `autocloud-collector`, Scheduler `autocloud-collect`,
schedule every 15 minutes. Active WebSocket sessions, query jobs and storage may
incur charges even with minimum instances zero. Exact current spend is unknown.

## Data and model outcome

Experiment `1c4121e4baad4aa3bf61776d28a232dc` finished collection with 2,097
successful HTTP requests. Its original `status.json` says `training_not_ready`,
but the nested result is actually `training_paused` due to the then-active user
hold. The user later explicitly resumed training; preserve the historical run
status and refer to its `resumed_training_result.json` for the separate fit.
The old hold marker was renamed with a `HOLD_TRAINING.resumed_...` suffix.
Do not restart that completed experiment.

Training input: `data/training_inputs/experiment_1c4121e4baad4aa3bf61776d28a232dc/`.
232 consecutive measured minutes, 2026-11-15 18:09 through 22:00 UTC. Selection
was fixed before fitting; no value-based filtering. Missingness <=9.05%; unchanged
exploratory gates passed. The full gappy history still fails; do not confuse its
dashboard-window readiness with the isolated saved cohort's readiness.

Saved run: `models/runs/20261116T051914Z_48d41482/`.
Contains evaluation, measured history, native manifest and nine XGBoost JSON
models, plus local Python bundles. Native scope/readiness/history/model checksum
validation passed. Training writer was fixed to save exact UTF-8 bytes on
Windows; the original CRLF history was restored to match its original LF hash.
The integrity gate was not weakened and models were not refit during repair.

**Zero of nine XGBoost forecasts beat last-value persistence on held-out MAE**,
while **five of nine beat the training historical-average baseline** (with
`forecast_diagnostics` quantifying the active-regime `request_count_5m`
improvement `0.1960` vs `0.7836` MAE and post-cutoff cessation error). On a
reproducible 1,800-minute (`conservative`, `.venv\Scripts\python.exe -m app.models.benchmark`,
`seed=42`, `dataset_sha256: da1b193e0a013311b13ec87ec25c2f8e0c35eb75373349233a4844dfc07c3a36`)
synthetic multi-cycle benchmark (`models/representative_forecast_benchmark.json` —
`1.25` daily clock cycles plus `62.8m`–`251.3m` shorter harmonic cycles), the
unchanged `ResourcePredictor` beat both Persistence (`9/9`) and Historical
Average (`9/9`); this verifies pipeline mechanics only and does not replace
the `0/9` real-data result. Do not deploy the exploratory real-data models for
scaling or claim superior real-world accuracy. Test data has already been
inspected: avoid repeated tuning against that same test set.
Isolation Forest held-out evaluation (`47` test minutes) was completed against
post-hoc experiment-event labels (`anomaly_labels_regime_shift.csv` /
`anomaly_labels_operational_fault.csv`): Isolation Forest detected post-experiment
regime shifts with `precision=1.0`, `recall=0.9524`, `f1=0.9756` (`20/21`, `[[26, 0], [1, 20]]`
across 47 rows vs threshold baseline `[[26, 0], [15, 0]]` across 41 observable rows,
and `[[26, 0], [0, 15]]` `F1=1.0000` on the like-for-like 41-row shared-observable
cohort), while the operational-normality audit (assuming all 47 rows healthy with
`0` positive fault examples; fault sensitivity unmeasured) measured a `42.55%`
(`20/47`, or `36.59%` = `15/41` shared) FPR because planned idle/scale-to-zero
differs from active-traffic training (`evaluation.json`,
`config/dashboard-evaluation.json` locally updated to
`sha256: 9461e93bd134b2650edc71166f09aefaf6a5fe29221560550f3dc3b8d5234841`;
cloud container image `autocloud-api-00006-pgf` still holds prior packaged copy
`781c05a06af17312b74f09b8405e9f7d1c4a8fe753627e1362cea4f6fa3bc82f` and pre-R1
review auth until the next user-approved rebuild). Anomaly inference remains
`not_deployed`. Traffic success and fixture tests prove neither accuracy nor savings.
Forecast horizons are 5/10/15 minutes; default exploratory requires 200 observed
minutes plus missingness/variation and purged measured 100/20/20 split labels.
Conservative 1440-minute profile remains available. Gates were not relaxed.

Metrics view: `astute-sign-506809-j8.autocloud.latest_metrics`.
Billing table:
`astute-sign-506809-j8.autocloud_billing.gcp_billing_export_v1_011640_0793FF_B5C560`.
Last verified export query had no matching Cloud Run rows. Unknown is not zero;
scope is all Cloud Run resources/regions in the project, not one API's bill.

## Key code and verification

- `app/agents/orchestrator.py`: actual finite LangGraph, optional Gemini selection,
  revalidation and no executor. `vertex_service.py`: bounded structured response.
- `app/services/analysis_service.py`, `app/api/analysis.py`,
  `app/dashboard/analysis.py`: new dashboard integration. POST `/api/analysis`
  accepts bounded options only; server owns scope and evidence. Duplicate options
  cache for 60 seconds per worker; different options during cooldown return 429.
- `app/services/model_dashboard.py`, `recorded_evaluation.py`: keep historical
  evaluation separate from current readiness and live inference.
- `app/services/review_store.py`, `app/api/reviews.py`, `app/dashboard/reviews.py`:
  dual-mode review workflow — local SQLite (`ReviewStore`) in non-production
  local mode, and durable authenticated Cloud Storage (`CloudReviewStore` with
  `if_generation_match=0`, `by_time/` bounded latest-200 index, and dual-header
  cryptographic Google OIDC verification via `X-AutoCloud-Authorization` and
  `DASHBOARD_REVIEW_BUCKET` / `DASHBOARD_REVIEW_AUDIENCE`, explicitly distinguishing
  `calling_service_principal` from self-reported human reviewer labels
  `service_authenticated_self_reported_label`). Deployed and live-verified on
  `autocloud-api-00007-x5w` / `autocloud-dashboard-00006-fhw`
  (`data/releases/20261116T110246Z/verification.json`).
- `app/services/cloudrun_service.py`, `scaling_trial.py`: operator-only bounded
  trial. Evidence is in `data/scaling_trials/.../live_result.json`; min 0 -> 1 -> 0
  restored, max 2 and serving revision unchanged, no active recovery marker at
  final verification. This was not a performance/cost optimisation experiment.
- `infrastructure/dashboard.Dockerfile`, `requirements-cloud.txt`: cloud image.

Prior full suite baseline: **217 passed** (`ANTIGRAVITY_REVIEW_2026-11-16.md`).
After local R1–R7 remediation, run the full offline suite in an unrestricted
PowerShell terminal (fresh basetemp avoids sandbox temp permissions; Streamlit
test shutdown emits a Windows PermissionError cleanup message after a successful
exit and is not a failed test):

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp C:\Users\sihan\AppData\Local\Temp\autocloud-check
```

Cloud/browser verification: prior revision `autocloud-api-00003-6gf` was
browser-verified with Gemini disabled; after applying the approved
`autocloudGeminiPredict` grant and updating to `autocloud-api-00004-bwt`,
authenticated live verification confirmed `capabilities.gemini_enabled=true`,
successful `connectivity_probe_only` (`gemini.status=succeeded`), and a
fresh-evidence measured workflow run (`data_status=fresh`,
`workflow_status=no_supported_action`, `gemini.status=succeeded`,
`execution_allowed=false`).

## Remaining work

1. ~~Obtain explicit approval for the exact Gemini inference grant above, then
   enable and live-test it.~~ Completed 16 November 2026 (`autocloud-api-00004-bwt`).
2. ~~Independent anomaly ground-truth labeling and accuracy evaluation.~~
   Completed 16 November 2026 (`models/runs/20261116T051914Z_48d41482/evaluation.json`;
   live anomaly inference remains disabled due to `42.55%` idle FPR and absence
   of server-fault labels).
3. ~~Representative forecasting evaluation/improvement against persistence, using
   a new independent test set if models are changed.~~ Completed 16 November
   2026 (`5/9` beat historical average on the 232m real cohort with active vs
   idle regime breakdown; `9/9` beat persistence & historical average on the
   1,800m conservative multi-cycle synthetic benchmark in
   `models/representative_forecast_benchmark.json`; exploratory real models remain
   undeployed).
4. ~~Durable authenticated cloud recommendation review history & R1–R7 hardening.~~
   Deployed and verified on 16 November 2026 (`autocloud-api-00007-x5w`,
   `autocloud-dashboard-00006-fhw`, bucket `astute-sign-506809-j8-autocloud-reviews`,
   release `data/releases/20261116T110246Z/`), including R1 403 rejections and live
   authenticated Streamlit WebSocket `"Load review history"` UI verification.
5. **Item 5 partially verified (isolated live Gemini breach + restart persistence;
   live Streamlit WebSocket `"Load review history"` check passed; real BigQuery
   shows 0 active production breaches):** on 2026-11-16T10:54:40Z,
   `GET /api/overview?source=bigquery&hours=1` returned HTTP 200
   (`latest_observation="2026-11-16T10:03:00+00:00"`, idle/scaled to zero,
   `data_status="stale"`, `recommendations_count=0`) and `GET /api/reviews`
   returned `items_count=0`. On an isolated in-memory 3-minute sustained breach
   fixture (`cpu=0.94`, `memory=0.92`, `error_rate=0.08`), one live regional
   `gemini-3.5-flash-lite` `run_workflow(..., use_gemini=True)` call succeeded
   (`workflow_status="awaiting_human_review"`, all 3 actions ordered with
   `validated_template` explanations and `execution_allowed=false`), and restart
   persistence passed on re-instantiated SQLite `ReviewStore` and isolated
   `CloudReviewStore` (`data/releases/20261116T090610Z/breach-gemini-isolated-verification.json`).
   Additionally, after deploying `autocloud-dashboard-00006-fhw` / `autocloud-api-00007-x5w`,
   an authenticated Streamlit WebSocket UI check confirmed `"Load review history"`
   works end-to-end (`data/releases/20261116T110246Z/verification.json`). End-to-end
   save/decision persistence across a live Cloud Run restart on a **real**
   production breach still awaits a legitimate production breach event (never
   fabricate production BigQuery/GCS breach rows).
6. **Item 6 checked (live `/api/costs` + Streamlit billing UI + counterfactual cost
   model saved in `data/releases/20261116T110246Z/cost-evaluation-summary.json`):**
   At `2026-11-16T11:28:52Z`, `GET /api/costs?days=7` and `days=31` both returned
   HTTP 200 with `status="no_exported_rows"`, a 31-day BigQuery diagnostic query
   confirmed `0` billing export rows across all services in
   `astute-sign-506809-j8.autocloud_billing.gcp_billing_export_v1_011640_0793FF_B5C560`,
   and the live Streamlit WebSocket UI check clicked **`Read billing export`**
   with zero error (`rendered_no_exported_rows_warning=true`). Actual Cloud Run
   spend stays unknown until Cloud Billing delivers rows. Counterfactual Tier-1
   `asia-south1` list-rate estimates (`CostAnalyser`, excluding free tier) show
   `USD 0.3377388` (24h `min_instances=1`) vs `USD 0.0159888` (`min_instances=0`,
   `estimated_savings=USD 0.3217500`, `counterfactual_estimate_not_measured`,
   `measured_savings=null`) and `USD 0.1094400/day` for `autocloud-collector`
   (96 cron attempts/day at 1m min). Re-run `/api/costs` once Billing rows arrive
   and complete authorized before/after performance/cost evaluation before claiming
   real savings.
7. **Item 7 completed (`docs/final-report.md` and `docs/presentation-outline.md`) +
   post-release `CloudReviewStore` local fixes:** drafted the final semester-end
   technical report and 10-slide presentation/demo guide. Also fixed two edge
   cases in `app/services/review_store.py` (repairing failed `by_time/` index
   writes on retry via `items/<id>.json` readback, and reading remaining slots
   from `items/` when `len(by_time/) < 200` so legacy unindexed reviews remain
   visible alongside newer indexed items), verified locally with two new
   regression tests in `tests/test_reviews.py`. Note: those two local
   `review_store.py` fixes are not yet baked into the `20261116T110246Z` Cloud
   Run image (`autocloud-api-00007-x5w`) unless another rebuild is approved.

Read `docs/dashboard-ai.md`, `docs/cloud-dashboard.md`, `docs/training-results.md`,
`docs/scaling-trial.md`, `docs/recommendations.md` and `docs/status.md`. Some older
sections in project docs describe historical milestones; this dated handoff and
the latest release evidence clarify the final known state. No new cloud audit
or mutation was performed merely to create this handoff.
