# Scheduled monitoring collection

Real metric collection and BigQuery ingestion/readback are verified. The next
step packages the same collector as a Cloud Run Job, then uses Cloud Scheduler
to invoke it every five minutes. This does not keep a background thread running
inside the FastAPI service and does not require a local terminal to stay open.

The collector image/job and recurring trigger are now deployed according to
user-provided output. The first on-demand dispatch through Scheduler completed
under its own identity; independent cron recurrence/freshness is still pending.
The existing API and its runtime identity are not modified by these steps.

## Reviewable configuration

| Resource | Configuration |
| --- | --- |
| Project / region | astute-sign-506809-j8 / asia-south1 |
| Collector image / job | autocloud-collector:v1 / autocloud-collector |
| Collector identity | autocloud-collector@astute-sign-506809-j8.iam.gserviceaccount.com |
| Scheduler job | autocloud-collect |
| Schedule | Every five minutes, Asia/Kolkata (288 scheduled invocations/day) |
| Lookback / ingestion lag | 30 minutes / 180 seconds |
| Resources per task | 1 CPU, 512 MiB, one task and parallelism 1 per execution |
| Task timeout / retries | 300 seconds / at most one task retry |
| Scheduler request retries | 0 configured retries; delivery can still be at least once |
| Destination | autocloud.infrastructure_metrics; read autocloud.latest_metrics |

The overlapping lookback recovers delayed observations. Read the deduplication
view to prevent repeated logical windows being counted twice. Parallelism 1
applies per execution, not across independently triggered executions; duplicate
triggers can overlap. BigQuery load retries and the view protect stored logical
records, not exactly-once execution. A schedule failure does not prove that the
collector failed, and scheduler success only means the execution was requested:
inspect Cloud Run execution completion and data freshness too.

No load generator is included. A quiet service that scales to zero may produce
few or no metrics. Do not impute that absence to create apparent training data.
Twenty-nine minutes of mostly idle observations are insufficient for useful
chronological model evaluation. Gather a longer representative history, then
design a labelled controlled-load experiment separately.

## Identity permissions

| Identity | Granted role | Scope |
| --- | --- | --- |
| Collector | Monitoring Viewer | Monitored project |
| Collector | BigQuery Job User | Ingestion project |
| Collector | BigQuery Data Editor | infrastructure_metrics table only |
| Scheduler | Cloud Run Invoker | Collector job only |

The collector receives no Cloud Run scaling/deployment permissions. Its stdout
is collected by Cloud Run; no direct Logging API write role is needed. ADC comes
from the attached service account; no keys or local ADC files enter the image.
The Scheduler trigger uses OAuth because its target is `run.googleapis.com`,
not OIDC. The active deployer needs permission to attach both identities.
The project's existing default build identity is still used for image builds;
its pre-existing Editor role has not been removed.

## Run one stage at a time

### If PowerShell scripts are disabled

The user reported that Windows blocks `.ps1` execution before the helper runs.
No cloud changes occur in that case. Use individual native commands in Command
Prompt; changing execution policy is not required. For the Identity stage:

```cmd
gcloud iam service-accounts create autocloud-collector --display-name="AutoCloud metric collector" --project=astute-sign-506809-j8
gcloud iam service-accounts create autocloud-scheduler --display-name="AutoCloud schedule invoker" --project=astute-sign-506809-j8
gcloud projects add-iam-policy-binding astute-sign-506809-j8 --member="serviceAccount:autocloud-collector@astute-sign-506809-j8.iam.gserviceaccount.com" --role="roles/monitoring.viewer" --condition=None
gcloud projects add-iam-policy-binding astute-sign-506809-j8 --member="serviceAccount:autocloud-collector@astute-sign-506809-j8.iam.gserviceaccount.com" --role="roles/bigquery.jobUser" --condition=None
bq --project_id=astute-sign-506809-j8 add-iam-policy-binding --table=true --member="serviceAccount:autocloud-collector@astute-sign-506809-j8.iam.gserviceaccount.com" --role="roles/bigquery.dataEditor" astute-sign-506809-j8:autocloud.infrastructure_metrics
```

Run one command at a time and stop on failure. The helper stages below are an
optional convenience when local execution policy permits them; direct gcloud
and bq commands provide the same reviewed deployment operations.

After identity setup succeeds, the direct **Build** command is:

```cmd
gcloud builds submit . --project=astute-sign-506809-j8 --region=asia-south1 --config=infrastructure/cloudbuild.yaml --substitutions=_IMAGE=asia-south1-docker.pkg.dev/astute-sign-506809-j8/autocloud/autocloud-collector:v1,_DOCKERFILE=infrastructure/collector.Dockerfile
```

It runs the complete test suite and publishes the collector image. It does not
deploy or schedule the job. Wait for SUCCESS before proceeding.

After a successful build, deploy the job with the direct command:

```cmd
gcloud run jobs deploy autocloud-collector --project=astute-sign-506809-j8 --region=asia-south1 --image=asia-south1-docker.pkg.dev/astute-sign-506809-j8/autocloud/autocloud-collector:v1 --service-account=autocloud-collector@astute-sign-506809-j8.iam.gserviceaccount.com --tasks=1 --parallelism=1 --max-retries=1 --task-timeout=300s --cpu=1 --memory=512Mi --args="--minutes=30,--output=/tmp/metrics.ndjson,--write-bigquery" --set-env-vars="APP_ENV=production,GCP_PROJECT_ID=astute-sign-506809-j8,GCP_REGION=asia-south1"
```

Only after deployment succeeds, run one execution and wait for completion:

```cmd
gcloud run jobs execute autocloud-collector --project=astute-sign-506809-j8 --region=asia-south1 --wait
```

Manual execution does not create a schedule. Inspect collector logs and BigQuery
freshness after it completes, then configure Scheduler separately.

After a successful manual run and verified data writes, the direct commands
for the **Schedule** stage are:

```cmd
gcloud services enable cloudscheduler.googleapis.com --project=astute-sign-506809-j8
gcloud run jobs add-iam-policy-binding autocloud-collector --project=astute-sign-506809-j8 --region=asia-south1 --member="serviceAccount:autocloud-scheduler@astute-sign-506809-j8.iam.gserviceaccount.com" --role="roles/run.invoker"
gcloud scheduler jobs create http autocloud-collect --project=astute-sign-506809-j8 --location=asia-south1 --schedule="*/5 * * * *" --time-zone="Asia/Kolkata" --uri="https://run.googleapis.com/v2/projects/astute-sign-506809-j8/locations/asia-south1/jobs/autocloud-collector:run" --http-method=POST --headers="Content-Type=application/json" --message-body="{}" --oauth-service-account-email=autocloud-scheduler@astute-sign-506809-j8.iam.gserviceaccount.com --attempt-deadline=30s --max-retry-attempts=0
```

The last command enables recurring cloud usage. Check its result, then verify
an actual triggered execution completes successfully before reporting the
recurring pipeline as verified.

### Optional PowerShell helper

The PowerShell helper prints exact command arguments by default. Add `-Execute`
only after reviewing and approving that stage. All default target values match
the confirmed project and region. Run from the project directory.

If using **Command Prompt**, prefix the helper with `powershell -NoProfile -File`:

```cmd
powershell -NoProfile -File infrastructure\collector.ps1 -Step Identity
```

Then execute the reviewed identity stage:

```cmd
powershell -NoProfile -File infrastructure\collector.ps1 -Step Identity -Execute
```

It creates two service accounts (skipping already-existing accounts), grants
Monitoring Viewer and BigQuery Job User to the collector, and grants Data Editor
on the one metrics table. It does not grant dataset/project-wide Data Editor.
The `bq` IAM command supports tables; it is not used to modify dataset IAM.
Any failed command stops the stage. Rerunning identity grants is additive.

After identity setup succeeds, preview then execute **Build**:

```cmd
powershell -NoProfile -File infrastructure\collector.ps1 -Step Build
powershell -NoProfile -File infrastructure\collector.ps1 -Step Build -Execute
```

The shared Cloud Build configuration runs tests, builds the dedicated collector
Dockerfile and publishes the image. Wait for SUCCESS before **Deploy**:

```cmd
powershell -NoProfile -File infrastructure\collector.ps1 -Step Deploy
powershell -NoProfile -File infrastructure\collector.ps1 -Step Deploy -Execute
```

Deployment does not immediately execute the collector. Run it once and wait
for successful completion before scheduling it:

```cmd
powershell -NoProfile -File infrastructure\collector.ps1 -Step Run -Execute
```

Verify the BigQuery view now contains fresh observations. A successful job can
report `no_observations` when the target has no available measurements; inspect
the structured summary in Cloud Logging, not only the execution status.

Only after the manual cloud execution passes, preview/execute **Schedule**:

```cmd
powershell -NoProfile -File infrastructure\collector.ps1 -Step Schedule
powershell -NoProfile -File infrastructure\collector.ps1 -Step Schedule -Execute
```

This enables Cloud Scheduler, grants its separate caller invocation permission
on the collector job, and creates the recurring HTTP trigger. If it already
exists, the create command fails rather than silently replacing the schedule.
Inspect/update the existing job explicitly instead of deleting it automatically.
If API enablement/IAM propagation causes an error, wait and rerun the failed
stage. No Owner/Editor grants should be needed by the new runtime identities.

## Observe and pause

After the first scheduled interval, inspect executions and scheduler state:

```cmd
powershell -NoProfile -File infrastructure\collector.ps1 -Step Status -Execute
```

Read collector stdout in Cloud Logging, filtering on resource type
`cloud_run_job` and job name `autocloud-collector`. Verify successful execution
and advancing timestamps in `autocloud.latest_metrics`. The optional archive is
not enabled and Cloud Storage is not a required sink in this deployment.

Pause recurring invocations when the experiment is not running:

```cmd
powershell -NoProfile -File infrastructure\collector.ps1 -Step Pause -Execute
```

Resume using `-Step Resume -Execute`. Pausing does not cancel an active
execution, delete data or stop the separately deployed API. A resumed collector
only covers its configured lookback; backfill longer gaps with a reviewed
manual collection if needed. Existing IAM grants/resources remain in place.

## Cost and validation limits

Cloud Run jobs have a minimum billable instance lifetime of one minute per
started instance. A 15-minute schedule avoids the extra starts of a one-minute
poll while still collecting one-minute observations in batches. Cloud Scheduler,
image storage, build execution, Monitoring and BigQuery usage may also incur
charges. Free-tier usage is shared across billing-account projects; this setup
does not promise a zero bill or measured savings. Review current regional
pricing and the already-configured budget alerts before enabling the schedule.

Local checks cover PowerShell parsing, command previews, SDK request encoding
and the existing offline collector tests. Cloud image build, job execution,
IAM enforcement and actual scheduled invocations require user-terminal
verification. Prepared files are not reported as deployed resources.

## Read-only monitoring freshness investigation (2026-11-16T11:59Z)

Read-only inspection against `astute-sign-506809-j8` / `asia-south1` (`autocloud-api`):
- **Scheduler & collector health:** Cloud Scheduler `autocloud-collect` is
  `ENABLED` (`*/15 * * * *`, `Asia/Kolkata`, `lastAttemptTime = 2026-11-16T11:45:05Z`)
  and all `12` trailing executions (`09:00Z`–`11:45Z`) completed with
  `CONDITION_SUCCEEDED` (`failedCount = 0`, `14.45s`–`30.99s` wall time).
- **BigQuery coverage & ingestion lag:** `autocloud.latest_metrics` holds `618`
  distinct minutes (`min_ts = 2026-11-15T11:40:00Z`, `max_ts = 2026-11-16T11:42:00Z`,
  `max_collected_at = 2026-11-16T11:45:28.148932Z`). The newest batch wrote `30/30`
  minutes (`11:12Z`–`11:42Z`) with `min_delay_sec = 208s` (`3m28s`, reflecting
  `lag_seconds=180` + job runtime). Across overlapping 30-minute runs and prior
  backfills, deduplicated `latest_metrics` row lag spans `208s`–`13,862s`
  (median `1,817s`, `95th` percentile `12,062s`).
- **Why the 15-minute freshness gate still triggers when active & when idle:**
  Direct Cloud Monitoring probe at `11:59:24Z` showed active data right up to
  `11:56:00Z` (`30/30` rows with `lag_seconds=180`) and `11:59:00Z` (`0s` lag), yet
  `latest_metrics` still ended at `11:42:00Z` (`17m24s > 15m` old) while waiting
  for the `12:00:04Z` cron run (`15m` cron + `3m` lag + `~0.5m` execution).
  Separately, when `autocloud-api` (`min_instances=0`) scales to zero during idle
  periods (e.g., `10:12Z`–`10:42Z`, `autocloud-collector-g9pxc`), Cloud Monitoring
  emits `samples = 0` (`status = "no_observations"`), producing true sparse hours
  (`09:00Z`: `36/60`, `10:00Z`: `9/60`). No collector schedule, lag, or freshness
  gate settings were modified.

Official references checked 2026-11-15:

- [Scheduled Cloud Run jobs](https://docs.cloud.google.com/run/docs/execute/jobs-on-schedule)
- [Scheduler OAuth and flags](https://docs.cloud.google.com/sdk/gcloud/reference/scheduler/jobs/create/http)
- [Cloud Run Job deployment](https://docs.cloud.google.com/sdk/gcloud/reference/run/jobs/deploy)
- [Table-level bq IAM](https://docs.cloud.google.com/bigquery/docs/reference/bq-cli-reference)
- [Cloud Run pricing](https://cloud.google.com/run/pricing)
