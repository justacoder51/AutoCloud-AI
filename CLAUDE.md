# Project development instructions

Read `Cloud.md` first; it is the authoritative specification. Inspect existing
code before edits. Follow its phase order and explicit approval requirement for
cloud changes. The first Cloud Run deployment and authenticated/private-access
smoke tests are verified. Phase 3 real collection, storage, readback and the
Scheduler invocation path are verified. Phase 4 ML code is in development;
real training requires the documented coverage gates and independent evaluation.
Do not deploy models, agents or scaling based on a tiny/mostly idle dataset.

User-approved forecast horizons are 5/10/15 minutes. The default exploratory
profile requires 200 observed minutes plus unchanged coverage/variation and
measured split-label checks. Preserve --profile=conservative (1,440 minutes),
label exploratory results preliminary and never treat readiness as deployment
approval. Native manifest v2 records the profile/horizons; old bundles require retraining.

The independent cost module was developed while real history accrues. Read
docs/cost-analysis.md and the dated config/pricing.json before financial changes.
Do not infer billable CPU from utilization or summed request latency, present
demo costs as real charges, mix currencies, or claim unmeasured savings.

The Phase 6 policy foundation and finite LangGraph/optional Vertex Gemini workflow
are documented in docs/recommendations.md. This is a local recommendation workflow,
not a deployed scaling authority. Preserve exact evidence validation, missingness,
freshness gates and constrained model output. Live fresh-data processing through
Vertex Flash-Lite in Mumbai is verified; evaluated real-data ML artifact integration
remains pending. Explicit native forecast loading and Billing reads are now wired
into the graph; see docs/machine-learning.md and docs/cost-analysis.md. Never turn readiness into a trained-model
claim; costs stay unknown without explicit scoped billable-unit inputs.

See README.md and docs/status.md for implementation status. Run
`.venv/Scripts/python.exe -m pytest -q` for local checks on Windows. Monitoring
unit tests can run independently as `python -m pytest tests/test_monitoring.py`.
See docs/monitoring.md for collection and storage instructions. Never commit
credentials, invent metrics, or claim unmeasured savings. Update documentation
when implementing each phase.
