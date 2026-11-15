# Project development instructions

Read `Cloud.md` first; it is the authoritative specification. Inspect existing
code before edits. Follow its phase order and explicit approval requirement for
cloud changes. Phase 1 is the current stage. Do not implement monitoring, ML,
agents or scaling until the first Cloud Run deployment is verified.

See README.md and docs/status.md for implementation status. Run
`.venv/Scripts/python.exe -m pytest -q` for local checks on Windows. Never commit
credentials, invent metrics, or claim unmeasured savings. Update documentation
when implementing each phase.
