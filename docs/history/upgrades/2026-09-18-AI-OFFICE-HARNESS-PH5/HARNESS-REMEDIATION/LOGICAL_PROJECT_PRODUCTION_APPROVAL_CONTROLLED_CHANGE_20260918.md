# Logical Project Production Approval — Controlled Change

- Date: 2026-09-18
- Project: AI-OFFICE-HARNESS-PH5
- Scope: production approval identity binding only
- Status: VALIDATED

## Defect
`contract_adapter` supports a logical `project_id` resolved from a plan-bound mapping, but `write_production_approval()` always emitted `project_root.name`. For PH5 this produced `global-gpt-harness-engineering` while the canonical mapping/Task projection requires `PHASE5_AI_OFFICE_HARNESS_UPGRADE`, making canonical Gate approval impossible without an unsafe manual rewrite.

## Correction
`write_production_approval()` now accepts an optional explicit `project_id`. The value is validated by the existing identifier validator. The default remains `project_root.name`, preserving all existing callers. The CLI exposes the same optional `--project-id` field.

## Authority Boundary
This change does not create approval. It only binds an approval record to the explicit logical project identity supplied by the authorized caller. Gate state, mapping, plan SHA, LV scope, owned-file scope, baseline HEAD, approval hash and downstream canonical validation remain unchanged and fail closed.

## Validation
- Approval/mapping/state focused suite: 44 tests PASS.
- Full Plan/Operator Resume targeted regression: 108 tests PASS.
- Full program regression in approved `mcp==2.2.0` environment: 1563 tests PASS, 12 skipped, RC=0.
- `py_compile`: PASS.
- `git diff --check`: PASS.

## Stable Semantics Preserved
- default approval `project_id` behavior unchanged;
- Router/MPRF/provider selection untouched;
- Full Plan runner/entry untouched;
- Prefix Adoption untouched;
- no approval is inferred from a logical ID;
- downstream canonical Gate-state validation must still match the approval record exactly.

Decision: CONTROLLED CHANGE PASS.
