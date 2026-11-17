# Private API and dashboard release

The updated cloud image contains FastAPI, Streamlit, bounded BigQuery/Billing
readers and the recorded evaluation summary. Experimental model weights, local
datasets, credentials and local review SQLite history are excluded. Model
inference and infrastructure execution are not enabled by this release.

The API receives `DASHBOARD_EVALUATION_FILE` and its SHA-256 digest. It validates
the packaged evaluation's checksum and scope before exposing the nine held-out
results. The dashboard retrieves a server-side Cloud Run identity token for its
configured HTTPS `run.app` API origin. The token never enters browser content.
Only Cloud Run IAM-authenticated callers can reach either service.

Cloud Run local files are ephemeral. When `DASHBOARD_REVIEW_BUCKET` is not
configured on the deployed API, the private cloud UI displays the review
capability as unavailable rather than presenting non-durable local SQLite
writes as a cloud approval history. Existing local reviews remain preserved on
the user's computer. Following explicit user approval on 16 November 2026,
durable authenticated cloud reviews (`CloudReviewStore` backed by regional
Cloud Storage bucket `astute-sign-506809-j8-autocloud-reviews` in
`asia-south1` with `if_generation_match=0` immutability and Google OIDC
verification via `DASHBOARD_REVIEW_BUCKET` and `DASHBOARD_REVIEW_AUDIENCE`) are
now deployed and live-verified on `autocloud-api-00006-pgf` and
`autocloud-dashboard-00005-ntj`.

## Approved runtime identities and permissions

Project: `astute-sign-506809-j8`, region: `asia-south1`.

| Identity | Permission | Scope |
| --- | --- | --- |
| `autocloud-api-reader@astute-sign-506809-j8.iam.gserviceaccount.com` | BigQuery Job User | Project, to create bounded query jobs |
| Same API identity | Custom role `autocloudGeminiPredict` (`aiplatform.endpoints.predict`) | Project `astute-sign-506809-j8` |
| Same API identity | Dataset READER | `autocloud` metrics dataset |
| Same API identity | BigQuery Data Viewer | Exact Billing export table `autocloud_billing.gcp_billing_export_v1_011640_0793FF_B5C560` |
| Same API identity | `roles/storage.legacyBucketReader`, `roles/storage.objectCreator`, `roles/storage.objectViewer` | Bucket `astute-sign-506809-j8-autocloud-reviews` only |
| `autocloud-dashboard@astute-sign-506809-j8.iam.gserviceaccount.com` | Cloud Run Invoker | `autocloud-api` service only |

These two service accounts were created after explicit approval; no keys were created. Neither
identity receives Owner, Editor, cloud mutation, or project-wide Cloud Storage permissions.
Public/unauthenticated access is not granted. API minimum/maximum instances are
0/2; dashboard minimum/maximum are 0/1. Request-based CPU billing is retained.
The dashboard uses a 60-minute WebSocket request timeout; active sessions may
incur runtime charges. The API uses a 60-second timeout for bounded queries.

## Release evidence

Local validation: 201 tests passed, including recorded-summary checksum/scope,
disabled cloud reviews, and configured-origin identity-token tests.
The Windows Streamlit temporary-directory cleanup warning occurs after the
successful test exit; it is not a runtime or test failure.

Build and rollout metadata are under `data/releases/20261116T055002Z/`.
Cloud Build `770047f9-9a8b-43f3-bb96-8fa34f8f4177` succeeded. The service plans
pin image digest `sha256:b8395ba243413ce4c6e9457bcf24dead337edfb07995723763d11a84e4477b87`.
`deployment-plan.json` contains the exact proposed services and grants.
Automatic approval review initially rejected the IAM setup because generic
deployment authorization did not specifically approve these identities and scopes.
The user subsequently explicitly approved the listed accounts and grants, and
they were applied. Cloud Resource Manager API was enabled to perform the approved
project-role grant. Existing unrelated project, dataset and service IAM entries
were preserved.

## Verified deployment — 16 November 2026

| Service | URL | Ready revision | Min / max |
| --- | --- | --- | --- |
| API | https://autocloud-api-l25hfnltba-el.a.run.app | `autocloud-api-00002-fvj` | 0 / 2 |
| Dashboard | https://autocloud-dashboard-l25hfnltba-el.a.run.app | `autocloud-dashboard-00002-rd8` | 0 / 1 |

The existing API revision `autocloud-api-00001-n6m` is retained for rollback.
Both services report ready. Neither has public/all-authenticated-user IAM
bindings, and unauthenticated HTTP requests to each returned 403.

Authenticated deployed API checks passed: readiness, BigQuery Monitoring read,
recorded evaluation with 0/9 beating persistence, and Billing export read.
Billing returned no matching Cloud Run rows; cost remains unknown. Cloud reviews
are explicitly disabled, while local review history remains preserved.

Browser verification through the authenticated developer proxy passed for
Infrastructure, Models, Recommendations and the explicit billing read. This
exercised the deployed dashboard's own service-account-to-API authentication.
The Models tab showed the completed 232-minute training cohort and held-out
comparison. Current stale measurements remain historical. Experimental model
inference, anomaly accuracy and savings are not claimed.

The first dashboard revision lacked `/app` on Python's module path for its
Streamlit console entrypoint. The final revision sets `PYTHONPATH=/app`, fixing
imports of the authentication helper. The Dockerfile also includes this default
for future builds; the deployed immutable image uses the runtime environment fix.

Cloud release checks passed 201 tests before packaging. Nine cloud/proxy tests
subsequently passed, including two new loopback origin and token relay checks.
Tokens are kept server-side in memory, never returned to the browser or written
to release metadata. `verification.json`, service summaries and rollback state
are saved in the release directory. Developer proxy changes are local tooling
and are not part of the deployed image.

## Verified R1–R7 hardened rollout — 16 November 2026

| Service | URL | Ready revision | Min / max |
| --- | --- | --- | --- |
| API | https://autocloud-api-l25hfnltba-el.a.run.app | `autocloud-api-00007-x5w` | 0 / 2 |
| Dashboard | https://autocloud-dashboard-l25hfnltba-el.a.run.app | `autocloud-dashboard-00006-fhw` | 0 / 1 |

Build `a1be38c7-e86a-4694-b6f8-f0188aae27e4` (`SUCCESS`) produced immutable image
`asia-south1-docker.pkg.dev/astute-sign-506809-j8/autocloud/autocloud-dashboard@sha256:1e5195a7732da62f16de800cc2d10ae0437d7e2e63cefcd71b7a1b11f262d8f1`
(release `data/releases/20261116T110246Z/` and `data/releases/ai-current.json`).
Packaged evaluation summary SHA-256 on `autocloud-api`:
`9461e93bd134b2650edc71166f09aefaf6a5fe29221560550f3dc3b8d5234841`.

Live verification (`data/releases/20261116T110246Z/verification.json`) confirmed:
- Unauthenticated `/`, `/health/ready`, `/api/overview`, `/api/reviews`, and
  dashboard `/` all returned HTTP 403.
- Authenticated `GET /` returned HTTP 200 with `stage="configured"` and
  `capabilities.autonomous_execution=false`.
- Authenticated `GET /api/overview?source=bigquery&hours=24` returned HTTP 200
  with `cloud_reviews=true`, `gemini_enabled=true`,
  `anomaly_evaluation_status="evaluated_preliminary"`,
  `shared_observable_comparison.evaluated_samples=41`,
  `fault_sensitivity_measured=false`, and `forecast_diagnostics` (`9` models,
  `0` beating persistence).
- Live `R1` negative checks on `/api/reviews` returned HTTP 403 for redacted-only
  `Authorization`, wrong generic Cloud SDK audience, and browser `Origin`.
- Live authenticated Streamlit WebSocket UI check
  (`wss://autocloud-dashboard-l25hfnltba-el.a.run.app/_stcore/stream`) clicked
  `"Load review history"` and rendered `"Latest 200 saved recommendations"`,
  `"calling dashboard service identity"`, and `"No saved recommendations yet"`
  without error — proving `autocloud-dashboard` -> `autocloud-api/api/reviews`
  dual-header `X-AutoCloud-Authorization` verification end-to-end.

## Verified cloud review rollout — 16 November 2026 (prior release `20261116T090610Z`)

Build `b4a117c2-b0d8-45d4-b0eb-a20f22a2995f` (`sha256:02987e09738e2412a1abd47aad67d074d78641352ede8cf32416b299d68b8826`,
prior revisions `autocloud-api-00006-pgf` / `autocloud-dashboard-00005-ntj`)
provisioned regional bucket `astute-sign-506809-j8-autocloud-reviews` (`ASIA-SOUTH1`,
uniform bucket-level access, enforced public access prevention); superseded on
16 November 2026 by release `20261116T110246Z`.

## Open the private cloud dashboard

Direct unauthenticated browser visits to the Cloud Run URLs return 403 by design.
Use the active local developer proxy at **http://127.0.0.1:8503/**. Unlike the local
dashboard on port 8501, this address forwards to the deployed cloud dashboard.
Keep the proxy terminal running while viewing it, and close the tab when finished
to release its active WebSocket request. Minimum zero allows idle scale-to-zero;
active sessions, query jobs and storage can still incur charges.

To restart with existing ADC from the project directory:

```cmd
.venv\Scripts\python.exe -m app.dashboard.private_proxy --url https://autocloud-dashboard-l25hfnltba-el.a.run.app --port 8503
```

Proxy dependencies are listed in `requirements-proxy.txt`. The proxy binds only
to IPv4 loopback, rejects cross-origin requests, forwards only to the specified
HTTPS `run.app` origin, and supports Streamlit WebSockets. Its HTTP client reuses
connections and respects the developer environment's outbound proxy settings.
It uses the existing ADC user's short-lived ID token and does not create keys.
The official Google Cloud CLI alternative is:

```cmd
gcloud run services proxy autocloud-dashboard --project=astute-sign-506809-j8 --region=asia-south1 --port=8503
```

## Primary references checked 16 November 2026

- https://docs.cloud.google.com/run/docs/authenticating/service-to-service
- https://docs.cloud.google.com/run/docs/triggering/websockets
- https://docs.cloud.google.com/build/docs/running-builds/submit-build-via-cli-api
