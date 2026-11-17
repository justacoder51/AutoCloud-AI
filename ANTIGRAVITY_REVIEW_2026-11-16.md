# AutoCloud AI: review for Antigravity

Review date: 16 November 2026 (UTC). Reviewer: Codex.

This is a separate review supplement. **ANTIGRAVITY_HANDOFF.md was not edited.**
No application code, model artifacts, evaluation files, IAM, infrastructure, or
deployments were changed during this review. Offline tests used temporary files;
saved models were evaluated without fitting. No new HTTP workload, Gemini call,
BigQuery query, or cloud operation was started.

## Verdict

The implementation has made substantial progress, and the recorded model numbers
are reproducible. It is not ready to be described as fully complete. Fix the
review authentication flaw first. Human reviewer attribution, evaluation
contracts, reproducibility, and production verification still need work.

Findings concern the current workspace, including existing code interacting with
Antigravity's additions. Git contains many untracked implementation files, so
this is not a claim that every issue was introduced by Antigravity.

## Verification performed

| Check | Result |
| --- | --- |
| Full offline pytest suite | **217 passed in 26.41 seconds**, exit code 0 |
| Post-test cleanup | Windows temporary-directory PermissionError printed during interpreter shutdown; tests themselves passed |
| Native forecast manifest, model checksums, history integrity and run scope | Passed through `inspect_run` for `20261116T051914Z_48d41482` |
| Saved forecast MAEs | All nine XGBoost and persistence MAEs reproduced from saved artifacts |
| Persistence comparison | **0/9** forecasts beat persistence on held-out MAE |
| Historical-average comparison | **5/9** forecasts beat the training historical average |
| Regime-label anomaly evaluation | Reproduced F1 **0.9756097561**, matrix `[[26,0],[1,20]]`, 47 rows |
| Operational-normality audit | Reproduced false-positive rate **20/47 = 42.5532%** |
| Threshold evaluation | Reproduced matrix `[[26,0],[15,0]]`, **41** evaluable rows |
| Isolated auth negative check | Fabricated unsigned reviewer claims were accepted when `K_SERVICE` was set |
| Isolated metric-contract negative check | Impossible claimed scores were accepted by `BinaryEvalScores` |
| Saved release evidence | Reviewed successful Gemini and private-service smoke-test records; these are historical evidence |

Test command used, from the project root:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp C:\Users\sihan\AppData\Local\Temp\autocloud-review-20261116
```

This review did not freshly inventory GCP, recheck IAM, exercise the deployed
browser, validate the bucket against real concurrent writes, or verify current
cloud billing. Test passes establish software behavior, not real model accuracy,
availability improvement, or cost savings.

## Findings and required improvements

### R1 — High: unsigned reviewer identity can be forged

**Locations:** `app/api/reviews.py:35-39`, `app/api/reviews.py:62`,
`tests/test_reviews.py:403`.

`verify_oidc_principal` decodes a token with `verify=False` whenever it ends in
`.SIGNATURE_REMOVED_BY_GOOGLE` and the process has `K_SERVICE` set. The suffix and
environment variable do not prove that Google authenticated this particular
header. An isolated check with a fabricated email, issuer, audience and future
expiry returned that fabricated email as the verified principal.

This matters even with a private API: Google's documentation says that when both
authorization headers exist, Cloud Run checks only `X-Serverless-Authorization`.
An authorized caller can authenticate at the edge with that header while passing
fabricated claims in `Authorization`, which this application reads. This is a
review/audit identity forgery issue; the check does **not** establish anonymous
access to the private service or infrastructure execution.

**Fix:** design an explicit boundary between edge service authentication and
application identity. Preserve and cryptographically verify the application
identity token with a strict issuer and audience. Reject arbitrary unsigned
tokens and ambiguous header combinations. Do not treat a marker suffix as
authentication. Remove generic SDK audiences from a production end-user identity
contract unless a narrowly documented operator path requires them.

**Acceptance:** tests must reject fabricated redacted tokens, mixed-header
identity substitution, wrong audiences, expired tokens and unrelated principals.
Keep a positive test for the chosen supported Cloud Run authentication path.
The existing test currently encodes the unsafe assumption that `K_SERVICE`
establishes token provenance and needs to change with the fix.

Primary reference: https://docs.cloud.google.com/run/docs/authenticating/service-to-service

### R2 — Medium: service identity is not human reviewer identity

**Locations:** `app/dashboard/authentication.py:15-18`,
`app/dashboard/home.py:190-193`, `app/api/reviews.py:129`,
`app/dashboard/reviews.py`.

The dashboard fetches its own service-account ID token for API calls. Consequently
the authenticated principal on a review identifies the dashboard service account.
The human reviewer field remains a self-entered label. Multiple people can
therefore create decisions under the same authenticated service principal.

**Fix:** distinguish `calling_service_principal`, `reviewer_label`, and a verified
end-user identity. Either add a supported authenticated end-user flow with
server-side validation, or accurately label the current capability as
service-authenticated reviews with self-reported human labels. Do not forward an
unverified email header or assume Cloud Run IAM supplies application user identity.

**Acceptance:** two authenticated human users are distinguishable if human audit
attribution is claimed; forged user identity is rejected. Otherwise UI, API and
documentation explicitly state the attribution limitation.

### R3 — Medium: training with labels produces metrics the inspector ignores

**Locations:** `app/models/train.py:26-51`,
`app/models/inference.py:201-204`.

The successful branch of `evaluate_anomalies` returns a label source and metric
blocks without a top-level status. The training CLI stores that result directly.
`inspect_run`, however, defaults a missing status to `not_evaluated` and skips
the metric blocks. A future `--train --labels-csv ...` run can therefore contain
actual classification metrics while the dashboard says they were not evaluated.
The saved-run enrichment helper avoids the problem by adding a status itself.

**Fix:** use a consistent versioned anomaly-evaluation schema for both paths,
including explicit success, no-label and no-overlap states.

**Acceptance:** a training-report-shaped labelled evaluation survives inspection
and dashboard serialization. Empty overlap stays unevaluated; existing unlabelled
runs remain supported. Verify this with fixtures rather than retraining real data.

### R4 — Medium: anomaly metric validation accepts contradictory results

**Location:** `app/models/inference.py:143-165`.

`BinaryEvalScores` checks numeric ranges, matrix dimensions and total count, but
does not check that precision, recall, F1 or FPR agree with the matrix. The
read-only negative check accepted precision/recall/F1 all equal to 1 and FPR 0
with matrix `[[0,10],[10,0]]`: every sample was actually misclassified.

**Fix:** derive displayed metrics from the confusion matrix, or verify supplied
metrics against it within a declared tolerance, including zero-denominator/null
semantics. Validate related optional diagnostics before presenting them as checked
evaluation data. The existing finite-value checks should remain.

**Acceptance:** contradictory metrics fail; the actual recorded 47-row audit and
zero-positive cases pass with explicitly defined semantics. This finding does
not imply that the current saved metrics are wrong; they reproduced correctly.

### R5 — Medium: generic evaluation helpers hardcode one experiment's conclusions

**Locations:** `app/models/train.py:89-94`, `app/models/train.py:170-174`.

The saved anomaly helper always describes traffic cessation after `21:38:59Z`,
even for another run or label source. The forecast helper always emits root
causes asserting a 232-minute cohort, specific November timestamps, a constant
request rate and a particular memory level. Its test invokes it on a different
synthetic fixture, which would still receive those real-experiment conclusions.

**Fix:** separate experiment-specific interpretation from reusable evaluation.
Derive factual diagnostics from the supplied records and external provenance.
Accept explicit provenance where necessary. Describe causal interpretations as
hypotheses unless independently established; aggregate MAE alone does not prove
why a model failed.

**Acceptance:** another duration, workload, cutoff and label source cannot inherit
this experiment's dates or conclusions. Add assertions about metadata correctness,
not only the presence of finite metric values.

### R6 — Medium: the 200-item review history limit does not bound cloud work

**Location:** `app/services/review_store.py:235-272`.

Each history read lists and downloads every decision and every saved snapshot
for the scope, then sorts them and returns 200. Storage reads, memory and response
latency grow with the entire history. SDK calls also have no explicit
application-level total request budget in this implementation.

**Fix:** provide a bounded index or a pagination/storage layout that supports
fetching the latest page without scanning all objects; fetch decisions only for
that page. Define timeouts and an overall request budget. Preserve generation
preconditions, deduplication, immutable final decisions and expired-approval
rejection, which are useful existing safeguards.

**Acceptance:** a large-history fake records a bounded number of reads for a
200-item page. Verify ordering, pagination, retries, conflicts and sanitized
unavailability responses. Do not add a destructive retention job as a shortcut.

### R7 — Medium: synthetic benchmark is not reproducible from the checked files

**Locations:** `models/representative_forecast_benchmark.json`,
`docs/training-results.md`, `docs/status.md`.

The saved JSON correctly identifies its synthetic source and disallows deployment.
However, it contains scores without a generator, seed, generation parameters,
dataset hash/path, dependency versions or reproduction command. References found
in app/tests/infrastructure/docs point to the JSON, not an executable benchmark
recipe. Another reviewer cannot reconstruct the reported 9/9 result from this
artifact alone.

**Fix:** preserve a deterministic, explicitly synthetic generator and benchmark
entry point, record versions/seed/parameters/data hash, and document one command
with expected tolerances. Keep generated data separate from measured data. Say
the model won on this constructed workload; avoid implying that sufficient
history generally guarantees a win. Thirty hours is also only 1.25 daily cycles,
so specify which shorter synthetic cycles the benchmark actually exercises.

**Acceptance:** a clean environment can regenerate the fixture and recompute both
baselines without credentials. This must not replace the real result: 0/9 beating
persistence. No synthetic benchmark establishes real accuracy or cost savings.

## Evaluation interpretation that must remain explicit

The current arithmetic is correct. The scope of the labels still limits what can
be concluded:

- Labels derived after examining this experiment describe planned traffic
  cessation, not independently confirmed operational faults. Call them post-hoc
  experiment-event labels rather than declaring fault ground truth complete.
- All 47 rows in the operational audit are assumed normal. Zero client errors
  during the active phase and no injected fault do not independently establish
  that every post-traffic minute was healthy. State this assumption and treat
  fault sensitivity as unmeasured because there are no positive fault examples.
- Isolation Forest and the threshold baseline are scored on different cohorts
  (47 versus 41). Preserve those coverage counts. Add a shared-observable-cohort
  comparison and abstention coverage before presenting comparative F1 as a
  like-for-like model ranking.
- Do not tune thresholds or models on this already inspected test partition.
  Future operational evaluation needs a newly held-out, independently documented
  cohort, normal idle behavior, actual labelled fault cases, and uncertainty
  estimates appropriate to correlated time-series data.

## Deployment and reproducibility gaps

The latest recorded cloud review release is
`data/releases/20261116T090610Z/`, with API revision `autocloud-api-00006-pgf`
and dashboard revision `autocloud-dashboard-00005-ntj`. Its source archive contains
the earlier evaluation with anomaly status `not_evaluated` and no forecast
diagnostics. These statements describe saved artifacts, not a fresh cloud check.

| Artifact | Evaluation SHA-256 |
| --- | --- |
| Recorded cloud release / packaged summary | `781c05a06af17312b74f09b8405e9f7d1c4a8fe753627e1362cea4f6fa3bc82f` |
| Current local summary | `a63e938693a120cd3ecee1a489958ec4f622910749a7244bf8481d6e8e8359b6` |

The docs appropriately describe the new evaluation edits as local. Do not claim
those new panels are already cloud-deployed. After the fixes, prepare one
immutable release with a matching evaluation checksum and test evidence, then
deploy only within explicit approval. Verify the actual authenticated Streamlit
save/reload/decision workflow and a persisted decision across service restarts;
an HTTP 200 on the dashboard shell does not verify its WebSocket UI behavior.
Use a fresh legitimate investigation recommendation; do not manufacture a live
recommendation to exercise approval. Do not execute infrastructure changes.

There are many untracked source files, while data/models and important evidence
are ignored. Before calling the project reproducible, review a safe source
checkpoint, dependency manifests, artifact retention/backup plan and clean-clone
tests. Do not automatically add ignored data, credentials or all untracked files.
Some tests assert the particular production evaluation's counts, so separate
stable schema fixtures from intentional recorded-artifact acceptance checks.

The root API response in `app/main.py:92` still says environment setup and that
monitoring/analytics are not enabled. Update that response to reflect configured
capabilities. Keep liveness separate from dependency health; document that the
current readiness endpoint does not verify BigQuery, Gemini or review storage.
Reconcile dated status entries so pending and superseded milestones are clear.

## What should be preserved

- Private Cloud Run access, separate runtime identities, scoped permissions and
  service-account authentication; no credential files or keys in images.
- Strict server-owned evidence, freshness/missingness gates, bounded BigQuery
  and billing reads, explicit manual Gemini controls and constrained outputs.
- Generation-precondition writes for immutable cloud decisions, local transaction
  safeguards, stale-approval blocking and `execution_allowed=false` everywhere
  in recommendation/review workflows.
- Training readiness profiles, purged chronological splits, validation-only
  selection, history/native model integrity checks and honest baseline reporting.
- Clear separation between recorded evaluation, candidate inference, deployed
  models and authorized infrastructure execution. Current model weaknesses are
  a valid experimental finding, not a reason to relax gates.

## Suggested order for Antigravity

1. Correct R1 and decide the human-identity contract in R2; add negative tests.
2. Fix R3-R5 and make the evaluation wording/coverage assumptions explicit.
3. Bound cloud review reads (R6) and preserve benchmark provenance (R7).
4. Rerun offline checks, prepare a matching immutable release, and perform only
   explicitly authorized deployment and authenticated persistence/UI checks.
5. Reconcile implementation status with remaining ML, cost/performance and
   end-to-end evaluation work. Do not declare project completion or assign a
   precise completion percentage from test count alone.

The previous handoff remains the continuity document. This report is a review
supplement; it does not authorize new traffic, retraining, fault injection,
permission grants, deployment, public access or infrastructure modification.
