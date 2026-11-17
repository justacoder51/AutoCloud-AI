# AutoCloud AI - Presentation Outline

Current scope is described in final-report.md, completion-review.md and status.md. Use the latest verified release artifacts for exact deployment values.

1. **Problem and scope:** Explain monitoring and resource-investigation guidance; separate desired optimisation from demonstrated savings.
2. **Hosted architecture:** Public Streamlit dashboard, private Cloud Run API, five-minute collector, Cloud Monitoring and BigQuery; keyless service identities.
3. **Measurement integrity:** Show timestamps, missing values and the restored fresh collection pipeline. A successful job alone is not proof of fresh measurements.
4. **Live forecasts:** Show experimental XGBoost alongside persistence. State the saved zero-of-nine persistence result and the unchanged readiness/freshness gates.
5. **Anomaly interpretation:** Show raw Isolation Forest flags, thresholds, missingness and operational annotations. Explain idle false positives and unmeasured fault recall.
6. **Broader guidance:** Show cited low-utilisation review or data-quality guidance when measured inputs support it. Do not claim a quiet window proves overprovisioning.
7. **Original Gemini explanations:** Click Generate Gemini explanations. Show original prose, cited evidence and its timestamp. Explain schema checks and the need for human review. The public prose route uses a bounded Vertex request; do not claim it is the original private LangGraph workflow. Original LangGraph code remains part of the project, with its routes blocked in public mode.
8. **ML improvement evaluation:** Present validation-only baseline comparison and retrospective results honestly. No new production weights were promoted from failed readiness or test outcomes.
9. **Multi-user security:** Present subject-bound tokens, complete IAM requirements and revocation checks. Explicitly state that real external onboarding remains gated pending OAuth configuration and live acceptance.
10. **Verification and remaining work:** Show test and live evidence. Testing mode is currently explicit and billable; restore an agreed budget after testing. No autonomous changes, independent fault accuracy or measured savings are demonstrated.

Demo remains public; do not display secrets, tokens, service-account keys or unredacted credential logs. Preserve ANTIGRAVITY_HANDOFF.md. Avoid presenting synthetic benchmarks or mocked sign-in tests as production evidence.

## Updated validation slide evidence

Use docs/measured-validation.md for the new frozen-model study: 438 newer measured minutes, CPU point-MAE wins at three horizons (3/9 overall), all CPU family-wise intervals include zero, and poor raw Isolation Forest availability specificity on separately logged outcomes. Distinguish this from the original 0/9 cohort. The error counter agrees with logged server-error outcomes but is not learned prediction. The billing export is empty and savings are unmeasured. Prospective recording is enabled, with no eligible live forecast at the deployment check. Do not claim general accuracy, mature prospective results, or positive savings.
