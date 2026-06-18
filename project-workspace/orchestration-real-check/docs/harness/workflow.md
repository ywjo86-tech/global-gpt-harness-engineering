# Workflow

1. Read `docs/DEVELOPMENT_PLAN.txt`, `CHANGELOG.txt`, and `logs/app.log`.
2. Refresh `docs/harness/orchestration-state.md`.
3. Split the work into logical threads.
4. Collect thread outputs.
5. Run fan-in review.
6. Request stage gate review.
7. Record `GO`, `CONDITIONAL GO`, or `NO-GO`.
8. Hand off only after a gate decision exists.

## Approval Rules

- Classify each work slice by the highest-risk item.
- General work may continue within the approved scope and may proceed automatically without repeated approval.
- Documentation-only stabilization may continue under delegated approval inside the approved scope.
- Caution work still requires `승인`, `진행해`, `계속 진행`, or `OK 진행`.
- Dangerous work still requires `위험 확인 후 승인`.
- Stage-gate approval does not replace the Safety Warning Protocol.

## Start Order for Threads

Each project thread should follow this order before work begins:

1. Global principles first.
2. Orchestration and gate rules second.
3. Project contract, change log, and activity log last.

## Automation Boundary

- This project uses document-driven orchestration, not an autonomous background agent runtime.
- The orchestrator coordinates threads explicitly through files and logs.
- The stage gate is a phase-readiness decision role, not a substitute for Safety Warning Protocol approval.
- Vault opening in Obsidian, sync setup, and other UI-side actions remain manual user tasks.

## Handoff Rule

Do not start the next phase until the gate decision is recorded.

## Output Rule

All validation and gate outcomes must appear in the project log and the orchestration state file.

## Required Record Shape

- Fan-out thread records should name the thread, assigned agent, input, expected output, validation criteria, merge point, and status.
- Fan-in records should name received threads, missing outputs, conflicts, duplicate work, requirement coverage, risk summary, QA need, next step decision, and final handoff readiness.
- Stage-gate records should name the phase, decision, evidence reviewed, conditions when applicable, remaining risks, and next step.
- Approval notes should name the risk class, approval needed, and whether stage-gate approval is separate.
