# Implementation status

## Synthetic demo deployed and verified — 17 November 2026

The public dashboard now has a sidebar **Data mode** radio with **Measured monitoring** (default) and **Synthetic demo**. The isolated demo supplies complete fictional usage charts, illustrative trend projections, scripted threshold alerts and demo guidance with prominent synthetic labels. It performs no BigQuery/API/Gemini calls, model training, forecast-ledger writes or infrastructure actions. Real observations and model gates are unchanged. See [Synthetic demonstration mode](synthetic-demo.md).

Dashboard-only release `20261117T075434Z-public` uses image `sha256:a489438ddc93b462cd76577076f0cca4a7d1b9093deeefd7483ef8b440e6d3bf`; Cloud Build `cdf6f31b-eb81-4131-92f6-c4ae7fb7346f` succeeded. Dashboard revision `autocloud-dashboard-00014-dt7` is ready. API remains `autocloud-api-00016-7ph`; its containers are unchanged. Recorded comparisons confirm dashboard IAM, scaling and environment settings are unchanged. No demo rows were inserted into BigQuery.

Validation: 292 offline tests passed; dependency/compilation checks passed. Anonymous HTTP/Streamlit verification passed for measured monitoring, synthetic demo and switch-back. Live demo rendered ten charts, two tables, five metrics, synthetic/model limitations and zero errors. No Gemini request was made. The first demo checker exposed a protobuf element-name compatibility difference (`dataframe` versus `arrow_data_frame`), fixed in the checker without changing the deployed app. Saved evidence: `verification-synthetic-demo.json`, `verification-dashboard-public.json`, `preserved-settings.json` in the release directory. The previous handoff is unchanged.

## Approved thirty-minute lab execution — 17 November 2026 IST

Private lab revision `autocloud-validation-lab-00001-pk4` is deployed, preflight passed, and actual traffic started at 00:21:57 IST with confirmed HTTP200 receipts. Stop is due by approximately 00:52 IST, then deletion before delayed metric collection. The experiment is still running, not completed.

User authorised a maximum thirty-minute campaign. See [Short validation run](short-validation-run.md). New capsule `20261116T184804Z`, plan SHA `43a8ba0002045e733e4a5fd52084de182781bd71bba2e9f04c484b807e921dc9`, maximum 450 requests. Dedicated minimal image built successfully (`6d8407d8-8081-4d81-8b75-26e8fec409f2`, digest `f8d655b22f9705299255d7a67517ea19ee7bf99e6585d4c6fde2cd7fa4d64ca4`); private lab deployment is in progress. The finite supervisor deletes the lab before waiting for delayed measurements, including after traffic failure. Full suite: 289 passed. No completed experiment or new accuracy claim yet. Production services and frozen model artifacts remain unchanged.

## Controlled validation preparation — 17 November 2026 IST

Prepared and locally tested a private fault-lab campaign; **no cloud build, service, identity or fault/load traffic has been started for it**. See [Controlled validation pilot](controlled-validation-pilot.md) for the frozen plan, hashes, 120-minute schedule, resource/request limits, independent actuation/outcome labels, scoring and cleanup commands. Capsule: `data/validation_campaigns/20261116T183803Z`. Plan SHA-256: `c21a61f29fc9fcce8f9939d7a5889e5780ca20e96eb8168419bc580b5a808e16`. Full offline suite: 288 passed. Production and model artifacts are unchanged. Approval is needed for the billable dedicated lab and bounded traffic under the earlier restriction on extra traffic/infrastructure experiments. This is an out-of-domain pilot; representative multi-day application validation and operational reliability remain unestablished.

Date: 2026-11-16 (reconciled following `ANTIGRAVITY_REVIEW_2026-11-16.md`).

## Current measured-validation release - 16 November 2026 (IST)

User scope: ML validation and measured cost evidence; OAuth onboarding is excluded. Release `20261116T175035Z-public` is deployed: API `autocloud-api-00016-7ph`, dashboard `autocloud-dashboard-00013-sdq`, image `sha256:8ece153fbb01f2f2b7c9d33057052ce036fc3e4955adcc1711d96ad2b2e3e35c`; Cloud Build `2f2799ef-f31a-4e5f-8309-820dda7551e5` SUCCESS. Public URL is unchanged.

### Actual measured outcomes

A registered, model-frozen temporal study collected 438 post-training-cohort measured minutes and 249 separately collected request-log records. All nine forecasts were evaluated without fitting or selecting on the snapshot. **CPU forecasts win on point MAE at all three horizons; memory and request forecasts lose (3/9 wins).** All CPU paired hour-block intervals adjusted for nine comparisons include zero. One changing development/verification workload and few blocks do not establish general superiority. The original saved cohort remains 0/9; the cohorts are distinct.

Four real /api/reviews HTTP503 request minutes provide separate-source availability labels. The strict request-count-matched comparison contains four positive and thirty-five no-observed-5xx minutes. Raw Isolation Forest flags all thirty-nine (TP4/FP35/TN0/FN0), so it is not a reliable availability detector at its current threshold. The measured error-rate signal agrees with the four positive and thirty-five no-5xx outcomes, but it already encodes the contemporaneous outcome: this is detection consistency, not independent learned fault prediction, early warning or general fault accuracy. One incident type and correlated minutes limit confidence.

The billing export table has zero rows and no matched rows over the bounded seven-day read. Costs and measured savings remain null, not zero. The billing linkage API returned 403, and the Billing Console requires sign-in; export account/settings could not be verified. There is no comparable optimisation baseline/treatment experiment. No positive savings claim is supported.

### Delivered validation features

- Models tab now shows the additional measured study, MAE comparisons, sample sizes, uncertainty, log-labelled outcomes and cost-evidence gap. The report is checksummed and scoped to the matching frozen model files.
- Added a recent measured-server-error recommendation independently of the experimental model and the sustained-pressure rule; it indicates an observed symptom, not a cause or permission to scale.
- Enabled an immutable prospective forecast ledger in the existing bucket. It records only already-computed future forecasts, at most one immutable record per model/origin. No traffic, training or infrastructure experiment is generated. The scorer requires the target to follow both application recorded time and GCS server creation time, with a later observed actual value. Unknown/expired/backdated predictions are excluded. The live check reported no eligible future forecasts, so **live archival/scored prospective accuracy has not yet been established**. Unit tests cover creation preconditions and anti-backdating. Set DASHBOARD_VALIDATION_LEDGER_ENABLED=false to stop recording; subsequent releases preserve an explicit setting.

### Verification and evidence

**280 tests passed**; dependency and container/model checks passed. The staged API served the matching measured study and enabled ledger, rejected foreign-project access and restricted endpoints, and kept anonymous API access blocked. Anonymous public HTTP/Streamlit UI passed without errors; explicit checks found the new validation headings, 3/9 count and savings-evidence section. Runtime and model hashes, raw snapshots, sanitised request logs, separate availability-label CSV, financial source metadata and full evaluations are under `data/validation_studies/20261116T172907Z/`. Release evidence is under `data/releases/20261116T175035Z-public/`.

Detailed results, reproduction commands and cost-proof prerequisites: `docs/measured-validation.md`. Genuine savings require the billing owner to verify the export, matured attributed costs, comparable workload/SLO observations and approval for a concrete supported optimisation. Do not create wasteful baseline resources just to manufacture savings. Current testing-mode Gemini setting, IAM, scaling, five-minute collection and model weights remain unchanged. ANTIGRAVITY_HANDOFF.md remains unchanged (SHA-256 `598af1c6370583c993a4b381d7d96902c8832ae106b4b9b111a202055d1dce2e`).

## Current original-explanation and acceptance release - 16 November 2026, 22:48 IST

This supersedes the older live-release statements below. Public dashboard: https://autocloud-dashboard-l25hfnltba-el.a.run.app/ (no login). API remains private.

Release `20261116T170715Z-public`: API `autocloud-api-00015-cv5`, dashboard `autocloud-dashboard-00012-79r`; image `sha256:f0d40fa13bf67f4a44d9ac7a7358cac1601d43ac075c7b1c21da385648314334`; Cloud Build `0faef026-c179-4b30-8567-d3eb12b7ad2d` SUCCESS.

### Implemented and live verified

- Gemini writes a summary and original explanations tied to each approved investigation ID, rendered with cited evidence. Templates are excluded from its prompt, and exact template echoes are rejected. Text checks reject digit tokens, URLs and common command patterns; these are guardrails, not proof that generated prose is true. The UI explicitly requires source review. The first prose candidate echoed templates, was marked superseded, and was not accepted as original writing.
- Added sustained complete-window low-utilisation review guidance without downsizing instructions or savings claims. It appears only when measured conditions support it.
- Added operational annotations separating observed scale-to-zero, uncorroborated model flags and threshold-supported investigations. Raw model scores/flags remain visible. No raw detector score, weight or freshness gate was changed.
- Added validation-only forecast baseline comparison and a test that changing held-out test values cannot affect selection. The saved cohort is retrospective, previously inspected evidence: eight selected methods are baselines, one XGBoost, with zero test MAE wins over persistence. The recent mixed-window readiness check fails missingness limits. No new production weights were promoted.
- Hardened dormant onboarding code: initiating-session OAuth state matching, access-token subject/email binding, both required IAM permissions, revalidation before cached external-project reads, and tests covering swapped identities, partial permission and revocation. Production auth/project routes remain blocked.

### Acceptance evidence

Full offline suite: **271 passed**. Dependencies and container checks passed. Staged live API checks returned successful overview and **original Gemini prose**, differing from every checked template. Restricted routes returned 403; arbitrary prompts returned 422; anonymous API access remained denied. Anonymous public HTTP/Streamlit UI passed with zero errors and the Generate Gemini explanations button. A second live check exercised that actual public button without login and rendered completed Gemini explanations. Evidence: `data/releases/20261116T170715Z-public/{verification-api.json,gemini-original-explanation.json,verification-dashboard-public.json,verification-gemini-public-ui.json,live-overview.json}`.

Offline ML/readiness evidence: `data/ml_improvement/20261116/{validation_selection.json,recent_observation_readiness.json,anomaly_interpretation.json,onboarding_readiness.json}`. The retrospective operational audit has twenty raw flags and zero threshold-supported investigations across forty-seven assumed-healthy rows; fault recall remains unmeasured. A corroboration policy can miss real faults.

### Remaining gates, not completed features

- Independent representative ML validation and positive fault labels remain necessary; synthetic fixtures and reusing the inspected cohort cannot establish accuracy or savings.
- External-project onboarding is NOT live. Deployed OAuth client ID, secret, redirect URI and session secret are absent. Durable browser callback/session recovery, standard verifier storage/sealing, tenant-store request budgets, real consent and two-user/project isolation require acceptance before exposure. See `docs/completion-review.md` for concrete setup and release prerequisites.
- Testing mode remains enabled under the user's explicit instruction. Normal budget restoration is deferred until testing is explicitly finished. The release helper now preserves the existing testing flag so it does not silently re-enable unlimited mode after a deliberate restoration. Per-request bounds and Google quotas remain active; clicks can incur charges.

The report and presentation notes are reconciled in `docs/final-report.md`, `docs/presentation-outline.md` and `docs/completion-review.md`. The earlier detailed private-release report is retained under docs/archive. IAM, scaling, collector cadence and model artifacts are preserved. ANTIGRAVITY_HANDOFF.md remains unchanged (SHA-256 `598af1c6370583c993a4b381d7d96902c8832ae106b4b9b111a202055d1dce2e`).

## Current Gemini testing release - 2026-11-16

User explicitly requested removing application Gemini limits for testing. Release `20261116T163125Z-public` is deployed and verified: API `autocloud-api-00013-t7g`, dashboard `autocloud-dashboard-00011-bgh`, image `sha256:808ad74c823ce3513101acb491760a064deb3ad754ac29b6fdd76be45dad7f67`, Cloud Build `79e6d1aa-8c7f-4419-9812-06d612805118` SUCCESS.

`DASHBOARD_GEMINI_TESTING_UNLIMITED=true` bypasses the application hourly/daily budget and result cache. Every explicit button click may make a new billable Gemini request. No automatic requests occur on page refresh. Existing GCS reservations are preserved. Google quotas, per-request timeout/token bounds, freshness and evidence checks, and disabled infrastructure execution remain in effect. The API remains private and the dashboard public. No IAM, scaling, collector schedule, model artifact or previous handoff changes were made.

Validation: **262 tests passed**, dependency/container checks passed. **Two consecutive real Gemini requests returned `completed` with `budget_mode=testing_unlimited`**. This supersedes the earlier pending live Gemini generation check. Anonymous public HTTP and Streamlit WebSocket UI passed with no errors, displaying testing mode and no hourly-cap caption. Restricted routes and arbitrary prompts were rejected; anonymous API access remains denied. Evidence is in `data/releases/20261116T163125Z-public/`, including `gemini-testing-1.json`, `gemini-testing-2.json`, `verification-api.json`, `verification-dashboard-public.json` and deployed service configs.

Restore `DASHBOARD_GEMINI_TESTING_UNLIMITED=false` on the API to re-enable the normal hourly budget; the public caption follows the API capability response. Gemini continues to prioritise approved IDs, while factual explanations are checked templates. Successful requests do not establish model accuracy or savings.

## Current public recommendations release - 2026-11-16

Supersedes older release statements below. Public URL: https://autocloud-dashboard-l25hfnltba-el.a.run.app/ (no sign-in).

Release `20261116T161023Z-public`: API `autocloud-api-00012-7h9`, dashboard `autocloud-dashboard-00010-chc`; image `sha256:f1c42f208683dcbd7d4373454af41e47ff4960d2ce641400dc52d5f997f59f70`; Cloud Build `a3e93d08-262c-4696-a628-5216ba87556e` SUCCESS. Existing IAM, scaling, model artifacts and five-minute collection are preserved.

Public recommendations cite measured thresholds, experimental model flags and monitoring gaps. Stale evidence only recommends restoring monitoring. Each item is investigation guidance, with no execution or estimated savings. Gemini can prioritise approved IDs via an empty server-side POST to `/api/public-explanation`; explanations remain checked templates. Arbitrary prompts, scope changes and browser-origin inputs are rejected. Original analysis, billing and write routes remain blocked.

Shared model budget: one attempt per UTC hour (24/day), enforced by atomic immutable GCS reservations. Failed calls consume the hour. Results use separate immutable objects to match existing create/read-only storage permissions. Storage failures skip Gemini. Model requests use one SDK attempt, 30-second timeout and 256 output tokens. This is not a cap on all hosting/query/storage charges.

Verification: 259 tests passed, dependency/container checks passed, live HTTP/security and anonymous Streamlit WebSocket UI checks passed with zero errors. Recommendation explanation bodies and both expected buttons rendered. API remains private. Candidate forecasts and anomaly scoring were available on fresh evidence during verification; this is not proof of accuracy or savings.

Outstanding: the first staged candidate `20261116T160118Z-public` returned Gemini `failed`; its result-cache overwrite was incompatible with existing storage permissions. The final release uses separate immutable records and has a create-only regression test. The failed call consumed the 16:00-17:00 UTC reservation. The corrected live endpoint returned `hourly_limit` without another model call. Successful post-fix Gemini generation is UNVERIFIED until the next slot at **2026-11-16 17:00 UTC**. Test once using the public button with fresh evidence and retain the result. Do not delete the reservation or bypass the cap.

Evidence: `data/releases/20261116T161023Z-public/`, including release/build metadata, `verification-api.json`, `gemini-budget-verification.json`, `verification-dashboard-public.json`, `live-overview.json` and `rollback-plan.json`. The initial failure remains in the superseded candidate directory. Explicit rollback targets are the prior fully verified public API `00010-clq` and dashboard `00009-mq7`.

`ANTIGRAVITY_HANDOFF.md` is unchanged (SHA-256 `598af1c6370583c993a4b381d7d96902c8832ae106b4b9b111a202055d1dce2e`).

## Collection freshness fix — 2026-11-16 15:45 UTC

User explicitly approved five-minute collection and one immediate execution. Changed only Scheduler `autocloud-collect` schedule from `*/15 * * * *` to `*/5 * * * *`; existing collector image, identities, limits, lag and model quality gates remain unchanged. Expected scheduled executions increase from 96 to 288 per day. Updated `infrastructure/collector.ps1` and `docs/scheduled-collection.md` to match.

The explicitly requested collector execution completed successfully at `2026-11-16T15:45:38Z`. The dashboard API then returned successful BigQuery reads with latest observation `15:42:00Z` (235 seconds old), CPU `0.711%`, memory `48.456%`, and `data_status=fresh`. Isolation Forest returned `experimental_observation_only`. XGBoost remained unavailable because sixteen consecutive measured target minutes were not available; freshness is no longer the blocker. Fresh threshold recommendation checks returned no sustained breach, so no operational recommendation was invented.

Evidence is in `data/pipeline_checks/20261116T154429Z/` (before/after Scheduler config, collection operation/completion, overview, verification). Five-minute polling reduces collection delay; a quiet scaled-to-zero service can still have missing measurements. No artificial traffic, imputation of missing targets, model training, API/dashboard redeployment, or IAM changes were used for this fix. Scheduler-triggered execution at 15:45:00Z also completed successfully at 15:45:22Z, independently of the manual run. Public HTTP and Streamlit WebSocket verification passed with zero errors and CPU/memory rendered; API remains private. Continue monitoring future cron freshness because these successes do not guarantee every future collection.

## Current live deployment — public read-only showcase (2026-11-16)

This section supersedes the historical deployment and pending-approval statements below.

- User explicitly authorized deployment and anonymous dashboard viewing. Public URL: https://autocloud-dashboard-l25hfnltba-el.a.run.app/ (no Google login or local proxy).
- Release `20261116T143031Z-public`, Cloud Build `72b10191-4634-45a1-b2bf-42d070e19394` succeeded. Both services use immutable image `sha256:d681e64ae7e7313e59170aeaf4d9c9c16a267f7f3eb2df5f3c3d6b7d2aa69c60`.
- API revision: `autocloud-api-00010-clq`; dashboard: `autocloud-dashboard-00009-mq7`. Existing service accounts, timeouts and instance limits were preserved. Only dashboard IAM gained `allUsers` / `roles/run.invoker`; API remains private.
- `DASHBOARD_PUBLIC_SHOWCASE=true` on both services. API permits only GET root, health and fixed host `autocloud-api` BigQuery overview (24-hour window). Billing, reviews, analysis/Gemini, auth, resources and onboarding routes are blocked server-side. Dashboard omits sign-in/onboarding, billing reads, review writes and Gemini controls. Shared overview cache is 60 seconds. This is a public host-project showcase, not unrestricted multi-tenant onboarding.
- Observation-only XGBoost and JSON Isolation Forest are connected through `DASHBOARD_FORECAST_RUN=/app/models/runs/20261116T051914Z_48d41482`. No retraining, extra workload, gate relaxation, infrastructure execution, or new Monitoring/Run viewer IAM roles were performed.
- Actual live API verification: overview HTTP 200, BigQuery query succeeded, models `candidate_evaluated`. At verification the latest observation was `2026-11-16T14:12:00Z`; both forecast and anomaly outputs were correctly unavailable due to the unchanged 15-minute freshness gate. This is not evidence of model accuracy or savings. Existing poor baseline/idle false-positive limitations remain visible.
- Validation: 250 offline tests passed; pip check passed; container model/dependency checks passed. Private and anonymous Streamlit WebSocket runs completed with zero error alerts and positive public-mode/evaluation content. Anonymous dashboard HTTP 200; anonymous API root/overview/reviews HTTP 403; API IAM has no public principals. Direct in-app browser also loaded the dashboard without login. Windows pytest temporary-directory cleanup emitted a permission warning after all tests passed (exit 0).
- Evidence: `data/releases/20261116T143031Z-public/{release.json,verification-api.json,verification-dashboard-private.json,verification-dashboard-public.json,live-overview.json}` and before/deployed service configs. Deployment/verification tools: `infrastructure/public_showcase_release.py`, `infrastructure/verify_public_showcase.py`.
- Rollback, if necessary: run `.venv\Scripts\python.exe -B -u infrastructure/public_showcase_release.py rollback data/releases/20261116T143031Z-public`. This first restores private dashboard IAM, then restores traffic to the previous verified private revisions. Do not route old write-enabled dashboard code to public traffic.
- `ANTIGRAVITY_HANDOFF.md` remains unchanged (SHA-256 `598af1c6370583c993a4b381d7d96902c8832ae106b4b9b111a202055d1dce2e`).

### Remaining work for Antigravity

1. Inspect the existing scheduled collector and ingestion freshness read-only. Restore reliable timely observations only within user authorization; do not manufacture data, start traffic experiments, or relax freshness/quality gates to fill graphs.
2. Verify fresh real observation-only forecasts and anomaly scores when measured inputs become sufficient. Improve forecast baseline performance and idle false positives before proposing operational use.
3. Keep OAuth and per-user onboarding disabled for public visitors. Address browser/session binding of OAuth state, binding the GCP access token to the signed-in identity, exact required IAM checks and revocation/reverification before exposing these flows. Mocked tests alone do not establish secure real OAuth/onboarding.
4. Public billing, Gemini requests, decision writes and cloud changes are intentionally unavailable. Any future authenticated owner interface must have a separate tested authorization boundary; do not simply remove the public read-only guard.

## Implemented locally (historical implementation notes)

- Observation-only XGBoost + pure-JSON Isolation Forest inference, authorized host resource selection, Google OAuth user sign-in, and keyless per-user onboarding release candidate `20261116T140549Z` prepared 2026-11-16 (pending deployment approval; live Cloud Run services unchanged on `20261116T122601Z` / `autocloud-api-00009-r79` & `autocloud-dashboard-00008-2vx`):
  - **Observation-only ML (`app/models/inference.py`, `app/services/model_dashboard.py`, `app/models/anomaly_detector.py`, `app/models/resource_predictor.py`, `app/dashboard/home.py`):**
    - Exported pure-JSON `anomaly_detector.json` & `anomaly_manifest.json` for `models/runs/20261116T051914Z_48d41482/` (verifiable parity against scikit-learn `IsolationForest` `decision_function` within `1e-12` and zero `.joblib` / pickle runtime loading) and switched runtime XGBoost loading to native `xgboost.Booster` + `xgboost.DMatrix` so the slim container runs without `scikit-learn`.
    - Connected XGBoost 5/10/15m forecasts alongside flat persistence (`persistence_prediction`, `delta_from_persistence`, imputed lag missingness, `assessed_at`, `observation_age_seconds`) and live Isolation Forest scores alongside `Thresholds` baseline (`threshold_baseline`, `threshold_triggers`, missing feature cells, `42.55%` overall / `95.24%` idle-only FPR limitations). Both remain labeled `experimental=true`, `observation_only=true`, `execution_allowed=false`, `deployment_allowed=false` and enforce 15m freshness + target-service checks (`"unavailable"` when stale, insufficient, or wrong service).
  - **Authorized Resource Selection (`app/config.py`, `app/services/resource_registry.py`, `app/services/gcp_monitoring.py`, `app/api/{monitoring,analysis,reviews}.py`):**
    - Added server-enforced host resource selection (`autocloud-api`, `autocloud-dashboard` via `DASHBOARD_ALLOWED_SERVICES`) plus a `httpx`-based Cloud Monitoring v3 REST collector (`source="monitoring"`) alongside BigQuery and local snapshots, keeping unallowlisted services blocked (`403`) and isolating 60s caches by `(owner_key, source, project, region, service, hours)`.
  - **User Sign-In & Secure Keyless Onboarding (`app/services/{user_auth,tenant_store}.py`, `app/api/auth_projects.py`, `app/dashboard/onboarding.py`, `app/services/review_store.py`):**
    - Implemented Google OAuth 2.0 PKCE (`S256`) + Google OIDC ID token verification + HMAC-SHA256 `X-AutoCloud-User-Session` session tokens (plus non-production `dev-login` blocked in `production`).
    - Implemented keyless GCP project onboarding (`POST /api/projects/onboard`, `verify`, `DELETE`): explicitly rejects private key / service-account credential JSON uploads (`400`), verifies caller project IAM permissions (`testIamPermissions`), records per-user isolated state in `LocalTenantStore` (SQLite) or append-only `CloudTenantStore` (`if_generation_match=0` under `tenants/{sha256(owner_sub)}/projects/...`), isolates reviews per `owner_sub`, and returns `not_applicable_external_project` from `/api/costs` for external projects.
  - **Release Candidate Prepared (No Live Mutation):**
    - Cloud Build `65c4c64f-f186-4434-bb8e-04979ea436d2` built & verified immutable digest `asia-south1-docker.pkg.dev/astute-sign-506809-j8/autocloud/autocloud-dashboard@sha256:b352669e4c84d6a3c5ba431a6424e0e26004d3fb3d642bf06b81344ea0f87ef1` (`source_tgz_sha256: 2debf9a66565fbb1cfb6d118b36c1306736c3abef037e4480e3a29b021b27da7`, excluding all `.joblib` files), writing `data/releases/20261116T140549Z/{deployment-plan.json,rollback-plan.json,release.json}` (`deployment_status: "prepared_pending_deployment_approval"`).

- Item 7 Final report & presentation outline + `CloudReviewStore` fixes and
  staged hotfix release `20261116T122601Z` deployed & verified 2026-11-16:
  - Added semester-end technical report (`docs/final-report.md`) and 10-slide
    presentation/demo guide (`docs/presentation-outline.md`).
  - Fixed `app/services/review_store.py`: (1) `capture()` repairs missing
    `by_time/` index entries on retry using `items/<id>.json` (`created_at`);
    (2) `history()` lists both `by_time/` and `items/` metadata refs and merges
    the top `200` indexed records with all unindexed legacy `items/` records to
    guarantee the global newest `200` (`(created_at DESC, id ASC)`) without
    re-downloading already-indexed `items/`; (3) `history()` enforces the
    overall `30.0s` (`HISTORY_BUDGET_SECONDS`) deadline across `get_bucket`,
    paginated `list_blobs`, JSON downloads, and bounded `DEFAULT_RETRY.with_deadline(...)`
    retries (raising `TimeoutError` -> HTTP `503` if exceeded); (4) fixed
    `_list_all_blobs` single-use `HTTPIterator.pages` access after live
    post-deploy verification on `20261116T120509Z` (`autocloud-api-00008-5tk`)
    returned `503` on `/api/reviews` (`ValueError: Iterator has already started`).
  - Read-only monitoring freshness audit (`data/releases/20261116T122601Z/monitoring-freshness-audit.json`)
    confirmed `autocloud-collect` cron (`*/15m`, `Asia/Kolkata`) and all `12`
    trailing `autocloud-collector` runs succeeded (`failedCount=0`,
    `max_ts = 2026-11-16T11:42:00Z`, `min_delay_sec=208s` at write time),
    explaining `>15m` freshness-gate staleness at cycle boundaries (`15m` cron +
    `3m` lag + job duration) and empty `no_observations` runs during
    scale-to-zero idle lulls (`10:12Z`–`10:42Z`). See scheduled-collection.md.
  - Staged deployment of immutable image
    `asia-south1-docker.pkg.dev/astute-sign-506809-j8/autocloud/autocloud-dashboard@sha256:bea5a49ccf99ce8a87b118599744b39aea28a3f4fadf2bbaad5462acc2f84f24`
    (Cloud Build `274772cf-2620-4615-a171-36f9cbea3008`) passed both stages:
    (a) `autocloud-api-00009-r79` (`generation 11`, `verification-api-stage.json`)
    verified `403` unauthenticated endpoints, `401/403` R1 negative checks,
    `GET /api/reviews` HTTP `200` (`0.3619s`) in Cloud Run logs, and positive
    live dashboard `Load review history` confirmation with `0` error alerts;
    (b) `autocloud-dashboard-00008-2vx` (`generation 8`, `verification.json`)
    reran full HTTP, R1, `/api/reviews` (`200`, `0.1720s`), and WebSocket UI
    checks (`overall_passed: true`, `history_loaded_confirmed: true`).
    Offline suite: `227 passed`.

- Item 6 Billing export check & counterfactual cost evaluation completed 2026-11-16
  (`data/releases/20261116T110246Z/cost-evaluation-summary.json`):
  - Verified live `GET /api/costs?days=7` and `GET /api/costs?days=31` (both
    HTTP 200, `status="no_exported_rows"`) plus a direct 31-day bounded diagnostic
    query across `astute-sign-506809-j8.autocloud_billing.gcp_billing_export_v1_011640_0793FF_B5C560`
    (`0` rows delivered yet for any service). Authenticated Streamlit WebSocket
    UI click on **`Read billing export`** rendered `"No matching Cloud Run billing rows have arrived for this period. Cost is unknown, not zero."`
    Actual billed Cloud Run cost therefore remains unknown pending Cloud Billing
    export ingestion.
  - Combined verified scaling trial control-plane result (`0 -> 1 -> 0` in 15s,
    no performance claim) with deterministic `CostAnalyser` list-rate
    counterfactuals (`config/pricing.json`, `asia-south1`, USD excluding free tier):
    232-minute request-based assumption (`2,097` requests, `600s` CPU / `300s` GiB)
    `USD 0.0159888`; 24-hour `min_instances=1` (`USD 0.3377388`) vs `min_instances=0`
    (`USD 0.0159888`) `counterfactual_estimate_not_measured` difference
    `USD 0.3217500` (`~95.27%`, `measured_savings=null`); and `autocloud-collector`
    cron job (96 runs/day at 1m minimum) `USD 0.1094400/day`. See cost-analysis.md.

- Item 5 Live breach / review check completed 2026-11-16:
  - Read-only live cloud check against `https://autocloud-api-l25hfnltba-el.a.run.app`
    (`GET /api/overview?source=bigquery&hours=1` and `GET /api/reviews` at
    `2026-11-16T10:54:40Z`) returned HTTP 200 for both: `snapshot_status="loaded"`,
    `query_status="succeeded"`, `coverage=9/60` (`0.15`), `latest_observation="2026-11-16T10:03:00+00:00"`
    (service idle/scaled to zero, `instance_count=0.0`, other metrics null),
    `recommendation_plan.data_status="stale"`, `recommendations_count=0`, and
    `reviews.items_count=0` (`execution_allowed=false`). No synthetic breach
    was injected into BigQuery or the production review bucket.
  - Isolated live Vertex AI breach prioritization and restart-persistence
    verification (`data/releases/20261116T090610Z/breach-gemini-isolated-verification.json`)
    constructed 3 consecutive fresh in-memory breach records (`cpu=0.94`,
    `memory=0.92`, `error_rate=0.08`) and executed `run_workflow(..., use_gemini=True)`
    against live regional `gemini-3.5-flash-lite` in `asia-south1`: returned
    `data_status="fresh"`, `workflow_status="awaiting_human_review"`,
    `gemini.status="succeeded"`, all 3 actions ordered with `explanation_source="validated_template"`,
    and `execution_allowed=false`. Restart-persistence across re-instantiated
    SQLite `ReviewStore` and isolated `CloudReviewStore` (`by_time/` index +
    immutable `approved`/`rejected`/`pending_review` states + overwrite
    `ReviewConflict`) passed. Live authenticated Streamlit persistence across a
    live Cloud Run container restart with a real BigQuery breach remains pending.

- External review remediation (R1–R7, `ANTIGRAVITY_REVIEW_2026-11-16.md`)
  completed locally AND deployed/verified on Cloud Run on 2026-11-16
  (release `data/releases/20261116T110246Z/`):
  - **R1 & R2 (`app/dashboard/authentication.py`, `app/api/reviews.py`, `app/dashboard/reviews.py`, `app/services/review_store.py`):**
    removed `.SIGNATURE_REMOVED_BY_GOOGLE` / `K_SERVICE` `jwt.decode(..., verify=False)`
    and generic Cloud SDK client IDs; `api_headers` now sends intact
    `X-AutoCloud-Authorization` alongside edge `Authorization`, mixed-header
    `X-Serverless-Authorization` attacks are rejected, and review metadata
    explicitly records `calling_service_principal` plus
    `reviewer_identity="service_authenticated_self_reported_label"`
    (`human_reviewer_verified=false`).
  - **R6 (`app/services/review_store.py`):** added reverse-timestamp `by_time/`
    index writes on `capture()`, bounded indexed `by_time/` downloads to the
    newest `200` indexed items + `200` per-ID decision lookups while still
    including all unindexed legacy `items/` records in global `(created_at DESC,
    id ASC)` top-200 selection, and enforced an overall `30.0s`
    (`HISTORY_BUDGET_SECONDS=30.0`, `GCS_TIMEOUT_SECONDS=10`) budget across
    bucket discovery, multi-page listing, downloads, and GCS SDK retries.
  - **R3–R5 (`app/models/train.py`, `app/models/inference.py`):** versioned
    `evaluate_anomalies` (`schema_version=1`, explicit `status`, `coverage`, and
    like-for-like `shared_observable_comparison`), added confusion-matrix metric
    consistency validation in `BinaryEvalScores`, replaced hardcoded experiment
    strings in `evaluate_saved_run_anomalies` and `evaluate_saved_run_forecasts`
    with dynamic `data_characteristics` and `diagnostic_hypotheses`, and
    validated `forecast_diagnostics` in `inspect_run`.
  - **R7 & Root API (`app/models/benchmark.py`, `app/main.py`):** preserved
    executable synthetic benchmark CLI (`.venv\Scripts\python.exe -m app.models.benchmark`,
    `seed=42`, `dataset_sha256: da1b193e0a013311b13ec87ec25c2f8e0c35eb75373349233a4844dfc07c3a36`),
    updated `GET /` for configured capabilities vs `environment-setup` in bare
    test config, and documented process-only semantics on `/health/ready`.
  - Built immutable image `sha256:1e5195a7732da62f16de800cc2d10ae0437d7e2e63cefcd71b7a1b11f262d8f1`
    (Cloud Build `a1be38c7-e86a-4694-b6f8-f0188aae27e4`) with refreshed
    `config/dashboard-evaluation.json` (`sha256: 9461e93bd134b2650edc71166f09aefaf6a5fe29221560550f3dc3b8d5234841`)
    and rolled out ready revisions `autocloud-api-00007-x5w` and
    `autocloud-dashboard-00006-fhw`. Live verification (`verification.json`)
    confirmed unauthenticated 403s, `GET /` `stage="configured"`, `GET /api/overview`
    updated 41-row shared-observable & 9-model diagnostic evaluation, `R1` 403
    rejections (redacted-only `Authorization`, wrong SDK audience, browser
    `Origin`), and live Streamlit WebSocket UI `"Load review history"` click
    completing without error. See cloud-dashboard.md.

- Forecasting evaluation, historical-average baseline & regime diagnostics
  completed 2026-11-16 (Item 3; updated after R5/R7): added `historical_average_test`
  comparison to `ResourcePredictor` (`app/models/resource_predictor.py`),
  dynamic `evaluate_saved_run_forecasts` (`app/models/train.py`), reproducible
  `app/models/benchmark.py`, and dashboard diagnostics expander
  (`app/models/inference.py`, `app/dashboard/home.py`).
  On the 232-minute real cohort (`models/runs/20261116T051914Z_48d41482`),
  `0 / 9` beat persistence while `5 / 9` beat training historical average
  (`request_count_5m` active-window MAE `0.1960` vs `0.7836` before cessation
  at `21:38:59Z`). On the deterministic 1,800-minute (`conservative` profile,
  `1.25` daily cycles + `62.8m`–`251.3m` shorter harmonic cycles) synthetic
  benchmark (`models/representative_forecast_benchmark.json`), `ResourcePredictor`
  beat both Persistence (`9 / 9`) and Historical Average (`9 / 9`); this
  verifies pipeline mechanics only and does not replace the `0 / 9` real-data
  result. Experimental forecasts remain `not_deployed`. See training-results.md.

- Independent post-hoc anomaly ground-truth labeling & held-out evaluation
  completed 2026-11-16 (Item 2; updated after R3/R4): derived post-hoc
  experiment-event label sets (`anomaly_labels_regime_shift.csv`,
  `anomaly_labels_operational_fault.csv`, `anomaly_labels_provenance.json`) from
  `status.json` and `phase_7.json` (`traffic_ended_at = 2026-11-15T21:38:59.189151+00:00`)
  for the 47-minute held-out test partition of run `models/runs/20261116T051914Z_48d41482`.
  On regime-shift labels, Isolation Forest scored `[[26, 0], [1, 20]]`
  (`F1 = 0.9756`, `47` rows) vs Threshold Baseline `[[26, 0], [15, 0]]`
  (`F1 = 0.0000`, `41` rows, `6` baseline abstentions), and `[[26, 0], [0, 15]]`
  (`F1 = 1.0000`) vs `[[26, 0], [15, 0]]` on the like-for-like 41-row
  shared-observable cohort. Under the operational-normality assumption (all 47
  test rows assumed healthy, `0` positive fault cases, fault sensitivity
  unmeasured), Isolation Forest FPR was `42.55%` (`20/47` across all `47`
  assumed-normal minutes; idle-only FPR was `20/21 = 95.24%`, active FPR was
  `0/26 = 0.00%`, and shared-cohort FPR was `15/41 = 36.59%`). Live anomaly
  inference stays disabled. See training-results.md.

- Durable authenticated cloud recommendation review history deployed and
  live-verified 2026-11-16 (alongside fixing `pd.Timedelta(1, unit="D")` in
  `app/dashboard/home.py`): added `CloudReviewStore` in
  `app/services/review_store.py`, OIDC verification (`verify_oidc_principal`)
  handling Cloud Run's `.SIGNATURE_REMOVED_BY_GOOGLE` edge-authenticated headers
  in `app/api/reviews.py`, `DASHBOARD_REVIEW_BUCKET` /
  `DASHBOARD_REVIEW_AUDIENCE` in `app/config.py`, `capabilities.cloud_reviews`
  in `app/api/monitoring.py`, `google-cloud-storage` in `requirements-cloud.txt`,
  and UI header/principal support in `app/dashboard/reviews.py` and `home.py`.
  After explicit user approval, created regional GCS bucket
  `astute-sign-506809-j8-autocloud-reviews` (`ASIA-SOUTH1`, uniform bucket-level
  access, public access prevention enforced) with scoped `legacyBucketReader`,
  `objectCreator`, and `objectViewer` for `autocloud-api-reader`, built image
  `sha256:02987e09738e2412a1abd47aad67d074d78641352ede8cf32416b299d68b8826`
  (Cloud Build `b4a117c2-b0d8-45d4-b0eb-a20f22a2995f`), and deployed
  `autocloud-api-00006-pgf` and `autocloud-dashboard-00005-ntj` (release
  `data/releases/20261116T090610Z/`). Verified unauthenticated 403s,
  `capabilities.cloud_reviews=true`, authenticated `GET /api/reviews` returning
  200 with `reviewer_identity="google_oidc_verified"`, `Origin` 403 rejection,
  mismatched capture 409 rejection, and dashboard 200; see recommendations.md and
  cloud-dashboard.md.

- Dashboard LangGraph + Gemini analysis deployed and live-verified 2026-11-16:
  manual analysis/connection controls, strict server-owned evidence, 60-second
  cache/cooldown and existing policy validation. After explicit user approval,
  custom role `projects/astute-sign-506809-j8/roles/autocloudGeminiPredict`
  (`aiplatform.endpoints.predict`) was created and bound to
  `autocloud-api-reader@astute-sign-506809-j8.iam.gserviceaccount.com`, and
  `DASHBOARD_GEMINI_ENABLED=true` with `DASHBOARD_GEMINI_MODEL=gemini-3.5-flash-lite`
  was enabled on `autocloud-api` (ready revision `autocloud-api-00004-bwt`,
  alongside dashboard `autocloud-dashboard-00003-qtq`). Authenticated cloud
  verification confirmed unauthenticated `/health` returns 403, `/api/overview`
  reports `gemini_enabled=true`, the connectivity probe succeeded
  (`connectivity_checked`, `gemini.status=succeeded`), and after the 60s
  cooldown the measured LangGraph + Gemini request returned `status=completed`,
  `data_status=fresh`, `workflow_status=no_supported_action`,
  `gemini.status=succeeded`, and `execution_allowed=false`; see dashboard-ai.md.

- Updated API and Streamlit dashboard deployed privately to Cloud Run on
  2026-11-16. Revisions `autocloud-api-00002-fvj` and
  `autocloud-dashboard-00002-rd8` are ready; minimum zero, maxima 2/1.
  Approved separate identities and read/invoke permissions are configured.
  Authenticated BigQuery, Billing and evaluation reads passed; unauthenticated
  requests return 403. Cloud dashboard browser checks passed through the local
  authenticated proxy on port 8503. See cloud-dashboard.md.

- Updated private cloud release prepared: server-to-server identity-token
  authentication, checksummed evaluation summary without weights, and explicit
  local-only review capability. All 201 tests pass. Specific runtime IAM grants
  were applied after explicit approval following the initial automatic rejection;
  the verified rollout is described in cloud-dashboard.md.

- Live operator scaling/rollback verified 2026-11-16 11:01 IST: service minimum
  0 → 1 → 0, reconciliation succeeded both ways, maximum 2 and original serving
  revision preserved. Durable checkpoints/result saved; no active recovery marker
  remains. This is control-plane verification, not a performance or savings claim.

- Real training-run dashboard integration: saved cohort readiness, 0/9 held-out
  persistence comparison and explicit anomaly-evaluation limitations. Local
  launcher selects the completed run; stale observations cannot produce live
  forecasts. 33 inference/dashboard tests pass.

- First measured exploratory training completed on 2026-11-16: 232-minute
  experiment cohort passed readiness; Isolation Forest and nine XGBoost models
  saved and native integrity validated. All nine forecasts lose to persistence
  on held-out MAE. Anomaly accuracy remains unevaluated. No deployment or scaling
  is justified by this run. Training hold was resumed by the user. See training-results.md.

- Operator-only Cloud Run minimum-instance trial foundation: explicit plan
  digest, five-minute expiry, etag checks, active-experiment guard, durable
  submission checkpoints and drift-aware rollback. No dashboard executor or
  unattended watchdog. Real apply/rollback testing remains pending; see scaling-trial.md.

- End-to-end verification at 2026-11-15 19:58 UTC: live BigQuery/API reads,
  stale-evidence rejection through LangGraph, billing empty-result semantics,
  review history and HTTP validation checks. All 183 offline tests passed;
  real model accuracy and savings are unestablished. See demo-walkthrough.md.

- Durable local recommendation review: server-validated capture, SQLite evidence
  snapshots, approve/reject decisions and dashboard history. Deduplicated saves,
  immutable decisions, stale-approval blocking and local-only endpoints. No
  infrastructure execution; training remains on hold. Six review tests pass,
  including a Streamlit save/decision flow, alongside 51 related policy,
  dashboard, billing and API checks. Fixtures establish behavior, not ML accuracy.

- Billing dashboard: explicit read-only `/api/costs` and Costs & actions form,
  environment-configured existing export, 1..31-day windows, five-minute cache,
  UTC daily/cost-type breakdown, exact per-currency totals and export delivery
  metadata. Empty exports stay unknown. No model training, invoice attribution,
  service estimates or savings are inferred.

- Models dashboard increment: current-window exploratory readiness is separate
  from explicit trusted-run evaluation and fresh out-of-sample candidate forecasts.
  Displays nine held-out forecast/persistence MAE/RMSE comparisons, origin and
  target timestamps, expiry and provenance. Does not train, auto-select a run,
  load anomaly pickle artifacts or approve deployment. Real training is pending.

- Dashboard BigQuery integration: explicit source/lookback selection, bounded
  scoped reads from latest_metrics, 60-second per-worker query/error caching,
  fetch/observation timestamps and expected-minute coverage. No implicit local
  fallback or new collection. 58 dashboard/API/Monitoring/policy tests pass.

- First Phase 7 increment: read-only `/api/overview` endpoint and Streamlit
  dashboard for scoped local Monitoring snapshots, historical charts, missingness,
  deterministic threshold previews and recorded training progress. Models/billing/
  approvals remain explicitly unavailable in this UI. See docs/dashboard.md.

- User-approved short forecasting horizons: 5, 10 and 15 minutes. Default
  exploratory readiness requires 200 observed minutes, <=20% missingness per
  feature, target variation and measured 100/20/20 train/validation/test labels
  after horizon purging. The conservative profile retains 1,440 observed minutes.
  Exploratory outputs remain preliminary with deployment_ready=false. Native
  manifest v2 records the profile/horizons and rejects older bundles.
- Validated environment configuration and bounded instance settings.
- FastAPI milestone endpoint, liveness/readiness and sanitized errors.
- Structured application logs and request IDs.
- Non-root Docker image definition and restricted build context.
- Cloud Build test/build/publish configuration; separate deployment preview.
- Setup, IAM, billing alerts, deployment and evaluation documentation.
- Phase 3 Monitoring adapter, validated Pandas/NumPy aggregation, NDJSON snapshots,
  BigQuery batch adapter and optional immutable Cloud Storage archive adapter.
- Reviewed BigQuery provisioning SQL and a real-data collection runbook. These
  new cloud storage resources have not been provisioned by this session.
- Dedicated collector Dockerfile and staged deployment helper covering identity,
  build, deployment, manual execution, scheduling, status and pause/resume.
  The shared Cloud Build file now accepts a Dockerfile substitution while
  retaining `Dockerfile` as the API-build default.
- Phase 4 data readiness checks, chronological/purged forecasting features,
  Isolation Forest and heuristic baseline, XGBoost CPU model-selection workflow,
  held-out metrics, optional labelled anomaly evaluation and candidate artifacts.
- Phase 5 independent cost module: centrally dated regional pricing, Decimal
  list-rate estimates, job minima/attempt rounding, counterfactual comparison,
  unknown-data diagnostics and an optional read-only Billing export adapter.
- Phase 6 foundation: strict evidence-bound investigation candidates, freshness
  and consecutive-window checks, deterministic proposal validation and a local
  JSON preview. A finite LangGraph workflow now integrates monitoring, model
  readiness, optional explicit cost inputs, optional bounded Vertex Gemini
  prioritisation/explanation selection and final policy validation. It has no
  infrastructure action or persisted approval authority.
- Explicit native XGBoost candidate export/inference: fixed target/horizon
  manifest, training medians, version/schema/history/model integrity checks,
  observed/fresh out-of-sample origin checks, CPU execution and disclosed
  imputation/held-out persistence comparisons. No workflow pickle loading.
- Optional explicit project-wide Billing export read integrated into LangGraph,
  independently of service estimates, with bounded time/bytes and exact Decimal
  serialization. Real Cloud Run cost rows and real trained models remain absent.

## Not completed

- Integration of independently evaluated real-data ML artifacts and live
  positive-pressure recommendation validation. Live Vertex and the fresh-data
  no-action workflow are verified; arbitrary model-written narrative is excluded
  from authoritative facts.
- First clock-triggered recurring execution/freshness verification. On-demand
  dispatch through Scheduler is verified; the cron schedule remains enabled.
  Collector/scheduler identities, IAM and
  Cloud Run Job deployment/manual execution are confirmed.
- Optional Cloud Storage archive verification.
- Phase 4 real-data readiness, training/evaluation on representative history
  and independent anomaly labels. CPU XGBoost integration is verified on fixtures.
  Later phases remain pending; no ML model has been deployed.
- Verified billable-unit inputs or Cloud Run cost rows in the Billing export,
  real cost reconciliation and before/after financial/performance experiments. Cost math
  is implemented; current project charges/savings are not yet established.

## Verification results

- Billing dashboard verification: 87 billing/API/dashboard/configuration/agent
  tests and two additional Streamlit form tests passed. The form tests use
  mocked exports and verify explicit submission plus recorded-zero vs missing
  cost behavior; they establish no real financial outcome. Python compilation
  passed. A live read of the configured export succeeded for
  2026-11-14T19:26:00Z--2026-11-15T19:26:00Z and returned no_exported_rows.
  Cloud Run costs therefore remain unknown; currency totals are empty, not zero.
  Local API restart with DASHBOARD_BILLING_TABLE is required to load/configure
  the endpoint. No training or infrastructure changes occurred.

- User requested holding model training while other work proceeds. Added a
  per-input HOLD_TRAINING check to the fresh training CLI and placed the marker
  in foreground experiment `1c4121e4baad4aa3bf61776d28a232dc`. Its traffic and
  collection continue; its eventual CLI training invocation will return paused
  before reading/fitting. No gates were relaxed or active process interrupted.

- User-authorized early assessment (2026-11-15T19:16:43Z): read the existing
  deduplication view without collecting traffic or writing cloud data. Saved
  query evidence and assessment in
  `data/assessments/20261115T191643Z_71616dd8/`. All-history: 257 observations
  over 453 minute boundaries, 196 gaps, per-feature missingness 44--66%, and
  inadequate 10/15-minute training/validation pairs. The longest observed
  continuous block is 82 minutes (14:00--15:21Z), with 25.6% missing latency/error
  rate. The active experiment's partial cohort has 63 consecutive minutes
  (18:10--19:12Z) with zero missing values in all eight features, but too few
  labels for the existing purged splits. No candidate passed readiness, so
  training was not attempted. Existing gates and traffic process were unchanged.

- Models dashboard increment: 92 inference/dashboard/API/orchestration/model
  regression tests passed. A further Streamlit AppTest rendered all nine
  evaluation/forecast rows and expired-horizon warnings using isolated synthetic
  fixtures (no cloud calls); this tests UI behavior, not real accuracy. Python
  compilation passed. No real model was selected or trained by this change.
  The real traffic experiment last read during this work was in phase 2 with
  457 successful requests from 457 attempts and trained=false.

- Live read-only dashboard BigQuery query succeeded against the configured
  project/region/service. Its one-hour window contained 45 observed minute
  buckets and 15 gaps (75% observation coverage). The latest returned observation
  was 2026-11-15T18:42:00Z and was correctly classified stale at assessment.
  No collector, traffic generator, training or cloud mutation was triggered by
  this check. The user's running local API needs restart to load the new route
  behavior; this session did not stop their servers or experiment.

- First dashboard increment: 34 dashboard/API/configuration/recommendation tests
  passed using a project-local temporary directory. Dashboard Python compilation
  passed. Reading the real local snapshot returned 16 historical minute buckets
  correctly flagged stale; the new experiment was still sending traffic.
  Streamlit is not installed in this session, so visual UI execution remains a
  user-terminal verification, with commands in docs/dashboard.md.
- The original background experiment `3f01b7cfbdf14b039462b9ab8fdb1512`
  lost its worker after 21 recorded successful requests. Its status was marked
  stopped after confirming process absence; termination cause is unknown. The
  user launched foreground replacement `1c4121e4baad4aa3bf61776d28a232dc`.
  Earlier background launch statements below describe the initial attempt,
  not a verified completion. The inaccessible completion watch was disabled.

- User authorised generating more real training data. A bounded background run
  `3f01b7cfbdf14b039462b9ab8fdb1512` started at 17:59:15 UTC on 2026-11-15
  (23:29:15 IST). It plans 210 minutes at rates 6/10/14/6/10/14/10 per minute
  in seven 30-minute phases, capped at 2,100 requests. Five minutes of Monitoring
  lag follow; nominal collection/training time is around 03:04 IST on Nov 16,
  plus processing time. It uses existing developer ADC ID tokens in memory;
  actual fixed-target preflight and the first background request returned 200.
  No new cloud resources, IAM, model deployment or relaxed quality gate is involved.
  The runner saves progress, supports a stop file, refuses duplicate active runs,
  and will train only on its own fully exposed real-data cohort if the existing
  exploratory checks pass. A final training outcome has not been observed yet.
  A ChatGPT completion watch was created for hourly checks, at most five runs;
  it must report the real terminal outcome and stop after a terminal report.
- New runner/transport tests exercise the full 215-minute sequence with an
  offline clock, request budgets, isolated cohort selection, truthful training
  outcomes, duplicate/failure stops and private ADC/HTTP handling. All 133 related
  tests passed in 17.30 seconds. A transient Windows rename lock found by testing
  is handled with a bounded status-file retry. The initial detached launch ended
  with its parent before traffic started; the active run uses a supervised exec
  session instead. The separate short traffic CLI's limits remain unchanged.
- Short-horizon/profile regression suite: 125 related tests passed in 16.45
  seconds with deprecation warnings treated as errors. Tests verify complete
  200-minute exploratory fitting, unchanged conservative gating, shared purged
  split counts, sparse-label refusal, native profile/horizon compatibility and
  expired short-horizon flags. No cloud configuration was changed.
- A fresh real BigQuery assessment under the exploratory profile found 177
  observed minutes over a 336-minute grid, with 159 gaps and >20% missingness
  in every metric. It correctly reported ready=false and trained=false despite
  the lower 200-minute gate. Measured split counts also remain insufficient
  (for example, 15-minute CPU has 60 training / 0 validation / 17 test pairs).
  No history was fabricated, imputed into labels or relabelled to force readiness.
- Native inference and billing increment: all 119 related tests passed in
  17.12 seconds with DeprecationWarning treated as an error. New tests cover
  native-model round-trip equivalence with the fitted pipeline, held-out baseline
  retention, hashes, scope/version/model keys, fresh/out-of-sample origins,
  missing targets, gaps, path/size boundaries, stale-output withholding and exact
  currency/credit serialization. Native fits are synthetic fixtures only.
- This session queried real BigQuery training history directly: readiness=false,
  trained=false, 159 observed minutes across a 318-minute grid with 159 gaps and
  more than 20% missing in every feature. The 1,440-minute gate was retained.
  No real-data model was trained, deployed or assigned an accuracy claim.
- Billing dataset discovery found standard table
  `astute-sign-506809-j8.autocloud_billing.gcp_billing_export_v1_011640_0793FF_B5C560`.
  The existing cost-report reader successfully checked schema/location and ran a
  scoped Cloud Run query, returning no_exported_rows. The newly integrated live
  graph query also returned no_exported_rows with exit code 0 at 17:08 UTC
  (22:38 IST); no zero-bill or single-service charge was inferred. The graph
  retained fresh metrics through 16:57 UTC, no supported action, null forecasts
  and measured_savings=null. Gemini was intentionally disabled for this billing
  integration check; its live path was independently verified earlier.
- This session executed the real collector and full workflow itself using
  existing ADC, without copying credentials. Collection over 16:22--16:52 UTC
  returned 181 samples, 16 observed records and 16 BigQuery rows. The subsequent
  BigQuery-to-LangGraph-to-Gemini run at 16:58:48 UTC (22:28:48 IST) returned
  data_status=fresh, workflow_status=no_supported_action, gemini.status=succeeded,
  and exit code 0 with `gemini-3.5-flash-lite` in `asia-south1`. No sustained
  threshold breach was established and no infrastructure action was allowed.
  Readiness remains false: 154 observed minutes, 313-minute grid, 159 gaps;
  forecasts/anomaly inference remain unavailable and costs remain unknown.
  The first session-side Gemini attempt failed with ImportError due to missing
  SOCKS support in the managed proxy environment. Installing httpx's socks extra
  resolved client initialisation; requirements-agents.txt now includes it.
  All 30 orchestrator tests passed after this dependency fix and pip check
  reported no broken requirements. Prior gcloud configuration restrictions
  described below do not prevent the now-verified Python ADC operations.
- The subsequent user-run BigQuery-to-LangGraph workflow read 138 observed
  minutes across a 222-minute grid (84 gaps), through 15:21 UTC. At assessment
  16:30 UTC the evidence was about 69 minutes old. It correctly returned
  blocked_evidence/stale, skipped Gemini and allowed no execution. ML readiness
  remained false (short, sparse history); costs stayed unknown. The storage-to-
  graph path and stale-data branch are verified; a fresh-data graph-to-Gemini
  run remains pending. This output alone does not determine whether missing
  recent metrics reflect an idle service, collection failures or another cause.
- User-provided live connectivity probe confirms `gemini-3.5-flash-lite` in
  `asia-south1` returned a valid structured selection with gemini_status=succeeded
  and execution_allowed=false. Vertex ADC access and the regional model request
  are verified. This metrics-free probe did not run monitoring, ML or cost
  analysis; the full BigQuery-to-graph-to-Gemini path still needs live verification.
- The first user-run live Vertex connectivity probe returned ClientError HTTP
  404 with the original `gemini-2.5-flash` default. Follow-up official lifecycle
  review found retirement on 2026-10-20. The default is corrected to
  `gemini-3.5-flash-lite`, with only verified Mumbai-compatible 3.5 Flash/Lite
  profiles accepted. Requests now use MINIMAL thinking level and omit the old
  numeric thinking budget/sampling override. A regression rejects retired or
  unknown profiles before calling Vertex; safe 404 diagnostics distinguish an
  unavailable model/region/access issue without printing provider bodies.
  Replacement-model live success is not yet verified; no endpoint migration or
  throughput purchase was performed. All 106 related tests pass after this fix
  (13.46 seconds, DeprecationWarning treated as an error).
- Phase 6 LangGraph/Vertex increment: 28 new offline tests pass. Combined with
  existing recommendation, cost, model, Monitoring and traffic checks, 104 tests
  passed in 9.33 seconds with DeprecationWarning treated as an error. `pip check`
  reports no broken requirements. Installed/pinned LangGraph 1.2.22 and Google
  Gen AI SDK 1.75.0. Tests use the real graph runtime and SDK request serialization
  through a mocked regional HTTP transport, including bounded/no-tool generation,
  invalid/omitted/duplicate model output, failure fallback, sanitised HTTP status,
  expired evidence, optional cost scope and the metrics-free connectivity probe.
  No live Gemini invocation, deployment, new IAM grants or scaling was performed.
  The local real-data graph run returned blocked_evidence because the available
  snapshot ended at 14:58 UTC; it reported 83 observed minutes over a 90-minute
  grid with 7 gaps and correctly withheld ML inference and unknown costs.
- The one-hour pilot `c4ad1bb36d604ee6977d30517ead7324` completed 600/600
  successful requests in 3597.844 seconds. The local manifest confirms 600
  events from 13:59:17 through 14:59:11 UTC (19:29:17--20:29:11 IST).
  Client p50/p95/p99 are 110/157/437.16 ms; these are not server latency,
  anomaly labels or cost-savings evidence. The subsequent 90-minute collector
  returned 936 samples and loaded 83 observed records through 14:58 UTC.
  Subsequent user-provided BigQuery readback over minute endpoints greater than
  13:59 and through 15:00 UTC confirms 61 observed buckets, 600 requests and
  peak measured server-error rate 0.0. The full pilot request total is verified
  in BigQuery. This later view includes observations beyond the pasted local
  snapshot; the producer of those additional rows was not independently checked.
- User-provided fresh preview at 14:50:53 UTC used observations through 14:47
  UTC, returned fresh with no sustained threshold breach, and kept model/cost
  status not_evaluated. The real-data policy preview path is verified.
- Combined recommendation, cost, model, monitoring and traffic regression suite:
  76 passed in 9.13 seconds with DeprecationWarning treated as an error. This
  excludes the previously documented Windows TestClient integration blocker.
- All 16 recommendation-policy tests pass, covering stale/gapped/missing data,
  duplicate polling, conflicting evidence, target/time boundaries, exact evidence
  references and rejection of invented facts, actions, prices and confidence.
  The local preview on the real snapshot reports stale (latest 13:36 UTC) and
  no recommendations; neither model nor financial analysis is claimed.
- User reports billing export setup completed with destination
  `astute-sign-506809-j8.autocloud_billing`. A subsequent `bq ls` returned no
  tables. Export delivery, table identity and actual charges remain unverified.
- While the user runs a one-hour real traffic pilot, independent cost-module
  development proceeded without altering that process or deployed resources.
  All 20 cost tests passed locally with deprecation warnings treated as errors.
  Tests cover decimal math, billing modes/minima, counterfactual scopes, stale
  rates, signed credits, query limits, empty exports and separate CLI modes.
- User subsequently confirmed all 20 cost tests pass in their terminal and the
  explicit demo returns illustrative USD 0.4252500, with actual exported costs
  and measured savings null. This validates the demo/estimation path, not the
  project's real charges. Billing-export destination discovery is next.
- USD list-rate assumptions for `asia-south1` were verified against official
  Google Cloud pricing/region documentation on 2026-11-15 and centralized in
  `config/pricing.json`, expiring 2027-02-13. No numeric price is spread through
  business logic. No-argument diagnostics keep estimates/export costs null;
  the explicit synthetic demo is labelled illustrative and is not the pilot's
  actual cost. A live Billing export query has not been verified.
- User-provided execution listing confirms Scheduler-triggered execution
  `autocloud-collector-m9tl6`, created at 12:56:40 UTC on 2026-11-15, completed
  1/1 tasks under `autocloud-scheduler@astute-sign-506809-j8.iam.gserviceaccount.com`.
  This was an on-demand Scheduler invocation; automatic cron recurrence and
  this execution's data freshness have not been independently read back yet.
- User-provided `Pasted text(1).txt` confirms ML dependencies installed,
  including CPU XGBoost 3.4.1, and all 32 model/monitoring tests passed. The
  BigQuery readiness assessment reports 32 measured minutes, latest timestamp
  12:11 UTC, with 93.75% missing latency/error-rate measurements and 37.5%
  missing request counts. It correctly returns ready=false and trained=false.
- The user's run reported 109 datetime deprecation warnings with pandas 2.3.3
  and NumPy 2.5.4. Reproducing locally identified pandas Timedelta keyword-unit
  construction. Model and fixture arithmetic now uses explicit numeric/unit
  construction; all 32 tests subsequently passed with DeprecationWarning
  treated as an error, including the real CPU XGBoost integration.
  Fixture tests verify split leakage controls, feature
  causality, train-only imputation, baseline evaluation and model-selection
  mechanics, plus parameterized and byte-budgeted BigQuery history reads.
- A bounded, fixed-target real traffic test tool has explicit execution opt-in,
  rate/count/duration caps, private CLI authentication, redirect refusal and
  experiment manifests. User execution `f66b3f675bf64280986bf493f1f69b82`
  completed in 120.015 seconds with 59 attempted and 59 successful requests.
  The local manifest confirms requests from 13:28:30 through 13:30:24 UTC
  (18:58:30--19:00:24 IST) on 2026-11-15. Client roundtrip p50/p95/p99 were
  110/141/1151.52 ms; these are not server latency metrics or anomaly labels.
  User-provided Monitoring/BigQuery readback now verifies all 59 requests:
  minute-end timestamps 13:29/13:30/13:31 UTC contain 14/30/15 requests,
  respectively. Mean server latencies are 12.5989/2.8178/2.6858 ms and measured
  server-error rates are all zero. The 13:32 row has zero requests and null
  latency/error-rate fields, as defined by the metric contract. The final
  collection loaded 8 records from 81 samples through 13:36 UTC. This verifies
  the real experiment-to-Monitoring-to-BigQuery path and view deduplication;
  it does not establish model accuracy, capacity or cost savings.
  No longer-running workload experiment is enabled.
- The assessment CLI was run on the available real 29-minute local snapshot.
  It correctly reported not ready due to insufficient history and sparse
  requests/latency/error measurements, with `trained=false`. No real-data models
  or accuracy/savings claims were produced.
- User-provided output confirms `autocloud-collector` job deployment with the
  dedicated collector identity. Manual execution `autocloud-collector-6mvjl`
  completed successfully (1/1 tasks). User-provided Cloud Logging output now
  confirms 42 samples, 5 records and 5 BigQuery rows for 12:06--12:36 UTC, with
  `status=collected` at 12:39:22 UTC on 2026-11-15 and exit(0). The dedicated
  cloud identity's Monitoring access and table writes are verified.
  The recurring trigger is now enabled as described below; triggered execution
  verification remains pending.
- User-provided output confirms Cloud Scheduler API enablement and job-scoped
  Cloud Run Invoker granted to the scheduler identity. Scheduler job
  `autocloud-collect` was created with state ENABLED, cron `*/15 * * * *`,
  timezone Asia/Kolkata and an OAuth-authenticated Cloud Run Jobs v2 target.
  Its creation output lists the next automatic invocation as 13:00 UTC
  (18:30 IST) on 2026-11-15. A successful Scheduler dispatch and subsequent
  collector execution/data write have not yet been observed.
- User-provided Cloud Build output confirms collector build
  `5a2128d1-4954-448c-a0a8-61d6db4a02fb` completed with `SUCCESS` in
  `asia-south1` on 2026-11-15 (1 minute 42 seconds). The configured complete
  test suite, dedicated collector Docker build and image publication passed.
  Published image:
  `asia-south1-docker.pkg.dev/astute-sign-506809-j8/autocloud/autocloud-collector:v1`.
- User-provided output confirms creation of `autocloud-collector` and
  `autocloud-scheduler` service accounts. The collector has project Monitoring
  Viewer and BigQuery Job User, plus BigQuery Data Editor scoped to
  `autocloud.infrastructure_metrics`. Scheduler invocation permission is now
  granted only on the collector job.
- User confirmed existing project `astute-sign-506809-j8` and region
  `asia-south1`. No new project is required.
- User-provided smoke-test evidence confirms authenticated readiness HTTP 200
  with `{"status":"ready"}` and request ID `f432b450757d4d4b90030ce6f03e1766`.
  Direct unauthenticated readiness returned HTTP 403. Cloud Run logs show
  startup, the 200 request at 11:50:07 UTC and denied request at 11:51:06 UTC on
  2026-11-15. The initial deployment gate is complete.
- All 18 new monitoring tests passed locally using offline fixtures/mock cloud
  adapters. They cover aggregation, missingness, invalid observations, error
  rates, filters, time windows, API failures and regional BigQuery batch retries.
  The original offline test run used fake Monitoring clients; the user has since
  installed the SDK and successfully verified live collection as described below.
- `Pasted text.txt` confirms monitoring dependencies installed in `.venv`, ADC
  login completed with this project as quota project, and a real collection
  queried 11:02--12:02 UTC on 2026-11-15. It returned 255 aligned samples and
  23 service-minute records, with `source=gcp-monitoring`, `status=collected`,
  `bigquery_rows=0` and no archive. BigQuery was intentionally disabled.
- The local `data/processed/metrics.ndjson` snapshot was read and all 23 rows
  passed MetricRecord validation. Observed windows span 11:40--12:02 UTC for
  `autocloud-api`. CPU, memory, network and instance metrics are present in all
  rows. Request count is missing in 11 rows; latency and error rate in 21 rows.
  Total observed request count is 2. Missing values were not converted to zero.
- Subsequent user-provided SQL output confirms regional dataset/table
  provisioning and creation of `autocloud.latest_metrics`. The table is daily
  partitioned, clustered by service name, and configured for 30-day retention.
  Collector output for 11:08--12:08 UTC confirms 323 samples, 29 records and
  `bigquery_rows=29`, with `status=collected`. The BigQuery load job completed;
  a query through the deduplication view is the next verification step.
- User-provided query output confirms the deduplication view returns exactly
  29 records for `autocloud-api`, spanning 11:40--12:08 UTC on 2026-11-15.
  Real collection, BigQuery ingestion and readback are verified.
- Every collector deployment stage was previewed successfully, with no cloud
  mutations. YAML parsing and collector build inputs were checked. All seven
  Monitoring request shapes were also encoded successfully with the real
  installed Monitoring SDK, and actual SDK distribution decoding passed.
  Collector container build and scheduled behavior remain cloud checks.
- User-provided CLI output confirms `billingEnabled=True`. Enabled services
  include Cloud Run, Artifact Registry, IAM, Logging, Monitoring, BigQuery,
  Storage, Pub/Sub and Vertex AI. The user subsequently enabled
  `cloudbuild.googleapis.com` successfully. This evidence is from the user's
  terminal, not a successful cloud query by this session.
- The user's Cloud Build default-service-account query in `asia-south1`
  returned `437897070681-compute@developer.gserviceaccount.com`.
- User-provided creation output confirms the `autocloud` Docker repository in
  `asia-south1` and runtime identity
  `autocloud-runtime@astute-sign-506809-j8.iam.gserviceaccount.com` now exist.
- User-provided IAM output confirms repository-scoped Artifact Registry Writer
  and project Logs Writer grants to the default build account. The output also
  shows an existing project Editor grant on that account; effective build
  privileges are therefore broader than the two new grants. That existing role
  has not been removed because the account may serve other project workloads.
  A dedicated build account with scoped access is a future hardening task.
- Private GitHub repository `justacoder51/AutoCloud-AI` is connected as `origin`;
  the initial commit is on `main`. Connector read/write access and remote README
  availability were verified.
- Billing and enabled-API checks were retried after the user logged in. Both
  are still blocked by this session's access to the gcloud credential database;
  login alone does not resolve the local filesystem restriction.
- Seven configuration/logging tests passed using the installed Python 3.12.9,
  FastAPI 0.135.3, Uvicorn 0.44.0, HTTPX 0.28.1 and pytest 9.0.2 environment.
- Three TestClient integration tests could not complete: Windows asyncio stalled
  while creating its local socket pair. They were interrupted; they are not
  reported as passing. Rerun the full suite in an unrestricted local terminal or
  Cloud Build before deployment.
- User-provided Cloud Build output confirms build
  `e38be75d-6b70-49a0-aa4f-ba045727da66` in `asia-south1` completed with
  `SUCCESS` on 2026-11-15 (45 seconds). The configured mandatory test step,
  Docker build and image publication completed successfully. Individual test
  counts are not present in the supplied output.
- Published image:
  `asia-south1-docker.pkg.dev/astute-sign-506809-j8/autocloud/autocloud-api:v1`.
- User-provided deployment output confirms Cloud Run revision
  `autocloud-api-00001-n6m` is deployed and serves 100% of traffic at
  `https://autocloud-api-437897070681.asia-south1.run.app`. Deployment used
  the dedicated runtime account, private IAM access, 1 CPU, 512 MiB memory,
  minimum 0 and maximum 2 instances. End-to-end smoke requests are verified as
  described above.
- The user confirmed billing budget alerts were already configured; alert
  amount, thresholds and notification delivery were not independently tested.
- The PowerShell deployment preview ran successfully with example values and
  made no cloud changes.
- A virtual environment was created and pip bootstrapped after correcting a
  temporary-directory access problem. Installing application dependencies into
  it failed because package-index DNS resolution is unavailable in this session.
  The environment is not ready to run the app until installation succeeds.
- Container build and remote publication are verified by user-provided build
  output, and deployment/smoke tests by user-provided output. Billing is enabled,
  budget alerts are user-confirmed, and runtime
  account attachment succeeded during deployment. No project roles have been
  requested for the runtime identity in this setup.

The passing subset was run with:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -m pytest -q -p no:cacheprovider -k 'invalid_configuration or environment_loading or structured_logging'
```

## Environment blockers

Python 3.12.9, Git, Docker CLI and Google Cloud CLI are installed. Initial checks
found that this session cannot write the default gcloud configuration/credential
database or access the Docker Desktop Linux engine pipe. No credentials were
copied or exposed. Resolve access in an authorised terminal/session before
deployment. The configured GCP project is not treated as deployment approval.

A separate login was attempted using an isolated, Git-ignored `.gcloud`
configuration. Browser authorization reached the CLI, but OAuth token exchange
failed because this session could not resolve `oauth2.googleapis.com`. The
separate login did not complete. Cloud commands currently run in the user's own
terminal; credentials are not copied or requested in chat.
