# First measured-data exploratory training result

Trained on 16 November 2026 at approximately 10:49 IST (05:19 UTC).
Run: `models/runs/20261116T051914Z_48d41482`.

The user resumed training after its hold. The experiment had recorded 2,097
successful HTTP requests. Its historical `training_not_ready` stage contains a
`training_paused` result, not an attempted fit. This new offline run is separate;
the original collection status has not been rewritten.

## Evidence and method

Used the previously assessed experiment cohort: 232 consecutive measured minutes
from 15 November 18:09 through 22:00 UTC. No observations were removed based on
their values or forecast results. Snapshot and cohort selection are recorded in
`data/training_inputs/experiment_1c4121e4baad4aa3bf61776d28a232dc/`.
All unchanged exploratory gates passed: at least 200 observed minutes, per-feature
missingness below 20%, variation and measured chronological split-label counts.
Maximum feature missingness was 9.05%. The broader gappy history still fails;
this successful assessment applies specifically to the experiment cohort.

Isolation Forest and nine XGBoost target/horizon models trained locally on CPU.
Depth selection used validation MAE only. Test labels were held out with horizon
purging. Missing feature imputation used training-fitted medians. The workload
was controlled real HTTP traffic, not labeled anomaly ground truth or a
representative production evaluation.

## Held-out forecast results

Lower MAE is better. CPU/memory errors below are utilization fractions; request
errors are requests per minute. Detailed RMSE and split metadata are in
`evaluation.json` inside the run directory.

| Target | Horizon | Test samples | XGBoost MAE | Persistence MAE |
| --- | --- | --- | --- | --- |
| CPU | 5 min | 36 | 0.00025746 | 0.00015311 |
| CPU | 10 min | 31 | 0.00030279 | 0.00014202 |
| CPU | 15 min | 26 | 0.00030900 | 0.00015798 |
| Memory | 5 min | 36 | 0.00002295 | approximately 0 |
| Memory | 10 min | 31 | 0.00001892 | approximately 0 |
| Memory | 15 min | 26 | 0.00001624 | approximately 0 |
| Requests | 5 min | 41 | 4.7951 | 1.2195 |
| Requests | 10 min | 36 | 5.3632 | 2.7778 |
| Requests | 15 min | 31 | 9.8740 | 4.8387 |

**Zero of nine forecasts beat persistence on test MAE**, while **five of nine
beat the training historical-average baseline** (`cpu_utilization_5m`,
`request_count_5m`, `memory_utilization_10m`, `request_count_10m`, and
`memory_utilization_15m`). Regime-partition diagnostics
(`forecast_diagnostics` in `evaluation.json`) show why:

1. **Sub-diurnal span:** The 232-minute (3.87-hour) cohort covers less than one
   24-hour cycle for `time_sin`/`time_cos` features.
2. **Piecewise-constant active step:** During the active Phase 7 test window
   (`21:14Z..21:39Z`), memory stayed flat (`11.13%`) and requests stayed at
   `10/min`, giving persistence `0.0000` MAE (XGBoost `request_count_5m`
   achieved `0.1960` MAE vs Historical Average `0.7836`, a `~75.0%` reduction).
3. **Unseen scale-to-zero transition:** After `traffic_ended_at`
   (`21:38:59Z`), traffic dropped to `0/min`, causing `request_count_5m` MAE
   to jump to `9.6242` (vs Persistence `2.5000`) on those 20 post-cutoff origins.

Training succeeded, but this exploratory candidate remains undeployed and must
not drive scaling. Do not repeatedly tune against this already-inspected test split.

## Controlled 1,800-minute multi-cycle benchmark (synthetic)

To verify that the unchanged `ResourcePredictor` (`depths=(2, 3)`) outperforms
both baselines when smooth multi-cycle periodic dynamics and sufficient history
exist, an executable deterministic benchmark was preserved in `app/models/benchmark.py`
and saved to `models/representative_forecast_benchmark.json` (explicitly labeled
`benchmark_type="synthetic_multi_cycle_workload"`, `deployment_allowed=false`):

- **Reproduction command:** `.venv\Scripts\python.exe -m app.models.benchmark`
  (`seed=42`, `dataset_sha256: da1b193e0a013311b13ec87ec25c2f8e0c35eb75373349233a4844dfc07c3a36`,
  `345–355` held-out test samples under the `conservative` profile).
- **Cycles exercised:** 1,800 minutes (30 hours) equals `1.25` 24-hour clock
  cycles plus 7–28 complete shorter harmonic workload cycles
  (`62.83m`, `125.66m`, `188.50m`, `251.33m` sinusoidal/modulo periods).
- **Beats Persistence MAE:** `9 / 9` models (e.g., `cpu_utilization_5m`:
  XGBoost `0.003326` vs Persistence `0.010409`; `request_count_15m`: XGBoost
  `0.061268` vs Persistence `2.136232`).
- **Beats Historical-Average MAE:** `9 / 9` models (e.g., `cpu_utilization_5m`:
  `0.003326` vs `0.063732`; `request_count_15m`: `0.061268` vs `3.201119`).

This demonstrates pipeline mechanics on a constructed smooth periodic workload;
it does not establish accuracy on real Cloud Run workloads and does not replace
the `0 / 9` measured real-data result above.

## Held-out anomaly evaluation (post-hoc experiment-event labels)

Post-hoc evaluation of the saved Isolation Forest artifact
(`anomaly_detector.joblib`, without refitting) ran against two **post-hoc
experiment-event label sets** derived strictly from client runner logs
(`data/training_runs/1c4121e4baad4aa3bf61776d28a232dc/status.json` and
`phase_7.json`, `traffic_ended_at = 2026-11-15T21:38:59.189151+00:00`,
300/300 HTTP 200), covering the 47 held-out test minutes
(`2026-11-15T21:14:00+00:00` through `2026-11-15T22:00:00+00:00`):

1. **Workload regime-shift detection (`anomaly_labels_regime_shift.csv`):**
   26 active Phase 7 minutes (`21:14Z..21:39Z`) labeled `0`; 21 post-experiment
   traffic-cessation and scale-to-zero minutes (`21:40Z..22:00Z`) labeled `1`.
   - **Full available cohort (47 vs 41 rows):** Isolation Forest achieved
     Precision `1.0000`, Recall `0.9524` (`20/21`), F1 `0.9756`, FPR `0.0000`,
     Confusion Matrix `[[26, 0], [1, 20]]` across all `47` test rows (missing
     only `22:00Z`, where CPU/latency/error were absent). The heuristic threshold
     baseline (`cpu>0.9`, `mem>0.9`, `err>0.05`, `lat>1000`) abstained on `6`
     wholly missing idle rows (`coverage.baseline_abstained_rows = 6`) and
     scored Precision `0.0000`, Recall `0.0000`, F1 `0.0000`, FPR `0.0000`,
     Confusion Matrix `[[26, 0], [15, 0]]` on its `41` observable rows.
   - **Like-for-like shared-observable cohort (41 rows, `shared_observable_comparison`):**
     Excluding the 6 wholly missing rows where the threshold baseline abstained,
     Isolation Forest achieved Precision `1.0000`, Recall `1.0000` (`15/15`),
     F1 `1.0000`, FPR `0.0000`, Confusion Matrix `[[26, 0], [0, 15]]` versus the
     threshold baseline's `[[26, 0], [15, 0]]` (`F1 = 0.0000`).

2. **Operational-normality specificity audit (`anomaly_labels_operational_fault.csv`):**
   **Operational-normality assumption:** all `47` test-partition minutes (including
   unlogged idle/scale-to-zero minutes after `21:39Z`) are assumed healthy (`0`)
   because Phase 7 recorded 0/300 client HTTP errors and no fault was injected.
   Because `positive_fault_examples = 0`, positive fault recall/sensitivity is
   **unmeasured** (`fault_sensitivity_measured = false`).
   - **Isolation Forest:** False Positive Rate `0.4255` (`20/47` across all `47`
     assumed-normal minutes: `0/26 = 0.00%` during active traffic and
     `20/21 = 95.24%` during idle/scale-to-zero minutes), Confusion Matrix
     `[[27, 20], [0, 0]]` on all `47` rows; `0.3659` (`15/41` on the `41`
     shared observable rows, `15/15 = 100.00%` on observable idle rows),
     Confusion Matrix `[[26, 15], [0, 0]]`.
   - **Threshold Baseline:** False Positive Rate `0.0000` (`0/41`), Confusion
     Matrix `[[41, 0], [0, 0]]` (`41` evaluated rows, `6` abstentions).

**Conclusion:** Isolation Forest detects workload regime shifts away from its
active-traffic training distribution (`F1 = 0.9756` across 47 rows; `1.0000` on
the 41 mutually observable rows), but produces a `42.55%` (`20/47`)
false-positive rate across all `47` assumed-normal minutes (`20/21 = 95.24%`
on idle/scale-to-zero minutes alone; `15/41 = 36.59%` on the 41-row shared
cohort) when planned serverless scale-to-zero/idle behavior is assumed
operationally normal. Fault sensitivity remains unmeasured, do not tune
thresholds or models on this already-inspected test set, and live anomaly
inference remains disabled.

## Artifacts and validation

Saved history, updated evaluation report (`evaluation.unlabelled.json` preserves
the original unlabelled report), post-hoc label CSVs and
`anomaly_labels_provenance.json`, nine native XGBoost JSON files, a versioned
manifest, and local Python model bundles. Native manifest inspection and
`config/dashboard-evaluation.json` checksum validation passed
(`sha256: 9461e93bd134b2650edc71166f09aefaf6a5fe29221560550f3dc3b8d5234841`).
Note that the deployed Cloud Run container image (`autocloud-api-00006-pgf`) still
holds the prior packaged copy until the next user-approved rebuild. No inference
on stale historical origins is presented as a live forecast.

An initial Windows text-write translated LF to CRLF after computing the history
checksum. The training writer now saves exact UTF-8 bytes. This run's history was
restored to the exact bytes matching the original checksum; the integrity gate
was not weakened. No refit or test-based model selection occurred during repair.
