# Phase 4: anomaly detection and resource forecasts

Cloud metric ingestion and BigQuery readback are verified. Cloud Scheduler's
on-demand invocation also completed under its own service identity. Phase 4
adds CPU-based model development; it does not deploy models or enable scaling.

## Modules and evidence

| Module | Purpose |
| --- | --- |
| models/dataset.py | Deduplicate one service, expose missing minutes, assess coverage and make chronological split masks |
| models/anomaly_detector.py | Train-only median imputation, Isolation Forest, heuristic baseline and labelled evaluation |
| models/resource_predictor.py | XGBoost CPU regressors, past-only features, validation selection and held-out forecasting metrics |
| models/train.py | Read validated local/BigQuery observations; assess by default and save candidates only with --train |
| models/benchmark.py | Deterministic 1,800-minute synthetic multi-cycle forecast benchmark (`python -m app.models.benchmark`) |

Tests use explicitly synthetic fixtures to verify algorithms and leakage rules.
They are not experiments on real infrastructure, evidence of cost savings, or
proof that a model improves performance. The available local real snapshot has
only 29 observed minutes and sparse request/latency measurements; its readiness
assessment correctly returns `ready=false` and `trained=false`.

## Install and assess (Command Prompt)

```cmd
cd /d "C:\Users\sihan\Desktop\cloud sem end project"
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q tests/test_models.py tests/test_monitoring.py
.venv\Scripts\python.exe -m app.models.train --from-bigquery --project=astute-sign-506809-j8 --region=asia-south1 --service=autocloud-api --days=7
```

The assessment query uses the deduplication view, service/region filters,
parameterized values, at most 30 days of history and a 100 MB maximum billed-byte
limit. These are read-only cloud operations with possible query usage charges.
It uses the already-configured local ADC identity, not the collector identity.
The existing collector only needs write access to its table; this CLI is for
the authorised research/development user.

For a local assessment without a cloud query:

```cmd
.venv\Scripts\python.exe -m app.models.train --input data\processed\metrics.ndjson
```

Output is printed and written to `models/assessment.json`. Assessment does not
fit a model. The default `exploratory` profile requires at least 200 observed
minutes over a grid of at least 200 minutes. `--profile=conservative` retains
the previous 1,440-observed-minute requirement. Both require at most 20%
missingness per model feature, target variation, and at least 100 measured
training / 20 validation / 20 test origin-label pairs for every target/horizon
after purging. Readiness reports the per-split counts and selected profile.
These are engineering gates, not statistical sample-size guarantees. Exploratory
results are explicitly preliminary; `deployment_ready` remains false.

The service is currently mostly idle. **Waiting alone may not produce enough
data:** it can scale to zero, and many request/latency values remain absent.
Plan a bounded, labelled workload experiment and gather representative history.
No load generator or additional paid workload is silently started by this code.
Never convert missing monitoring values to zero to pass readiness checks.

A bounded opt-in request test is now available in
[controlled-traffic.md](controlled-traffic.md). The default two-minute plan checks
the measurement path; it cannot produce a sufficient training history by itself.

## Forecasting protocol

Use a regular one-minute UTC grid. Missing minutes stay missing. Keep current
measurements, 1/5/15-minute lags, past-only 15-minute rolling means and time-of-day
features. Future observations never enter an earlier origin's feature vector.
Inputs include CPU, memory, requests, network, latency, error rate and instances.

Split the timeline 60% training, 20% validation and 20% test. At each 5/10/15-minute
horizon, purge training/validation origins whose future target would reach the
next split. Test labels must also fall within the observed timeline. Missing
targets are excluded rather than imputed. Require at least 100 usable training
labels and 20 validation/test labels per target/horizon, plus training variation.

Fit imputation on training only. Compare two tree depths on validation MAE,
then evaluate the selected model once on the test split. Do not refit using
test observations. Report MAE, RMSE and MAPE where absolute actual values exceed
1e-6, including the number of MAPE samples. Compare all test results with persistence (the measured target at the forecast
origin) and the training historical-average baseline (`historical_average_test`
in `ResourcePredictor`). A model can lose to the baseline; that result is
retained and not presented as an improvement. Post-hoc baseline and dynamic regime diagnostics for saved runs (`data_characteristics`
and `diagnostic_hypotheses`) are supported via `evaluate_saved_run_forecasts` in
`app/models/train.py`.

Each forecast reports CPU/memory as fractions in [0,1], and traffic as a
nonnegative expected request count per minute. CPU is explicitly selected;
`xgboost-cpu` avoids the full GPU package. Confidence remains null because no
calibrated prediction intervals have been fitted. The origin is the last
observed metric timestamp, not necessarily wall-clock now; Monitoring has delay.

## Anomaly protocol

Isolation Forest learns from the first chronological training partition only,
with train-only median imputation. Entirely unobserved rows are not training
examples. Completely unobserved inference rows remain unclassified. Partial
missingness is exposed in each result. Raw decision scores below zero indicate
outliers under the fitted isolation boundary; **scores are not probabilities**.

The comparison baseline flags observed CPU/memory above 0.9, server-error rate
above 0.05 or mean latency above 1,000 ms. These are configurable heuristic
defaults in `Thresholds`, not universal SLOs. If none of those features is
measured, the baseline is unknown. Severity is also heuristic, not calibrated.
The explanation names the largest deviation from training medians/IQRs; it is
not causal attribution or an Isolation Forest feature-importance claim.

Precision, recall, F1, confusion matrix and false-positive rate require
independent ground-truth labels. Without them, the report says `not_evaluated`.
Do not use the model's own flags or threshold baseline as ground-truth labels.
Optional labels CSV format, for the same target service:

```csv
timestamp,anomaly_label
2026-11-16T10:00:00+00:00,0
2026-11-16T10:01:00+00:00,1
```

Actual labels must come from a documented experiment or independent review.
`evaluate_anomalies` returns a versioned schema (`schema_version: 1`) with explicit
`status` (`evaluated` vs `not_evaluated` when overlap is empty), `coverage`, and
like-for-like `shared_observable_comparison` when predictors differ in missing-row
abstentions; unlabelled rows are not assumed normal. Post-hoc evaluation of an
existing saved run's `anomaly_detector.joblib` without refitting is supported via
`evaluate_saved_run_anomalies` in `app/models/train.py`, and `inspect_run`
(`app/models/inference.py`) validates finite binary classification scores
(`BinaryEvalScores`) against `confusion_matrix` within `1e-6` tolerance before
exposing `anomaly_evaluation` in the Models dashboard.

## Train only after assessing real history

```cmd
.venv\Scripts\python.exe -m app.models.train --from-bigquery --project=astute-sign-506809-j8 --region=asia-south1 --service=autocloud-api --days=7 --train
```

Add `--labels-csv=PATH` for labelled anomaly evaluation. If readiness fails,
training refuses with exit code 2 and saves only the assessment. If ready, a
unique `models/runs/` directory contains both model artifacts, the validated
input snapshot and an evaluation JSON with dataset fingerprint, library versions,
split boundaries, validation decisions, persistence comparisons and uncertainty.
Artifacts are marked `offline_candidate_not_deployed`; no scaling policy
automatically consumes them. The training CLI additionally writes nine native
XGBoost JSON models and `forecast_manifest.json` containing fixed target/horizon
keys, train-fitted imputation statistics, feature schema, XGBoost version,
training-history hash and held-out MAE versus persistence. The workflow does not
load joblib/pickle files. Retained joblib files are for trusted offline research.

## Explicit candidate inference

After a real run passes readiness, training and held-out evaluation, select its
directory explicitly:

```cmd
.venv\Scripts\python.exe -m app.agents.run --from-bigquery --project=astute-sign-506809-j8 --region=asia-south1 --days=1 --forecast-run=models\runs\YOUR_RUN_ID
```

The loader checks one target, exact XGBoost version, native-file and history
SHA-256 hashes, the feature schema, and re-runs the shared training readiness
gate on the saved snapshot. It refuses unknown model keys, path escapes and
oversize files. Only explicitly chosen trusted local runs produced by the
training CLI are supported: hashes detect changes, not a malicious producer.
XGBoost itself advises loading only its own native model files. Older runs
without a native manifest require a new evaluated training run.

Inference needs sixteen consecutive observed minutes with measured CPU, memory
and request counts, an origin at most 15 minutes old, and an origin later than
the entire training/validation/test snapshot. Other missing feature values use
only saved training medians and are disclosed in `imputed_features`.
Future-dated training/inference evidence is rejected. Trees execute on CPU.
Outputs retain 5/10/15-minute horizons, null confidence and held-out model and
persistence MAEs, including losses to persistence. These are offline candidate
forecasts, not deployment approval or evidence of improved capacity or savings.
They cannot create scaling actions or replace the deterministic evidence catalog.
Anomaly inference remains unavailable until independent evaluation is available.
Native manifest schema version 2 records both horizons and training profile;
the loader rechecks the recorded profile's gate. Old 15/30/60-minute bundles
are rejected and require retraining, never silent relabelling. Forecasts expose
the observation origin, target timestamp, remaining lead time at assessment and
`forecast_in_past`, because Monitoring lag can consume a short forecast horizon.

The earlier live assessment on 2026-11-15 found 159 observed minutes over a 318-minute grid,
with 159 gaps and more than 20% missing in every metric. No real model was
trained or loaded. Waiting one day alone does not satisfy the gate: actual
coverage, target variation and representative workload evidence are required.
The native save/load path is verified using explicitly synthetic test fixtures.

Real forecasting accuracy, labelled anomaly performance, scheduled data freshness
and end-to-end inference still need experiments. Useful further checks include
multiple rolling-origin folds, uncertainty calibration, drift and independent
test workloads. They are not claimed as implemented in this first version.

## Official references (checked 2026-11-15)

- [Isolation Forest decision scores](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html)
- [Leakage and preprocessing](https://scikit-learn.org/stable/common_pitfalls.html)
- [Time splits and gaps](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)
- [CPU-only XGBoost installation](https://xgboost.readthedocs.io/en/latest/install.html)
