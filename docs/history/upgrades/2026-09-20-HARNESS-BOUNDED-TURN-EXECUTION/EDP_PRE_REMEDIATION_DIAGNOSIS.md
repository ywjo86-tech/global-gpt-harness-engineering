# EDP Pre-Remediation Diagnosis — Bounded Operator Turn Execution

Protocol: EDP-1.0
Authority: current user directive; existing Operator Continuation Store; Operator Turn Exit Guard; verified 2026-09-20 execution history.

## Frozen obligations
- BTE-001: do not start another task when estimated work plus reserve does not fit the soft turn budget.
- BTE-002: require a durable checkpoint before a budget-driven turn yield.
- BTE-003: in-flight long work requires durable process/log continuation evidence before yield.
- BTE-004: prevent redundant task-by-task generic full regressions; keep Gate-close/final EDP cadence while preserving explicit acceptance proofs.
- BTE-005: budget yield must be reported as non-terminal and must not grant orchestration authority.

## Findings
- BTE-F-001 — MAJOR / RESOLVED BY REMEDIATION: no turn-budget admission decision existed before starting another task.
- BTE-F-002 — MAJOR / RESOLVED BY REMEDIATION: Exit Guard had no safe non-terminal checkpoint-yield disposition.
- BTE-F-003 — MAJOR / RESOLVED BY REMEDIATION: generic full-regression cadence was not encoded, allowing repeated ~1 minute suite runs in one turn.
- BTE-F-004 — MAJOR / RESOLVED BY REMEDIATION: durable checkpoint existence was not coupled to durable in-flight process/log evidence for budget-driven yield.

Pre-remediation decision: REMEDIATION_REQUIRED.
