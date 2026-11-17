# AutoCloud completion and acceptance review

Date: 16 November 2026 (IST). This report distinguishes implemented code from measured outcomes and live prerequisites. Deployment details are recorded in docs/status.md and data/releases.

| Requested work | Result | Remaining acceptance requirement |
|---|---|---|
| Gemini-written explanations | Added structured, original prose grounded in approved IDs and displayed evidence; summaries and explanations are rendered separately from checked guidance. Exact template echoes, extra IDs, digits and common command/URL patterns are rejected. | Live original-text generation and the anonymous public Gemini button passed on release 20261116T170715Z-public; evidence is recorded in its release directory. Text checks are not proof that generated claims are true; users must verify cited evidence. |
| Better ML performance | Added validation-only comparison of XGBoost, persistence and training historical average, including preferred-method test metrics. Tested that changing test targets cannot change selection. | Retrospective previously inspected cohort still has zero preferred-method test MAE wins over persistence. New mixed-window readiness fails missingness limits. No new weights are promoted. Representative measured history and independent fault labels remain necessary. |
| Idle false-positive handling | Raw scores remain unchanged; each minute now distinguishes observed scale-to-zero, uncorroborated model signal and threshold-corroborated investigation. | Retrospective healthy-period assumption: twenty raw flags across forty-seven rows, no corroborated pressure investigations. This is a policy distinction, not proof of improved detector accuracy; fault recall remains unmeasured. |
| Broader resource guidance | Added review of sizing when an entire consecutive thirty-minute window has measured low CPU/memory and low error rate on active instances, with exact evidence. | It is a review prompt, not permission to resize. Peak traffic, service objectives and billing evidence are required before resource changes or savings claims. |
| Other users' projects | Hardened OAuth initiating-session state matching, user/access-token subject binding, full required IAM checks and revalidation before cached external-project reads. Added regression tests. | Production onboarding stays blocked. OAuth client ID, client secret, redirect URI and session secret are absent. Browser redirect/session recovery, real consent and two-user/project isolation must pass before exposure. |
| Final testing and reporting | Offline tests, container checks and staged live verification are recorded with deployment evidence; report/status/presentation notes are updated. | External OAuth and independent ML/cost acceptance remain explicitly incomplete. |
| Budget after testing | Testing mode remains active as explicitly requested. Existing budget objects are preserved; the release helper now preserves the configured testing flag. | End testing explicitly, then restore the application budget or approve a revised budget. Changing this during ongoing testing would reverse the prior instruction. |

## External onboarding release prerequisites

Keep the host showcase public and leave current API allowlist restrictions in place until these checks pass. A public website does not grant access to another person's private cloud data.

1. The project owner must configure a Google OAuth web client, consent branding/audience and authorised test users. Client creation/consent cannot be replaced with fabricated credentials. Do not send client secrets, access tokens or service-account keys in chat.
2. Review the exact redirect URI and complete durable browser/session binding or validate the original-tab manual callback flow. The current strict state check deliberately fails closed if the initiating session is lost; cross-tab/redirect recovery is not yet live verified.
3. Store the OAuth client secret and a cryptographically random session secret in Secret Manager, and prepare secret-specific access for the API identity. No broad project-wide secret role is required. Configure GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, DASHBOARD_OAUTH_REDIRECT_URI and DASHBOARD_SESSION_SECRET through the reviewed release plan.
4. Test Google consent, successful login, expired/replayed state, swapped access tokens, missing one required permission, revocation and permission removal during a cached read. Use two real accounts and separately authorised projects; mocked providers do not establish real IAM correctness.
5. Review tenant-store event-list deadlines/pagination and replace the custom PKCE sealing scheme with standard authenticated encryption or server-side verifier storage before general external onboarding.
6. Only after this acceptance, expose scoped optional connection controls. Never make private customer metrics anonymous or remove the host/external target distinction. No service-account key uploads are accepted.

## Budget restoration after the testing phase

Current testing mode intentionally permits repeated potentially billable button requests. Ordinary refresh never calls Gemini. Google quotas and per-request size/time limits still apply.

When testing is explicitly finished, restore the existing shared hourly budget by updating DASHBOARD_GEMINI_TESTING_UNLIMITED=false on the API. The UI follows the API capability; update the dashboard setting too for configuration consistency. The release tool preserves this value on subsequent releases. The existing normal budget is one attempt per UTC hour, with immutable reservations and separate immutable results; choose a revised daily/frequency policy if that is too restrictive for normal use. No budget or spending cap can be claimed to cover all Cloud Run, BigQuery and storage costs.

## Scientific limits

The saved workload, post-hoc regime labels and synthetic unit fixtures serve different purposes. None demonstrates real fault sensitivity or measured cloud savings. Retrospective re-evaluation of an already inspected cohort is not independent validation. Existing exploratory models remain observation-only, and no autonomous infrastructure executor has been connected.
