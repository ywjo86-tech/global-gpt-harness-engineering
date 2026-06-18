# Workflow

1. Read `docs/DEVELOPMENT_PLAN.txt`, `CHANGELOG.txt`, and `logs/app.log`.
2. Refresh `docs/harness/orchestration-state.md`.
3. Split the work into logical threads.
4. Collect thread outputs.
5. Run fan-in review.
6. Request stage gate review.
7. Record `GO`, `CONDITIONAL GO`, or `NO-GO`.
8. Hand off only after a gate decision exists.

## Handoff Rule

Do not start the next phase until the gate decision is recorded.

## Output Rule

All validation and gate outcomes must appear in the project log and the orchestration state file.

## Required Record Shape

- Fan-out thread records should name the thread, assigned agent, input, expected output, validation criteria, merge point, and status.
- Fan-in records should name received threads, missing outputs, conflicts, duplicate work, requirement coverage, risk summary, QA need, next step decision, and final handoff readiness.
- Stage-gate records should name the phase, decision, evidence reviewed, conditions when applicable, remaining risks, and next step.
