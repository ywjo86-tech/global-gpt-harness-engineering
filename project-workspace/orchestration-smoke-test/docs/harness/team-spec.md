# Team Spec

## Roles

- Project Orchestrator
  - Reads the execution contract.
  - Splits work into logical threads.
  - Runs fan-out and fan-in.
  - Requests the stage gate decision.

- Stage Gate Reviewer
  - Independently checks phase completion.
  - Returns `GO`, `CONDITIONAL GO`, or `NO-GO`.
  - Does not implement changes.

## Thread Plan

- T1
  - purpose: confirm the execution contract and phase boundary
  - output: contract review note
- T2
  - purpose: confirm gate rules and reporting requirements
  - output: gate review note

## Merge Point

- Merge after T1 and T2 complete.
- The orchestrator compares outputs against the development plan.
- The stage gate reviewer decides whether the phase may advance.

## Validation Criteria

- `docs/DEVELOPMENT_PLAN.txt` is read first.
- Orchestration state is updated.
- Fan-out is explicit.
- Fan-in is explicit.
- Stage gate is independent.
