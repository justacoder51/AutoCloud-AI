# Synthetic demonstration mode

The dashboard adds an opt-in sidebar **Data mode** control. **Measured monitoring** remains the default. Select **Synthetic demo** for populated presentation charts.

The demo generates a reproducible, fictional six-hour window with 360 complete minute rows, seed 42, and explicit `source="synthetic-demo"` and `service_name="synthetic-example"`. Example timestamps are fixed to 17 November 2026, 00:00–05:59 UTC. They do not imply live cloud activity. The view shows a prominent synthetic-data warning and separate demo tab names.

## What is displayed

- CPU, memory, requests, ingress/egress bytes, instances, response latency and error fraction.
- Nine illustrative trend projections alongside a persistence example, with charts for CPU, memory and requests. These are **not XGBoost predictions**.
- A scripted fictional incident and threshold-alert examples. These are **not Isolation Forest outputs or independently labelled fault validation**.
- Rule-based example investigation guidance. No Gemini request, capacity action or savings claim is made.

## Isolation from measured evidence

The synthetic branch renders before API authentication or HTTP access. It does not read/write BigQuery or Cloud Storage, start collection/traffic, train/load ML artifacts, record forecasts, invoke Gemini, or execute resource changes. Synthetic rows are rejected by the measured `MetricRecord` source schema. Current model gates, measured history and recorded evaluation results remain unchanged.

This implementation uses its own local demo source rather than inserting fake rows into the real BigQuery dataset. Therefore it adds no demo table, IAM grant, scheduled job or new cloud service. Switching back to **Measured monitoring** resumes the existing, private-API-backed measured view. Demo completeness is never presented as real training readiness or model accuracy.

## Validation and rollout

The offline suite passes **292 tests**, including deterministic data generation, measured-schema rejection, bounded projections, scripted alert counts and Streamlit rendering with HTTP calls forbidden. Dependency and compilation checks pass. Existing NumPy deprecation and Windows temporary-directory cleanup warnings are not model-performance findings.

The dashboard-only image update uses the existing Cloud Build/release process and preserves API deployment, IAM, scaling, service identity and environment settings. Live acceptance checks cover default measured rendering, selection of the synthetic view, its labels/charts, and switching back without mixing state. No Gemini button is clicked during verification.

Live release evidence is recorded separately in `data/releases/20261117T075434Z-public`.

The release is now deployed and verified on dashboard revision `autocloud-dashboard-00014-dt7`. Anonymous live checks confirmed measured-to-demo-to-measured switching, all ten demo charts, both tables, five metrics, visible synthetic/projection limitations and zero rendered errors. API revision `autocloud-api-00016-7ph`, dashboard environment/IAM and scaling settings are unchanged. No BigQuery write or Gemini request was made. Image digest: `sha256:a489438ddc93b462cd76577076f0cca4a7d1b9093deeefd7483ef8b440e6d3bf`.
