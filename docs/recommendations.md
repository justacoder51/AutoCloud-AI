# Recommendation workflow and policy

Phase 6 combines deterministic, evidence-bound investigation candidates with a
finite LangGraph workflow and an optional Vertex AI Gemini adapter. It runs
locally and does not change the deployed API. There is no scaling operation,
cloud execution endpoint or subprocess execution capability. Local dashboard
review endpoints record investigation decisions only, as described below.

## LangGraph and Vertex AI

Install the pinned agent dependencies (also included in development requirements):

```cmd
.venv\Scripts\python.exe -m pip install -r requirements-agents.txt
```

Run the graph without an LLM, reading the existing deduplication view:

```cmd
.venv\Scripts\python.exe -m app.agents.run --from-bigquery --project=astute-sign-506809-j8 --region=asia-south1 --days=1
```

Omit `--from-bigquery` to read the local snapshot. A BigQuery read uses the
existing bounded query (100 MB cap, 1--30 days). It can incur query charges;
local-file mode makes no cloud calls. Use trusted collection/storage inputs.

The graph runs monitoring validation, model readiness, optional cost estimation,
optional Gemini selection, then final policy validation. It is acyclic, with
recursion capped at 10; no tool/retry loop or persisted approval state exists.
Isolation Forest/XGBoost outputs remain null and not_evaluated until independently
evaluated real-data artifacts are integrated. Passing a readiness gate does not
load or train a model. Readiness defaults to the 200-minute exploratory profile;
`--profile=conservative` retains 1,440 minutes. Both use 5/10/15-minute forecasts
and retain missingness and measured split-label checks. This increment does not
complete live training or validate model-driven scaling.

An explicit `--usage=path.json` accepts the existing ServiceUsage schema and
uses the existing Decimal cost engine. Project/region/service must match;
synthetic inputs and future usage periods are refused. User-assumption estimates
keep their provenance, exclusions and time period. No usage input means unknown
cost, not zero. `--billing-table` and `--billing-days` optionally read actual
project-wide exported Cloud Run usage costs through the existing Billing adapter.
These costs remain separate from any single-service estimate and can be queried
even when current monitoring evidence is stale; no stale-data action is enabled.
No estimate is assigned to a recommendation as savings or performance benefit.
`--forecast-run` explicitly selects a trusted native-model run for candidate
forecasts after its evidence and compatibility checks pass; see
`machine-learning.md`. Without a run, predictions remain null. The current real
history does not yet pass training readiness.

To permit one potentially billable Vertex request:

```cmd
.venv\Scripts\python.exe -m app.agents.run --from-bigquery --project=astute-sign-506809-j8 --region=asia-south1 --days=1 --use-gemini
```

If the workload is idle and evidence is stale, independently verify the regional
Vertex connection with one small, explicitly requested model call:

```cmd
.venv\Scripts\python.exe -m app.agents.run --check-vertex --project=astute-sign-506809-j8 --region=asia-south1
```

This probe skips all input-file/BigQuery reads and sends an empty catalog labelled
insufficient evidence. It checks connectivity and structured output only, and
does not claim that monitoring, ML or cost analysis ran. No traffic is necessary.

The adapter uses ADC and the already-enabled Vertex AI API. The existing local
user identity/ADC is used; no runtime IAM grants are made by this workflow.
A future deployed agent needs its own suitably scoped Vertex access; do not
give collector or scheduler identities additional permissions for this local test.
Do not paste credentials or tokens in chat. If ADC expires, renew it in your own
terminal using the existing setup instructions.

The default model is `gemini-3.5-flash-lite`, configurable via `VERTEX_MODEL` or
`--model` to the verified profiles `gemini-3.5-flash-lite` or `gemini-3.5-flash`.
The previous default `gemini-2.5-flash` was retired on 2026-10-20; its first live
probe returned 404. The initial documentation review missed that retirement.
Current model documentation checked 2026-11-15 lists `asia-south1` for the new
profiles. Live access for `gemini-3.5-flash-lite` is verified for this project;
the alternate Flash profile is not live-tested. No endpoint/model fallback or
throughput purchase occurs.
The adapter permits only `asia-south1`, v1 API, 30-second HTTP timeout, one SDK
attempt, one candidate and 256 output tokens, with `thinking_level=MINIMAL`.
It omits the deprecated numeric thinking budget and sampling overrides for these
models. MINIMAL is not a guarantee of zero thinking tokens. No tools are supplied
and automatic function calling is disabled.
Payload is capped at 32 KB and response at 8 KB. ADC refresh can have separate
authentication latency; this is not a hard wall-clock or currency spend cap.

Gemini receives the bounded candidate evidence, capability statuses and configured
instance bounds, not the complete historical dataset or bill. Instance bounds
are policy constraints, not verified live Cloud Run configuration. Gemini returns
only a summary code and an ordering of all supported candidate actions. Codes
are rendered into checked explanation templates. Arbitrary model-written prose
is deliberately excluded from the authoritative report: no numerical or causal
claim is accepted from an LLM. This increment is constrained prioritisation and
explanation selection, not open-ended diagnosis or autonomous optimisation.

Duplicate/omitted/invented actions or inconsistent summaries are rejected. API,
safety, truncation and malformed-response failures retain a deterministic report
with `gemini.status=failed_or_rejected`, the error class and an HTTP status when
available; raw provider messages and bodies are excluded.
Stale evidence skips the model entirely. Evidence is rechecked after the model
call; an expired selection is discarded. Exit codes: 0 for completed offline or
successful live processing; 2 for a requested Gemini step that failed/was rejected,
was skipped or expired; 1 for input/workflow errors. An empty recommendation list
is a valid result and does not require generating artificial production pressure.

Live Vertex connectivity and the fresh Monitoring-to-BigQuery-to-LangGraph-to-
Gemini no-action branch were verified on 2026-11-15 with Flash-Lite in Mumbai.
The workflow returned fresh data, gemini.status=succeeded and exit code 0;
ML readiness remained false and costs remained unknown. A live sustained-pressure
recommendation and evaluated model integration remain unverified. Offline tests
also exercise the actual graph runtime and SDK serialization using an in-memory
HTTP transport. Managed sessions using SOCKS proxies require httpx's socks extra,
now included in requirements-agents.txt; proxy addresses are never logged.

Official references checked 2026-11-15:

- [LangGraph StateGraph](https://reference.langchain.com/python/langgraph/graph/state/StateGraph)
- [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/)
- [Gemini 2.5 Flash regions](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash)
- [Model lifecycle and retirements](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/model-versions)
- [Gemini 3.5 Flash-Lite regions and lifecycle](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash-lite)
- [Supported thinking settings](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/thinking)

## Local preview

Use the existing development environment; no new packages are needed:

```cmd
.venv\Scripts\python.exe -m pytest -q tests/test_recommendations.py
.venv\Scripts\python.exe -m app.agents.preview
```

The preview reads `data/processed/metrics.ndjson`. To obtain a fresh local
snapshot first (safe while the separate traffic pilot is running):

```cmd
.venv\Scripts\python.exe -m app.data.collector --project=astute-sign-506809-j8 --region=asia-south1 --service=autocloud-api --minutes=30 --write-bigquery
.venv\Scripts\python.exe -m app.agents.preview
```

The cloud scheduled collector writes BigQuery, not the local snapshot. Therefore
an old local preview may report stale even when cloud collection is healthy.
The CLI accepts explicit `--input`, `--project`, `--region` and `--service`.
It prints JSON and does not start traffic or invoke an LLM.

## Evidence and rules

`recommendation_agent.py` reuses the validated Monitoring record schema, rejects
mixed targets and future evidence, deduplicates logical records by collection
time and requires three consecutive observed minutes by default. Latest data
must be at most 15 minutes old. Equal-time conflicting records are rejected.
Thresholds are configurable engineering heuristics, not learned service SLOs:

| Sustained condition in every window minute | Investigation |
| --- | --- |
| CPU utilisation greater than 0.90 | Review pressure and capacity constraints |
| Memory utilisation greater than 0.90 | Inspect memory pressure and application logs |
| Server error rate greater than 0.05 | Inspect failing requests and application logs |

Missing measurements are not imputed. A gap, insufficient history or stale data
produces a diagnostic with no recommendations. No threshold breach is not a
health guarantee, particularly when measurements are missing. The source field
records provenance supplied by collection; it is not a cryptographic attestation
of a locally supplied file. Production evidence must come from trusted storage.

Candidates carry exact values, record IDs, timestamps, units, threshold,
problem, proposed investigation, unknown performance impact, null financial
impact and confidence, uncertainty, operational risks and pending review status.
Model and cost status remain `not_evaluated`; available modules are not silently
treated as evaluated inputs. Forecast-based or financial recommendations await
their separate validation gates.

`validation.py` treats a proposed recommendation as untrusted. It validates the
strict schema and recomputes the current catalog from trusted records/policy,
then requires exact candidate equality. Valid JSON alone is insufficient.
Changed evidence, invented diagnoses/prices/probabilities, unsupported actions
and expired candidates are rejected. The orchestrator selects from this catalog
and renders only checked explanations alongside the validated facts.

All candidates have `execution_allowed=false`. Bounded scaling, authenticated
multi-user infrastructure approval, action auditing and rollback remain Phase 8 work.

## Local recommendation reviews

The Recommendations tab explicitly saves current deterministic candidates and
loads the latest 200 saved records. FastAPI recomputes the scoped plan and checks
the displayed evidence fingerprint. Clients cannot submit recommendation text or
metrics. Refresh alone creates no records. Duplicate saves retain prior decisions.

`data/reviews.sqlite3` stores exact evidence snapshots, creation and expiry times,
and a final approve/reject decision with reviewer label, reason and UTC timestamp.
Transactions prevent competing decisions from overwriting each other. Identical
retries are safe; conflicting changes return HTTP 409. Records persist across API
restarts. Back up this file to retain history; it is ignored by git and is not a
tamper-proof or authenticated audit system.

Approval accepts an investigation for manual follow-up, not infrastructure
changes. Approval is blocked after the standard 15-minute evidence freshness
window; rejection remains available. History preserves original decisions and
shows evidence expiry. There are no execution or deletion endpoints.

Endpoints: `GET /api/reviews`, `POST /api/reviews/capture`, and
`POST /api/reviews/{id}/decision`. Local clients in non-production mode only;
browser Origin requests are rejected. Streamlit calls the API server-side.
Reviewer labels are self-reported, not authenticated. Keep both servers bound
to loopback; this workflow is not for public or multi-user hosting.

## Durable authenticated cloud reviews

When `DASHBOARD_REVIEW_BUCKET` is configured (and optionally
`DASHBOARD_REVIEW_AUDIENCE` for strict Cloud Run `run.app` audience validation),
`app/api/reviews.py` switches from local SQLite to `CloudReviewStore`
(`app/services/review_store.py`) and `GET /api/overview` advertises
`capabilities.cloud_reviews=true`:

- Requests must not include a browser `Origin` header. The dashboard (`api_headers`
  in `app/dashboard/authentication.py`) sends both `Authorization: Bearer <token>`
  (for Cloud Run edge IAM, where Google Front End removes the signature) and
  `X-AutoCloud-Authorization: Bearer <token>` (preserved intact to the container).
- `extract_application_bearer_token` and `verify_oidc_principal` in `app/api/reviews.py`
  require a full 3-part cryptographically signed JWT, reject `.SIGNATURE_REMOVED_BY_GOOGLE`
  tokens (even when `K_SERVICE` is set) and mixed-header substitution attempts
  (`X-Serverless-Authorization` with mismatched/missing application tokens), and
  verify `iss in {"accounts.google.com", "https://accounts.google.com"}`, strict
  `aud == DASHBOARD_REVIEW_AUDIENCE`, `email_verified == true`, and `email`.
- **Service identity vs human reviewer attribution:** because the dashboard service
  authenticates using its service account ID token, `calling_service_principal`
  records the verified calling service principal while human reviewer names remain
  self-reported labels (`reviewer_identity="service_authenticated_self_reported_label"`,
  `human_reviewer_verified=false`). Multiple operators using the dashboard share
  the same service principal unless end-user OIDC authentication is separately added.
- `CloudReviewStore` validates that the configured Cloud Storage bucket exists
  in the configured region (`asia-south1`; it never auto-creates buckets),
  writes immutable JSON objects under `reviews/<scope_hash>/items/<id>.json`,
  `reviews/<scope_hash>/by_time/<reverse_us>_<id>.json` (for bounded latest-200
  ordering), and `reviews/<scope_hash>/decisions/<id>.json` using
  `if_generation_match=0`, and bounds `history()` to at most 200 indexed items
  and 200 direct per-ID decision downloads with 10-second per-call timeouts and
  an overall read-operation/time budget.
- Existing freshness, 15-minute evidence approval expiry, immutable decision,
  and `execution_allowed=false` policy rules remain enforced identically to the
  local SQLite workflow.
- Cloud rollout verified 16 November 2026: bucket
  `astute-sign-506809-j8-autocloud-reviews` (`ASIA-SOUTH1`, uniform bucket-level
  access, public access prevention enforced, scoped `legacyBucketReader` +
  `objectCreator` + `objectViewer` for `autocloud-api-reader`) is live on
  `autocloud-api-00006-pgf` and `autocloud-dashboard-00005-ntj`. Note that the
  hardened dual-header cryptographic verification, `by_time/` bounded reads, and
  `service_authenticated_self_reported_label` metadata updates are currently
  verified locally awaiting the next user-approved Cloud Build + Cloud Run rollout.
