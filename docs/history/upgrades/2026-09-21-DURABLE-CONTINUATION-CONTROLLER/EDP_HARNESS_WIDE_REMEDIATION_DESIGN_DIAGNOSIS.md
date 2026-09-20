# DCC Harness-Wide Operational Remediation — EDP Design Diagnosis

**Date:** 2026-09-21
**Protocol:** `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` / EDP-1.0
**Target Amendment:** `docs/superpowers/specs/2026-09-21-dcc-harness-wide-operational-remediation-design.md`
**Target Amendment SHA256:** `e859a8d9c16cea6d77809923e86d394a7b1bae4b6ce3ef8ffbcc0f8527c4fcfe`
**Parent Spec:** `docs/superpowers/specs/2026-09-20-durable-continuation-controller-design.md`
**Source Diagnosis:** `docs/history/upgrades/2026-09-21-DURABLE-CONTINUATION-CONTROLLER/EDP_HARNESS_WIDE_OPERATIONAL_REDIAGNOSIS.md`
**Stable executable baseline:** `a40626c31353f90c0d4c9e677d3886ea5ccce393`
**Scope:** Design-level remediation integrity and readiness for explicit user review. This diagnosis does not authorize implementation or claim runtime defects are already fixed.

## 1. Decision

`EDP_DESIGN_DECISION=PASS_FOR_USER_REVIEW`

The Amendment closes the design/contract gaps for all sixteen recorded Harness-wide findings without creating an alternate orchestration, provider, effect, approval, notification-control, or runtime-migration authority. No design-level blocker or major remains within the available evidence.

`IMPLEMENTATION_PLAN_GATE=BLOCKED_PENDING_EXPLICIT_USER_APPROVAL_OF_AMENDMENT`

The existing implementation Plan remains intentionally superseded-for-execution by the prior NOT_ALL_PASS diagnoses. It MUST NOT be edited into executable authority or executed until the user reviews/approves this Amendment.

## 2. Canonical Source Register

1. Current user direction: remediate the diagnosed Harness-wide operational defects, then re-diagnose before implementation.
2. `EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` / EDP-1.0.
3. Original user-approved DCC Design Spec.
4. Harness-wide operational EDP diagnosis with 4 BLOCKER + 12 MAJOR.
5. User Decision & Attention Policy R2 approved design.
6. Operator Turn Exit Guard design.
7. Full Plan continuity design/implementation evidence.
8. Current Router/MPRF, Full MCP effect-journal, runtime-migration/release production code and focused regressions.
9. Stable active runtime `a40626c...` and same-session fresh regression evidence.
10. Target Amendment is a candidate, not yet approved authority.

## 3. Fresh Evidence

- Target Amendment static self-review: 63 checks / 63 PASS before final adversarial strengthening.
- Finding IDs represented: `16/16`.
- Amendment normative requirements: `HWO-MUST-001..020 = 20/20`.
- Amendment acceptance criteria: `HWO-AC-001..015 = 15/15`.
- Cross-domain focused regression after Amendment edits: `274/274 PASS`.
- Same-session full repository regression before the docs-only Amendment: `1887 PASS`, `15 skipped`; executable files were unchanged afterward.
- `git diff --check`: PASS.
- Working diff at diagnosis: documentation only; no runtime/test executable mutation.
- Current production migration inspection confirmed `MigrationStore.rollback()` is bookkeeping-only and does not reverse `runtime-current`; Amendment section 15 was strengthened to require migration-v2 source-release binding plus explicit reverse activation.

## 4. Primary Domain Evidence Matrix

| Domain | Claim | Evidence | Result |
|---|---|---|---|
| Authority | Full Plan remains sole next-state authority | Amendment §2, §8, §12, §17 | PASS |
| Provider | Router/MPRF remain provider selection/health authorities | §2, §8; same-contract re-evaluation only | PASS |
| Effects | Full MCP remains effect authority | §2, §11; DCC consumes journal evidence read-only | PASS |
| Migration | RuntimeMigrationTransaction remains activation authority | §2, §15; migration-v2 extends same authority | PASS |
| Approval | R2 decision boundaries remain hard stops | §2, §8, §9, §10 | PASS |
| DCC contract fidelity | Exact original wire fields restored | §6 | PASS |
| Source lineage | Approved base + ancestry + previous receipt + tree/commit proof | §7 | PASS |
| Wait recovery | Receipt/provider/resource/migration/approval recovery owners are disjoint | §8 | PASS |
| Operator yield | Platform limitation acknowledged; safe-yield checkpoint contract defined | §9 | PASS |
| Attention | Outbound adapter + R2 eligibility + durable receipts + no control authority | §10 | PASS |
| Historical Attention | Explicit lineage-based supersession, no timestamp inference | §10.2 | PASS |
| Durable storage | Worktree-independent state root and legacy read compatibility | §5 | PASS |
| Locking | Run lock outermost; DCC lock inner; stale owner fencing | §12 | PASS |
| Transaction | Required success and failure/delegation dispositions represented | §13 | PASS |
| EDP publication | validated/closure/publication identities are distinct and diff-bound | §14 | PASS |
| Rollback | Pre-close qualification + migration-v2 reverse activation defined | §15 | PASS |
| Live operation | Active-runtime loss-of-Operator 3+ Gate canary required | §16 | PASS |
| Backward compatibility | New fields additive; historical evidence not reinterpreted | §5, §20 | PASS |
| Notification deployment | live transport requires separate explicit network/credential authorization | §10.1, HWO-MUST-019 | PASS |
| Workstream isolation | Four bounded implementation workstreams with ordering | §17 | PASS |

`DOMAIN_EVIDENCE_COVERAGE=20/20=100%`

## 5. Finding Closure Matrix — Design Level

| Finding | Design closure | Status |
|---|---|---|
| DCC-ORCH-F001 | root triad + immutable runtime binding | RESOLVED_IN_DESIGN |
| DCC-ORCH-F002 | exact original GateContinuationContract wire schema | RESOLVED_IN_DESIGN |
| DCC-ORCH-F003 | closed `continuation_contracts_by_gate` production interface | RESOLVED_IN_DESIGN |
| DCC-ORCH-F004 | deterministic ancestry/receipt/tree/commit lineage proof | RESOLVED_IN_DESIGN |
| DCC-ORCH-F005 | canonical typed wait taxonomy; no `AUTO_CONTINUATION_PENDING` alias | RESOLVED_IN_DESIGN |
| DCC-ORCH-F006 | all required transaction dispositions | RESOLVED_IN_DESIGN |
| DCC-ORCH-F007 | validated/closure/publication identity triad | RESOLVED_IN_DESIGN |
| DCC-HW-F008 | safe-yield / OperatorTurnCheckpoint contract with no control authority | RESOLVED_IN_DESIGN |
| DCC-HW-F009 | outbound production delivery adapter contract + durable receipts | RESOLVED_IN_DESIGN |
| DCC-HW-F010 | explicit run-supersession archival contract | RESOLVED_IN_DESIGN |
| DCC-HW-F011 | typed provider/resource recovery owner under canonical authorities | RESOLVED_IN_DESIGN |
| DCC-HW-F012 | ToolEffectJournal/effect bridge verifier binding | RESOLVED_IN_DESIGN |
| DCC-HW-F013 | stable `harness_state_root`, legacy read-only compatibility | RESOLVED_IN_DESIGN |
| DCC-HW-F014 | canonical lock hierarchy/fencing rule | RESOLVED_IN_DESIGN |
| DCC-HW-F015 | migration-v2 source binding, active qualification, real reverse activation | RESOLVED_IN_DESIGN |
| DCC-HW-F016 | live active-runtime 3+ Gate AUTO canary after Operator loss | RESOLVED_IN_DESIGN |

`FINDING_DESIGN_COVERAGE=16/16=100%`

## 6. Original DCC Requirement Preservation

The Amendment does not replace the original twenty DCC MUST requirements. Cross-check result:

- DCC-MUST-001~003: sole Full Plan authority / AUTO opt-in / manual legacy default — preserved and strengthened by HWO-MUST-002/003/018.
- DCC-MUST-004~007: sealed scope/verifier/attestation and verifier negative-space — preserved and strengthened by HWO-MUST-002/004/012.
- DCC-MUST-008~010: durable transaction, Git tree equality, source lineage — preserved and strengthened by HWO-MUST-004/006/014.
- DCC-MUST-011~014: wait compatibility, exact recovery eligibility, canonical lock/fencing, migration delegation — preserved and strengthened by HWO-MUST-005/011/014/015.
- DCC-MUST-015~018: decision/effect boundaries, dangerous retry/effect reconciliation, Attention outbound-only — preserved and strengthened by HWO-MUST-008/009/012/018/019.
- DCC-MUST-019~020: additive legacy compatibility and exhaustive qualification — preserved and strengthened by HWO-MUST-013/017/020.

`ORIGINAL_DCC_MUST_PRESERVATION=20/20=100%`

## 7. Cross-Authority Consistency

### User Decision & Attention Policy R2

PASS. Provider replacement is allowed only through Router under the same sealed capability/output/validation and approval coverage. Ambiguous effects, risk/scope changes, or approval mismatch stop. Attention delivery is gated by R2 eligibility: immediate genuine decisions, ordinary incidents only after the semantic-progress threshold.

### Operator Turn Exit Guard

PASS. The Amendment does not grant Exit Guard control authority. It adds durable evidence required for a safe yield and explicitly states local code cannot force a ChatGPT platform turn to remain open.

### Router / MPRF

PASS. Provider wait recovery uses fresh MPRF facts and Router re-evaluation of the exact persisted request/eligibility contract; reconciler does not select a provider.

### Full MCP / ToolEffectJournal

PASS. DCC does not execute arbitrary effects and only consumes canonical intent/receipt reconciliation evidence for attestation.

### Runtime Migration

PASS at candidate-design level after adversarial correction. The first draft relied on bookkeeping `rollback()` too broadly; direct code inspection disproved that assumption. The final Amendment introduces migration-v2 source-release binding and an explicit reverse activation sequence while preserving RuntimeMigrationTransaction as sole authority.

## 8. Negative-Space Audit

Explicitly checked and absent from the final Amendment:

- independent DCC scheduler/next-Gate authority;
- Attention inbound resume/approval authority;
- direct provider selection by wait recovery;
- DCC arbitrary Full MCP effect execution;
- automatic push/merge/system/package/credential authority;
- generic auto-resume of `WAITING_RESOURCE`;
- auto-resume of `WAITING_APPROVAL`;
- direct DCC runtime-current mutation outside migration authority;
- timestamp-only Attention supersession;
- historical evidence rewrite/mass migration;
- worktree-local canonical state for new jobs;
- predecessor closure before active-runtime qualification;
- claim that transaction `rollback()` alone restores runtime-current;
- live-notification readiness without an approved/configured transport.

`NEGATIVE_SPACE_OPEN_MATERIAL_COUNT=0`

## 9. Adversarial Second Pass

Challenge: assume the Amendment still reproduces the same silent-stop class.

- Operator turn ends unexpectedly: multi-step workflows have durable safe-yield/owner checkpoint requirements; autonomous execution remains Full Plan-owned, non-autonomous re-entry requires durable checkpoint + Attention.
- Provider recovers without chat: typed provider wait owner re-evaluates canonical MPRF/Router facts.
- Resources recover without chat: resource wait owner re-probes sealed thresholds.
- Receipt wait: DCC only handles exact AUTO receipt/recovery reasons.
- Governed write crashed after effect: ToolEffectJournal evidence is mandatory before attestation/retry.
- Worktree removed: new canonical state is outside worktree.
- Reconciler races foreground DCC: one run-lock-first hierarchy and epoch fencing.
- Runtime candidate fails only when active: predecessor remains quiesced, source runtime is bound, explicit reverse activation occurs before transaction is marked rolled back.
- Chat/operator is removed during live qualification: canary specifically requires systemd/reconciler completion without chat.
- Notification sender is absent: design refuses production-delivery readiness instead of pretending delivery works.

`ADVERSARIAL_NEW_BLOCKER_MAJOR=0`

## 10. PASS Challenge

Potential invalidators and checked locations:

- Could the Amendment weaken existing authority? Checked §2/§8/§11/§12/§15/§21 and original authority docs: no material weakening found.
- Could provider/resource recovery become a hidden scheduler? Recovery only reopens the current bound wait under Full Plan; it cannot choose a Gate/Task.
- Could notification become an external control path? Adapter is outbound-only and no inbound route is defined.
- Could stable state root silently reinterpret old jobs? Legacy fallback is read-only/manual and no in-place migration is authorized.
- Could migration rollback still be bookkeeping-only? Final design requires explicit runtime reverse activation and source release binding.
- Could implementation planning re-create one huge risky patch? §17 requires bounded workstreams and A-C integration before publication workstream D.

`PASS_CHALLENGE_OPEN_COUNT=0`

## 11. Closure Metrics

```text
BLOCKER_COUNT=0                    # design-candidate scope
UNRESOLVED_MAJOR_COUNT=0           # design-candidate scope
UNRESOLVED_MINOR_COUNT=0
HWO_MUST_REQUIREMENT_COVERAGE=20/20=100%
HWO_ACCEPTANCE_COVERAGE=15/15=100%
FINDING_DESIGN_COVERAGE=16/16=100%
ORIGINAL_DCC_MUST_PRESERVATION=20/20=100%
MUST_TRACEABILITY_COVERAGE=100%
DOMAIN_EVIDENCE_COVERAGE=100%
NEGATIVE_SPACE_OPEN_MATERIAL_COUNT=0
CROSS_DOCUMENT_CONFLICT_COUNT=0
BROKEN_REFERENCE_COUNT=0
UNRESOLVED_MATERIAL_TBD_COUNT=0
UNRESOLVED_MATERIAL_OPEN_QUESTION_COUNT=0
ADVERSARIAL_NEW_BLOCKER_MAJOR=0
PASS_CHALLENGE_OPEN_COUNT=0
SOURCE_AUTHORITY_STATUS=CANDIDATE_USER_REVIEW_REQUIRED
REGRESSION_REDIAGNOSIS_STATUS=274_FOCUSED_PASS_AND_EXECUTABLE_BASELINE_UNCHANGED
MATERIAL_DEFECT_SEARCH=EXHAUSTED_FOR_AVAILABLE_EVIDENCE_AT_DESIGN_STAGE
EDP_DESIGN_DECISION=PASS_FOR_USER_REVIEW
IMPLEMENTATION_PLAN_GATE=BLOCKED_PENDING_EXPLICIT_USER_APPROVAL_OF_AMENDMENT
```

## 12. Disposition

The Harness-wide remediation design is coherent enough for user review and has no open blocker/major at the **design-candidate** level. This does not mean the runtime defects are fixed; implementation has not begun.

Required next sequence:

```text
user reviews/approves Amendment
-> invoke writing-plans
-> supersede current monolithic DCC Plan with coordination plan + four bounded workstream plans
-> Spec/Plan cross-document EDP
-> Harness-wide pre-execution EDP
-> only then request/consume implementation execution approval
```

No source implementation, push, runtime activation, Attention transport deployment, or historical state migration is authorized by this design diagnosis.
