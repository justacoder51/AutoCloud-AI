# AutoCloud AI

AI-powered cloud infrastructure monitoring and resource optimisation, following
[Cloud.md](Cloud.md). Development is intentionally gated by working milestones.

## Current milestone

The cloud Recommendations tab now has explicit LangGraph analysis controls.
Gemini integration code is ready but cloud calls remain disabled pending the
additional inference IAM approval. See [dashboard AI workflow](docs/dashboard-ai.md).

The updated API and dashboard are deployed privately on Cloud Run and were
browser-verified on 16 November 2026. Open the cloud dashboard through an
authenticated developer proxy; see [cloud access and deployment evidence](docs/cloud-dashboard.md).
The cloud view includes recorded model evaluation; model inference and durable
cloud review decisions are not enabled.

First measured-data training completed; see [training results](docs/training-results.md).
All nine exploratory forecasts performed worse than persistence on held-out MAE.
Artifacts are saved locally; no model deployment or scaling is approved by these results.

A bounded operator-only scaling trial is implemented separately from review
approvals. Live minimum-instance 0 → 1 → 0 and restored service readiness were
verified on 16 November 2026; maximum 2 and serving revision were preserved.
See [trial safeguards and results](docs/scaling-trial.md).

Local recommendation review is available in the Recommendations tab: save
supported candidates, record approve/reject decisions and reload durable history.
Approval is for manual investigation only; it never executes cloud changes.
See [review workflow](docs/recommendations.md#local-recommendation-reviews).
The [demo walkthrough and verification](docs/demo-walkthrough.md) records the
live checks, 183-test result and remaining evaluation limitations.

The local foundation and the first Cloud Build test/build/publish run succeeded.
Image `autocloud-api:v1` is available in the project's `autocloud` repository.
Cloud Run revision `autocloud-api-00001-n6m` is deployed. Authenticated readiness
returned 200, unauthenticated access returned 403, and request logs were verified.
Budget alerts are confirmed
by the user. Billing is enabled, the image repository and runtime account
exist, and build permissions were configured. The private GitHub repository is
connected; project `astute-sign-506809-j8` and region `asia-south1` are confirmed.
The model/monitoring suite has 32 passing tests, including real CPU XGBoost
integration; eight additional tests verify bounded traffic controls. Real
Monitoring collection and BigQuery ingestion succeeded: the latest
run produced 323 samples and loaded 29 service-minute observations. Readback
through the deduplication view confirmed all 29 records. The dedicated collector
Cloud Run Job is deployed and its first cloud execution collected 42 samples
and loaded 5 records successfully. The 15-minute Cloud Scheduler trigger is
enabled, and an on-demand invocation through Scheduler completed successfully
under its dedicated identity. Phase 4 ML code now includes readiness gates,
Isolation Forest and XGBoost forecasting/evaluation; representative data and
real training are still pending. The independent cost module has 20 passing
tests, dated regional pricing and an optional Billing export reader. Actual
usage/billing inputs and measured savings remain unverified. Phase 6 now has a
deterministic recommendation/policy foundation, a finite LangGraph workflow and
an opt-in ADC/Vertex Gemini adapter. Live Monitoring-to-BigQuery-to-LangGraph-to-
Gemini processing is verified with fresh data and a valid no-action result.
Native candidate forecast loading and optional Billing export reads are wired
into the workflow. Real ML training and Cloud Run cost rows remain unavailable;
the local dashboard is implemented and scaling remains pending. There are no fabricated
measurements or savings claims.

Forecast horizons are now 5, 10 and 15 minutes. The default exploratory training
profile targets 200 observed minutes with coverage and purged split-label checks;
results remain preliminary. `--profile=conservative` retains the 1,440-minute
gate. This change does not make sparse real history ready automatically.

A user-authorised bounded background training-history experiment is now running:
210 minutes, at most 2,100 requests, followed by Monitoring collection and
readiness-gated exploratory training. See docs/controlled-traffic.md for status
and stop commands. Its final training outcome is not established yet.

## Local setup (PowerShell, Python 3.11+)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Visit `http://127.0.0.1:8080/docs` or call:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health/ready
```

Endpoints: `/` identifies the current milestone; `/health/live` and
`/health/ready` check this process. Readiness does not imply that GCP has been
configured. Responses have request IDs and the application emits JSON logs.
Unhandled errors return sanitized responses.

Configuration is read from environment variables listed in `.env.example`.
For example, `$env:PORT = '8080'`. A `.env` file is not loaded automatically
by the Python application. In production, set `APP_ENV=production` and
`GCP_PROJECT_ID`; interactive API documentation is disabled. Cloud Run IAM
protects the entire deployed service. Local development binds to loopback and
does not implement a separate login mechanism.

## Docker

Start Docker Desktop with the Linux engine, then:

```powershell
docker build -t autocloud-api:local .
docker run --rm -p 127.0.0.1:8080:8080 --env-file .env autocloud-api:local
```

Copy `.env.example` to `.env` first or omit `--env-file .env` for defaults.
The container runs as a non-root user and listens on Cloud Run's `PORT`.
Only application code and runtime requirements enter the Docker context.

## GCP and deployment

Follow [the setup and deployment checklist](docs/setup.md). A preview is safe:

```powershell
.\infrastructure\deploy.ps1 -ProjectId astute-sign-506809-j8 -Region asia-south1 `
  -RuntimeServiceAccount autocloud-runtime@astute-sign-506809-j8.iam.gserviceaccount.com
```

The script only prints commands unless `-Execute` is supplied after approval.
It builds and publishes through Cloud Build, then deploys a private Cloud Run
service with zero minimum and at most two instances. Cloud Build runs tests
before building. It does not create a project, link billing, grant IAM or create
an Artifact Registry repository. Confirm these prerequisites first. Cloud Build
is not yet connected to a GitHub trigger; automated deployment is deferred.

The application configuration bounds are validation only; actual Cloud Run
limits are set by deployment flags. This application has no scaling permissions
or scaling endpoints. Region `asia-south1` is the confirmed deployment region.
No numeric pricing is assumed.

## Design and remaining work

- [Monitoring collection, metric units and BigQuery setup](docs/monitoring.md)
- [Scheduled cloud collection and scoped identities](docs/scheduled-collection.md)
- [ML readiness, chronological evaluation and candidate artifacts](docs/machine-learning.md)
- [Bounded controlled traffic experiment](docs/controlled-traffic.md)
- [Cost estimates, dated pricing and optional Billing export](docs/cost-analysis.md)
- [Evidence-bound recommendation policy and local preview](docs/recommendations.md)
- [Architecture and phase gates](docs/architecture.md)
- [Evaluation methodology](docs/methodology.md)
- [Current verification and blockers](docs/status.md)

Install `requirements-monitoring.txt` for standalone collection, or
`requirements-dev.txt` for development and the full test suite. The v1 FastAPI
Docker image still installs only runtime requirements and has not been
redeployed for monitoring. Add the remaining structure from `Cloud.md` as each
phase begins; verify data readiness and independent model evaluation before
using ML output in recommendations or infrastructure changes.
# Local monitoring dashboard

The read-only Streamlit dashboard and FastAPI `/api/overview` endpoint support
explicit BigQuery reads and local snapshots. See [dashboard setup](docs/dashboard.md) for separate-terminal
commands and current limitations. The Models tab now separates observed-window
readiness from explicit trusted candidate evaluation and forecasts. The Costs &
actions tab supports explicitly configured billing-export reads. Real model
selection, verified Cloud Run cost rows and approval integration remain pending.

