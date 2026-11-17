# Bounded real traffic experiment

## Training-history run

On user request, `app.data.training_experiment` provides a bounded background
baseline-collection run. It does not relax the existing per-block traffic caps.
Seven 30-minute phases use 6/10/14/6/10/14/10 requests per minute: 210 minutes,
at most 2,100 requests, and no more than 14 requests/minute. This reviewed
longer workload is opt-in and may incur Cloud Run/logging/BigQuery usage.
The machine must stay awake with network access. It creates no cloud resources,
changes no IAM/scaling settings, and performs no model deployment.

```cmd
.venv\Scripts\python.exe -m app.data.training_experiment
.venv\Scripts\python.exe -m app.data.training_experiment --execute
.venv\Scripts\python.exe -m app.data.training_experiment --status
.venv\Scripts\python.exe -m app.data.training_experiment --stop
```

Preview is the default. The already-started run should not be started again;
duplicate active runs are refused. Status, per-phase request manifests and the
collected baseline are under `data/training_runs/`. A stop request is checked
between requests and short sleep chunks; an in-flight request/credential refresh
or bounded collection/training subprocess can take longer to finish.
The runner uses existing authorised developer ADC identity tokens in memory,
and a fixed-target HTTPX transport with redirects disabled and SOCKS support.
The regular short traffic CLI still uses its original gcloud authentication.
Tokens and provider error bodies are not saved.

After traffic completes, the runner waits five minutes for Monitoring, collects
the last four hours through the existing collector and writes real observations
to BigQuery. It selects only fully exposed minute endpoints from this experiment
into `baseline.ndjson`, avoiding contamination by older sparse windows. It then
calls the existing exploratory training CLI with --train, retaining the 200-minute,
coverage, variation and measured split-label gates. Completion is reported as
`completed` only when trained=true; otherwise it reports `training_not_ready`
or a failure. No missing metric or target is manufactured. Baseline traffic is
not independently labelled anomaly ground truth. A later detection demonstration
needs separate test traffic kept out of this training experiment.

## Short pipeline check

### Holding automatic training

A `HOLD_TRAINING` marker beside the experiment's future `baseline.ndjson`
pauses the fresh training CLI before assessment/fitting, without interrupting
traffic or metric collection. The CLI returns `status=training_paused` and
`trained=false`. This also works for the already-running foreground worker,
which starts the training module in a separate process after collection.
That worker may record its legacy top-level `training_not_ready` stage; the
nested training status distinguishes a user hold from failed readiness, and
the dashboard exposes that distinction plus `training_hold_requested`.
The hold is specific to this input directory, not a global training switch.
Do not remove it or resume training without the user's instruction.

The current real history is short and mostly idle. A first controlled test can
check that real requests appear in Monitoring and BigQuery. It is not sufficient
to train/evaluate the ML models and is not a capacity or savings experiment.

`app.data.traffic` sends requests only to the confirmed private API root URL.
It obtains the active gcloud user's ID token in memory, does not log/save it,
does not follow redirects and needs no local proxy. It labels HTTP User-Agent
with an experiment identifier. The API service code/configuration is unchanged.

From the project folder in Command Prompt, preview the default experiment:

```cmd
.venv\Scripts\python.exe -m app.data.traffic
```

The preview sends no requests and performs no token lookup. To explicitly start
the reviewed plan (at most 60 requests, nominally 30/minute over two minutes):

```cmd
.venv\Scripts\python.exe -m app.data.traffic --execute
```

This creates real API traffic and can incur request, compute and logging usage.
It does not create cloud resources or make the service public. Keep this local
terminal running until the test ends; unlike the cloud collector, the traffic
generator runs on your computer. Ctrl+C stops it and saves partial results.

The rate is an upper bound, not a throughput guarantee. Requests are sequential;
slow requests are not followed by catch-up bursts. No new request starts after
the duration budget, though an in-flight request/token lookup may finish later.
There is a fixed request cap, a ten-second HTTP timeout and early stopping for
401/403/429/redirects or three consecutive server/network failures. CLI errors
are recorded by exception type, not potentially sensitive command output.

All limits can be lowered or changed explicitly, within hard maximums of one
hour, 120 requests/minute and 1,000 total requests. Do not run repeated or longer
experiments without reviewing the workload and budget first. The command has
no option for forwarding credentials to arbitrary URLs.

The result is saved under `data/experiments/` with timestamps, HTTP statuses,
the exact requested limits and client round-trip percentiles. Those client
timings include network overhead and are not the same as Cloud Run's server
latency distributions. Experiment traffic is real observed traffic; neither
successful HTTP responses nor this test's timing intervals are independent
ground-truth anomaly labels.

After allowing at least three minutes for metric ingestion, collect the recent
window explicitly, or let the enabled 15-minute schedule collect it:

```cmd
.venv\Scripts\python.exe -m app.data.collector --project=astute-sign-506809-j8 --region=asia-south1 --service=autocloud-api --minutes=30 --write-bigquery
```

Read the deduplication view, verify request counts/latency coverage around the
experiment timestamps, and retain the experiment manifest. Reassess data quality.
A two-minute test cannot meet the default 200 measured-minute exploratory gate
or the optional 1,440-minute conservative gate. Missingness and measured
train/validation/test label counts must also pass.
The next research step is a reviewed longer experiment with varied demand,
representative workload, independent anomaly labels and separate evaluation
periods. No longer or recurring workload generator is enabled by this script.

Official references checked 2026-11-15:

- [Developer authentication to private Cloud Run](https://docs.cloud.google.com/run/docs/authenticating/developers)
- [urllib request/redirect API](https://docs.python.org/3.12/library/urllib.request.html)
