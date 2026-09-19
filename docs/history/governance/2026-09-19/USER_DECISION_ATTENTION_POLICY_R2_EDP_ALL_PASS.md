# User Decision & Attention Policy R2 — EDP ALL PASS

**Date:** 2026-09-19  
**Protocol:** `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` / EDP-1.0  
**Baseline:** `ee27f8bd0718a49a390a0f82b933c7fec0b8d9a1`  
**Design commit:** `3bb79e34204db999cee725bebef8bd8405eaf166`

## Decision

`EDP_DECISION=ALL_PASS`

The approved R2 policy is implemented without moving Full Plan, Router, MPRF, Full MCP, Manual Action, or AI Office authority. User approval is reserved for genuine decision boundaries; ordinary runtime incidents remain durably recorded immediately but are user-visible only after the R2 delivery policy permits them.

## Authority Freeze

- GPT remains Operator.
- Full Plan remains sole Task/Gate/fan-in/next-state authority.
- Router remains sole provider/model selection authority.
- MPRF remains provider runtime/health/recovery-fact authority.
- Full MCP remains state-changing effect authority.
- Attention remains outbound-only with `control_authority=NONE`.
- No provider expansion or AI Office Phase 7 capability is activated.

## Evidence Matrix

| ID | Obligation / risk | Implemented control | Verification | Result |
|---|---|---|---|---|
| EDP-R2-01 | Policy must not become a second orchestrator | pure `user_interaction_policy.py`; no dispatch/resume/reroute APIs | AST negative-space + runtime probes | PASS |
| EDP-R2-02 | Ordinary FULL_PLAN transition must remain automatic | no Gate semantic changes | Gate focused regression | PASS |
| EDP-R2-03 | GATE_BY_GATE approval boundary must remain | protected existing transition | Gate focused regression | PASS |
| EDP-R2-04 | Approval coverage must be evidence-bound | `ApprovalCoverageEvidence` exact semantic digests + explicit risk/operation coverage | policy tests | PASS |
| EDP-R2-05 | Dangerous retry must fail closed by default | default coverage absent → fresh approval | retry tests | PASS |
| EDP-R2-06 | Safe dangerous retry requires effect reconciliation | only `NO_EFFECT` / `RECONCILED` plus exact coverage | retry tests | PASS |
| EDP-R2-07 | Incident evidence must be immediate | AttentionOutbox record is created at incident occurrence | attention/watch tests | PASS |
| EDP-R2-08 | Ordinary user delivery must wait for no-progress threshold | read-only watcher applies 300-second semantic-progress policy | attention/watch tests | PASS |
| EDP-R2-09 | Genuine decision request must be immediate | `IMMEDIATE_DECISION` for WAITING_APPROVAL | runner/watch tests | PASS |
| EDP-R2-10 | Heartbeat must not count as semantic progress | existing split timestamps preserved | runner stall test | PASS |
| EDP-R2-11 | Recovered stale incidents must not notify | current reason/progress/terminal suppression | adversarial policy tests | PASS |
| EDP-R2-12 | Direct low-level delivery must not bypass deferred policy | deferred events require explicit eligible event IDs | outbox adversarial test | PASS |
| EDP-R2-13 | Historical attention evidence must remain readable | v1 schema retained; class inferred when absent | policy/watch tests | PASS |
| EDP-R2-14 | Existing unrelated dirty patch must remain untouched | byte-identical patch SHA comparison | backup/current SHA match | PASS |

## Traceability

- UDAP-MUST-001~004,018 → approval coverage + user-decision evaluator → TEST-UDAP-003~008,017.
- UDAP-MUST-005~008 → Full Plan protected transition semantics + incident-only integration → TEST-UDAP-001~005,017.
- UDAP-MUST-009~014 → AttentionOutbox + read-only delivery watcher → TEST-UDAP-009~016.
- UDAP-MUST-015~018 → retry policy + approval/effect evidence → TEST-UDAP-006~008,017~018.

`MUST_REQUIREMENT_COVERAGE=100%`  
`MUST_TRACEABILITY_COVERAGE=100%`

## Negative-Space Audit

The new policy module contains no Router, MPRF, Full MCP, Gate execution, resume, reroute, publish, or provider/model-selection call path. It cannot mutate orchestration state.

Changed runtime files are limited to:

- `runtime/orchestrator/user_interaction_policy.py`
- `runtime/orchestrator/production_attention.py`
- `runtime/orchestrator/production_attention_watch.py`
- `runtime/orchestrator/production_full_plan_runner.py`
- `runtime/orchestrator/retry_policy.py`

No Router, MPRF, Full MCP, AI Office, canonical plan, or Gate transition implementation file was modified.

## Adversarial Second Pass

Two material counterexamples were found during the first post-implementation challenge and corrected before closure:

1. A recovered `STALLED_SUSPECTED` or resolved `WAITING_APPROVAL` record could remain pending and surface after recovery progress. Correction: current semantic progress/current incident status suppresses stale delivery.
2. Direct `AttentionOutbox.deliver()` could send deferred incidents without the 300-second policy. Correction: deferred records are not directly deliverable unless an eligible event ID is supplied by a policy layer.

Both corrections were written test-first and revalidated. A second adversarial runtime probe confirmed:

- FULL_PLAN → automatic `SYSTEM_TRANSITION`;
- GATE_BY_GATE → `WAIT_FOR_NEXT_GATE_USER_APPROVAL`;
- dangerous retry without evidence → blocked;
- exact coverage + `NO_EFFECT` → retry allowed;
- `AMBIGUOUS` effect → blocked;
- unresolved deferred incident at 300s → eligible;
- recovered incident → suppressed;
- policy authority negative-space → PASS.

`ADVERSARIAL_NEW_BLOCKER_MAJOR=0` after remediation.

## Regression Evidence

- Baseline before implementation: 120 focused tests PASS; compile/diff PASS.
- Task 1 TDD: 11/11 PASS.
- Task 2 Attention/continuity: 15/15 PASS.
- Task 3 core Gate/runner/retry: 97/97 PASS.
- Compatibility follow-up: 35/35 PASS.
- Adversarial correction suite: 65/65 PASS.
- Final core focused qualification: 236/236 PASS.
- Full MCP focused qualification: 78/78 PASS.
- Full repository regression: **1,656 tests PASS, 16 skipped, RC=0**.
- `python -m compileall -q runtime tests`: PASS.
- `git diff --check`: PASS.
- policy AST authority negative-space: PASS.
- unrelated Provider ACTION dirty patch backup/current SHA-256: `9e6a5afff9ffe787320b875d491d5b82c2727a4813cd63acf93ba3f86b40f6f0` / identical.

## Closure Metrics

```text
BLOCKER_COUNT=0
UNRESOLVED_MAJOR_COUNT=0
UNRESOLVED_MINOR_COUNT=0
MUST_REQUIREMENT_COVERAGE=100%
MUST_TRACEABILITY_COVERAGE=100%
DOMAIN_EVIDENCE_COVERAGE=100%
NEGATIVE_SPACE_OPEN_MATERIAL_COUNT=0
CROSS_DOCUMENT_CONFLICT_COUNT=0
BROKEN_REFERENCE_COUNT=0
UNRESOLVED_MATERIAL_TBD_COUNT=0
UNRESOLVED_MATERIAL_OPEN_QUESTION_COUNT=0
ADVERSARIAL_NEW_BLOCKER_MAJOR=0
PASS_CHALLENGE_OPEN_COUNT=0
SOURCE_AUTHORITY_STATUS=VALID
REGRESSION_REDIAGNOSIS_STATUS=PASS
MATERIAL_DEFECT_SEARCH=EXHAUSTED_FOR_AVAILABLE_EVIDENCE
```

## Final Decision

`EDP_DECISION=ALL_PASS`

The R2 remediation is qualified for use as the next Harness baseline. It reduces unnecessary user interruptions without weakening fail-closed approval, recovery, evidence, or effect-authority guarantees.

AI Office may now resume from a fresh Run identity using this new baseline. Historical failed Runs remain immutable; previously verified TASK-015/TASK-016 evidence may only be adopted through the existing prefix-adoption contract.