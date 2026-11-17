# Approved thirty-minute validation campaign

Status: private lab deployed and traffic running. Actual traffic timer started 17 November 2026, 00:21:57 IST; first confirmed requests returned HTTP200 with valid actuation receipts. Traffic stops by approximately 00:52 IST, followed by immediate service/identity deletion. Measurement collection follows the ingestion holdback. No completed validation result is claimed.

The user authorised shortening and running the private test for **at most thirty minutes**. The previous two-hour preparation is superseded and was never run.

- Campaign: `data/validation_campaigns/20261116T184804Z`.
- Plan SHA-256: `43a8ba0002045e733e4a5fd52084de182781bd71bba2e9f04c484b807e921dc9`.
- Cloud Build: `6d8407d8-8081-4d81-8b75-26e8fec409f2`, SUCCESS.
- Immutable private lab image: `asia-south1-docker.pkg.dev/astute-sign-506809-j8/autocloud/autocloud-validation-lab@sha256:f8d655b22f9705299255d7a67517ea19ee7bf99e6585d4c6fde2cd7fa4d64ca4`.
- Service: `autocloud-validation-lab`, `asia-south1`, 1 CPU / 512 MiB, requested max one / min zero instance, private invocation, dedicated service account with no project roles.
- Deployed revision: `autocloud-validation-lab-00001-pk4`; service UID `f729fbb9-2c61-4368-92e3-d40b25771f46`.
- Traffic: maximum 450 sequential requests, maximum 24/minute, one concurrency, hard thirty-minute schedule. No new request is started in the final ten seconds, leaving room for in-flight work to finish.

Schedule: sixteen minutes steady, one idle, one low, one ramp, one bursty; four one-minute probes (CPU, memory, latency, HTTP503) each followed by one recovery minute; two final steady minutes. Only one episode per probe type is available, so this cannot establish general reliability. Five-/ten-minute forecasts will have few eligible samples and fifteen-minute forecasts may have none. The sixteen-minute observed-history gate remains unchanged.

The supervisor deletes the dedicated lab service and recorded identity **immediately after the traffic phase or its failure**, before waiting fifteen minutes beyond the final complete metric minute. Cloud Monitoring history remains readable after deletion. It then captures actual measurements and scores the frozen models. Builds, deployments and delayed metric availability add wall-clock time outside the thirty-minute traffic window. Registry images, source archive and logs remain and may incur storage charges.

Live state is recorded in `supervisor.json`, startup in `execution.json`, terminal traffic status in `execution-events.ndjson`, deletion in `cleanup.json` and results in `evaluation.json`. A stale startup is not completion. No production deployment, model fitting, target-scope relaxation or infrastructure execution is performed. Intent, confirmed actuation and independently observed client HTTP/latency effects remain separate. This artificial cross-service probe does not prove representative production accuracy, early prediction or savings.

Local checks: **289 tests passed in 36.16 seconds** (nine lab-harness tests). Compilation passed. Existing prospective-ledger NumPy deprecation warnings and Windows temporary-directory cleanup warning persisted; pytest returned 0. `ANTIGRAVITY_HANDOFF.md` is unchanged.

An hourly outcome check is scheduled through Automations, task `Automation_f179dcfcf428819189c7d17c00e31065`; it reports terminal/stalled evidence and disables itself afterward. The finite supervisor, not the hourly check, enforces traffic duration and immediate cleanup.
