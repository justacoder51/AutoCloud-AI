# Architecture and incremental implementation

The target system is the architecture specified in `Cloud.md`: Cloud Monitoring
feeds validated time-windowed records into BigQuery, with model artifacts in
Cloud Storage. Isolation Forest, XGBoost and a cost engine feed a LangGraph
workflow; Gemini explains validated evidence. FastAPI serves Streamlit. Any
scaling operation passes deterministic policy validation, human approval and
durable auditing before the restricted Cloud Run adapter executes it.

The current implementation is deliberately smaller: `app/config.py` validates
environment settings, `app/utils/logging.py` emits structured logs, and
`app/main.py` provides a deployment/health-check service. Docker packages that
service. Cloud Build tests, builds and publishes; deployment is a separate
explicit operation. Cloud Run IAM is the deployed authentication boundary.

With the initial deployment now verified, Phase 3 adds a separate one-shot
Monitoring collector, Pandas/NumPy processing, local NDJSON snapshots, optional
Cloud Storage archival and BigQuery batch ingestion. Cloud provisioning remains
separate from collection. The v1 web service is unchanged; scheduling and a
monitoring API are not yet deployed. See `monitoring.md` for units, missingness,
deduplication, IAM and real-data verification steps.

Real collection, BigQuery ingestion and deduplication-view readback are verified.
The prepared periodic deployment uses a separate Cloud Run Job and Cloud
Scheduler HTTP/OAuth invocation every 15 minutes, with separate collector and
invoker identities. The job and Scheduler invocation path are deployed and
verified; independent automatic recurrence verification remains separate.
See `scheduled-collection.md`.

The local FastAPI now serves bounded Monitoring and Billing reads to Streamlit,
with current-window model readiness and explicitly selected native forecasts.
The dashboard's threshold preview remains separate from the optional Gemini
workflow. Recommendation snapshots and final investigation decisions persist in
local SQLite, with freshness checks and no executor. These local additions have
not been deployed to the existing Cloud Run service. See `demo-walkthrough.md`
for current verification evidence and limits.

## Gates

| Phase | Deliverable | Exit evidence |
| --- | --- | --- |
| 1 | Environment, billing/budget, IAM, Python and GitHub | Setup verified; local tests pass |
| 2 | Initial Docker/FastAPI Cloud Run deployment | Private authenticated URL, logs and smoke test |
| 3 | Real supported monitoring metrics and historical storage | Source-labelled records; collection/processing tests |
| 4 | Isolation Forest and chronological XGBoost forecasts | Held-out evaluation against baselines; saved artifacts |
| 5 | Central verified pricing/billing and alternatives | Dated regional sources; estimates separated from actual bills |
| 6 | LangGraph/Gemini validated recommendations | Evidence-bound structured outputs and policy tests |
| 7 | Streamlit monitoring and approval views | API integration and dashboard verification |
| 8 | Approved scaling, audit and rollback | Durable approval, bounded execution and rollback tests |
| 9 | Controlled before/after evaluation | Measured performance and cost evidence |

Future modules and empty notebooks are not generated in advance. Monitoring and
storage code is tested offline and real collection/storage/readback are verified.
The Scheduler on-demand invocation path is also verified; independent automatic
cron recurrence/freshness evidence is still pending. Phase 4 now adds guarded
offline Isolation Forest and XGBoost training/evaluation. Model readiness checks
currently reject the tiny/sparse real dataset; no real-data model is deployed.
The Phase 6 LangGraph workflow checks monitoring, model readiness and optional
explicit cost inputs, optionally requests structured Gemini prioritisation through
Vertex AI, and revalidates against the current trusted catalog. Live fresh-data
processing through Gemini is verified with a no-action result; evaluated model
artifact integration remains pending. The policy
foundation builds deterministic investigation candidates from fresh,
consecutive observations and validates proposals against a recomputed catalog.
It has no execution capability; see `recommendations.md`. Kubernetes
and GPU resources are not part of the design.

While real ML history accrues, the independent Phase 5 cost module is prepared
and tested. Dated regional rate cards price explicit billable-unit inputs;
an optional adapter reads project-scoped Billing exports with signed credits.
Estimates, exported usage costs and measured savings remain distinct. The live
standard Billing table is discovered and its Cloud Run query returns no rows
yet. Explicit Billing reads and native candidate forecast runs can be selected
in the local graph; native forecast inference is tested on synthetic fixtures,
while real training remains blocked by coverage gates. No cost API or cost-driven
action is deployed.
