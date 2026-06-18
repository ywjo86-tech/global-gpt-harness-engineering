# Team Spec

## Roles

- Project Orchestrator
  - Reads the execution contract.
  - Splits work into logical threads.
  - Runs fan-out and fan-in.
  - Requests the stage gate decision.
  - Coordinates a manual, file-based orchestration flow rather than an autonomous background runtime.

- Stage Gate Reviewer
  - Independently checks phase completion.
  - Returns `GO`, `CONDITIONAL GO`, or `NO-GO`.
  - Does not implement changes.
  - Does not replace Safety Warning Protocol approval.

## Thread Plan

- T1
  - purpose: confirm the execution contract and phase boundary
  - start order: global principles first, orchestration and gate rules second, project contract/history/log last
  - output: contract review note
- T2
  - purpose: confirm gate rules and reporting requirements
  - start order: global principles first, orchestration and gate rules second, project contract/history/log last
  - output: gate review note

## Approval Rules

- Classify each thread by the highest-risk item it contains.
- General work may continue within the approved scope without repeated approval and may be executed automatically by the orchestrator.
- Documentation-only stabilization may continue under delegated approval inside the approved scope.
- If a thread contains caution work, request a user `승인`, `진행해`, `계속 진행`, or `OK 진행` before doing it.
- If a thread contains dangerous work, request `위험 확인 후 승인` before doing it.
- A stage-gate `GO` or `CONDITIONAL GO` does not replace the Safety Warning Protocol.

## Merge Point

- Merge after T1 and T2 complete.
- The orchestrator compares outputs against the development plan.
- The stage gate reviewer decides whether the phase may advance.

## Validation Criteria

- Global principles are read first.
- Orchestration and gate rules are read second.
- Project contract, change log, and activity log are read last.
- `docs/DEVELOPMENT_PLAN.txt` is read first.
- Orchestration state is updated.
- Fan-out is explicit.
- Fan-in is explicit.
- Stage gate is independent.
- Approval classification uses the highest-risk item in the thread.
- The workflow is document-driven and manually operated, not an always-on multi-agent runtime.
- General work inside the approved scope can be processed automatically by the orchestrator without repeated approval.
