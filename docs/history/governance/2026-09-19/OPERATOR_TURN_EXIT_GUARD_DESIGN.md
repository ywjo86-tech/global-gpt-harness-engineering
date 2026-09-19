# Operator Turn Exit Guard — Design Contract

**Date:** 2026-09-19
**Status:** APPROVED DIRECTION / EDP PREIMPLEMENTATION CANDIDATE
**Protocol:** `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` / EDP-1.0
**Authority:** explicit user instruction to diagnose, implement, and complete without unnecessary mid-work stops
**Baseline:** `c11ca2794b15d670d80f82439fd0af7e6bb372c4`

## Goal
Prevent an Operator turn from being treated as finished while executable work remains inside an already approved Full Plan contract.

## Authority Freeze
- Full Plan remains sole owner of Task/Gate/fan-in/next-state transitions.
- Router remains sole provider/model selector.
- MPRF remains provider runtime/health/recovery-fact authority.
- Full MCP remains state-changing effect authority.
- User Decision & Attention Policy R2 remains sole policy for genuine user decision and incident-notification eligibility.
- Exit Guard is read-only classification. It MUST NOT dispatch, resume, reroute, approve, patch, select a provider/model, or mutate orchestration state.

## Required dispositions
`CONTINUE_EXECUTION`, `REQUEST_USER_DECISION`, `NOTIFY_STALLED`, `ALLOW_COMPLETION_RESPONSE`.

## Requirements
- **OEG-MUST-001:** `READY`, `DISPATCHED`, `RUNNING`, `VERIFYING`, `RECOVERING` with executable/incomplete work => `CONTINUE_EXECUTION`.
- **OEG-MUST-002:** `WAITING_PROVIDER`/`WAITING_RESOURCE` ordinary incidents before R2 notification eligibility => `CONTINUE_EXECUTION`, not a final response.
- **OEG-MUST-003:** genuine user-decision state (`WAITING_APPROVAL` or R2 UserDecisionAssessment.required) => `REQUEST_USER_DECISION` immediately.
- **OEG-MUST-004:** unresolved incident eligible under R2 after the stall window => `NOTIFY_STALLED`.
- **OEG-MUST-005:** `BLOCKED`/`FAILED` is not completion. If a verified continuation/recovery action is supplied, return `CONTINUE_EXECUTION`; otherwise notification is allowed only through R2 eligibility, never by terminal-state name alone.
- **OEG-MUST-006:** completion response requires `state=COMPLETED`, `terminal_reason=ALL_GATES_COMPLETED`, all declared Gates complete, no active queue item, and every caller-supplied completion obligation true.
- **OEG-MUST-007:** `CANCELLED` is not successful completion and cannot produce `ALLOW_COMPLETION_RESPONSE`.
- **OEG-MUST-008:** `PREPARED`, patch-ready, Fresh-Run-ready, Manual-Action-ready, validation-ready, or next-task-ready are continuation facts, not completion facts.
- **OEG-MUST-009:** Guard consumes already-produced state/decision/attention facts; it never invents a user approval or next action.
- **OEG-MUST-010:** Full Plan result/entry output includes a canonical `operator_exit` assessment so callers cannot silently omit the check.
- **OEG-MUST-011:** a standalone read-only CLI/check function can re-evaluate persisted state before a user-facing final response.
- **OEG-MUST-012:** GATE_BY_GATE semantics remain unchanged; an actual next-Gate approval boundary remains a genuine user decision.
- **OEG-MUST-013:** R2 300-second semantic/recovery progress rules remain unchanged and are reused rather than reimplemented differently.
- **OEG-MUST-014:** Router/MPRF/Full MCP/AI Office authority negative-space remains unchanged.
- **OEG-MUST-015:** historical Full Plan state remains readable; no state schema rewrite is required.
- **OEG-MUST-016:** final-response allowance fails closed on malformed or incomplete Full Plan state.

## Completion obligations
The caller may supply named booleans such as `EDP_ALL_PASS`, `STABLE_BASELINE_SEALED`, or project-specific exit criteria. Any false/missing required obligation blocks `ALLOW_COMPLETION_RESPONSE` and returns `CONTINUE_EXECUTION` when no user decision/stall notification is due.

## Integration boundary
Create `runtime/orchestrator/operator_exit_guard.py`; integrate only read-only assessment into `production_full_plan_entry.py`; add a documented invocation requirement to `docs/harness/orchestration-execution-standard.md`. Do not change Gate transition, provider selection, MPRF lifecycle, Full MCP effect authority, or AI Office workflow authority.
