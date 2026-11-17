# Controlled ML validation pilot — prepared, not executed

Superseded by the user-approved [thirty-minute campaign](short-validation-run.md). This section preserves the earlier two-hour proposal, which was never executed. Use only the new campaign's plan/checksum and status; the historical capsule is no longer executable after the reviewed code changes.

Prepared 17 November 2026 IST. This is a tested local harness and reviewable plan, **not a completed cloud experiment or evidence of improved accuracy**.

## Frozen preparation

Directory: `data/validation_campaigns/20261116T183803Z` (UTC directory name).

- Plan SHA-256: `c21a61f29fc9fcce8f9939d7a5889e5780ca20e96eb8168419bc580b5a808e16`.
- Source archive SHA-256: `f2c4f8808e64d53f1f463c90f4b8492e514a73beedb8d12a7fbc3a7b2d009a91`.
- Status: `prepared_not_built_or_deployed`. No image digest exists yet.

The capsule contains the plan, two-file source archive, build configuration and preparation metadata. The archive contains only the dedicated Dockerfile and lab application, excluding credentials, production configuration, model weights and user data.

| Item | Proposed configuration |
| --- | --- |
| Project / region | `astute-sign-506809-j8` / `asia-south1` |
| New service | `autocloud-validation-lab`, private IAM invocation |
| New identity | Same-named service account, no project roles |
| Compute | 1 vCPU, 512 MiB, requested min 0 / max 1 instance, request-based CPU, no CPU boost |
| Requests | Sequential, at most 24/minute and 1,800 total; no retries or catch-up bursts |
| Duration | 120 actual minutes, then 15–16 minutes of telemetry ingestion time |
| Expiry | Server rejects work after 135 minutes; explicit cleanup still required |
| CPU / memory probes | Up to 3 CPU seconds/request, 4-second wall deadline; at most 64 MiB extra memory with 120-second expiry checked on requests and recovery cleanup |
| Latency / error probes | 2-second delay / explicit HTTP 503 |

Cloud Build, Cloud Run, registry, storage and logging can be billable. Resource/request limits are not a monetary cap. Build artifacts/logs remain after service cleanup and can incur storage charges. Production deployments, model weights and decision gates are unchanged.

## Workloads, labels and scoring

First hour: 20 minutes steady, 10 idle, 10 low, 10 ramping and 10 bursty. Second hour: twelve episodes, three each of CPU stress, memory growth, latency and HTTP error. Each has two minutes of exposure and three of recovery. Order is frozen using seed 20261116.

These are diverse request patterns against a bounded compute probe, **not representative application/database/dependency behaviour**. Controlled injections alone cannot establish real-world accuracy.

The runner journals intent before sending. The server returns matching run/sequence actuation receipts with actual times and allocation/CPU information. Separately, the external runner measures HTTP status and end-to-end latency. A 5xx or >1-second client latency is the preregistered availability/latency impact. CPU/memory exposure without that impact remains a stress probe. Missing receipts stop the runner. Transport failures, missing telemetry, idle and recovery do not become healthy negatives.

Labels never read model scores or feature thresholds. Client latency includes transport/cold-start effects and does not prove a server-side cause. Contemporaneous latency/error rate are input features, so detection is not early warning.

The collector reads actual Cloud Monitoring minutes directly for the lab, with a fifteen-minute ingestion holdback and no BigQuery writes or scheduler changes. Evidence, model and code hashes are checked. No shifted timestamps or fake zero targets.

All nine frozen forecasts are compared with persistence overall and by origin regime, requiring sixteen consecutive measured origin minutes plus measured future targets. Targets can cross regimes. Anomaly outputs include confusion counts, control false-alarm minutes, per-probe episode detection, time to first flag and missingness. Failed campaigns retain their failed status. Three repeats/type cannot establish general accuracy.

This pilot is **outside the training domain**: weights were trained for `autocloud-api`; lab rows retain their actual service identity. Offline evaluation checks original artifact integrity and reports that mismatch. Live inference scope checks remain unchanged. No result automatically promotes a model or permits resource execution.

## Commands after explicit approval

From the project root. None of these cloud build, deployment or traffic commands has been run:

```powershell
$campaign = "data/validation_campaigns/20261116T183803Z"
$approved = "c21a61f29fc9fcce8f9939d7a5889e5780ca20e96eb8168419bc580b5a808e16"
.venv\Scripts\python.exe -B -m infrastructure.validation_lab_cloud build $campaign --execute --approved-plan-sha $approved
.venv\Scripts\python.exe -B -m infrastructure.validation_lab_cloud build-status $campaign
# Continue only after build-status reports SUCCESS and records its immutable digest.
.venv\Scripts\python.exe -B -m infrastructure.validation_lab_cloud deploy $campaign --execute --approved-plan-sha $approved
# Start promptly after deployment. Takes approximately two hours.
.venv\Scripts\python.exe -B -u -m infrastructure.validation_campaign run $campaign --approved-plan-sha $approved
# After fifteen minutes beyond the final complete minute:
.venv\Scripts\python.exe -B -m infrastructure.validation_campaign collect $campaign
.venv\Scripts\python.exe -B -m infrastructure.validation_campaign evaluate $campaign
# Always clean up, including after failure.
.venv\Scripts\python.exe -B -m infrastructure.validation_lab_cloud cleanup $campaign --execute --approved-plan-sha $approved
```

Do not restart a started campaign in the same directory. `execution.json` records startup; `execution-events.ndjson` records termination. Stale startup without termination means interrupted/stalled, not completed. On interruption, clean up; Monitoring history can still be collected afterward. Inspect recorded operations before retrying deployment. Expiry stops work but does not delete resources/artifacts.

The helper refuses to reuse existing services/identities. Before traffic, the runner checks private IAM, fixed service identity, immutable image, plan hash, resource settings and expiry. It discovers the URL through the fixed Cloud Run API and never follows token-bearing redirects. No project role or public invoker binding is added.

## Remaining reliability work

The prior actual study remains unchanged: 3/9 point-MAE wins on 438 measured minutes, no multiplicity-adjusted CPU improvement established, and unacceptable raw-detector false alarms on the narrow availability cohort. This pilot has no new results yet.

After checking the measurement path, separately register a multi-day study of the actual application with representative measured workload traces, quiet periods, bursts, revisions and deployment transitions. Keep complete days/incidents together in splits. Have a person review incident start/end, impact and recovery using independent probes/logs; keep unknown labels separate and repeat incident families across days.

Choose promotion criteria and sample-size/power requirements before scoring the untouched holdout. Compare forecasts with persistence and train-only history/seasonal baselines using paired day/episode uncertainty and multiple-comparison control. Report anomaly precision, recall, false alarms/hour, detection time and missingness by fault/workload. Improve failures on a separate development set, then evaluate another untouched holdout. A successful lab run alone never authorizes operational use.

## Local verification

**288 tests passed in 36.43 seconds**, including eight new harness tests. Dependency check and compilation passed. Existing NumPy deprecation warnings and a Windows temporary-directory cleanup warning appeared after successful tests; pytest exit was 0. Unit fixtures test controls/math and are not accuracy evidence. Container build/live lab verification await approval.

`ANTIGRAVITY_HANDOFF.md` remains unchanged: `598af1c6370583c993a4b381d7d96902c8832ae106b4b9b111a202055d1dce2e`.

References: [Cloud Run deployment options](https://docs.cloud.google.com/sdk/gcloud/reference/run/deploy), [Cloud Run pricing](https://cloud.google.com/run/pricing).
