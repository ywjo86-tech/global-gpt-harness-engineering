# EDP Approved External Venv Validation — ALL PASS

- Status: **SUPERSEDED**
- Defect: Full Plan preflight accepted the approved external venv, while worker validation later required only a project-local `.venv`.
- Remediation: active approved venv is accepted when project-local `.venv` is absent; sealed command identity remains stable; no system-Python fallback.
- Focused regression: **135 PASS / 1 opt-in skip**
- Validation toolchain: **12 PASS**
- Full regression: **1588 PASS / 12 skip / RC=0**
- Blocker: **0**
- Unresolved Major: **0**
- PASS challenge: **0**
- Authority boundaries unchanged: Full Plan / Router / MPRF / Full MCP.

> Superseded by `EDP-PH5-EXTERNAL-INTERPRETER-BOUNDARY-20260918`; this record is not closure authority.
