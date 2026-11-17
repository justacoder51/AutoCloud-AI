# Measured ML validation and savings audit

Date: 16 November 2026 (IST). OAuth onboarding is outside this study.

## Scope and provenance

The existing model weights were frozen. The snapshot has 438 post-training-cohort measured minutes, drawn from one changing development/verification workload. No model was fitted, tuned or selected on this new snapshot. This is an offline temporal replay, not a prospective prediction log or representative production validation.

Study: `data\validation_studies\20261116T172907Z`. Raw observations, protocol, SHA-256 hashes, query job IDs, sanitised request-log outcomes and analysis runtime versions are preserved. Sources cover timestamps after `2026-11-15T22:00:00+00:00` through `2026-11-16T17:19:00+00:00` (UTC).

## Frozen forecast results

Utilisation errors below are percentage points; request errors are requests per minute. The same eligible origins are used within each model/baseline comparison. Origins need the same sixteen consecutive measured-target minutes required by live inference.

| Target / horizon | Pairs | XGBoost MAE | Persistence MAE | Point-MAE win |
|---|---:|---:|---:|---|
| cpu_utilization_5m | 154 | 0.7683 | 1.3996 | Yes |
| memory_utilization_5m | 153 | 32.1838 | 3.6223 | No |
| request_count_5m | 194 | 7.1854 | 0.9485 | No |
| cpu_utilization_10m | 127 | 0.8740 | 1.3932 | Yes |
| memory_utilization_10m | 127 | 32.8652 | 3.5905 | No |
| request_count_10m | 156 | 7.9619 | 0.9872 | No |
| cpu_utilization_15m | 112 | 0.9563 | 1.7024 | Yes |
| memory_utilization_15m | 112 | 33.2005 | 4.3722 | No |
| request_count_15m | 125 | 9.3165 | 1.1840 | No |

**Three of nine point estimates beat persistence, all CPU horizons. Memory and request-count forecasts lose.** Paired hour-block resampling uses 2,000 replicates; all CPU intervals adjusted for nine comparisons include zero. Blocks can still be dependent and are few. These results do not establish broad superiority or a calibrated accuracy percentage. The original saved cohort remains zero of nine; the two cohorts must not be conflated.

The memory median shifted from about eleven percent in the original history to about forty-one percent in the new snapshot. This describes distribution shift across multiple revisions; it does not identify a causal fault.

## Separate-source availability labels

Complete pagination returned 249 request-log records. Four HTTP 503 requests to /api/reviews occurred at four minute endpoints, associated with the recorded review-history incident. Labels were derived only from logged HTTP outcomes: a positive minute has an observed 5xx; a negative-labelled minute has at least one observed 2xx and no observed 5xx. Other minutes remain unknown. No-error labels do not certify general infrastructure health.

The strict paired comparison has thirty-nine count-matched minutes: four positive and thirty-five no-5xx minutes. The wider fifty-five-minute comparison is also saved to disclose alignment sensitivity.

| Signal | TP | FP | TN | FN | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| raw_flag | 4 | 35 | 0 | 0 | 0.103 | 1.000 |
| threshold_flag | 4 | 23 | 12 | 0 | 0.148 | 1.000 |
| observed_error_signal | 4 | 0 | 35 | 0 | 1.000 | 1.000 |

The raw detector flags every evaluated request minute and is not reliable for this availability task at its current threshold. The measured error-rate signal agrees with the logged outcome on this small sample, but error rate already encodes that contemporaneous outcome. This is a consistency/detection check, **not learned fault prediction or early warning**. Four minutes from one incident type are not four independent fault families. The descriptive recall interval for four successes is approximately fifty-one to one hundred percent; dependence can make even that interval optimistic.

The application now emits an observed-server-error investigation when recent measured errors are present, rather than waiting for an experimental model or a sustained pressure rule. It does not diagnose a cause or authorise scaling.

## Prospective evidence

The opt-in forecast ledger archives already-computed, genuinely future forecasts in the existing GCS bucket using generation-zero immutable records. Repeated origin requests cannot overwrite them. No extra workload or model training is generated. The scorer only accepts predictions whose target time follows both payload recorded_at and the GCS server creation timestamp, and whose actual outcome is present in a later measured snapshot. Backdated/expired predictions and unknown actuals are rejected.

Records occur only when eligible forecasts are already computed by dashboard requests; this is not uniform or representative sampling. A few matured predictions would demonstrate the measurement path, not establish general accuracy.

Reproduction commands (PowerShell, repository root):

```powershell
$env:PYTHONPATH="."
.venv\Scripts\python.exe -B -u infrastructure/collect_validation_evidence.py
.venv\Scripts\python.exe -B -m app.models.real_validation data\validation_studies\20261116T172907Z
.venv\Scripts\python.exe -B infrastructure/score_prospective_ledger.py data\validation_studies\20261116T172907Z --date 20261116
```

The prospective scorer needs a later snapshot containing realised targets. The collection command creates a new study directory; use that new directory when scoring later records.

## Cost evidence and the gate for savings

The existing standard billing export has **zero table rows** and returns zero matching rows for the bounded seven-day query. Financial amounts and savings remain null, not zero. The read-only billing-account linkage request returned HTTP 403; account linkage/export settings could not be independently verified under the current credentials. The standard schema also lacks resource.name/resource.global_name. Resource attribution would need verified service labels or detailed export.

The recorded minimum-instance trial changed the setting briefly and rolled it back within seconds. It was an operator test, not an optimisation baseline/treatment comparison. Manual removal of unrelated GPU resources must not be credited as a learned-model saving.

To establish measured savings:

1. The billing owner verifies the enabled export, linked account, destination and delivery in Cloud Billing. No credentials should be shared in chat.
2. Collect matured, resource-attributed baseline costs and comparable delivered workload, latency/error objectives, currency, credits and other cost drivers. Empty or partial exports cannot be treated as zero.
3. Identify a supported real optimisation, specify its exact resource/configuration, exposure window, rollback, workload and spending bounds, then obtain approval for that concrete change. Do not create an intentionally wasteful baseline merely to advertise savings.
4. Run a comparable baseline/treatment or crossover measurement, controlling concurrent releases and workload differences. Account for Gemini, model serving, collector, query, storage and build overhead.
5. Report the actual net result, including zero savings or a cost increase. List-price estimates or CPU utilisation differences alone are not measured savings.

No additional cloud infrastructure, fault/load traffic, billing export configuration or optimisation treatment was changed for this audit. Only ordinary evidence reads and small optional prediction archives are used.

Official billing references: [Export availability and limitations](https://docs.cloud.google.com/billing/docs/how-to/export-data-bigquery), [Standard versus detailed exports](https://docs.cloud.google.com/billing/docs/how-to/export-data-bigquery-setup).
