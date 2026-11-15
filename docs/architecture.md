# Architecture and incremental implementation

The target system is the architecture specified in `Cloud.md`: Cloud Monitoring
feeds validated time-windowed records into BigQuery, with model artifacts in
Cloud Storage. Isolation Forest, XGBoost and a cost engine feed a LangGraph
workflow; Gemini explains validated evidence. FastAPI serves Streamlit. Any
scaling operation passes deterministic policy validation, human approval and
durable auditing before the restricted Cloud Run adapter executes it.

The current implementation is deliberately smaller: `app/config.py` validates
environment settings, `app/utils/logging.py` emits structured logs, and
`app/main.py` provides a deployment/health-check service. Docker packages that
service. Cloud Build tests, builds and publishes; deployment is a separate
explicit operation. Cloud Run IAM is the deployed authentication boundary.

## Gates

| Phase | Deliverable | Exit evidence |
| --- | --- | --- |
| 1 | Environment, billing/budget, IAM, Python and GitHub | Setup verified; local tests pass |
| 2 | Initial Docker/FastAPI Cloud Run deployment | Private authenticated URL, logs and smoke test |
| 3 | Real supported monitoring metrics and historical storage | Source-labelled records; collection/processing tests |
| 4 | Isolation Forest and chronological XGBoost forecasts | Held-out evaluation against baselines; saved artifacts |
| 5 | Central verified pricing/billing and alternatives | Dated regional sources; estimates separated from actual bills |
| 6 | LangGraph/Gemini validated recommendations | Evidence-bound structured outputs and policy tests |
| 7 | Streamlit monitoring and approval views | API integration and dashboard verification |
| 8 | Approved scaling, audit and rollback | Durable approval, bounded execution and rollback tests |
| 9 | Controlled before/after evaluation | Measured performance and cost evidence |

Future modules and empty notebooks are not generated in advance. No BigQuery,
Vertex AI, monitoring or analytics functionality is claimed in this milestone.
Kubernetes and GPU resources are not part of the design.
