# AutoCloud AI

AI-powered cloud infrastructure monitoring and resource optimisation, following
[Cloud.md](Cloud.md). Development is intentionally gated by working milestones.

## Current milestone

Phase 1 local foundation is implemented. The first FastAPI service and Docker
packaging are ready for validation and an approved Cloud Run deployment. Cloud
project setup, billing, IAM, remote GitHub creation and cloud deployment have not
been performed. Monitoring, ML, pricing, agents, dashboard and scaling actions
remain future phases; there are no fabricated measurements or savings claims.

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
.\infrastructure\deploy.ps1 -ProjectId YOUR_PROJECT_ID `
  -RuntimeServiceAccount autocloud-runtime@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

The script only prints commands unless `-Execute` is supplied after approval.
It builds and publishes through Cloud Build, then deploys a private Cloud Run
service with zero minimum and at most two instances. Cloud Build runs tests
before building. It does not create a project, link billing, grant IAM or create
an Artifact Registry repository. Confirm these prerequisites first. Cloud Build
is not yet connected to a GitHub trigger; automated deployment is deferred.

The application configuration bounds are validation only; actual Cloud Run
limits are set by deployment flags. This application has no scaling permissions
or scaling endpoints. Region `asia-south1` is a proposed default, not a confirmed
user selection or a pricing assertion. No numeric pricing is assumed.

## Design and remaining work

- [Architecture and phase gates](docs/architecture.md)
- [Evaluation methodology](docs/methodology.md)
- [Current verification and blockers](docs/status.md)

Create monitoring and storage modules only after the initial deployment is
verified. Add the remaining structure from `Cloud.md` as each phase begins.
