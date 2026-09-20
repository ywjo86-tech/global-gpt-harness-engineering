# Full Plan Durable Continuation Controller — Design Spec

**Date:** 2026-09-20
**Status:** USER-DIRECTION-APPROVED / SPEC-REVIEW-PENDING
**Stable BASE:** `a40626c31353f90c0d4c9e677d3886ea5ccce393`
**Diagnosis:** `docs/history/upgrades/2026-09-20-DURABLE-CONTINUATION-CONTROLLER/EDP_PRE_DESIGN_GOAL_DIAGNOSIS.md`
**Protocol:** `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` / EDP-1.0

## 1. Purpose

Remove the structural dependency on an active ChatGPT response turn for continuation of work that is already authorized by an approved Full Plan. After a Gate has been executed and objectively verified within the sealed contract, the Harness must be able to persist completion evidence, perform an explicitly permitted local commit, and continue to the next eligible Full Plan Gate without requiring GPT to issue another chat-driven receipt/resume command.

This feature is continuity infrastructure. It is **not** an approval engine, an alternative orchestrator, a provider router, an effect backend, or a runtime migration owner.

## 2. Problem Statement

The current GPT Operator Plan path is durable in state but still contains a chat-turn dependency:

```text
approved Full Plan
  -> GPT/operator performs Gate work
  -> verification succeeds
  -> operator must create PASS receipt
  -> operator must resume WAITING_RESOURCE
  -> Full Plan advances
```

If the chat execution turn ends between verification and receipt/resume, the durable Full Plan safely stops at `OPERATOR_TASK_RECEIPT_PENDING`, but no process owns the remaining mechanical continuation. The state is safe yet operationally silent until a later operator turn arrives.

The desired behavior is:

```text
approved FULL_PLAN contract
  -> execute within sealed bounds
  -> deterministic verification
  -> durable attestation
  -> permitted local commit if required
  -> mechanical receipt sealing
  -> canonical Full Plan transition
  -> next eligible Gate
```

with no additional user decision unless a genuine decision boundary is reached.

## 3. Authority Model

### 3.1 Hard authority invariants

- **DCC-AUTH-001:** Full Plan remains the sole owner of Task/Gate/fan-in/next-state transitions.
- **DCC-AUTH-002:** The Durable Continuation Controller (DCC) is an internal Full Plan execution/recovery mechanism. It has no independent project-planning, approval, next-Gate-selection, provider-selection, runtime-migration, or arbitrary effect authority.
- **DCC-AUTH-003:** GPT remains Operator for planning, design, execution approval, contract revision, and exception handling.
- **DCC-AUTH-004:** User Decision Policy R2 remains authoritative. Initial risky execution, material contract revision, risk-envelope escalation, and ambiguous dangerous effect require a user decision.
- **DCC-AUTH-005:** `GATE_BY_GATE` next-Gate approval semantics remain unchanged. DCC automatic cross-Gate continuation is FULL_PLAN-only.
- **DCC-AUTH-006:** Router and MPRF authority remain unchanged.
- **DCC-AUTH-007:** Execution Backend / Full MCP remains governed effect authority. DCC must never become an arbitrary command/effect bridge.
- **DCC-AUTH-008:** Runtime activation remains owned by `RuntimeMigrationTransaction` and its successor handoff.
- **DCC-AUTH-009:** Attention remains outbound-only and `control_authority=NONE`.

### 3.2 Continuation is not approval

DCC may answer only:

> Does this observed result satisfy the already-sealed continuation contract for this exact Gate and source lineage?

DCC may not answer:

> Is this new action acceptable, should scope expand, or should a new risk be approved?

Any question of the second type becomes `USER_DECISION_REQUIRED`, `PLAN_REVISION_REQUIRED`, or another existing fail-closed state.

## 4. Canonical Requirements

The following requirements are the normative traceability contract for this Spec. Later sections elaborate them but do not weaken them.

| ID | Normative requirement |
|---|---|
| DCC-MUST-001 | Full Plan remains sole continuation/next-state authority; DCC cannot independently choose or approve work. |
| DCC-MUST-002 | Automatic continuation is opt-in and only valid for `FULL_PLAN` Gates sealed as `AUTO_WITHIN_APPROVED_CONTRACT`. |
| DCC-MUST-003 | Legacy or contract-less jobs default to `MANUAL_OPERATOR`; absence never implies automatic authority. |
| DCC-MUST-004 | Auto-eligible Gates seal closed write/forbidden scope, verification, commit, risk, approval-coverage, and continuation rules. |
| DCC-MUST-005 | Dynamic execution facts never mutate immutable authority; they are digest-bound evidence derived from it. |
| DCC-MUST-006 | Automatic completion requires a deterministic `VerifiedGateAttestation`; free-form test strings are insufficient. |
| DCC-MUST-007 | Verifier has no approval, next-state, provider, migration, or arbitrary effect authority. |
| DCC-MUST-008 | A durable crash-safe continuation transaction spans execution observation, verification, commit, receipt, and advancement. |
| DCC-MUST-009 | Verification binds base HEAD, verified tree, changed-path set, evidence, and resulting commit; commit tree equals verified tree. |
| DCC-MUST-010 | Source evolution uses sealed lineage policy plus receipt/transaction evidence rather than pre-invented future commit hashes. |
| DCC-MUST-011 | Existing Full Plan top-level states remain compatible while typed wait reason/substate distinguishes unrelated wait causes. |
| DCC-MUST-012 | Only an auto-eligible operator-receipt wait may be mechanically recovered; other waits cannot be aliased to it. |
| DCC-MUST-013 | DCC and reconciler share canonical run locking plus lease/epoch/fencing/idempotency; dual ownership is prohibited. |
| DCC-MUST-014 | Runtime migration is delegated exclusively to the existing migration/successor transaction flow. |
| DCC-MUST-015 | Approval, decision, scope/authority drift, risk escalation, ambiguous effect, and forbidden-effect boundaries remain hard stops. |
| DCC-MUST-016 | Push, destructive Git, system, network/external, package, credential, and equivalent effects retain separate explicit authority. |
| DCC-MUST-017 | Dangerous retry/effect recovery requires existing approval coverage plus effect reconciliation and cannot bypass Full MCP semantics. |
| DCC-MUST-018 | Attention is notification fallback only and never controls continuation. |
| DCC-MUST-019 | New schemas are additive/versioned/fail-closed; historical jobs/states/receipts remain compatible and are not reinterpreted as AUTO. |
| DCC-MUST-020 | Final qualification includes crash/failure injection, duplicate ownership pressure, drift, reboot, migration, mode, approval, effect, and legacy compatibility tests. |

## 5. Operating Modes

### 5.1 `MANUAL_OPERATOR`

Default for all existing jobs and all Gates without the new contract. Current `OperatorPlanReceiptStore` behavior remains valid: an operator-supplied verified receipt is required.

### 5.2 `AUTO_WITHIN_APPROVED_CONTRACT`

Available only when all of the following are true:

1. run mode is `FULL_PLAN`;
2. the Gate contains a sealed `GateContinuationContract`;
3. approval lineage is valid and covers the operation/risk classes;
4. current source lineage matches the sealed preconditions;
5. observed changed paths are inside the allowed write set and outside forbidden scope;
6. all required verifier checks produce a valid attestation;
7. no user decision, migration exception, external-effect exception, or ambiguous effect is present.

Failure of any condition does not downgrade to best effort. It fails closed to the appropriate existing wait/block/decision path.

## 6. `GateContinuationContract`

A new machine-readable contract is sealed into the immutable Full Plan authority core.

Minimum schema:

```text
schema_version
gate_id
continuation_policy
approved_base_head
source_lineage_policy
allowed_write_paths
forbidden_paths
required_verifiers
required_evidence_classes
commit_policy
risk_classes
approval_coverage_ref
approval_coverage_digest
external_effect_policy
runtime_migration_policy
```

### 6.1 Contract rules

- Unknown fields fail closed.
- Missing contract means `MANUAL_OPERATOR`.
- `allowed_write_paths` is closed, not advisory.
- `forbidden_paths` always wins over allowed scope.
- verifier requirements are IDs from a closed verifier registry, never arbitrary shell text.
- `commit_policy` is one of `NO_COMMIT`, `LOCAL_COMMIT_ALLOWED`, or another future explicitly versioned value.
- generic DCC never gains a `PUSH_ALLOWED` value. Push remains a separately authorized external effect.
- contract is part of `authority_core_sha256` and cannot be changed through runtime bindings.

## 7. Source Lineage Model

Future commit hashes cannot be known when an immutable plan is initially sealed. Therefore source authority is split into immutable policy and dynamic evidence.

### 7.1 Immutable policy

The Gate contract binds:

- `approved_base_head`;
- permitted ancestry relation;
- allowed changed paths;
- forbidden paths;
- whether the Gate consumes the previous Gate's verified receipt head;
- whether a local commit is expected.

### 7.2 Dynamic evidence

Each transaction records:

- actual pre-execution HEAD;
- base/parent receipt source head where applicable;
- observed changed-path digest;
- verified Git tree SHA;
- resulting commit SHA and tree SHA if a commit occurs;
- ancestry proof result.

A source transition is valid only when the dynamic facts satisfy the immutable lineage policy. Runtime evidence records a fact; it never expands the policy.

## 8. `VerifiedGateAttestation`

Automatic receipt sealing requires an independent deterministic attestation object.

Minimum schema:

```text
schema_version
project_id
run_id
gate_id
authority_core_sha256
continuation_contract_sha256
base_head
verified_tree_sha
changed_paths_sha256
verifier_results[]
evidence_refs[]
risk_coverage_digest
approval_coverage_digest
verdict
attestation_sha256
```

### 8.1 Verifier restrictions

- verifier is read-only with respect to orchestration state and user approval;
- verifier cannot call `create_pass_receipt`, `resume_operator_plan_after_receipt`, provider selection, runtime activation, or arbitrary tool effects;
- required verifier IDs come from a closed registry;
- verifier command/environment identity must be deterministic and version-bound;
- free-form `tests=["PASS"]` is insufficient for auto continuation;
- `verdict=PASS` is valid only if every mandatory verifier result and binding check is PASS.

The attestation proves conformance to existing authority. It does not create new authority.

### 8.2 Eligibility evaluator separation

A pure `ContinuationEligibilityEvaluator` classifies whether the sealed authority/evidence permits mechanical continuation. It has `control_authority=NONE` and cannot dispatch, resume, commit, create receipts, select providers, or activate runtime. The Full Plan-owned DCC consumes this classification and may invoke only the canonical Full Plan transition/recovery APIs allowed by the sealed contract. This preserves User Decision Policy R2's evaluator-only continuation-policy boundary.

### 8.3 Receipt schema compatibility

Historical `orchestration.operator-plan-receipt.v1` receipts remain byte-unchanged and are treated as the existing manual/operator evidence form. DCC **must not mint v1 receipts automatically**.

Automatic continuation introduces `orchestration.operator-plan-receipt.v2` with at least:

```text
schema_version
receipt_mode = AUTO_ATTESTED
project_id
run_id
gate_id
plan_sha256
spec_sha256
authority_core_sha256
continuation_contract_sha256
attestation_sha256
branch
source_head
source_tree_sha
status = PASS
created_at
receipt_sha256
```

The receipt store/consumer may read both schemas, but v2 is accepted only when the referenced immutable attestation exists and independently validates against the same job/Gate/authority/source bindings. No v1 receipt is migrated or rewritten to v2. Unknown receipt versions fail closed.

## 9. `GateContinuationTransaction`

Each auto-eligible Gate has one durable transaction keyed by project/run/gate/authority identity.

Canonical phases:

```text
PREPARED
EXECUTION_OBSERVED
VERIFIED
COMMIT_INTENT
COMMITTED
RECEIPT_SEALED
ADVANCED
```

Terminal failure dispositions include:

```text
BLOCKED
USER_DECISION_REQUIRED
DELEGATED_RUNTIME_MIGRATION
ROLLED_BACK
```

### 9.1 Phase invariants

- transitions are monotonic and digest chained;
- identity/authority fields are immutable after PREPARED;
- every phase write is atomic + fsync and retains previous-good recovery where applicable;
- a crash cannot cause phase regression;
- phase recovery revalidates actual Git/orchestration state before advancing;
- a completed external/local effect is never blindly re-executed because a later bookkeeping phase is missing.

### 9.2 Crash recovery examples

**Crash after verification, before commit**
Reload `VERIFIED`, recompute workspace/tree bindings, then continue only if identical.

**Crash after commit, before receipt**
Reload `COMMITTED`, verify commit/tree/evidence binding, seal receipt without rerunning the Gate effect.

**Crash after receipt, before Full Plan advance**
Reload `RECEIPT_SEALED`, verify canonical receipt and Full Plan state, then invoke the idempotent canonical transition once.

## 10. Git Verification and Commit Semantics

### 10.1 TOCTOU protection

Before verifier PASS:

- compute base HEAD;
- compute changed-path set and digest;
- construct/identify the exact candidate tree;
- run required verification against that candidate state;
- seal `verified_tree_sha`.

Immediately before commit:

```text
current_candidate_tree_sha == verified_tree_sha
current_changed_paths_digest == attested_changed_paths_digest
```

must both hold.

If not, DCC fails closed and re-verification is required.

### 10.2 Commit policy

`LOCAL_COMMIT_ALLOWED` permits only a bounded local commit inside the approved repository/branch/write scope. It does not imply push, merge, destructive Git, branch deletion, tag publication, release publication, or any external effect.

Commit messages must be deterministic or policy-bounded and recorded in the transaction. Resulting commit tree must equal the verified tree.

## 11. Wait Semantics

The existing top-level Full Plan state model is preserved for compatibility. DCC does not add a parallel state machine.

`WAITING_RESOURCE` gains/uses a typed reason such as:

```text
LOW_RESOURCE_BACKPRESSURE
OPERATOR_TASK_RECEIPT_PENDING
RUNTIME_MIGRATION_QUIESCED
CONTINUATION_RECOVERY_PENDING
```

Only `OPERATOR_TASK_RECEIPT_PENDING` with a valid auto contract and eligible transaction may enter DCC mechanical recovery.

The following can never be treated as that condition:

- `WAITING_APPROVAL`;
- `WAITING_PROVIDER`;
- low-resource wait;
- runtime migration quiescence;
- artifact-contract failure;
- ambiguous dangerous effect;
- plan/authority/source drift.

## 12. Ownership, Locking, and Reconciler Integration

DCC does not run a second competing scheduler.

- canonical Full Plan run lock remains the exclusive mutation lock;
- lease/epoch/fencing/idempotency semantics are reused;
- periodic reconciler detects eligible continuation recovery but must enter the same single-owner path;
- two processes observing the same pending transaction must not both advance it;
- stale owner epochs are fenced before effect/commit/receipt mutation;
- DCC recovery is idempotent under duplicate reconciliation.

The preferred integration is an internal Full Plan continuation service invoked by the production runner/reconciler, not a separately authoritative daemon.

## 13. User Decision and Effect Boundaries

DCC must stop for:

- first execution lacking valid approval;
- requirement/scope/constraint/success/deliverable/authority revision;
- risk class outside approval coverage;
- dangerous effect with missing/ambiguous reconciliation;
- unapproved changed path;
- source/authority digest mismatch;
- GATE_BY_GATE next-Gate transition;
- external/system/package/credential effect requiring separate approval.

DCC may not turn a technical success into an implicit approval for any of these cases.

## 14. Runtime Migration Boundary

Runtime-changing work is explicitly excluded from generic DCC commit/advance handling.

When a Gate requires runtime activation:

1. DCC/Full Plan classifies the next action as `DELEGATED_RUNTIME_MIGRATION`;
2. existing `RuntimeMigrationTransaction` creates and binds the successor;
3. predecessor quiescence, runtime activation, successor registration/verification, and predecessor closure follow the existing migration state machine;
4. the successor resumes the Gate/next Gate under the new runtime;
5. DCC may continue only after the migration transaction reaches a valid successor state.

DCC never writes `runtime-current` directly.

## 15. Governed Effect Boundary

DCC itself owns no arbitrary effect execution.

- governed file/API/system effects continue through existing Execution Backend / Full MCP / bounded Manual Action paths;
- dangerous retries obey approval coverage + effect reconciliation;
- ambiguous effect remains a user-decision boundary;
- DCC transaction may reference EffectJournal/effect evidence but must not replace it;
- local Git commit is handled only by the explicit bounded `commit_policy` described above.

## 16. Attention and Operator Exit

Attention remains a safety net, not the continuation engine.

Normal auto-eligible receipt wait should be consumed by DCC before it becomes a long-lived stall. If DCC cannot advance because of an error, inconsistent evidence, lock conflict, unrecoverable crash state, or prolonged lack of semantic progress, the existing attention pipeline persists and eventually surfaces the incident according to User Decision Policy R2.

`WAITING_APPROVAL` / genuine decision events remain immediately eligible for user delivery.

Operator Exit Guard must recognize that an auto-eligible continuation transaction with pending work is not successful turn completion. It may permit the chat turn to end only when durable autonomous ownership is proven or the run is in an explicit legitimate wait/terminal state.

## 17. Backward Compatibility

- existing job schema remains readable;
- no `GateContinuationContract` => manual behavior;
- historical receipt JSON is not rewritten;
- historical state/migration evidence remains immutable;
- new transaction/attestation schemas are additive and versioned;
- unknown schema versions fail closed;
- current `GATE_BY_GATE`, Manual Action, Router, MPRF, Full MCP, runtime migration, Attention, and Operator Exit negative-space contracts remain regression surfaces.

No migration may reinterpret an existing historical job as auto-authorized.

## 18. Expected Implementation Surfaces

The implementation plan may refine file names, but the intended boundaries are:

### New modules

- `runtime/orchestrator/gate_continuation_contract.py`
- `runtime/orchestrator/verified_gate_attestation.py`
- `runtime/orchestrator/gate_continuation_transaction.py`
- `runtime/orchestrator/durable_continuation.py`

### Controlled modifications

- `runtime/orchestrator/operator_plan_execution.py`
- `runtime/orchestrator/production_run_authority.py`
- `runtime/orchestrator/production_full_plan_runner.py`
- `runtime/orchestrator/production_full_plan_boot.py`
- `runtime/orchestrator/operator_exit_guard.py`
- attention/user-interaction modules only where typed continuation/stall classification requires it

### Protected negative-space surfaces

- Router/MPRF selection ownership;
- Full MCP effect ownership;
- `RuntimeMigrationTransaction` authority;
- GATE_BY_GATE next-Gate approval;
- explicit external/dangerous action approval policy.

## 19. Required Test Strategy

### L1 — Contract/schema

- closed GateContinuationContract schema;
- unknown field/version rejection;
- MANUAL default for legacy jobs;
- contract included in `authority_core_sha256`;
- runtime bindings cannot mutate continuation authority.

### L2 — Attestation/verifier

- forged/free-form PASS evidence rejected;
- missing verifier rejected;
- changed-path mismatch rejected;
- approval/risk digest mismatch rejected;
- verifier negative-space cannot approve/resume/select provider/migrate runtime.

### L3 — Transaction/recovery

Inject crash at every boundary:

- PREPARED -> execution;
- after execution observation;
- after VERIFIED;
- after COMMIT_INTENT;
- after actual commit before COMMITTED persistence;
- after COMMITTED before receipt;
- after receipt before advance;
- after advance before final transaction projection.

Each recovery must be idempotent and must not duplicate effects/commits/Gate completion.

### L4 — Ownership/concurrency

- reconciler and foreground controller race;
- duplicate timer wakeup;
- stale epoch owner;
- server/process restart;
- state previous-good recovery;
- no double receipt and no double next-Gate enqueue.

### L5 — Boundary/adversarial

- GATE_BY_GATE never crosses Gate automatically;
- WAITING_APPROVAL never auto-resumes;
- low resource is not receipt wait;
- migration quiescence is not receipt wait;
- plan/scope/authority/source drift stops;
- unapproved file change stops;
- push/system/external/package/credential attempt stops;
- dangerous ambiguous effect stops;
- runtime migration uses successor transaction only.

### L6 — Production/full regression

- representative 3+ Gate FULL_PLAN continues with the initiating chat/operator absent after Gate A verification;
- commit-before-receipt crash recovers without Gate re-execution;
- systemd reconciler recovers a pending auto continuation after restart;
- legacy MANUAL_OPERATOR job preserves current behavior;
- current continuity/authority/migration/attention focused suites remain green;
- full repository regression, compileall, diff-check, clean-tree checks pass.

## 20. Requirements Traceability Matrix

| Requirement | Design representation | Required proof |
|---|---|---|
| DCC-MUST-001 | §3 authority model, §12 ownership | authority negative-space; only canonical Full Plan transition API advances state |
| DCC-MUST-002 | §5 operating modes | FULL_PLAN auto-positive + GATE_BY_GATE auto-negative tests |
| DCC-MUST-003 | §5 manual default, §17 compatibility | legacy job fixture remains MANUAL_OPERATOR |
| DCC-MUST-004 | §6 GateContinuationContract | closed-schema/write-scope/risk/verification contract tests |
| DCC-MUST-005 | §6 immutable contract, §7 dynamic evidence | authority digest tamper and runtime-binding expansion rejection |
| DCC-MUST-006 | §8 VerifiedGateAttestation | free-form/forged receipt rejection |
| DCC-MUST-007 | §8 verifier restrictions | verifier import/call negative-space tests |
| DCC-MUST-008 | §9 GateContinuationTransaction | crash injection at every phase |
| DCC-MUST-009 | §7 source lineage, §10 Git TOCTOU | changed-path/tree equality and race tests |
| DCC-MUST-010 | §7 immutable policy + dynamic lineage | ancestry/previous-receipt chain tests |
| DCC-MUST-011 | §11 wait semantics | legacy state compatibility + typed reason tests |
| DCC-MUST-012 | §11 auto-recovery eligibility | wait-cause matrix proves only receipt wait is eligible |
| DCC-MUST-013 | §12 run lock/fencing | concurrent controller/reconciler and stale epoch tests |
| DCC-MUST-014 | §14 runtime migration boundary | migration delegation/successor tests; no direct runtime-link call |
| DCC-MUST-015 | §13 user decision boundaries | approval/scope/risk/source drift hard-stop tests |
| DCC-MUST-016 | §10 commit limit, §13 effect boundaries | push/system/external/package/credential negative-space tests |
| DCC-MUST-017 | §15 governed effect boundary | effect reconciliation + ambiguous-effect tests |
| DCC-MUST-018 | §16 Attention and Operator Exit | outbound-only + stall/recovery delivery tests |
| DCC-MUST-019 | §17 backward compatibility | old job/state/receipt schema fixtures and unknown-version fail-close |
| DCC-MUST-020 | §19 test strategy | L1-L6 failure injection + full regression + EDP closure |

## 21. Acceptance Criteria

All of the following are mandatory:

- **DCC-AC-001:** Approved FULL_PLAN can progress across at least three Gates without another chat-driven receipt/resume command when every Gate remains inside the sealed contract.
- **DCC-AC-002:** GATE_BY_GATE behavior is unchanged.
- **DCC-AC-003:** Existing jobs without DCC contract remain manual.
- **DCC-AC-004:** Free-form/forged attestation cannot produce a valid auto receipt.
- **DCC-AC-005:** Tested tree and committed tree are provably equal.
- **DCC-AC-006:** Crash at every transaction boundary recovers without duplicate effect/commit/receipt/Gate completion.
- **DCC-AC-007:** Reconciler/controller concurrency yields one durable owner.
- **DCC-AC-008:** Approval/scope/risk/source drift fails closed.
- **DCC-AC-009:** Runtime migration continues only through existing successor handoff.
- **DCC-AC-010:** Push/system/external/package/credential work is not automatically authorized.
- **DCC-AC-011:** Attention remains outbound-only and signals only after autonomous recovery is unable to progress, except immediate genuine decision events.
- **DCC-AC-012:** Router/MPRF/Full MCP authority negative-space remains unchanged.
- **DCC-AC-013:** Full regression and EDP-1.0 close ALL PASS with no unresolved blocker/major.

## 22. Rollout Strategy

1. Add schemas and validation with auto continuation disabled globally.
2. Add transaction + verifier infrastructure under tests only.
3. Enable `AUTO_WITHIN_APPROVED_CONTRACT` for a synthetic non-dangerous FULL_PLAN fixture.
4. Run failure injection and restart/concurrency tests.
5. Enable for a bounded repository-local implementation scenario with `LOCAL_COMMIT_ALLOWED`, no push.
6. Verify production reconciler recovery.
7. Keep legacy/manual fallback available throughout qualification.
8. Only after EDP ALL PASS may this become the new stable Harness baseline.

No broad automatic migration of historical jobs is allowed.

## 23. Rollback

Because old jobs default to manual, rollback is primarily feature-disable and runtime-release rollback:

- disable auto eligibility for new jobs;
- preserve transaction/attestation evidence read-only;
- return receipt workflow to MANUAL_OPERATOR for future runs;
- activate the last verified immutable runtime through the existing runtime migration procedure when a runtime rollback is required.

Rollback must not delete evidence or rewrite completed historical transactions.

## 24. Non-Goals

This project does not:

- make ChatGPT asynchronous or background-running;
- allow Attention to control execution;
- eliminate user approval for genuine decision boundaries;
- automatically push to Git remotes;
- merge branches automatically;
- perform package/system/network/credential actions without separate authority;
- replace Router/MPRF/Full MCP;
- replace RuntimeMigrationTransaction;
- convert GATE_BY_GATE into FULL_PLAN;
- permit arbitrary shell commands as verifier or commit policy;
- infer approval from successful tests.

## 25. Success Definition

The defect class is considered structurally closed when a pre-approved FULL_PLAN can survive loss of the initiating GPT/chat execution turn at every mechanical handoff point and still either:

1. continue safely to completion under the same sealed authority, or
2. stop in an explicit, correctly classified wait/block/decision state with durable evidence and appropriate Attention behavior.

A silent `OPERATOR_TASK_RECEIPT_PENDING` that requires an otherwise unnecessary future chat turn is no longer an acceptable steady state for an auto-eligible Gate.
