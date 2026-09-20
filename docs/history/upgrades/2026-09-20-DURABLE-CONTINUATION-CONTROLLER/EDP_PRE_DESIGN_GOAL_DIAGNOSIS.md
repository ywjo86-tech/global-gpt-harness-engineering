# Durable Continuation Controller — Goal / Pre-Design EDP Diagnosis

- Date: 2026-09-20
- Protocol: `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` / EDP-1.0
- Stable BASE: `a40626c31353f90c0d4c9e677d3886ea5ccce393`
- Target: proposed durable continuation architecture for approved Full Plan execution
- Decision: `EDP_DECISION=ALL_PASS`
- Scope: design qualification only; no runtime implementation is authorized by this report

## 1. Goal

Eliminate the structural dependency on an active ChatGPT turn for already-approved Full Plan continuation. Inside an unchanged, evidence-bound approval contract, Full Plan must be able to execute, verify, commit when explicitly permitted, seal completion evidence, and advance to the next eligible Gate without a chat-turn handoff. Genuine approval boundaries, external/dangerous effects, runtime migration, and ambiguous recovery must remain fail-closed.

## 2. Authority Freeze

1. GPT remains Operator at planning/approval/exception boundaries.
2. Full Plan remains the sole owner of Task/Gate/fan-in/next-state transitions.
3. The proposed Durable Continuation Controller is a Full Plan internal mechanism, **not** a new orchestration or approval authority.
4. User Decision Policy R2 remains authoritative for initial execution approval, material contract revision, risk escalation, and ambiguous dangerous effects.
5. `GATE_BY_GATE` keeps the next-Gate user approval boundary; automatic cross-Gate continuation applies only to explicitly opted-in `FULL_PLAN` execution.
6. Router/MPRF provider authority is unchanged.
7. Execution Backend / Full MCP remains state-changing effect authority; the continuation mechanism must not directly gain arbitrary tool/effect authority.
8. Runtime release changes remain delegated to `RuntimeMigrationTransaction`; generic continuation may not retarget `runtime-current`.
9. Attention remains outbound-only and gains no resume/approve/reroute authority.
10. Git push, destructive Git, system changes, external API/network operations, package installation, credentials, and other separately-approved effects remain outside generic automatic continuation.

## 3. Source Register

| Source | Role | Status |
|---|---|---|
| Current user direction | Goal and sequencing authority | PASS |
| `a40626c...` | Current stable source/runtime baseline | PASS |
| `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` | Diagnosis authority | PASS |
| `USER_DECISION_ATTENTION_POLICY_R2_APPROVED_DESIGN.md` | Decision/attention/continuation boundary | PASS |
| `FULL_PLAN_CONTINUITY_EDP_REMEDIATION_R1.md` | Continuity/recovery invariants | PASS |
| `docs/harness/orchestration-runtime-work-items.md` R01-R25 | Gate-mode and dangerous/external action boundaries | PASS |
| `production_full_plan_runner.py` | Canonical durable Full Plan state/lease/transition implementation | PASS |
| `operator_plan_execution.py` | Current operator receipt wait/receipt contract | PASS |
| `production_run_authority.py` | Immutable authority core | PASS |
| `production_full_plan_boot.py` | Periodic/startup reconciliation | PASS |
| `runtime_migration_handoff.py` + `runtime_release.py` | Runtime migration authority | PASS |
| Focused baseline regression | 116 tests PASS | PASS |

`SOURCE_AUTHORITY_STATUS=VALID`

## 4. Frozen Design Obligations

- **DCC-MUST-001:** Full Plan remains sole continuation/next-state authority; DCC cannot independently choose or approve work.
- **DCC-MUST-002:** Automatic continuation is opt-in and allowed only for `FULL_PLAN` Gates whose sealed contract explicitly says `AUTO_WITHIN_APPROVED_CONTRACT`.
- **DCC-MUST-003:** Existing/legacy jobs default to `MANUAL_OPERATOR`; absence of the new contract never implies automatic authority.
- **DCC-MUST-004:** Every auto-eligible Gate carries a machine-readable sealed contract for allowed write scope, forbidden scope, verification requirements, commit policy, risk class, approval coverage, and continuation mode.
- **DCC-MUST-005:** Dynamic execution facts never mutate the immutable authority core; they are digest-bound transaction/evidence records derived from that authority.
- **DCC-MUST-006:** Completion requires a deterministic `VerifiedGateAttestation`; free-form test strings alone cannot authorize a PASS receipt.
- **DCC-MUST-007:** Verifier has no approval, next-state, provider, migration, or arbitrary effect authority.
- **DCC-MUST-008:** A Gate continuation transaction is durable and crash-safe across execution, verification, commit, receipt sealing, and advancement.
- **DCC-MUST-009:** Verification binds base HEAD, verified tree SHA, changed-path set, evidence digests, and resulting commit; commit tree must equal the verified tree.
- **DCC-MUST-010:** Source evolution uses a sealed lineage policy plus prior receipt/transaction evidence; future commit hashes are not fabricated into the initial authority core.
- **DCC-MUST-011:** `WAITING_RESOURCE` compatibility is preserved while a typed `wait_reason_code`/substate distinguishes low resource, operator receipt, migration quiescence, and other wait causes.
- **DCC-MUST-012:** Only the typed auto-eligible receipt wait may be autonomously recovered by DCC; migration/resource/provider/approval waits cannot be confused with it.
- **DCC-MUST-013:** Controller/reconciler use one canonical run lock plus lease/epoch/fencing/idempotency semantics; dual ownership is prohibited.
- **DCC-MUST-014:** Runtime migration is delegated to the existing migration transaction and successor-verification flow; no generic runtime-link mutation exists.
- **DCC-MUST-015:** `WAITING_APPROVAL`, `USER_DECISION_REQUIRED`, plan/scope/authority drift, risk escalation, ambiguous effect, and forbidden effects remain hard stops.
- **DCC-MUST-016:** Git push/destructive Git/system/external/package/credential effects require their existing explicit authority and are never implied by auto-continuation eligibility.
- **DCC-MUST-017:** Dangerous retry/effect recovery requires existing approval coverage plus effect reconciliation; DCC cannot bypass Full MCP/EffectJournal semantics.
- **DCC-MUST-018:** Attention is a fallback notification path after autonomous recovery cannot make semantic progress; it never controls state.
- **DCC-MUST-019:** Schema migration is additive/versioned/fail-closed; historical jobs/states/receipts remain readable and byte-unchanged where required.
- **DCC-MUST-020:** Final qualification includes crash/failure injection at every transaction boundary, duplicate-dispatch pressure, authority/source drift, reboot, migration, GATE_BY_GATE, approval, external-effect, and legacy-job cases.

## 5. Findings and Design Remediation

| Finding | Severity | Initial problem | Corrected design disposition | Status |
|---|---|---|---|---|
| DCC-F001 | MAJOR | A separately authoritative “Controller” would violate UDAP-MUST-005/006 and Full Plan sole next-state authority. | DCC is explicitly a Full Plan internal mechanism; transition selection remains in canonical Full Plan APIs. | RESOLVED |
| DCC-F002 | MAJOR | Current Gate/job schema lacks machine-readable write/test/risk/commit continuation bounds. | Add sealed `GateContinuationContract`; missing contract defaults to manual. | RESOLVED |
| DCC-F003 | MAJOR | Current PASS receipt accepts free-form evidence strings and could become self-certifying if automated. | Require deterministic `VerifiedGateAttestation` digest before mechanical receipt sealing. | RESOLVED |
| DCC-F004 | MAJOR | `WAITING_RESOURCE` currently represents unrelated low-resource, receipt-wait, and migration-quiesced states. | Preserve top-level state for compatibility and add mandatory typed reason/substate before any auto-resume. | RESOLVED |
| DCC-F005 | MAJOR | Verification→commit→receipt contains crash and TOCTOU windows. | Add durable `GateContinuationTransaction` plus verified-tree/commit-tree equality and recovery-by-phase. | RESOLVED |
| DCC-F006 | MAJOR | Periodic reconciler and a new controller could concurrently own the same Run. | Reuse canonical run lock + lease/epoch fencing; reconciler invokes one recovery path and cannot create a second owner. | RESOLVED |
| DCC-F007 | MAJOR | Generic auto-resume could corrupt runtime migration predecessor/successor semantics. | Runtime migration remains an explicit delegated transaction kind and cannot use generic receipt-wait recovery. | RESOLVED |
| DCC-F008 | MAJOR | Automatic cross-Gate advance could violate `GATE_BY_GATE` and explicit-dangerous-action boundaries. | Auto cross-Gate continuation is FULL_PLAN-only; GATE_BY_GATE/push/system/external actions retain explicit approval rules. | RESOLVED |
| DCC-F009 | MAJOR | Immutable authority cannot pre-bind unknown future commit hashes, while source drift still must be detected. | Seal base HEAD + lineage policy; bind each actual tree/commit in transaction/attestation/receipt chain and require ancestry + allowed-diff proof. | RESOLVED |
| DCC-F010 | MAJOR | Controller could accidentally duplicate Full MCP/EffectJournal effect authority. | DCC may orchestrate only existing authorized calls and local bounded commit policy; all governed effects remain under existing effect authority/reconciliation. | RESOLVED |
| DCC-N001 | NOTE | Splitting top-level wait states would create unnecessary schema/regression blast radius. | Keep existing state enum and add a typed compatible reason/substate field. | CLOSED |

## 6. Mandatory Evidence Matrix

| Domain | Claim | Evidence | Result |
|---|---|---|---|
| D01 Authority | Full Plan stays sole next-state authority | UDAP-MUST-005/006; FPCE authority register; corrected DCC-MUST-001 | PASS |
| D02 Approval | Genuine approval boundaries are not bypassed | UDAP-MUST-001~004/015~018; R15/R25; DCC-MUST-015/016 | PASS |
| D03 Gate mode | GATE_BY_GATE remains manual between Gates | R02-R05; UDAP-MUST-008; DCC-MUST-002/015 | PASS |
| D04 Contract | Auto authority is machine-readable and sealed | current authority-core design + DCC-MUST-003~005 | PASS |
| D05 Verification | Receipt cannot be free-form self-certification | current receipt implementation observed; DCC-MUST-006/007 | PASS |
| D06 Git/source | Tested tree equals committed tree; lineage is bounded | current Git binding gaps + DCC-MUST-009/010 | PASS |
| D07 Recovery | Crash windows are durable/replay-safe | FPCE-MUST-002/009/011/012; DCC-MUST-008 | PASS |
| D08 Ownership | Reconciler/controller cannot dual-own | existing run lock/lease/epoch/idempotency + DCC-MUST-013 | PASS |
| D09 Wait semantics | receipt wait cannot alias migration/resource wait | observed shared WAITING_RESOURCE + DCC-MUST-011/012 | PASS |
| D10 Runtime migration | existing successor protocol remains exclusive | runtime migration transaction code + DCC-MUST-014 | PASS |
| D11 Effect authority | Full MCP/EffectJournal authority does not move | UDAP authority freeze; R25; DCC-MUST-016/017 | PASS |
| D12 Compatibility | historical jobs remain manual/readable | immutable authority schema behavior + DCC-MUST-003/019 | PASS |
| D13 Attention | notification remains outbound-only | UDAP-MUST-009~014 + DCC-MUST-018 | PASS |
| D14 Qualification | design has adversarial/failure test closure | DCC-MUST-020 | PASS |

`DOMAIN_EVIDENCE_COVERAGE=100%`

## 7. Requirements Traceability Matrix

| Obligation | Target design representation | Planned proof | Status |
|---|---|---|---|
| DCC-MUST-001~003 | Full Plan-owned DCC + manual default | authority negative-space + legacy-job tests | PASS |
| DCC-MUST-004~005 | sealed GateContinuationContract + immutable/dynamic split | schema/digest/tamper tests | PASS |
| DCC-MUST-006~007 | VerifiedGateAttestation | forged/free-form receipt rejection tests | PASS |
| DCC-MUST-008 | GateContinuationTransaction | phase crash/recovery tests | PASS |
| DCC-MUST-009~010 | source/tree lineage contract | TOCTOU, ancestry, unauthorized-path tests | PASS |
| DCC-MUST-011~012 | wait reason/substate | wait-cause matrix tests | PASS |
| DCC-MUST-013 | single-owner fencing | concurrent reconciler/controller tests | PASS |
| DCC-MUST-014 | migration delegation | predecessor/successor migration tests | PASS |
| DCC-MUST-015~017 | approval/effect hard stops | R2 decision + dangerous/external negative-space tests | PASS |
| DCC-MUST-018 | attention fallback only | stall/recovered-event tests | PASS |
| DCC-MUST-019 | additive migration/manual fallback | old-job/old-state compatibility tests | PASS |
| DCC-MUST-020 | failure injection qualification | L1-L6 matrix + full regression | PASS |

`MUST_REQUIREMENT_COVERAGE=100%`
`MUST_TRACEABILITY_COVERAGE=100%`

## 8. Negative-Space Audit

The corrected design explicitly prohibits:

- DCC as a second orchestrator or approval authority;
- auto progression of `GATE_BY_GATE` to the next Gate;
- auto-resume of `WAITING_APPROVAL`, provider/resource waits, or migration quiescence as receipt waits;
- free-form test strings as sufficient automatic PASS authority;
- commit of a tree different from the verified tree;
- unsealed write-scope/risk/verification expansion;
- automatic Git push/destructive Git/system/package/credential/external API authority;
- direct provider/model selection by DCC;
- direct runtime-link retargeting by DCC;
- direct arbitrary Full MCP effect execution by DCC;
- historical job reinterpretation from MANUAL to AUTO;
- Attention as a resume/control channel.

`NEGATIVE_SPACE_OPEN_MATERIAL_COUNT=0`

## 9. Cross-Document Consistency

The corrected design is consistent with:

- Full Plan sole next-state ownership in FPCE and User Decision Policy R2;
- FULL_PLAN automatic ordinary Gate transition and GATE_BY_GATE approval separation;
- R25 separate approval for push/system/external/package/credential effects;
- immutable authority core semantics by separating sealed policy from dynamic transaction facts;
- existing runtime migration predecessor/successor transaction authority;
- existing Attention outbound-only policy;
- existing lease/epoch/idempotency continuity model.

`CROSS_DOCUMENT_CONFLICT_COUNT=0`
`BROKEN_REFERENCE_COUNT=0`

## 10. Adversarial Second Pass

The tentative PASS was challenged against these counterexamples:

1. Controller independently selects next Gate -> prohibited; Full Plan canonical transition remains owner.
2. Existing job with no new fields auto-runs -> prohibited; default MANUAL_OPERATOR.
3. Forged `tests=["PASS"]` creates automatic receipt -> prohibited; attestation digest required.
4. Test passes, unrelated process changes file, commit follows -> commit-tree equality fails closed.
5. Commit succeeds, process dies before receipt -> transaction resumes from COMMITTED and does not rerun effect.
6. Receipt seals, process dies before Gate advance -> transaction/reconciler advances idempotently once.
7. Reconciler and controller wake together -> run lock/epoch fencing permits one owner.
8. `RUNTIME_MIGRATION_QUIESCED` mistaken for receipt wait -> typed wait cause prohibits generic recovery.
9. GATE_BY_GATE next Gate auto-starts -> mode guard blocks.
10. Auto continuation performs push/system/external call -> forbidden unless a separate existing authority path proves explicit permission; generic DCC cannot do it.
11. Approval scope changes between Gates -> lineage/authority mismatch becomes decision/revision stop.
12. Dangerous effect status is ambiguous -> R2 requires user decision; no automatic retry.
13. Future commit SHA unknown at job creation -> lineage policy binds allowed transition without inventing mutable authority.
14. Historical receipt/state schema cannot understand new fields -> additive versioning and manual fallback preserve compatibility.

`ADVERSARIAL_NEW_BLOCKER_MAJOR=0`

## 11. PASS Challenge

PASS-critical claims were challenged against the current source implementation and approved governance/continuity contracts. The largest conflicts were F001-F010; each has an explicit corrected design rule and a planned negative/adversarial proof. No unresolved authority, state, migration, effect, or compatibility contradiction remains at the design-goal level.

Focused current-baseline regression executed before closure:

- `tests.test_operator_plan_execution`
- `tests.test_production_full_plan_runner`
- `tests.test_production_full_plan_boot`
- `tests.test_runtime_migration_handoff`
- `tests.test_runtime_migration_authority_negative_space`
- `tests.test_user_interaction_policy`
- `tests.test_operator_exit_guard`
- `tests.test_production_attention_watch`
- Result: **116 tests PASS / 0 failure / RC 0**

`PASS_CHALLENGE_OPEN_COUNT=0`

## 12. Closure Metrics

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

## 13. Exhaustion Statement

`MATERIAL_DEFECT_SEARCH: EXHAUSTED_FOR_AVAILABLE_EVIDENCE`

All EDP-1.0 search paths applicable before Spec authoring were executed against the current baseline, governance documents, Full Plan continuation implementation, receipt path, reconciler, migration path, and focused regressions. This qualifies the **corrected design direction** for conversion into a written Spec; it does not authorize implementation.
