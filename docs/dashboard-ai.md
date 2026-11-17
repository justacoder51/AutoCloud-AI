# Dashboard LangGraph and Gemini integration

## Original Gemini explanations

The latest release asks Gemini to write a summary and cited explanation for each approved investigation ID, rather than only ranking template text. The request includes evidence, titles and kinds but excludes existing template explanations. Schema checks enforce exactly the supplied IDs; text checks reject exact template copies, digit tokens, URLs and common shell-command patterns. These checks do not prove factual correctness. Generated prose is labelled for review, with numerical measurements and model limitations displayed separately as source evidence. The model has no tools and no infrastructure executor. Generation uses a bounded request and output, and ordinary refresh does not call Gemini.

Older ranking-only documentation below describes prior releases. Testing mode remains explicitly enabled until the user ends testing.

## Gemini testing mode

User-approved testing deployment sets `DASHBOARD_GEMINI_TESTING_UNLIMITED=true` on the API and dashboard. Each explicit public button click can make a new Gemini request without application hourly/daily reservations or cached results. Existing GCS reservation objects are preserved, and no broader IAM is required. Google quotas, billing, freshness checks, validated action selection, per-request timeout/token limits and disabled infrastructure execution still apply. Ordinary refresh does not call Gemini. Restore the setting to `false` to re-enable the shared hourly budget.

## Public read-only recommendations

The public deployment uses evidence-based advice from `/api/overview`, including fresh threshold investigations, experimental Isolation Forest flags, unexpired candidate forecast pressure, and actionable monitoring-coverage checks. Stale evidence only produces guidance to restore monitoring. Experimental model advice does not establish faults, justify scaling, or estimate savings.

The public **Prioritise recommendations with Gemini** button sends an empty server-side POST to `/api/public-explanation`. The API supplies the fixed host-project BigQuery evidence; caller prompts, target selection and browser-origin requests are rejected. Gemini may only order the checked advice IDs. Explanations and numeric facts remain server-generated; this is not open-ended chat or a separate authenticated dashboard.

A GCS generation-zero object under `public-advice-budget/YYYYMMDD/HH.json` reserves each UTC hour before any model request. This enforces at most one attempt per hour across API workers, instances and restarts (24 per UTC day). Failed calls consume the slot. Storage failures skip Gemini. A separate immutable result object is created under `public-advice-results/YYYYMMDD/HH.json`; neither record is overwritten, matching the runtime identity's existing create/read-only storage permissions. Completed matching evidence can reuse the saved ordering; otherwise the UI reports that the shared allowance was used. Requests have a 30-second model timeout, one SDK attempt and a 256-token output limit. This caps model call frequency, not all dashboard/storage/query costs.

The public mode continues to block the original `/api/analysis` form, billing, review writes, authentication/onboarding and infrastructure controls. Existing LangGraph workflow documentation below describes the original private-mode endpoint, not the public bounded advice route.


The Recommendations tab has an explicit **Run AI analysis** form. The existing
threshold preview remains available separately. Neither ordinary page refresh
nor loading a tab calls Gemini. `POST /api/analysis` accepts only bounded lookback
hours, boolean Gemini/billing options, and an explicit connectivity-check option.
It does not accept metric records, project IDs, model paths, prompts or commands.
Cloud Run IAM protects the API; browser-origin requests to the analysis route
are rejected. The Streamlit server supplies its service identity token.

The API reads its configured BigQuery project/region/service, runs the existing
acyclic LangGraph workflow, and optionally makes one Gemini request through
Vertex AI in `asia-south1`. Inputs are exact bounded investigation candidates,
status fields and infrastructure limits. Gemini selects a validated summary code
and orders those candidates. It cannot invent metrics, costs, diagnoses, actions
or calibrated confidence. Explanations remain validated templates. Policy is
recomputed after the call; evidence that expires during analysis is withheld.

No trained model inference or infrastructure executor is connected to this
endpoint. The saved exploratory model evaluation remains in the Models tab.
Measured savings remain null. Optional billing covers the trailing day and uses
the bounded daily export read with a 20-second result timeout. Missing billing
rows remain unknown. Provider authentication/retries may add latency.

## Controls and status

- `DASHBOARD_GEMINI_ENABLED` defaults to false. Without it, LangGraph can run
  deterministic evidence/policy checks but the API rejects Gemini requests.
- `DASHBOARD_GEMINI_MODEL` defaults to `gemini-3.5-flash-lite`; the allowlist is
  the existing Flash-Lite/Flash pair, with region restricted to Mumbai by the adapter.
- Gemini output is capped at 256 tokens and one attempt, with a 30-second model
  timeout. An explicit request may incur model and query charges.
- Each worker serializes requests and caches identical options for 60 seconds,
  including failures. Different options during cooldown return 429. This is a
  per-worker limit, not a shared quota or project-wide spending cap.
- Stale, insufficient or incomplete evidence skips Gemini and reports
  `skipped_unusable_evidence`. API/model failures are sanitized; fallback does not
  claim a successful Gemini call.
- Results keep their original assessment time and cache marker. Showing a prior
  result does not imply current freshness; explicitly rerun to reassess.

**Check Gemini connection** is a separate, explicitly billable test using an
empty catalog labeled `connectivity_probe_only`. It reads no monitoring or
billing data, generates no infrastructure recommendations and proves only
connectivity and schema compliance. This supports honest testing when measured
evidence is stale. It shares the analysis cooldown.

## Runtime permission

The deployed API identity is
`autocloud-api-reader@astute-sign-506809-j8.iam.gserviceaccount.com`.
Its original approved permissions were BigQuery query/read access only.
Gemini additionally requires `aiplatform.endpoints.predict`. The custom
project role `projects/astute-sign-506809-j8/roles/autocloudGeminiPredict`
contains only that permission. It does not grant model deployment, tuning,
infrastructure mutation or IAM administration. The application further restricts
the model, region, output schema and request count.

Vertex AI API is already enabled. Automatic approval review initially rejected
creation/binding of the custom role while the new persistent inference access
was unapproved (`data/releases/gemini-permission-plan.json`). Following explicit
user approval on 16 November 2026, `projects/astute-sign-506809-j8/roles/autocloudGeminiPredict`
(`aiplatform.endpoints.predict`, stage `GA`) was created and bound on project
`astute-sign-506809-j8` to `autocloud-api-reader@astute-sign-506809-j8.iam.gserviceaccount.com`.

Local validation: all 208 tests passed, including actual graph execution with
mocked Gemini, stale-evidence skip, sanitized provider failures, explicit UI
submission, option validation, cooldown/cache behavior and no-data connectivity
probe behavior.

## Cloud rollout verified 16 November 2026

Build `e91b0663-d6c5-4392-843a-d9a24a28a0eb` succeeded. The immutable image is
`sha256:91878ac4f2f1748ae94eac53e2d2071ac6d4aff7cdb73b68d5488d3078b28594`.
Initial rollout ready revisions were `autocloud-api-00003-6gf` (with Gemini
disabled, returning `workflow_status=blocked_evidence`, `gemini.status=disabled`
for deterministic runs and HTTP 409 for Gemini requests) and
`autocloud-dashboard-00003-qtq`. Existing service identities, private IAM and
minimum-zero/maxima-2-and-1 scaling were preserved. API request timeout is 120
seconds to accommodate explicit bounded workflow requests; ordinary overview
and billing controls retain their existing behavior.

After the explicit Gemini IAM approval, `autocloud-api` was updated (generation 6,
pre-update backup in `data/releases/20261116T072454Z/autocloud-api-before-gemini.json`)
with `DASHBOARD_GEMINI_ENABLED=true` and `DASHBOARD_GEMINI_MODEL=gemini-3.5-flash-lite`,
reconciling to ready revision `autocloud-api-00004-bwt` while keeping the same
image digest, service account, 120s timeout, scaling (`0/2`) and private IAM:
- Unauthenticated `GET /health` returned HTTP 403.
- Authenticated `GET /api/overview?source=bigquery&hours=24` returned HTTP 200
  with `capabilities.gemini_enabled=true` and `capabilities.gemini_model="gemini-3.5-flash-lite"`.
- The explicit live connectivity probe (`connectivity_check=true`) returned HTTP 200
  with `status=completed`, `mode=connectivity_probe_only`,
  `workflow_status=connectivity_checked`, `gemini.status=succeeded` and
  `execution_allowed=false` (saved in
  `data/releases/20261116T072454Z/gemini-connectivity-verification.json`).
- After the 60-second cooldown, the measured LangGraph + Gemini workflow
  (`use_gemini=true`, `hours=24`, `include_billing=false`) returned HTTP 200
  with `status=completed`, `data_status=fresh` (latest observation
  `2026-11-16T07:42:00+00:00`), `workflow_status=no_supported_action`,
  `gemini.status=succeeded`, `model_analysis.status=not_evaluated`,
  `cost_analysis.status=usage_or_billing_export_required` and
  `execution_allowed=false` (saved in
  `data/releases/20261116T072454Z/analysis-verification.json`).

Primary references checked 16 November 2026:
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/access-control
- https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash-lite
