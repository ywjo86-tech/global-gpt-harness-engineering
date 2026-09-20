# Durable Continuation Controller — EDP Pre-Implementation-Plan Diagnosis

**Date:** 2026-09-21
**Protocol:** `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` / EDP-1.0
**Stable BASE:** `a40626c31353f90c0d4c9e677d3886ea5ccce393`
**Target Spec:** `docs/superpowers/specs/2026-09-20-durable-continuation-controller-design.md`
**Spec SHA256:** `022e251f7b1c1b9904cc065f38396913f1f66dc14d110d071a6faaf91bbd8ee5`
**Approval Evidence:** 2026-09-21 user confirmation `Goal 승인`
**Pre-Design Goal Diagnosis:** `docs/history/upgrades/2026-09-20-DURABLE-CONTINUATION-CONTROLLER/EDP_PRE_DESIGN_GOAL_DIAGNOSIS.md`
**Pre-Design Diagnosis SHA256:** `dbec7654cc6e8a7a9afa7bbbd874a15b292d11ae1b039f9de256afc7aceff317`

## Decision

`EDP_DECISION=ALL_PASS`

The corrected Full Plan Durable Continuation Controller design is structurally ALL PASS and has received explicit Spec approval (`Goal 승인`), so implementation-plan authoring is authorized. The design does not create a second orchestrator or approval authority. It constrains automatic continuation to an internal Full Plan mechanism operating only inside a sealed `AUTO_WITHIN_APPROVED_CONTRACT` Gate contract.

## Authority Freeze

- GPT remains Operator for planning, design, execution approval, contract revision, and exception handling.
- Full Plan remains sole Task/Gate/fan-in/next-state authority.
- `GATE_BY_GATE` next-Gate approval remains unchanged.
- User Decision Policy R2 remains authoritative for initial risky execution, material contract revision, risk escalation, and ambiguous dangerous effects.
- Router/MPRF remain provider-selection/runtime authorities.
- Execution Backend / Full MCP remains state-changing effect authority.
- Runtime activation remains delegated to `RuntimeMigrationTransaction` and verified successor handoff.
- Attention remains outbound-only with `control_authority=NONE`.

## Source Register

| Source | Role | Status |
|---|---|---|
| Current user Goal | requested structural solution to chat-turn continuation dependency | PASS |
| Stable BASE `a40626c31353f90c0d4c9e677d3886ea5ccce393` | current verified Harness source baseline | PASS |
| `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` | canonical diagnosis protocol | PASS |
| `USER_DECISION_ATTENTION_POLICY_R2_APPROVED_DESIGN.md` | continuation/user-decision authority | PASS |
| `FULL_PLAN_CONTINUITY_EDP_REMEDIATION_R1.md` | continuity/recovery invariants | PASS |
| `docs/harness/orchestration-runtime-work-items.md` | FULL_PLAN/GATE_BY_GATE and external-effect boundaries | PASS |
| pre-design Goal diagnosis | frozen DCC-MUST-001..020 obligation set | PASS |
| target DCC design Spec | implementation-design target | PASS |

## Findings / Remediation History

| Finding | Severity | Status | Problem | Correction |
|---|---|---|---|---|
| DCC-F001 | MAJOR | RESOLVED | Initial concept could be read as giving a new Controller independent orchestration authority. | DCC is explicitly Full Plan-owned internal mechanism; eligibility evaluator has `control_authority=NONE`; Full Plan alone advances state. |
| DCC-F002 | MAJOR | RESOLVED | Initial concept risked crossing existing GATE_BY_GATE and explicit external-effect approval boundaries. | AUTO is FULL_PLAN-only; GATE_BY_GATE unchanged; push/destructive Git/system/network/package/credential effects remain separately authorized. |
| DCC-F003 | MAJOR | RESOLVED | Initial Spec prose preserved semantics but omitted canonical `DCC-MUST-001..020` IDs and explicit internal RTM. | Added canonical 20-MUST table and 20/20 Spec RTM; section numbering normalized. |
| DCC-F004 | MAJOR | RESOLVED | Reusing receipt v1 for automatic completion would blur manual vs machine-attested evidence and permit weak self-certification semantics. | Historical v1 remains manual-only; auto path uses attestation-bound `operator-plan-receipt.v2`; DCC is forbidden from minting v1. |

## Evidence Matrix

| ID | Claim checked | Evidence | Result |
|---|---|---|---|
| DCC-EDP-01 | No alternate orchestration authority | §3 DCC-AUTH-001/002; §12 ownership; evaluator `control_authority=NONE` | PASS |
| DCC-EDP-02 | Automatic continuation is explicit opt-in | DCC-MUST-002; §5 `AUTO_WITHIN_APPROVED_CONTRACT` | PASS |
| DCC-EDP-03 | Legacy jobs fail closed to manual | DCC-MUST-003; §5.1; §17 compatibility | PASS |
| DCC-EDP-04 | Gate authority is machine-verifiable and closed | §6 `GateContinuationContract` closed fields/write/verification/risk/commit policy | PASS |
| DCC-EDP-05 | Dynamic evidence cannot rewrite authority | DCC-MUST-005; §7 source-lineage split | PASS |
| DCC-EDP-06 | Free-form PASS cannot self-certify | §8 attestation + v2 receipt binding; v1 auto-mint prohibited | PASS |
| DCC-EDP-07 | Crash recovery is durable/idempotent | §9 transaction phases and crash replay invariants | PASS |
| DCC-EDP-08 | Git TOCTOU is bounded | §10 verified tree/commit tree equality; local-commit-only policy | PASS |
| DCC-EDP-09 | Wait causes cannot alias each other | §11 typed wait reason/substate; only auto-receipt wait recoverable | PASS |
| DCC-EDP-10 | Reconciler/controller dual ownership prevented | §12 canonical lock + lease/epoch/fencing/idempotency | PASS |
| DCC-EDP-11 | User approval boundary preserved | §13 decision/risk/scope/authority hard stops | PASS |
| DCC-EDP-12 | Runtime migration remains separate | §14 delegation to existing migration transaction | PASS |
| DCC-EDP-13 | Full MCP effect authority preserved | §15 effect reconciliation/ambiguity boundary | PASS |
| DCC-EDP-14 | Attention stays notification-only | §16 outbound-only role | PASS |
| DCC-EDP-15 | Backward compatibility is explicit | §17 additive versioning; v1 manual + v2 auto; unknown versions fail closed | PASS |
| DCC-EDP-16 | Implementation surfaces are bounded | §18 new modules / controlled modifications / protected negative-space | PASS |
| DCC-EDP-17 | Failure injection is comprehensive | §19 L1-L6 tests | PASS |
| DCC-EDP-18 | Requirements are traceable | §20 maps DCC-MUST-001..020 to design/proof | PASS |
| DCC-EDP-19 | Acceptance is measurable | §21 DCC-AC-001..013 | PASS |
| DCC-EDP-20 | Rollout/rollback is fail-closed | §22 rollout + §23 rollback; AUTO remains opt-in/manual fallback retained | PASS |

`DOMAIN_EVIDENCE_COVERAGE=100%`

## Requirements Traceability

- `DCC-MUST-001..020`: 20/20 present in the canonical requirement table.
- `DCC-MUST-001..020`: 20/20 have explicit mappings in Spec §20.
- `DCC-AC-001..013`: 13/13 explicit acceptance criteria are present.

`MUST_REQUIREMENT_COVERAGE=100%`
`MUST_TRACEABILITY_COVERAGE=100%`

## Negative-Space Audit

Material absence checks found no open defect after remediation:

- independent DCC approval authority: absent;
- independent DCC next-Gate-selection authority: absent;
- automatic GATE_BY_GATE cross-Gate continuation: absent;
- auto-minted receipt v1: prohibited;
- free-form PASS strings sufficient for AUTO: prohibited;
- direct runtime-current activation by generic continuation path: prohibited;
- direct Router/MPRF provider selection: absent;
- direct arbitrary Full MCP effect authority: absent;
- automatic push/destructive Git/system/network/package/credential authority: absent;
- legacy job reinterpretation as AUTO: prohibited;
- unknown receipt/contract schema permissive fallback: prohibited;
- crash boundary without replay disposition: none in canonical transaction lifecycle;
- unbounded Controller/Reconciler dual owner: prohibited by shared fencing model.

`NEGATIVE_SPACE_OPEN_MATERIAL_COUNT=0`

## Cross-Document Consistency

The corrected Spec is consistent with the existing continuity and user-decision authorities:

- User Decision Policy R2 evaluator-only policy is preserved by the pure `ContinuationEligibilityEvaluator` and Full Plan-owned state transition.
- Full Plan continuity invariant is strengthened: eligible approved work gains a durable owner after chat-turn loss.
- GATE_BY_GATE remains approval-bound; FULL_PLAN-only automation matches existing mode semantics.
- external/dangerous effects retain explicit approval boundaries.
- runtime migration remains delegated to its existing predecessor/successor protocol.

`CROSS_DOCUMENT_CONFLICT_COUNT=0`
`BROKEN_REFERENCE_COUNT=0`

## Adversarial Second Pass

The diagnosis actively challenged the tentative PASS with these counterexamples:

1. Controller becomes alternate orchestrator -> blocked by DCC-AUTH-001/002 and evaluator/controller split.
2. AUTO silently applies to historical jobs -> blocked by MANUAL default and explicit contract opt-in.
3. Generic `WAITING_RESOURCE` is auto-resumed -> blocked by typed wait reason/substate eligibility matrix.
4. Verifier self-approves with a string -> blocked by immutable attestation + closed verifier registry + receipt v2 binding.
5. Tested tree differs from committed tree -> blocked by tree equality and COMMIT_INTENT recovery rules.
6. Commit succeeds but crash occurs before receipt -> transaction recovers from committed tree without re-executing Gate work.
7. Receipt succeeds but crash occurs before advance -> receipt replay is idempotent; canonical Full Plan advances once.
8. Reconciler and DCC race -> canonical run lock/lease/epoch fencing admits one owner.
9. GATE_BY_GATE crosses next Gate -> explicitly prohibited and acceptance-negative tested.
10. Push/system/network/package/credential action inherits AUTO -> explicitly outside local-commit authority.
11. Runtime migration is treated as normal receipt wait -> excluded and delegated to RuntimeMigrationTransaction.
12. v1 manual receipt is silently reinterpreted as AUTO -> prohibited; v2 required for auto-attested completion.
13. Approval/risk/source drift is repaired mechanically -> prohibited; becomes decision/revision/block state.
14. Attention mutates execution -> prohibited; outbound-only.
15. Router/MPRF/Full MCP authority shifts -> protected negative-space and acceptance test.

`ADVERSARIAL_NEW_BLOCKER_MAJOR=0`

## PASS Challenge

Every PASS-critical claim was challenged against the target Spec, current production source interfaces, existing continuity policy, user-decision policy, Gate-mode semantics, runtime migration path, and receipt schema behavior. The material findings discovered during review were corrected before this final diagnosis and remain recorded above.

`PASS_CHALLENGE_OPEN_COUNT=0`

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
EDP_DECISION=ALL_PASS
```

## Exhaustion Statement

`MATERIAL_DEFECT_SEARCH: EXHAUSTED_FOR_AVAILABLE_EVIDENCE`

All mandatory EDP paths applicable before implementation-plan authoring were executed against the available authority, current Stable BASE source, and corrected design Spec. This is an evidence-scoped structural PASS, not a claim that future implementation cannot introduce defects.

## Disposition

The Spec has received explicit user approval (`Goal 승인`) and implementation-plan authoring is authorized. This diagnosis does not authorize production implementation: execution remains gated on separate approval of the reviewed implementation Plan and its effect boundaries.
