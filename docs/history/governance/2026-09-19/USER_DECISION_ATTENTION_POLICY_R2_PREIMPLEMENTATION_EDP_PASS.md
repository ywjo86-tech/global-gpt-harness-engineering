# User Decision & Attention Policy R2 — Pre-Implementation EDP PASS

**Date:** 2026-09-19  
**Protocol:** `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` / EDP-1.0  
**Target design:** `USER_DECISION_ATTENTION_POLICY_R2_APPROVED_DESIGN.md`  
**Implementation plan:** `docs/superpowers/plans/2026-09-19-full-plan-user-decision-attention-r2.md`  
**Baseline:** `ee27f8bd0718a49a390a0f82b933c7fec0b8d9a1`

## 1. Authority Register

1. Current explicit user decision: corrected R2 direction is approved for controlled implementation.
2. Canonical EDP-1.0 standard.
3. Existing Full Plan continuity authority and silent-stop invariants.
4. Existing Full Plan Hybrid Authority & Attention EDP ALL PASS authority boundaries.
5. Current verified repository source at the baseline above.
6. The R2 design candidate and its implementation plan; these may strengthen but not override items 1–5.

## 2. Frozen Obligations

`UDAP-MUST-001` through `UDAP-MUST-018` are the complete material obligation set for this remediation. `TEST-UDAP-001` through `TEST-UDAP-018` are the required acceptance/adversarial proof set.

No provider expansion, AI Office Phase 7 activation, Gate meaning change, Router selection change, MPRF runtime authority change, or Full MCP effect-authority change is authorized.

## 3. Evidence Matrix

| Domain | Claim | Evidence | Result |
|---|---|---|---|
| EDP-D01 Authority | Policy evaluator does not become an orchestrator | UDAP-MUST-005/006; Full Plan source still owns successor enqueue | PASS |
| EDP-D02 Gate compatibility | FULL_PLAN stays automatic; GATE_BY_GATE stays approval-gated | current `gate_exit_action` source + baseline tests | PASS |
| EDP-D03 Approval scope | Only initial/material/risk-escalation/ambiguous-effect cases require a decision | UDAP-MUST-001~004 | PASS |
| EDP-D04 Coverage evidence | Approval coverage cannot be a naked boolean | UDAP-MUST-018; exact-compatible approval refs/digests required | PASS |
| EDP-D05 Dangerous retry | Safe reuse requires coverage + reconciled/no effect | UDAP-MUST-015~017 | PASS |
| EDP-D06 Incident durability | Evidence is persisted immediately | UDAP-MUST-009 | PASS |
| EDP-D07 Delivery timing | Ordinary notification requires 300s no semantic/recovery progress | UDAP-MUST-010/012/013 | PASS |
| EDP-D08 Decision delivery | Genuine approval/decision request is immediate | UDAP-MUST-011 | PASS |
| EDP-D09 Attention authority | Notification remains outbound-only/no control authority | UDAP-MUST-014 | PASS |
| EDP-D10 Migration | Historical records remain byte-unchanged/readable and class is inferred | compatibility section + TEST-UDAP-016 | PASS |
| EDP-D11 Fresh-run lineage | No fabricated USER_OWNER approval | UDAP-MUST-007 + TEST-UDAP-017 | PASS |
| EDP-D12 Cross-system boundary | Router/MPRF/Full MCP/AI Office authority is unchanged | Authority Freeze + TEST-UDAP-018 | PASS |

## 4. Traceability Matrix

- UDAP-MUST-001~004,018 → Task 1 policy evaluator → TEST-UDAP-003~008,017.
- UDAP-MUST-005~008 → Task 1 + Task 3 integration → TEST-UDAP-001~005,017.
- UDAP-MUST-009~014 → Task 1 + Task 2 Attention path → TEST-UDAP-009~016.
- UDAP-MUST-015~018 → Task 1 + Task 3 retry evidence path → TEST-UDAP-006~008,017~018.

`MUST_TRACEABILITY_COVERAGE=100%`.

## 5. Negative-Space Audit

Checked specifically for missing or accidentally transferred authority:

- no alternate next-state owner is introduced;
- no user notification component gains resume/reroute/patch authority;
- no ordinary FULL_PLAN Gate approval renewal is introduced;
- no GATE_BY_GATE approval boundary is removed;
- no dangerous retry is authorized from missing/ambiguous effect evidence;
- no naked approval-coverage boolean is accepted by the approved design;
- no historical approval is rewritten;
- no current AI Office failed Run is mutated or reused.

No material negative-space omission remains in the design contract.

## 6. Cross-Document Consistency Audit

The R2 design is consistent with the Full Plan continuity invariant: `Gate GO + eligible successor + no approval required` must continue without a silent stop. It also preserves the existing requirement that genuine approval waits are not bypassed.

The previous Attention ALL PASS contract required typed incident evidence and outbound-only notification. R2 preserves both while separating evidence creation from user-delivery eligibility.

The current `gate_orchestrator.py` already implements the required mode split. Therefore the plan correctly treats Gate transition semantics as protected regression scope rather than an implementation target.

The current dangerous retry rule remains the conservative default. R2 only adds an evidence-bound path for approved, safely reconciled re-execution.

## 7. Adversarial Second Pass

Assumed the design was unsafe and searched for counterexamples capable of transferring authority or suppressing required user involvement.

1. **Policy becomes a second orchestrator:** blocked by UDAP-MUST-005/006; evaluator returns classifications only.
2. **Delayed notification loses incident evidence:** blocked by UDAP-MUST-009; persistence remains immediate.
3. **Approval coverage can be fabricated as a boolean:** blocked by UDAP-MUST-018; evidence-bound projection is required.
4. **Dangerous retry duplicates an uncertain effect:** blocked by UDAP-MUST-015~017; ambiguous/missing effect evidence requires user decision.
5. **Fresh Run fabricates approval:** blocked by UDAP-MUST-007; verified lineage is required and no USER_OWNER evidence may be minted.
6. **Long-running heartbeat is mistaken for semantic progress:** blocked by UDAP-MUST-012 and existing separate liveness/semantic timestamps.
7. **Recovered old incident still notifies:** blocked by UDAP-MUST-013 and current-state delivery evaluation.
8. **Historical record bypasses R2 because metadata is absent:** blocked by deterministic class inference without record rewrite.
9. **FULL_PLAN loses automatic continuation:** protected by TEST-UDAP-001 and no planned Gate semantic modification.
10. **GATE_BY_GATE loses approval boundary:** protected by TEST-UDAP-002 and no planned Gate semantic modification.

`ADVERSARIAL_NEW_BLOCKER_MAJOR=0`.

## 8. PASS Challenge

Every closure-critical claim has a concrete implementation target and an executable acceptance test. No PASS claim depends only on absence of evidence: the source locations containing Gate mode semantics, semantic-progress separation, Attention outbound-only behavior, and dangerous retry fail-closed behavior were inspected directly.

No unresolved design dependency requires guessing before implementation.

## 9. Closure Metrics

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
REGRESSION_REDIAGNOSIS_STATUS=NOT_APPLICABLE_PRE_IMPLEMENTATION
MATERIAL_DEFECT_SEARCH=EXHAUSTED_FOR_AVAILABLE_EVIDENCE
```

## 10. Decision

`EDP_DECISION=PASS_FOR_CONTROLLED_IMPLEMENTATION`

The corrected R2 design is structurally compatible with Harness authority and Full Plan continuous execution. Implementation may begin in the isolated remediation worktree using TDD. Final operational acceptance still requires post-implementation full regression and a fresh EDP ALL PASS; this pre-implementation PASS is not a stable-baseline declaration.