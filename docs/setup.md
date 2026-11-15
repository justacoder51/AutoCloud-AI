# Phase 1 setup and initial deployment

Cloud changes require explicit human approval under `Cloud.md` sections 10, 13
and 15. Commands below are instructions for review, not evidence of execution.
Use a dedicated project and confirm which billing account is authorised.

## Required decisions

- Confirm an existing project ID, or a globally unique ID for a new project.
- Confirm billing account and monthly alert amount/currency.
- Confirm region (proposed: `asia-south1`).
- Confirm deployer identity, build identity and runtime identity.
- Confirm GitHub owner/repository and visibility before creating a remote.

The CLI currently names an existing project, but that does not establish billing,
API access or permission to deploy. Never assume that configured means approved.

## Authentication and preflight

Run in a terminal that can access your normal Google Cloud SDK configuration:

```powershell
gcloud auth login
gcloud auth list
gcloud projects describe YOUR_PROJECT_ID
gcloud billing projects describe YOUR_PROJECT_ID
gcloud services list --enabled --project=YOUR_PROJECT_ID
```

For later Python integrations use `gcloud auth application-default login` locally.
On Cloud Run use its attached service account with Application Default
Credentials; never download a service account key. Do not commit credentials.

## Project, billing and alerts (approval required)

If a new project is required, use `gcloud projects create YOUR_PROJECT_ID`,
including organisation/folder options where the account requires them. Link an
approved billing account using:

```powershell
gcloud billing projects link YOUR_PROJECT_ID --billing-account=YOUR_BILLING_ACCOUNT_ID
```

Create a monthly project-scoped budget in Cloud Billing > Budgets & alerts.
Use the approved amount in the billing account currency and alert thresholds
at 50%, 90% and 100%; verify that the intended recipients receive notifications.
An alerts-only budget does not cap spending. No budget amount is assumed here.

Enable only the APIs needed for the first milestone:

```powershell
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com iam.googleapis.com logging.googleapis.com --project=YOUR_PROJECT_ID
gcloud artifacts repositories create autocloud --repository-format=docker --location=asia-south1 --project=YOUR_PROJECT_ID
gcloud iam service-accounts create autocloud-runtime --display-name="AutoCloud runtime" --project=YOUR_PROJECT_ID
```

Monitoring, BigQuery, Storage, Pub/Sub and Vertex AI configuration belongs to
subsequent phases. Avoid enabling every service up front.

## Least-privilege IAM review

| Identity | Required scope for this milestone |
| --- | --- |
| Setup administrator | Project creation, approved billing linkage, API enablement, repository/service-account creation and narrowly scoped IAM grants |
| Deployer | Cloud Run deployment permissions; Service Account User on the runtime identity; Cloud Build submission and build/source staging permissions |
| Build identity | Artifact Registry Writer on `autocloud`, Logs Writer, and access to the source staging bucket used by Cloud Build |
| Runtime identity | No project roles: this initial service does not call Google APIs |
| Reviewer/tester | Cloud Run Invoker on the deployed service |

Inspect `gcloud builds get-default-service-account --project=YOUR_PROJECT_ID`
before granting roles: do not assume the legacy Cloud Build account is used.
Use resource-scoped IAM grants wherever available. See the official deployment
and Cloud Build documentation for the exact permissions needed by your account
and organisation policies; avoid broad Owner/Editor grants as shortcuts.

## Review and execute the deployment

1. Run local tests and Docker smoke checks from the README.
2. Preview `infrastructure/deploy.ps1` with the selected project and runtime
   identity. Review the image, private-access policy, instance limits and region.
3. After explicit approval, rerun with `-Execute`. This incurs build, image
   storage and runtime usage. The script stops on a failed command.
4. Capture the deployed URL:

```powershell
$serviceUrl = gcloud run services describe autocloud-api --project=YOUR_PROJECT_ID --region=asia-south1 --format="value(status.url)"
$identityToken = gcloud auth print-identity-token
$headers = @{ Authorization = "Bearer $identityToken" }
Invoke-RestMethod "$serviceUrl/health/ready" -Headers $headers
1..20 | ForEach-Object { Invoke-RestMethod "$serviceUrl/" -Headers $headers }
gcloud run services logs read autocloud-api --project=YOUR_PROJECT_ID --region=asia-south1 --limit=50
```

Do not log or save the identity token. Verify unauthenticated access is denied,
the authenticated readiness response succeeds, and request logs appear. Record
the revision and test date in `docs/status.md`. Only then begin monitoring.

## GitHub

The local repository can be initialised independently of cloud setup. Before
the first commit inspect `git status` for credentials and generated files.
Choose an approved owner/name and visibility, create the GitHub repository,
add its remote, and push after reviewing the staged files. No remote is assumed
and no GitHub repository has been created by this implementation.

## Official references (checked 2026-11-15)

- [FastAPI on Cloud Run](https://docs.cloud.google.com/run/docs/quickstarts/build-and-deploy/deploy-python-fastapi-service)
- [Cloud Run deployment flags](https://docs.cloud.google.com/sdk/gcloud/reference/run/deploy)
- [Service identity and permissions](https://docs.cloud.google.com/run/docs/configuring/services/service-identity)
- [Cloud Build configuration](https://docs.cloud.google.com/build/docs/build-config-file-schema)
- [Budget alerts](https://docs.cloud.google.com/billing/docs/how-to/budgets)

Pricing calculations are deferred to Phase 5. Verify regional pricing and
billing exports then; estimated expenditure must remain separate from bills.
