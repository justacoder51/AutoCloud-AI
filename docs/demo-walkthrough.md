# AutoCloud AI demo walkthrough and verification

Verified locally on 2026-11-15 at approximately 19:58 UTC. This is a working
monitoring and recommendation prototype, not a completed optimisation experiment.
Model training is on hold. Do not start traffic, change gates, deploy models or
change infrastructure as part of this walkthrough.

## Start or reuse the local application

Reuse the existing API and dashboard if they are running. If needed, use separate
Command Prompt terminals in the project directory. Existing ADC must already be
configured. These commands do not provision cloud resources.

API terminal:

```cmd
set GCP_PROJECT_ID=astute-sign-506809-j8
set DASHBOARD_BILLING_TABLE=astute-sign-506809-j8.autocloud_billing.gcp_billing_export_v1_011640_0793FF_B5C560
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Dashboard terminal:

```cmd
.venv\Scripts\python.exe -m streamlit run app/dashboard/home.py --server.address=127.0.0.1
```

Open http://localhost:8501/. The API root welcome message is legacy deployment
text; use `/health/ready` and the specific `/api/` endpoints to verify capabilities.
Leave the existing experiment terminal alone. Its training hold does not stop
already-running traffic collection.

## Five-minute presentation

1. **Infrastructure (one minute).** Select BigQuery and 24 hours. Refresh once.
   Explain the project/service scope, latest observation versus fetch time,
   coverage and gaps. Charts show measurements; missing values stay unknown.
   A request sum covers measured buckets, not every request ever sent.
2. **Training experiment and Models (one minute).** Show the recorded heartbeat,
   request counts and training hold. Explain that readiness checks assess the
   selected window, not all possible training cohorts. Readiness is not training
   or deployment approval. No evaluated real model is currently selected.
3. **Recommendations (one minute).** Explain the consecutive-minute threshold
   rules and evidence freshness gate. The dashboard preview does not call Gemini.
   An empty candidate list is a valid outcome; do not invent a recommendation for
   the demo. The separate LangGraph workflow applies evidence and policy checks;
   optional Gemini integration was verified earlier, not re-invoked in this check.
4. **Review history (one minute).** Click Load review history. If real supported
   candidates exist, Save current recommendations for review preserves their
   evidence. A human can then enter a reviewer label and reason, acknowledge the
   evidence, and record an approve/reject decision. Do not approve just to populate
   the demo. Approval is manual investigation only; stale approval is blocked and
   no cloud executor exists. The history is local and reviewer labels are not
   authenticated identities.
5. **Costs & actions (one minute).** Select one day and click Read billing export.
   Explain project-wide Cloud Run scope, currencies, credits and UTC dates. Empty
   results mean unknown cost, not zero. No measured savings are established.

## Verification evidence

Sanitized local evidence is saved in
`data/verification/local-20261115T195800Z.json` (ignored by git).
Values below describe that check, not a continuously updated status.

| Check | Observed outcome |
| --- | --- |
| API live / ready | HTTP 200, `ok` / `ready` |
| BigQuery to local API | Loaded 287 of 1,440 expected minute buckets (19.9%) |
| Latest measurement | 2026-11-15 19:42 UTC |
| Live evidence through LangGraph | `blocked_evidence`, `stale`, no recommendations |
| Gemini in this verification | Disabled; no new Vertex request |
| Model readiness for dashboard window | Failed missingness and some measured split-label requirements |
| Selected real model | None |
| Existing traffic experiment | 1,011 successful / 1,011 attempted, sending traffic, recent recorded heartbeat |
| Training hold | Present; trained=false; deployment_allowed=false |
| Billing | Query succeeded, no matching Cloud Run rows for trailing day |
| Review history | HTTP 200, empty, execution_allowed=false |
| Invalid monitoring window | HTTP 422 |
| Cross-origin review request | HTTP 403 |

The full offline suite passed: **183 tests, one deprecation warning, 30.77 seconds**.
The process exited successfully. Streamlit's temporary-directory finalizer emitted
a sandbox cleanup PermissionError after test completion; this was not a test
failure. The deprecation warning concerns a NumPy timedelta conversion in the
dashboard fixture path and remains a maintenance item.

Tests cover missing/future/conflicting evidence, scoped reads, stale policy
blocking, invalid model outputs, cost arithmetic, review persistence, concurrent
decisions and dashboard interactions. Model and decision paths use synthetic or
mocked fixtures where necessary. They validate software behavior, not real model
accuracy, real cost savings or a live human approval. No real recommendation was
saved or approved during this verification because no supported candidate existed.

## Reproduce the offline checks

From PowerShell in the project directory:

```powershell
$testTemp = Join-Path (Get-Location) ('.tmp/verification-' + [guid]::NewGuid().ToString('N'))
.venv\Scripts\python.exe -m pytest -q --basetemp=$testTemp --tb=short
```

These checks exercise fixture models in temporary directories; they do not resume
the measured-data training experiment or deploy anything.

## Remaining evaluation work

- Resume measured-data training only when requested, then assess an appropriate
  cohort and evaluate held-out forecasts against persistence.
- Obtain independent anomaly labels before reporting detection accuracy.
- Validate actual displayed cost amounts after billing export rows arrive.
- Verify the real candidate-to-human-review path when supported evidence exists.
- Authenticate reviewers and design bounded execution, auditing and rollback
  before any multi-user or infrastructure-changing workflow.
- Run an explicitly authorised before/after experiment before claiming savings
  or performance improvements. None are established by the current demo.
