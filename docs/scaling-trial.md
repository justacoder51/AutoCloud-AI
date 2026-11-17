# Operator-controlled scaling trial foundation

This increment implements a narrow Cloud Run adapter and local trial controller.
It is separate from investigation review decisions, AI agents and dashboard
buttons. It is not an autonomous scaling system. The bounded live rollback test
below is now verified.

## Supported change

Only a service minimum-instance trial from 0 to 1 and back to 0 is supported.
An existing service or revision cap of one or two is required. The service must
be ready, use automatic scaling and have no revision-level minimum. The patch
updates only `scaling.minInstanceCount`; images, routing, IAM and CPU are untouched.
One warm instance can incur charges; this trial does not establish savings.

`CloudRunService.minimum` defaults to Cloud Run `validateOnly=true`. Actual changes
require the explicit mutation path through `ScalingTrial.apply`. Planning reads
the current service and generates a five-minute plan and digest. Application
checks the approved digest, target, bounds, etag, configuration fingerprint and
active experiment status. Investigation approvals do not supply this digest.

## Recovery behavior

Before sending a mutation, the controller writes and fsyncs an exclusive active
plan and append-only events under `data/scaling_trials/<target-hash>/`. An
unfinished trial blocks another apply. API errors and timeouts preserve the
checkpoint; an uncertain request must not be blindly retried. Journals contain
configuration hashes, not the full service configuration or credentials.

After the service has reconciled, `rollback()` reads the live resource and checks
for configuration drift before restoring the minimum with its current etag.
Calling it after reconciliation verifies minimum zero and releases the marker.
A submitted operation is not completion. Failed readiness or drift requires
operator reconciliation rather than overwriting unrelated changes.

There is currently no background watchdog, unattended timed rollback, authenticated
multi-user approval API or dashboard execution button. An operator must stay with
the trial, verify reconciliation and finish rollback. Local journals are not a
tamper-proof audit system. Do not delete an active marker to bypass recovery.

## Original live preflight

Read-only Cloud Run v2 access confirmed service `autocloud-api` in `asia-south1`,
generation 1, ready revision `autocloud-api-00001-n6m`, service maximum 2 and
minimum 0 (default), with no revision-level scaling settings. The existing
collection experiment is still active, so a real mutation is deferred to avoid
changing its workload measurements. Model training remains on hold.
The live validation-only patch was accepted and returned an operation with
`done=false`; operation completion was not verified. No persistent update was
requested. Eleven scaling tests passed, plus 16 related review/API tests.

## Sources and testing

Checked 2026-11-15:
- https://docs.cloud.google.com/run/docs/reference/rest/v2/projects.locations.services/patch
- https://docs.cloud.google.com/run/docs/reference/rest/v2/projects.locations.services

Mock tests cover apply/rollback/verification, changed plans, mismatched approvals,
configuration drift, active experiment blocking, uncertain submissions, unsafe
baselines and exact patch fields. These tests establish controller behavior only;
they are not evidence of application availability.

## Verified live trial — 16 November 2026

At 11:01 IST (05:31 UTC), after the collection experiment reached a terminal
state, the user-authorized minimum-instance trial completed on `autocloud-api`
in `asia-south1`, project `astute-sign-506809-j8`.

| Checkpoint | Observed result |
| --- | --- |
| Before | Minimum 0, service maximum 2, ready |
| Apply | Minimum 1 submitted with exact update mask and current etag |
| Applied | Reconciliation complete, minimum 1, generation 2 |
| Rollback | Minimum 0 submitted with the new etag |
| Restored | Reconciliation complete, minimum 0, maximum 2, generation 3, ready |
| Serving revision | `autocloud-api-00001-n6m` before and after |
| Unrelated configuration fingerprint | Unchanged |
| Recovery marker | Cleared only after verified restoration |

The mutation sequence and verification completed between 05:31:23 and 05:31:38
UTC. The configured minimum 1 was verified at 05:31:34 UTC. This verifies the
service configuration change and rollback through the control plane. It does
not prove application latency, uninterrupted request handling, actual instance
provisioning duration or performance improvements. No load test, Gemini request,
model deployment, IAM change or traffic-routing change was performed. Temporary
minimum-instance charges may appear later; no savings or exact cost is claimed.

The original plan, durable event log and sanitized result are stored under
`data/scaling_trials/8836811147e95095030db1e8990c696dad228898b1b80e8787b36f242c8198cd/`.
The completed result is `live_result.json`. No active trial remains for this
target. Existing recommendation approvals still authorize investigation only;
this separate operator trial does not enable dashboard/cloud execution.
