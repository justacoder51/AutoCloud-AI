# Cost analysis while real ML history accumulates

Phase 4 model code is prepared but real training is gated on sufficient measured
history. Phase 5 cost code can be developed and tested independently during
the one-hour traffic pilot. This does not complete real ML evaluation or change
the deployed API/collector, schedule, IAM, or active traffic experiment.

## Current scope

- `config/pricing.json` contains dated regional USD list-rate assumptions.
- `models/cost_analyser.py` uses Decimal arithmetic for estimated components
  and like-for-like counterfactual comparisons.
- `services/billing_service.py` optionally reads a supplied standard/detailed
  Billing export, keeping signed credits, currencies and cost types separate.
- `models/cost_report.py` reports unknown costs by default; demo usage is opt-in.

There is no verified billable-unit input or Billing export table configured for
this project's cost module yet. Current project cost is therefore unknown, not
zero. No measured savings, automatic recommendations, currency conversion or
cost-driven scaling actions are claimed.

## Pricing assumptions

Rates were checked on 2026-11-15 using Google's pricing and region pages.
Mumbai (`asia-south1`) is in Tier 1. The file supports request-based services,
instance-based services and standard jobs. It expires on 2027-02-13 and rejects
estimation outside its verification/expiry interval or for an unverified region.
Update and review the central configuration when prices or scope change.

| Profile | CPU USD/vCPU-second | Memory USD/GiB-second | Requests USD/million |
| --- | --- | --- | --- |
| Request-based active | 0.000024 | 0.0000025 | 0.40 |
| Request-based idle minimum instances | 0.0000025 | 0.0000025 | No separate idle requests |
| Instance-based services / standard jobs | 0.000018 | 0.000002 | No request charge |

Job estimates apply a one-minute minimum to every started instance attempt,
including retries, and round above that to 100 ms. Each attempt's supplied
lifetime must include startup/shutdown. The simple job model assumes the stated
CPU and memory allocation throughout; it does not model GPUs or allocation
changes during an attempt. Service inputs must already be billable allocation
units, including applicable minimums/rounding and startup CPU allocations.

Estimates exclude account-wide free-tier credits, negotiated/CUD discounts,
taxes, FX, network, image storage, builds, BigQuery, Monitoring and Scheduler.
They are **Cloud Run compute/request list-rate estimates**, not a total project
or invoice quote. The module does not multiply CPU utilization by elapsed time
or sum request latencies to invent billable CPU: concurrency, startup and billing
mode make those shortcuts unreliable.

## Offline tests and demonstration (another Command Prompt)

The traffic pilot can continue in its existing terminal. Open a second terminal
at the project folder and run:

```cmd
.venv\Scripts\python.exe -m pytest -q tests/test_costs.py
.venv\Scripts\python.exe -m app.models.cost_report
.venv\Scripts\python.exe -m app.models.cost_report --demo
```

Tests and the demo make no cloud calls. The no-argument command returns null
estimated/actual values and `usage_or_billing_export_required`. `--demo` uses
explicit synthetic usage and returns `illustrative_estimate`; its result is
not the cost of the current traffic pilot or the deployed project.

## Explicit usage input

Create a reviewed JSON document using your own metered units or clearly labelled
assumptions. Fields for service usage are:

```json
{
  "project_id": "astute-sign-506809-j8",
  "region": "asia-south1",
  "service_name": "illustrative-service",
  "period_start": "2026-11-15T00:00:00+00:00",
  "period_end": "2026-11-15T01:00:00+00:00",
  "source": "user_assumptions",
  "billing_mode": "request_based",
  "active_vcpu_seconds": "1000",
  "active_gib_seconds": "500",
  "idle_vcpu_seconds": "0",
  "idle_gib_seconds": "0",
  "requests": 1000000
}
```

These values illustrate the schema only. For `source=verified_metering`, supply
an `evidence_reference` pointing to the actual measurement source. That estimate
is still labelled `estimated_not_billed`. Instance-based services use all
billable lifetime allocation in the active unit fields; separate idle fields
must be zero. For job usage, set `billing_mode=jobs` and replace service-unit
fields with `attempts`, each containing `instance_lifetime_seconds`, `vcpu` and
`memory_gib` for one started attempt. Include retries separately.

```cmd
.venv\Scripts\python.exe -m app.models.cost_report --usage data\processed\usage.json
```

An optional `--alternative=PATH` compares the same project/service/region/period.
The result is explicitly counterfactual: performance equivalence and actual
savings require before/after experiments. Negative estimated savings are kept;
the percentage is null when the starting estimate is zero. Model arithmetic
never triggers a cloud modification.

## Optional actual exported usage costs

If Billing export is already configured, provide its full table ID. Otherwise,
review export setup in Cloud Billing first; this module does not enable it or
grant billing access. Standard Billing export costs are project-wide for the
Cloud Run billing service, including other Cloud Run resources in the project;
they cannot be treated as the cost of `autocloud-api` alone.

```cmd
.venv\Scripts\python.exe -m app.models.cost_report --billing-table=BILLING_PROJECT.DATASET.EXPORT_TABLE --project=astute-sign-506809-j8 --start=2026-11-15T00:00:00+00:00 --end=2026-11-16T00:00:00+00:00
```

The reader checks the schema, infers dataset location, filters by project and
usage period, and caps each query at 100 MB billed bytes and a 31-day window.
Credits are added with their signed values; gross cost is not multiplied by
unnesting repeated credit entries. Empty results are `no_exported_rows`, not a
zero invoice. Exported costs can be delayed or adjusted and are not guaranteed
to equal the final invoice. INR and USD rows are not mixed or converted.
Export reports and estimates are separate CLI modes, with no automatic
reconciliation between a project-wide export and a single-service estimate.

Read-only export querying requires the caller's appropriate BigQuery access;
the existing collector identity is not granted access to billing data. The live
table `astute-sign-506809-j8.autocloud_billing.gcp_billing_export_v1_011640_0793FF_B5C560`
was discovered and queried successfully on 2026-11-15. The project-scoped Cloud
Run query returned `no_exported_rows`, not a zero bill. Current Cloud Run charges
are therefore still unknown. Tests use clearly labelled usage fixtures and
mocked query clients.

The LangGraph CLI can now read the export directly, alongside its independent
optional service estimate:

```cmd
.venv\Scripts\python.exe -m app.agents.run --from-bigquery --project=astute-sign-506809-j8 --region=asia-south1 --days=1 --billing-table=astute-sign-506809-j8.autocloud_billing.gcp_billing_export_v1_011640_0793FF_B5C560 --billing-days=1
```

`--billing-days` bounds the trailing usage window to 1--31 days, ending at CLI
invocation time. The table is explicit; the workflow does not enable export,
create tables or grant IAM. The same parameterized, byte-budgeted adapter checks
the export schema and uses its dataset location. Decimal amounts are emitted as
strings, preserving currency, signed credits and project-wide resource scope.
An estimate and exported cost can coexist but are not reconciled as equivalent
service costs. Empty exports remain `no_exported_rows`. There is no automatic
currency conversion, zero-cost fallback or measured savings claim. A billing
query failure stops the run; it is not replaced by an invented result.

Official sources checked 2026-11-15:

Dashboard integration added 2026-11-16: the explicit Costs & actions form reads
the same export adapter in daily mode through `/api/costs`. This adds bounded
daily aggregation, per-currency totals and latest matching export/usage
timestamps, with five-minute per-worker caching and no implicit billing query on
monitoring refresh. See [dashboard setup](dashboard.md). Estimates, final invoice
amounts and savings remain separate. Standard schema/export timing documentation
was rechecked on 2026-11-16; export delivery can lag usage and later adjustments
can change historical usage-period results.

## Verified Item 6 billing & counterfactual evaluation (16 November 2026)

Saved artifact: `data/releases/20261116T110246Z/cost-evaluation-summary.json`.

- **Live `/api/costs` & BigQuery export delivery (`2026-11-16T11:28:52Z`):**
  Both `GET /api/costs?days=7` and `GET /api/costs?days=31` returned HTTP 200
  with `status="no_exported_rows"`, and a direct 31-day bounded query against
  `astute-sign-506809-j8.autocloud_billing.gcp_billing_export_v1_011640_0793FF_B5C560`
  returned `0` exported rows across all GCP services (`cloud_run_rows_present=false`).
  Authenticated Streamlit WebSocket UI check clicked **`Read billing export`** and
  rendered `"No matching Cloud Run billing rows have arrived for this period. Cost is unknown, not zero."`
  with `billing_api_error_present=false`. Actual project Cloud Run spend therefore
  remains **unknown, not zero**, pending Cloud Billing export ingestion.
- **Operator scaling trial control-plane result (`live_result.json`):** Verified
  `autocloud-api` `min_instances` `0 -> 1 -> 0` between `05:31:23Z` and
  `05:31:38Z` (`generation` `1 -> 2 -> 3`, `Ready: CONDITION_SUCCEEDED`, serving
  revision unchanged). Control-plane reconciliation passed; latency/cold-start
  performance equivalence was not measured.
- **`CostAnalyser` illustrative counterfactual list-rate models (`config/pricing.json`, Tier-1 `asia-south1`, USD, excluding free-tier credits):**
  - `experiment_232m_request_based_estimate` (`2,097` requests; assumed `600` active vCPU-s, `300` active GiB-s): `USD 0.0159888` (`status="illustrative_estimate"`, `actual_billed_cost=null`).
  - `counterfactual_24h_min1_vs_min0`: warm `min_instances=1` (`85,800s` idle + `600s` active) `USD 0.3377388` vs. `min_instances=0` (`0s` idle + `600s` active) `USD 0.0159888` -> estimated list-rate reduction `USD 0.3217500` (`~95.27%`, `status="counterfactual_estimate_not_measured"`, `measured_savings=null`).
  - `collector_job_24h_estimate` (`96` cron runs/day at 1-minute minimum, `1` vCPU, `0.5` GiB): `USD 0.1094400/day` (`status="illustrative_estimate"`).

- [Cloud Run pricing](https://cloud.google.com/run/pricing)
- [Region pricing tiers](https://docs.cloud.google.com/run/docs/locations)
- [Standard Billing export schema and credit handling](https://docs.cloud.google.com/billing/docs/how-to/export-data-bigquery-tables/standard-usage)
