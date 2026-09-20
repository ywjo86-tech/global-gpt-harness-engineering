# Durable Continuation Controller — Harness-Wide Operational EDP Re-Diagnosis

**Date:** 2026-09-21  
**Protocol:** `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` / EDP-1.0  
**Diagnosis method:** Harness skill + systematic root-cause investigation + direct production-code/live-runtime evidence  
**Stable active runtime:** `a40626c31353f90c0d4c9e677d3886ea5ccce393`  
**Reviewed design branch HEAD before this record:** `af377da1862fe00a09dc25f9cbcc0a56a07232b8`  
**Target Spec:** `docs/superpowers/specs/2026-09-20-durable-continuation-controller-design.md`  
**Target Plan:** `docs/superpowers/plans/2026-09-21-durable-continuation-controller.md`  
**Scope:** GPT Operator -> approval/authority -> Full Plan -> Provider Router/MPRF -> Worker/Full MCP effects -> Git/receipt -> reconciliation/recovery -> runtime migration/release -> Attention/Exit Guard -> evidence retention/rollback.

## Decision

`EDP_DECISION=NOT_ALL_PASS`

The active Harness baseline is healthy, but the proposed DCC implementation Plan and several existing Harness-wide operational ownership boundaries contain material gaps. Implementation execution and publication MUST remain blocked until the findings below are remediated and re-diagnosed.

## Fresh Runtime and Regression Evidence

- Cross-domain focused regression: `255/255 PASS`.
- Full repository regression: `1887 tests PASS`, `15 skipped`.
- `python3 -m compileall -q runtime tests`: PASS.
- `git diff --check`: PASS.
- Active immutable runtime: `a40626c31353f90c0d4c9e677d3886ea5ccce393`.
- Reconciler dry-run: `42 jobs`, `blocked=0`, `resume_requested=0`.
- Nonterminal registered Full Plan runs observed: `0`.
- systemd reconciler timer: `active/enabled`; service `Result=success`, `ExecMainStatus=0`.
- OmniRoute live boundary: `127.0.0.1:20128`; unauthenticated `/v1/models=401`, authenticated `/v1/models=200`.
- Attention Watch: `33` eligible historical events, all from terminal `BLOCKED` runs and all older than the current stable closure.

## Authority Register

1. Current user request: diagnose DCC and Harness-wide operational collision/error risk.
2. `EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` is the common diagnosis authority.
3. DCC user-approved Design Spec is the feature authority.
4. User Decision & Attention Policy R2 is user-decision/attention authority.
5. Operator Turn Exit Guard design is GPT-turn completion classification authority.
6. Full Plan continuity contract is durable run/queue/recovery authority.
7. Multi-Provider Foundation requalification preserves Router/MPRF provider authority.
8. Full MCP / ToolEffectJournal code remains governed effect authority.
9. RuntimeMigrationTransaction and runtime release code remain runtime activation authority.
10. Verified current source/runtime state is implementation evidence, not permission to weaken the authorities above.

## Findings

### DCC-ORCH-F001 — BLOCKER — Implementation Job self-mutates its sealed executor runtime
Inherited and reconfirmed. Task 0 binds `runtime_code_root` to the implementation worktree, while Task 1 modifies that runtime. Direct reproduction produced `EXECUTOR_RUNTIME_SOURCE_DRIFT` before commit and `EXECUTOR_GENERATION_DRIFT` after commit.

**Correction:** bind execution to an exact immutable known-good runtime release; keep the implementation worktree as `project_root` only.

### DCC-ORCH-F002 — BLOCKER — Plan weakens the approved GateContinuationContract
Inherited and reconfirmed. Approved fields including `approved_base_head`, `required_evidence_classes`, `approval_coverage_ref`, `external_effect_policy`, and `runtime_migration_policy` are absent or renamed in the Plan.

**Correction:** implement the exact approved serialized schema or explicitly amend/reapprove the Spec.

### DCC-ORCH-F003 — MAJOR — No production builder path creates AUTO Gates
Current `build_operator_plan_job()` has no per-Gate continuation-contract input. The Plan describes opt-in AUTO but does not define the production builder interface that creates/seals it.

**Correction:** add a closed, backward-compatible `continuation_contracts_by_gate`-equivalent interface with strict known-Gate validation and authority sealing.

### DCC-ORCH-F004 — MAJOR — Source-lineage proof is incomplete
The Plan has commit-tree/branch CAS safety but does not fully implement approved-base ancestry and previous-receipt source lineage.

**Correction:** add closed lineage policies plus deterministic ancestry/previous-receipt proof and negative tests.

### DCC-ORCH-F005 — MAJOR — Wait taxonomy diverges from the approved Spec
The Plan introduces `AUTO_CONTINUATION_PENDING`; the approved Spec uses `OPERATOR_TASK_RECEIPT_PENDING` as the eligibility entry and `CONTINUATION_RECOVERY_PENDING` for recovery classification.

**Correction:** align Plan/runtime taxonomy to approved authority or amend/reapprove the Spec.

### DCC-ORCH-F006 — MAJOR — Continuation transaction dispositions are incomplete
The Plan omits durable `USER_DECISION_REQUIRED`, `DELEGATED_RUNTIME_MIGRATION`, and `ROLLED_BACK` dispositions required by the approved Spec.

**Correction:** persist and test every approved disposition with restart/idempotency behavior.

### DCC-ORCH-F007 — MAJOR — Validated code, closure, and publication HEADs are ambiguous
The Plan does not explicitly bind `validated_code_head`, docs-only `closure_head`, and `publication_head` with executable-surface diff proof.

**Correction:** bind all three identities and require no executable drift from validated code to publication.

### DCC-HW-F008 — MAJOR — GPT Operator Exit Guard is advisory, not an enforced turn boundary
`operator_exit_guard` is read-only and the production entry only returns an `operator_exit` assessment. Repo standards say the Operator MUST obey it, but no runtime component can mechanically prevent the ChatGPT/tool execution turn from ending. `operator_turn_budget` similarly has no production enforcement call site.

**Impact:** planning, document sealing, manual receipt preparation, and other Operator-owned work can still stop between commands even when the Guard would say `CONTINUE_EXECUTION`.

**Correction:** require a durable owner/checkpoint before any Operator yield and make the outer Operator workflow treat non-allow dispositions as a mandatory continuation/handoff contract, not advisory metadata.

### DCC-HW-F009 — MAJOR — Attention has no production user-delivery adapter
`AttentionOutbox.deliver()` exists, but no production runtime call site invokes it. `production_attention_watch.py` only discovers/prints eligible events.

**Impact:** Harness can persist and detect a stall yet never actually notify the user, matching the observed receipt-wait incident class.

**Correction:** add an outbound-only delivery adapter/service with durable delivery receipts. It must retain `control_authority=NONE`.

### DCC-HW-F010 — MAJOR — Attention lacks historical run supersession/backlog policy
Fresh watch returned `33` eligible events, all from old `BLOCKED` runs across 33 unique runs. Current suppression handles same-run semantic progress/terminal completion but not newer-run supersession/archival of historical failed attempts.

**Impact:** connecting a sender now can flood the user with obsolete incidents.

**Correction:** add durable superseded/archived notification disposition keyed to verified run lineage; preserve evidence, suppress obsolete delivery.

### DCC-HW-F011 — BLOCKER — Provider/resource waits have no autonomous recovery owner
The periodic reconciler returns `PRESERVE_WAIT` for all `WAIT_STATES`. Production `resume_wait()` calls exist only for GPT/operator receipt/manual-action paths. Provider and resource recovery tests manually call `resume_wait()`.

**Impact:** even after DCC fixes auto receipt waits, a provider becoming healthy again or resource pressure clearing can leave Full Plan indefinitely waiting for another Operator command. This violates the Harness-wide no-silent-stop/Full-Plan-owned continuation goal.

**Correction:** add a typed wait-recovery owner: MPRF/Router fact re-evaluation for `WAITING_PROVIDER`, resource probe re-evaluation for low-resource `WAITING_RESOURCE`; never auto-resume approval or migration waits.

### DCC-HW-F012 — MAJOR — DCC auto-attestation is not concretely bound to Full MCP effect evidence
The current Harness has `ToolEffectJournal` intent/receipt v2 and `effect_evidence_bridge` verification. The DCC Plan only accepts an optional `effect_reconciliation` fact and does not define its canonical source or a registered verifier that consumes journal evidence.

**Impact:** external/governed effects could be locally verified by Git state while their side-effect reconciliation remains unproven, creating retry/duplication risk.

**Correction:** either restrict DCC v1 to `external_effect_policy=NO_EXTERNAL_EFFECT`, or add an effect-journal verifier using canonical effect evidence and production-shaped crash/retry E2E.

### DCC-HW-F013 — MAJOR — Durable run evidence is coupled to cleanup-able worktrees
Jobs, state, receipts, migrations, attention, and proposed DCC transaction/attestation evidence live under `harness_root/_workspace`. Task 0 sets `harness_root` to the implementation worktree. The Plan has no retention/archive step before worktree cleanup, while the Spec requires historical evidence preservation.

**Impact:** later worktree cleanup can remove canonical execution/audit evidence or make global discovery impossible.

**Correction:** use a stable durable Harness state root independent of project worktrees, or define digest-verified archival/materialization before cleanup.

### DCC-HW-F014 — MAJOR — Transaction lock and canonical run-lock hierarchy is undefined
The Spec says the Full Plan run lock is the exclusive orchestration mutation lock. Task 5 adds a separate transaction-root lock, while Tasks 8/9 reuse the run lock, but no lock-order rule exists.

**Impact:** foreground DCC and reconciler can create lock inversion/deadlock or split ownership under crash/race pressure.

**Correction:** define one lock hierarchy and add explicit lock-inversion/concurrent-reconcile failure injection.

### DCC-HW-F015 — BLOCKER — Publication closes predecessor before final active-runtime qualification and lacks a legal rollback path
Task 14 performs runtime migration through `PREDECESSOR_CLOSED`, then Step 8 performs final fresh regression. `RuntimeMigrationTransaction.rollback()` is illegal after `PREDECESSOR_CLOSED`, and the Plan defines no reverse migration if Step 8 fails.

**Impact:** a defect discovered only under the active immutable runtime can leave the new runtime active without the planned legal rollback route.

**Correction:** execute critical active-runtime canary/qualification before predecessor closure, or predefine and test a successor-to-last-good reverse migration transaction. Close predecessor only after rollback-window qualification succeeds.

### DCC-HW-F016 — MAJOR — No live post-publication AUTO canary proves systemd/reconciler wiring
Task 12 uses isolated temporary repositories. Task 14 runs tests from the active runtime but does not register a real harmless AUTO Full Plan and prove systemd reconciliation after loss of the initiating Operator.

**Impact:** unit/E2E tests can pass while actual runtime-current/search-root/systemd/permission wiring fails.

**Correction:** before stable-baseline declaration, run a live bounded 3-Gate AUTO canary under the active immutable runtime, terminate the initiating foreground owner after Gate A, and prove v2 receipts plus systemd-driven completion with no chat action.

## Passed / Preserved Harness Domains

- Active Harness runtime is immutable and healthy.
- Provider Router/MPRF authority-focused regressions pass; no DCC implementation currently bypasses them.
- Full MCP effect journal/evidence bridge is present and its focused regressions pass.
- Runtime release activation validates active registered jobs through the provided `job_search_root`; the real activation API is not the weaker local helper path.
- Runtime migration authority negative-space regression passes.
- OmniRoute live loopback/authentication boundary passes.
- systemd reconciliation timer/service is healthy when evaluated with the correct user-bus environment.
- Current reconciler has no blocked active work and no nonterminal run exists at diagnosis time.
- GATE_BY_GATE, manual v1 receipt, explicit external-effect approval, and runtime-migration ownership are correctly preserved at the design-intent level.

## Harness-Wide Interaction Matrix

| Operational boundary | Result | Finding |
|---|---|---|
| GPT Operator -> durable owner | FAIL | F008, F011 |
| User approval -> Full Plan authority | PASS with DCC schema blocker | F002 |
| Full Plan -> DCC AUTO contract | FAIL | F003, F005, F006 |
| Source/Git -> attestation | FAIL | F004, F007 |
| Provider Router/MPRF -> continuation | FAIL on wait recovery ownership | F011 |
| Full MCP effect -> DCC attestation | FAIL | F012 |
| Reconciler -> DCC owner | design incomplete | F014 |
| Runtime migration/release -> rollback | FAIL | F015 |
| Attention -> user notification | FAIL | F009, F010 |
| Worktree lifecycle -> durable evidence | FAIL | F013 |
| Active runtime -> production AUTO proof | FAIL | F016 |
| Existing baseline regressions | PASS | none |

## Required Remediation Order

1. Fix immutable executor-runtime separation and restore exact approved DCC contract schema.
2. Define stable durable Harness state/evidence root before adding new DCC stores.
3. Add the concrete AUTO job-builder path and complete source/effect lineage bindings.
4. Normalize wait taxonomy and implement autonomous typed provider/resource wait recovery outside approval/migration waits.
5. Complete transaction dispositions and establish one canonical lock hierarchy.
6. Integrate canonical Full MCP effect reconciliation or explicitly prohibit external effects in DCC v1.
7. Make GPT Operator yield/exit contingent on durable owner evidence; wire Attention delivery plus historical supersession.
8. Define validated-code/closure/publication identity and pre-close rollback/canary protocol.
9. Add live active-runtime AUTO canary plus restart/systemd loss-of-Operator test.
10. Re-run Harness-wide focused suite, full regression, chaos/failure injection, cross-document RTM, adversarial pass, and EDP closure.

## Closure Metrics

```text
BLOCKER_COUNT=4
UNRESOLVED_MAJOR_COUNT=12
UNRESOLVED_MINOR_COUNT=0
DCC_REQUIREMENT_ID_COVERAGE=20/20
DCC_TRACEABILITY_STATUS=MAPPED_BY_ID_BUT_IMPLEMENTATION_FIDELITY_FAIL
HARNESS_WIDE_DOMAIN_EVIDENCE_COVERAGE=100%
NEGATIVE_SPACE_OPEN_MATERIAL_COUNT=9
CROSS_DOCUMENT_MATERIAL_CONFLICT_COUNT=5
BROKEN_REFERENCE_COUNT=0
ADVERSARIAL_NEW_BLOCKER_MAJOR=9
PASS_CHALLENGE_OPEN_COUNT=16
SOURCE_AUTHORITY_STATUS=VALID_PLAN_AND_HARNESS_REMEDIATION_REQUIRED
REGRESSION_REDIAGNOSIS_STATUS=BASELINE_PASS_OPERATIONAL_CONTRACT_FAIL
MATERIAL_DEFECT_SEARCH=EXHAUSTED_FOR_AVAILABLE_EVIDENCE
EDP_DECISION=NOT_ALL_PASS
```

## Disposition

Do not start DCC implementation from the current Plan. Do not treat the healthy `1887`-test baseline as evidence that the operational design is safe. First revise the DCC Plan and the Harness-wide operational contracts identified above; preserve the approved authority boundaries; then perform the same Harness-wide EDP re-diagnosis. Implementation execution is eligible only after fresh `EDP_DECISION=ALL_PASS`.
