# AutoCloud AI - Current Project Report

Latest dashboard feature, 17 November 2026: an optional [synthetic demo mode](synthetic-demo.md) is deployed on dashboard revision `autocloud-dashboard-00014-dt7`. It presents explicitly fictional usage charts, illustrative trend projections and scripted alert/guidance examples. It does not insert fake BigQuery records, call Gemini, train models or alter real model gates. Anonymous measured/demo/switch-back verification passed and the offline suite has 292 passing tests. This feature adds presentation examples, not new model-accuracy or cost-savings evidence.

New local preparation: [Controlled validation pilot](controlled-validation-pilot.md), 17 November 2026 IST. A frozen private lab harness and scoring tools passed the offline suite (288 tests). Cloud build/deployment and the 120-minute campaign await explicit approval. No new accuracy result, production change or operational promotion is claimed.

Date: 16 November 2026 (IST). This is a report of implemented behavior and measured limitations, not a claim that all research and multi-user acceptance is complete.

## Latest measured validation addendum

The authoritative new study and deployment are described in [Measured validation](measured-validation.md) and [Implementation status](status.md). Release `20261116T175035Z-public` (API `00016-7ph`, dashboard `00013-sdq`) adds the measured-evidence panel and prospective recording support. The frozen models have **3/9 point-MAE wins on 438 newer measured minutes**, all CPU horizons, with no CPU improvement established after multiplicity-adjusted uncertainty. The separate original cohort remains 0/9. Four logged HTTP503 minutes now provide narrow availability-event labels; the raw detector also flags all thirty-five matched no-5xx minutes. General fault accuracy remains unestablished. The export has zero rows and no comparable optimisation experiment; measured savings are null. The new scope excludes OAuth work. The remainder of this report describes the earlier implemented features and original cohort, not a claim that every validation gate is passed.

## Delivered system

AutoCloud provides a public Streamlit dashboard at https://autocloud-dashboard-l25hfnltba-el.a.run.app/ backed by a private Cloud Run API. A separate keyless collector reads Cloud Monitoring and ingests BigQuery every five minutes. Reads are scoped and cached; unknown measurements remain missing. Forecasts and anomaly scores require fresh measurements and are observation-only. Infrastructure execution is disabled.

The latest verified host-feature release is `20261116T170715Z-public`, immutable image `sha256:f0d40fa13bf67f4a44d9ac7a7358cac1601d43ac075c7b1c21da385648314334`, built by Cloud Build `0faef026-c179-4b30-8567-d3eb12b7ad2d`. API `autocloud-api-00015-cv5` and dashboard `autocloud-dashboard-00012-79r` are deployed. Exact live acceptance evidence is saved in that release directory and reconciled in docs/status.md.

## Recommendations and Gemini explanations

Recommendations combine sustained threshold evidence, experimental model signals and data-quality checks. A consecutive, fully measured low-utilisation window can prompt a sizing review, with explicit requirements to inspect peak traffic, service objectives and allocation before considering changes. No savings are estimated from utilisation alone.

Gemini now generates a summary and original explanatory prose for approved investigation IDs, using supplied evidence rather than the existing template sentences. Generated explanations are displayed with their cited source evidence. Structural checks reject additional IDs, exact template echoes, digit tokens, URLs and common command patterns. These checks are not a semantic proof of factual accuracy. Users must review generated explanations, and the model has no tools or execution capability.

The first live prose candidate echoed templates; it was not accepted as original writing. The revised prompt excludes template explanations. Live verification of the revised API returned completed Gemini-generated prose, and every explanation differed from its checked template. Provider/API and public UI verification artifacts record the actual result.

## ML findings and improvement work

On the saved measured experiment cohort, all nine XGBoost forecasts lost to or tied last-value persistence on held-out MAE. The measured cohort contained 232 minutes and 2,097 requests. Those observations do not establish production forecast skill. A separate synthetic periodic benchmark checks pipeline mechanics only.

The improvement evaluation compares XGBoost, persistence and training historical average using chronological validation only. It reports preferred-method errors on a purged test partition. A regression test changes test targets and verifies that selection is unchanged. Retrospective selection preferred baselines in eight target/horizon combinations and XGBoost in one; preferred-method test MAE still had zero wins over persistence. Because this cohort was previously inspected, this is retrospective evidence, not independent validation.

The recent mixed observation window fails the existing missingness readiness gate. No new production model weights were promoted and no gates were relaxed. More representative measured history is required for an independent candidate evaluation.

Isolation Forest retains its raw scores and flags. The saved healthy-period audit had twenty flags among forty-seven assumed-normal rows; idle-only false positives were especially high. New operational annotations separate observed scale-to-zero, uncorroborated model signals and threshold-supported investigations. Retrospectively, there were twenty raw flags and no threshold-supported investigations. That distinction does not prove a more accurate classifier: positive fault recall remains unmeasured, and a corroboration policy can miss genuine faults. Raw output remains visible.

## External project onboarding

Code hardening now checks the initiating browser session's OAuth state, binds the supplied Google access token to the signed-in subject and verified email, requires both Monitoring and Cloud Run permissions, and rechecks access before returning even cached external-project data. Unit tests cover swapped identities, partial permissions and revocation.

Production onboarding remains blocked. The deployed configuration lacks an OAuth client ID, client secret, redirect URI and session secret. Browser redirect/session recovery, standard verifier storage/sealing, bounded tenant-history access, real Google consent and two-user/project isolation require further acceptance before exposure. The public host showcase remains available without login. A public website cannot make private customer-project data anonymous.

See `docs/completion-review.md` for concrete release prerequisites. Service-account key uploads remain prohibited; secrets must be configured through Secret Manager, never through chat.

## Acceptance and costs

The full offline suite passed 271 tests. Container dependency/model checks and staged API checks passed; public HTTP/Streamlit verification evidence is saved per release. Tests using synthetic fixtures or mocked OAuth providers verify behavior, not real accuracy, real OAuth correctness or measured savings.

Gemini testing mode remains enabled by explicit user request. Every button click can make a billable request; ordinary refresh does not call Gemini. Google quotas and per-request bounds apply. When testing is explicitly finished, restore an agreed application budget. The deployment helper preserves the configured testing flag rather than silently resetting it.

No autonomous infrastructure executor, independently demonstrated fault sensitivity, or measured cloud savings is claimed. IAM/scaling limits and the previous ANTIGRAVITY_HANDOFF.md are preserved. The earlier detailed private-release report is archived in `docs/archive/` as historical evidence.
