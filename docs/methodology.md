# Evaluation plan

No experiments or real savings are reported yet. The initial milestone verifies
configuration, health endpoints, error sanitisation, logs and deployment readiness.

After a verified deployment, collect timestamped, service-labelled Cloud
Monitoring observations. Record missing/unsupported metrics explicitly. Keep
synthetic development data labelled and separate from real measurements.

- Compare Isolation Forest with thresholds using independently labelled
  held-out anomalies: precision, recall, F1, confusion matrix and false-positive
  rate. Raw scores are not calibrated probabilities.
- For each service and 5/10/15-minute horizon, split chronologically before
  fitting preprocessing or models. Evaluate XGBoost against persistence or
  historical means with MAE and RMSE, plus MAPE only for nonzero meaningful
  targets. Avoid leakage across horizon boundaries with appropriate split gaps.
- The initial exploratory profile requires 200 observed minutes plus coverage,
  variation and measured 100/20/20 train/validation/test labels per target/horizon.
  The optional conservative profile retains 1,440 observed minutes. Report the
  selected profile and label exploratory results preliminary, not deployment proof.
- Keep dated regional cost assumptions centrally configured. Reconcile estimates
  against billing exports; distinguish estimated savings from measured savings.
- Compare baseline and approved optimised configurations under comparable load
  and observation duration: p50/p95/p99 latency, requests per second, error rate,
  CPU/memory, instance count and expenditure. Include uncertainty and trade-offs.
- Test policy bounds, approval binding to immutable action details, duplicate
  execution protection, audit persistence, failure handling and rollback before
  enabling infrastructure actions.

Record dataset provenance, model versions, split boundaries, cloud revision,
load conditions, observation periods and limitations for reproducibility.
