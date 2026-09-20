# Full Plan Continuity + Design Skill Root-Cause Remediation Design

Status: SPEC-REVIEW-PENDING
Protocol: EXHAUSTIVE_DIAGNOSIS_PROTOCOL / EDP-1.0
Incident: FINAL-OP-20260920-R2 / TASK-014 runtime activation migration
Scope: design-time prevention + runtime continuity + user attention + interrupted final operationalization resume

## 1. Goal

Remove the root cause of the 2026-09-20 Full Plan stop, not only its symptoms.
The change must make self-replacing operations such as runtime/service/supervisor/worktree migration continuity-safe by construction, detect any orphaned terminal transition, and make the design skill reject plans that omit those guarantees.

Final success requires diagnosis -> remediation -> regression -> EDP re-diagnosis with Universal PASS Gate ALL PASS.

## 2. Verified Incident Facts

- `FINAL-OP-20260920-R2` completed TASK-003 through TASK-013.
- TASK-014 entered `WAITING_RESOURCE / OPERATOR_TASK_RECEIPT_PENDING` after pre-activation work.
- Repository regression completed: 1,807 tests PASS, 15 skipped.
- `runtime-current` was successfully retargeted to immutable release `424c1c255cced0ca53e7012a780b54281500fc3d`.
- R2 was explicitly terminalized as `CANCELLED / RUNTIME_ACTIVATION_MIGRATION`.
- No TASK-014 PASS receipt exists.
- No successor R3 durable Full Plan job exists.
- Runtime activation evidence was nevertheless committed through `208afea`.
- Periodic reconciler publishes terminal attention for BLOCKED/FAILED, but not CANCELLED.
- Existing successor protection covers missing successor queue entries inside a live Full Plan, not cross-runtime self-replacement after terminalization.

## 3. EDP Pre-Remediation Findings

| ID | Severity | Finding | Current Evidence |
|---|---|---|---|
| EDP-CONT-001 | MAJOR | Design skill has no mandatory Stateful Continuity Review for self-replacing operations. | `.agents/skills/harness-design/SKILL.md` lacks owner/successor/self-reference checks. |
| EDP-CONT-002 | MAJOR | Runtime activation requires zero nonterminal jobs, but the executing Full Plan is itself nonterminal; no migration transaction resolves that self-reference safely. | `runtime_release._active_registered_jobs()` + `activate_runtime_release()`. |
| EDP-CONT-003 | MAJOR | Predecessor can become terminal before a successor is durably registered. | R2 `CANCELLED / RUNTIME_ACTIVATION_MIGRATION`, no R3. |
| EDP-CONT-004 | MAJOR | CANCELLED terminal states are skipped by the periodic reconciler without mandatory Attention publication. | `production_full_plan_boot.reconcile_job()` publishes only BLOCKED/FAILED terminal attention. |
| EDP-CONT-005 | MAJOR | Existing missing-successor checks are intra-run only; cross-runtime successor ownership is not represented. | `test_missing_successor_is_explicit_block_with_attention` covers queue successor, not runtime migration. |

Pre-remediation decision: **FAIL — REMEDIATION_REQUIRED**.

## 4. Rejected Narrow Fixes

### Option A — Alert on every CANCELLED only
Rejected as insufficient. It improves notification but does not prevent ownership loss.

### Option B — Let runtime activation ignore the current active job
Rejected as unsafe. A generic exemption can retarget runtime while an active worker or unrelated Full Plan still depends on the old runtime.

### Selected Option C — Durable Migration Transaction + Design-Time Continuity Audit
A migration is represented as a digest-bound transaction that reserves the successor before predecessor terminalization. Runtime activation may exempt only the exact migration participant proven quiescent by that transaction. The reconciler can recover or alert from the transaction after process/session loss.

## 5. Design-Skill Root-Cause Remediation

Modify `.agents/skills/harness-design/SKILL.md` and `docs/harness/skill-design-guide.md` so any design containing runtime replacement, service restart, supervisor replacement, worktree/repository replacement, deployment activation, migration, scheduler/reconciler replacement, state-store move, or deliberate active-job termination must perform a **Stateful Continuity Review**.

The review must answer, with explicit artifacts or state transitions:

1. Who owns durable continuation before the transition?
2. Does that owner terminate, become unreachable, or change runtime/source during the transition?
3. What exact successor identity is reserved before ownership can be relinquished?
4. Can there be a period where continuation-owner count is zero?
5. Does any safety precondition include the currently executing owner itself?
6. How is the self-reference resolved without weakening the safety guard?
7. What survives chat/process/server interruption at every transition boundary?
8. Who detects successor creation/activation failure?
9. What Attention event is emitted if the goal is incomplete after a terminal transition?
10. What rollback path restores a durable owner if activation cannot complete?

The skill must reject a design as **NOT READY** if any applicable answer is missing.

### Mandatory Continuity Invariants

- `CI-CONT-01`: Until approved work reaches successful completion, at least one durable continuation owner or sealed recovery transaction exists.
- `CI-CONT-02`: A predecessor cannot be terminalized for migration until successor identity and recovery material are durably sealed.
- `CI-CONT-03`: Any non-COMPLETED terminal transition must bind either a verified successor or a durable user-attention obligation.
- `CI-CONT-04`: Zero-active-owner and similar preconditions require a self-reference/paradox audit.
- `CI-CONT-05`: Every self-replacement design defines Before -> Quiesce -> Transition -> Successor Verify -> Predecessor Close -> Rollback.

## 6. Durable Runtime Migration Transaction

Create a dedicated, authority-bounded migration transaction rather than encoding migration by a free-form CANCEL reason.

Proposed module: `runtime/orchestrator/runtime_migration_handoff.py`.

Transaction fields:
- migration_id
- project_id / predecessor_run_id / successor_run_id
- current_gate / resume_gate
- approved plan/spec digests and authority-core digest
- predecessor state SHA and source HEAD
- target runtime release HEAD and manifest digest
- successor job specification digest
- created_at / phase / transaction_sha256

Allowed phases are `PREPARED`, `PREDECESSOR_QUIESCED`, `RUNTIME_ACTIVATED`, `SUCCESSOR_REGISTERED`, `SUCCESSOR_VERIFIED`, `PREDECESSOR_CLOSED`, `ROLLED_BACK`, `BLOCKED`.

The transaction has recovery authority only over the exact pre-approved migration identities and cannot approve scope, choose providers, execute tool effects, or declare completion.

### Safe Transition Order

1. Build and verify target immutable runtime while predecessor remains durable.
2. Seal successor job specification and migration transaction.
3. Quiesce predecessor to an explicit wait state; no worker/effect may remain active.
4. Activation guard verifies all other nonterminal jobs are absent and the only exemption is the exact quiesced predecessor bound to the transaction.
5. Activate `runtime-current`.
6. Register the sealed successor job from the new runtime and verify its durable state.
7. Only after successor verification, close predecessor as `MIGRATED_TO_SUCCESSOR`.
8. If any step fails, transaction remains recoverable and Attention is emitted; predecessor is never silently abandoned.

## 7. Terminal Orphan Attention

Extend terminal reconciliation from “terminal state exists” to “terminal disposition is valid”.

Rules:
- `COMPLETED` remains silent when completion evidence is valid.
- `BLOCKED` and `FAILED` retain existing durable Attention behavior.
- `CANCELLED` must not be silently skipped unless it is explicitly user-requested/superseded or is bound to a verified migration successor.
- A migration predecessor with missing/unverified successor produces `RUNTIME_MIGRATION_ORPHANED`.
- An incomplete durable migration transaction produces `RUNTIME_MIGRATION_RECOVERY_REQUIRED`.
- Attention publication remains outbound-only; it cannot resume, approve, reroute, or mutate execution scope.

The periodic reconciler must re-emit idempotently if a direct cancellation path failed before Attention publication.

## 8. Crash / Restart Recovery

Recovery must be deterministic at these crash points:

- after transaction PREPARED, before predecessor quiesce;
- after predecessor quiesce, before runtime activation;
- after runtime activation, before successor registration;
- after successor registration, before successor verification;
- after successor verification, before predecessor close;
- after predecessor close, before final receipt/evidence publication.

For each point, restart/reconcile must either continue the same transaction idempotently or stop in `BLOCKED` with durable Attention. It must never create an unbound successor, duplicate a worker effect, or infer new approval.

## 9. Skill TDD / Pressure Tests

The Skill modification itself follows RED -> GREEN -> REFACTOR.

RED scenario: “An active Full Plan must retarget its own runtime, but activation requires active-job count zero.” The current design skill is expected to omit the self-reference/successor reservation requirement; capture that as baseline failure evidence.

GREEN scenario: with the modified skill, the same request must identify the paradox and require the migration transaction, successor reservation, orphan attention, and rollback before declaring the design ready.

Adversarial variants: systemd restart, supervisor binary replacement, worktree deletion, server reboot, scheduler replacement, and state-store relocation.

## 10. Authority Boundaries

Unchanged authorities:
- Full Plan remains task/gate/continuation authority.
- Provider Router remains provider/model selection authority.
- Tool Authorization + SingleToolBroker + EffectJournal remain effect authority.
- Completion Authority remains completion authority.
- Attention remains outbound notification only.

New migration logic receives no independent approval authority. It may only replay or complete an already-sealed migration transaction whose plan/spec/authority digests match the predecessor approval.

## 11. Interrupted Final Operationalization Resume

After the remediation itself passes focused and full regression:

1. Reconstruct the interrupted TASK-014 state from R2 evidence and committed activation artifacts.
2. Create a successor run using the new migration handoff contract, bound to the same approved final-operationalization scope plus this explicitly approved remediation addendum.
3. Mark TASK-014 complete only after activation evidence and successor continuity are both verified.
4. Resume TASK-015 final EDP re-diagnosis.
5. Do not fabricate the missing R2 TASK-014 receipt; preserve R2 as historical incident evidence.

## 12. EDP Re-Diagnosis Domains

Applicable evidence domains must include:
- ED-01 Design Skill Continuity Audit
- ED-02 Self-Reference / zero-owner paradox detection
- ED-03 Migration transaction integrity
- ED-04 Quiescence and activation guard
- ED-05 Successor registration and verification
- ED-06 Crash/restart recovery
- ED-07 Terminal orphan attention
- ED-08 Existing Full Plan continuity regression
- ED-09 Provider/Tool/Completion authority non-expansion
- ED-10 Runtime-current and reconciler operational convergence
- ED-11 Cross-document/governance consistency
- ED-12 Interrupted TASK-014/TASK-015 closure continuity

## 13. Expected Change Surface

Design/process layer:
- Modify `.agents/skills/harness-design/SKILL.md`.
- Modify `docs/harness/skill-design-guide.md`.
- Modify `.agents/skills/new-project-orchestrator/SKILL.md` only to require the continuity audit when its architecture/implementation planner emits a self-replacing stateful design; it must not duplicate the whole standard.
- Add deterministic skill-contract/pressure fixtures under `tests/`.

Runtime layer:
- Create `runtime/orchestrator/runtime_migration_handoff.py`.
- Modify `runtime/orchestrator/runtime_release.py` for transaction-bound activation exemption only.
- Modify `runtime/orchestrator/production_full_plan_runner.py` only as needed for explicit quiesce/migrated disposition.
- Modify `runtime/orchestrator/production_full_plan_boot.py` for migration recovery and terminal-orphan detection.
- Extend continuity/runtime-release/attention tests.

Governance/evidence layer:
- Add pre-remediation diagnosis, post-remediation re-diagnosis, failure-injection evidence, and final closure evidence under `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/`.
- Update current-state projection only after measured PASS.

## 14. Negative-Space Requirements

The remediation must prove all of the following remain false:
- migration logic cannot approve a new scope;
- migration logic cannot select a provider/model;
- migration logic cannot launch arbitrary tool effects;
- Attention cannot resume a job;
- a generic active-job bypass cannot be used outside a sealed migration transaction;
- a successor cannot change plan/spec/authority digests;
- a predecessor cannot claim COMPLETED because migration succeeded;
- historical R2 evidence cannot be rewritten into a synthetic PASS receipt;
- a missing successor cannot be classified as a successful migration;
- a design containing self-replacement cannot pass Skill validation without continuity answers.

## 15. Final Universal PASS Gate

Final ALL PASS is permitted only when measured evidence shows:

`BLOCKER_COUNT=0`
`UNRESOLVED_MAJOR_COUNT=0`
`MUST_REQUIREMENT_COVERAGE=100%`
`MUST_TRACEABILITY_COVERAGE=100%`
`DOMAIN_EVIDENCE_COVERAGE=100%`
`NEGATIVE_SPACE_OPEN_MATERIAL_COUNT=0`
`CROSS_DOCUMENT_CONFLICT_COUNT=0`
`BROKEN_REFERENCE_COUNT=0`
`UNRESOLVED_MATERIAL_TBD_COUNT=0`
`UNRESOLVED_MATERIAL_OPEN_QUESTION_COUNT=0`
`ADVERSARIAL_NEW_BLOCKER_MAJOR=0`
`PASS_CHALLENGE_OPEN_COUNT=0`
`SOURCE_AUTHORITY_STATUS=VALID`
`REGRESSION_REDIAGNOSIS_STATUS=PASS`
`MATERIAL_DEFECT_SEARCH=EXHAUSTED_FOR_AVAILABLE_EVIDENCE`
