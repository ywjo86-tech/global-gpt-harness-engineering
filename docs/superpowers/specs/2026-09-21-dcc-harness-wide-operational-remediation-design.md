# DCC Harness-Wide Operational Remediation — Design Amendment

**Date:** 2026-09-21
**Status:** CANDIDATE / USER-REVIEW-REQUIRED
**Amends:** `docs/superpowers/specs/2026-09-20-durable-continuation-controller-design.md`
**Diagnosis:** `docs/history/upgrades/2026-09-21-DURABLE-CONTINUATION-CONTROLLER/EDP_HARNESS_WIDE_OPERATIONAL_REDIAGNOSIS.md`
**Protocol:** `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` / EDP-1.0
**Stable active runtime:** `a40626c31353f90c0d4c9e677d3886ea5ccce393`

## 1. Purpose

Close the sixteen material Harness-wide operational findings discovered after the original Durable Continuation Controller design was approved. This amendment preserves the original DCC authority model while making continuation safe across GPT Operator yield, Full Plan waits, Provider/MPRF recovery, Full MCP effects, durable evidence retention, reconciliation, Attention delivery, and runtime publication/rollback.

The target is not merely “DCC works.” The target is:

> Every already-authorized Harness workflow either continues under a single durable owner or stops in a correctly classified durable wait/decision state with a real notification path. No chat-turn loss, provider/resource recovery, worktree cleanup, reconciler race, or runtime publication window may create a silent operational stop or weaken existing authority.

## 2. Authority and Compatibility Freeze

The following authorities remain unchanged:

- GPT remains Operator for planning, design, execution approval, contract revision, exception handling, and decisions that cannot be reduced to already-approved mechanical continuation.
- Full Plan remains the sole Task/Gate/fan-in/next-state authority.
- User Decision & Attention Policy R2 remains the user-decision and notification-eligibility authority.
- Provider Router remains provider/model selection authority; MPRF remains provider runtime/health/recovery-fact authority.
- Execution Backend / Full MCP remains governed state-changing effect authority.
- `RuntimeMigrationTransaction` remains runtime activation/successor-handoff authority.
- Attention remains outbound-only and has `control_authority=NONE`.
- `GATE_BY_GATE` next-Gate approval behavior remains unchanged.
- Historical jobs, receipts, states, migrations, and attention evidence are not rewritten or silently reinterpreted as AUTO.

Where this amendment conflicts with the original DCC Spec on an amended topic, this amendment is the candidate successor authority after explicit user approval. Unamended DCC requirements remain in force.

## 3. Approaches Considered

### 3.1 Direct patch to the original DCC Plan

Rejected. It would mix DCC-local fixes with independent Harness-wide ownership defects and would preserve the risk that Operator, wait recovery, Attention, and publication behavior drift independently.

### 3.2 One giant replacement Harness design

Rejected. It would unnecessarily reopen already-qualified Router/MPRF/Full MCP/runtime-migration authority and create excessive regression risk.

### 3.3 Incremental Harness-wide amendment with four bounded workstreams

Selected. One umbrella authority defines cross-component invariants, while implementation is later split into four independently reviewable workstreams:

1. **Continuation Core & Authority** — DCC contract, source lineage, transaction, receipts, immutable runtime separation.
2. **Wait / Operator / Attention** — typed wait recovery, safe Operator yield, notification delivery, supersession.
3. **Evidence / Effects / Persistence** — stable state root, Full MCP effect evidence, lock hierarchy, retention.
4. **Publication / Rollback / Live Qualification** — code/closure/publication identities, pre-close runtime qualification, live AUTO canary.

No workstream may become an alternate orchestrator.

## 4. Canonical Remediation Requirements

| ID | Normative requirement |
|---|---|
| HWO-MUST-001 | A mutating implementation worktree MUST NOT be the sealed executor runtime. `project_root`, immutable `runtime_code_root`, and durable `harness_state_root` are distinct bindings. |
| HWO-MUST-002 | `GateContinuationContract` MUST serialize the exact approved authority fields from the original DCC Spec; implementation aliases may not weaken or rename the wire contract without another approved amendment. |
| HWO-MUST-003 | Production job construction MUST support an explicit, closed per-Gate continuation-contract mapping; missing mapping remains `MANUAL_OPERATOR`, unknown Gate mapping fails closed. |
| HWO-MUST-004 | AUTO source authority MUST prove `approved_base_head`, allowed ancestry relation, previous verified receipt lineage when required, current HEAD/tree, and resulting commit lineage deterministically. |
| HWO-MUST-005 | Typed wait semantics MUST preserve `OPERATOR_TASK_RECEIPT_PENDING` and `CONTINUATION_RECOVERY_PENDING`; provider/resource/migration/approval waits must remain distinguishable and may not be aliased to AUTO receipt recovery. |
| HWO-MUST-006 | `GateContinuationTransaction` MUST durably represent `BLOCKED`, `USER_DECISION_REQUIRED`, `DELEGATED_RUNTIME_MIGRATION`, and `ROLLED_BACK` in addition to the normal monotonic success path. |
| HWO-MUST-007 | EDP publication MUST bind `validated_code_head`, `closure_head`, and `publication_head` separately and prove zero executable-surface drift from validated code to publication. |
| HWO-MUST-008 | GPT Operator yield MUST be safe: a turn may yield only with terminal completion, an explicit user-decision wait, or a durable continuation checkpoint bound to an autonomous owner or resumable Operator handoff. |
| HWO-MUST-009 | Attention MUST have a production outbound delivery adapter with durable delivery receipts; delivery grants no inbound control authority. |
| HWO-MUST-010 | Historical Attention MUST use explicit run-supersession/archival evidence so obsolete incidents are preserved but not delivered as current incidents. |
| HWO-MUST-011 | `WAITING_PROVIDER` and low-resource `WAITING_RESOURCE` MUST have autonomous Full Plan-owned recovery evaluation using their canonical authorities; `WAITING_APPROVAL` and runtime-migration waits remain non-auto-resumable by this path. |
| HWO-MUST-012 | AUTO attestation MUST consume canonical Full MCP/ToolEffectJournal reconciliation evidence for governed writes; unproven or ambiguous effects block continuation. |
| HWO-MUST-013 | New durable jobs/state/receipts/migrations/attention/DCC evidence MUST live under a stable state root independent of disposable Git worktrees; legacy roots remain readable without mutation. |
| HWO-MUST-014 | Full Plan run lock is the outer mutation lock. Any DCC transaction lock is inner; reverse acquisition is forbidden and stale fencing epochs may not mutate Git, receipts, or state. |
| HWO-MUST-015 | Runtime publication MUST preserve a rollback window until active-runtime qualification passes. Predecessor closure is forbidden before successor verification plus active-runtime qualification/canary evidence. |
| HWO-MUST-016 | Stable-baseline publication MUST include a live active-runtime 3+ Gate AUTO canary that loses the initiating foreground Operator and completes through systemd/reconciler without chat-driven resume. |
| HWO-MUST-017 | New schemas/fields are additive and fail closed. Legacy job/state/receipt/migration evidence remains readable and never gains AUTO authority by inference. |
| HWO-MUST-018 | DCC, wait recovery, Attention, and Operator checkpointing MUST NOT acquire provider selection, Full MCP effect execution, runtime activation, user approval, or next-Gate selection authority. |
| HWO-MUST-019 | Notification transport configuration and any external notification network/credential effect require an explicit deployment authorization; absence of a configured live transport blocks claims of production Attention delivery. |
| HWO-MUST-020 | Final qualification MUST close all 16 findings with Harness-wide EDP, cross-domain regression, crash/race injection, reboot/systemd recovery, live delivery/canary evidence, and `BLOCKER=0`, `MAJOR=0`. |

## 5. Root and Identity Model

New production jobs use three distinct roots:

```text
project_root        = mutable project/implementation Git worktree
runtime_code_root   = exact immutable qualified Harness release
harness_state_root  = stable durable state root independent of worktrees
```

Default durable root:

```text
GCH_STATE_ROOT=${GCH_STATE_ROOT:-${XDG_STATE_HOME:-$HOME/.local/state}/global-gpt-harness}
```

Rules:

- `project_root` may advance through approved local commits.
- `runtime_code_root` is immutable for one registered run generation; a runtime change requires `RuntimeMigrationTransaction` successor handoff.
- `harness_state_root` is never a project worktree and is never removed by project worktree cleanup.
- Job authority binds all three roots and their applicable repository/release identities.
- Legacy jobs lacking `harness_state_root` continue to resolve their historical `harness_root` exactly as before and are not migrated in place.
- Discovery may read both the stable root and explicitly configured legacy roots, deduplicated by `(project_id, run_id, authority_core_sha256)`.

The stable root owns durable namespaces for registered jobs, Full Plan runs, receipts, runtime migrations, Attention, DCC transactions/attestations, Operator checkpoints, supersession records, and live canary evidence.

## 6. Exact Gate Continuation Authority

The original DCC `GateContinuationContract` wire schema remains canonical:

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

Required values/semantics:

- `continuation_policy`: `MANUAL_OPERATOR` or `AUTO_WITHIN_APPROVED_CONTRACT`.
- `commit_policy`: `NO_COMMIT` or `LOCAL_COMMIT_ALLOWED` for v1.
- `external_effect_policy`: `NO_EXTERNAL_EFFECT` or `GOVERNED_REPOSITORY_EFFECTS_ONLY` for v1.
- `runtime_migration_policy`: `NO_RUNTIME_MIGRATION` or `DELEGATE_RUNTIME_MIGRATION`.
- `source_lineage_policy` is a closed enum; v1 supports `EXACT_BASE` and `APPROVED_DESCENDANT_CHAIN`.

A production builder accepts a mapping equivalent to:

```text
continuation_contracts_by_gate: Mapping[gate_id, GateContinuationContract]
```

The builder rejects unknown Gate IDs, duplicate contracts, mismatched `gate_id`, unknown schema values, and authority-core drift. Omitted Gates remain manual.

## 7. Source and Evidence Lineage

For `APPROVED_DESCENDANT_CHAIN`, every AUTO Gate proves:

1. current pre-execution HEAD is equal to or a Git descendant of `approved_base_head`;
2. if the Gate consumes a previous Gate head, previous v2 receipt `source_head` equals the expected parent lineage anchor;
3. observed changed-path digest is inside sealed scope;
4. verified candidate tree is the tree that required verifiers evaluated;
5. any local commit has parent equal to the accepted pre-commit head and tree equal to `verified_tree_sha`;
6. rewritten/non-descendant history, wrong parent receipt, changed branch, or changed tree fails closed.

The attestation records immutable evidence; it does not expand source authority.

## 8. Typed Wait Recovery Model

Top-level Full Plan states remain compatible. Recovery is selected only after exact typed classification.

| Top-level state | Canonical wait reason/substate | Recovery owner |
|---|---|---|
| `WAITING_RESOURCE` | `OPERATOR_TASK_RECEIPT_PENDING` | DCC only when a valid AUTO contract/transaction exists; otherwise manual Operator |
| `WAITING_RESOURCE` | `CONTINUATION_RECOVERY_PENDING` | DCC transaction reconciler |
| `WAITING_RESOURCE` | `LOW_RESOURCE_BACKPRESSURE` | Full Plan resource recovery evaluator using fresh resource probe |
| `WAITING_RESOURCE` | `RUNTIME_MIGRATION_QUIESCED` | RuntimeMigrationTransaction only |
| `WAITING_PROVIDER` | `PROVIDER_UNAVAILABLE` / `PROVIDER_RECOVERY_PENDING` | Full Plan wait-recovery path using fresh Router/MPRF facts under the same sealed capability/output/validation contract |
| `WAITING_APPROVAL` | any | user decision only |

The periodic reconciler may request recovery evaluation. It may not itself select a provider, fabricate approval, or treat a generic `WAITING_RESOURCE` as resumable.

Provider recovery rules:

- the wait state durably binds the original Router request digest, eligibility snapshot digest, capability/output/validation contract digest, and last Router decision ref;
- fresh MPRF health/runtime facts are required;
- Router re-evaluates that same sealed request/eligibility contract;
- provider/model substitution inside existing approval coverage is allowed only through Router authority;
- if the request/risk/output contract changes, return `USER_DECISION_REQUIRED` or `PLAN_REVISION_REQUIRED`;
- stale or ambiguous provider/effect facts remain waiting/blocked.

Resource recovery rules:

- fresh resource probe must satisfy the run's sealed thresholds;
- resume is compare-and-swap against the expected wait reason, Gate, state SHA, and owner epoch;
- pressure clearing does not bypass unrelated receipt/migration waits.

## 9. Operator Safe-Yield Contract

Local Harness code cannot force the ChatGPT platform to keep a response turn open. Therefore the enforceable goal is **safe yield, not impossible turn termination**.

For every registered multi-step execution, the Operator workflow must ensure one of these durable dispositions before a user-facing yield/finalization point:

1. `TERMINAL_COMPLETE` — Full Plan completion facts and request obligations are complete;
2. `USER_DECISION_WAIT` — an explicit durable decision event exists and is notification-eligible;
3. `AUTONOMOUS_OWNER_BOUND` — a Full Plan/DCC/reconciler owner, lease/epoch, transaction/checkpoint, and resume path are durably bound;
4. `OPERATOR_HANDOFF_CHECKPOINT` — autonomous continuation is impossible, but exact next action/evidence/authority is durably checkpointed and Attention delivery is available so re-entry is not silent.

A new `OperatorTurnCheckpoint` is immutable/digest-bound and records at least:

```text
schema_version
project_id
run_id
gate_id_or_stage
authority_core_sha256
checkpoint_kind
owner_kind
owner_ref
resume_contract_sha256
last_semantic_progress_at
created_at
checkpoint_sha256
```

`OperatorTurnCheckpoint` is evidence only and has `control_authority=NONE`; it cannot dispatch, resume, select providers, create approval, or execute effects. `operator_exit_guard` consumes this durable fact. A non-allow disposition remains a non-success result. The outer Operator policy must execute or checkpoint the next authorized step; it may not reinterpret `CONTINUE_EXECUTION` as completion.

## 10. Attention Delivery and Supersession

### 10.1 Delivery adapter

Add a closed outbound adapter boundary:

```text
AttentionDeliveryAdapter.send(event) -> immutable delivery receipt
```

Production v1 supports a separately configured/authorized `HTTPS_WEBHOOK_V1` adapter and a test-only capture adapter. The production adapter:

- accepts only a preconfigured allowlisted HTTPS endpoint;
- reads credentials only from an approved secret reference/environment binding;
- never includes an inbound command/control route;
- receives only events already declared delivery-eligible by User Decision & Attention Policy R2 (`WAITING_APPROVAL`/genuine decisions immediate; ordinary incidents only after the configured semantic-progress threshold, currently 300 seconds);
- uses bounded timeout/retry and idempotency key = Attention `event_id`;
- persists delivery receipt before marking an event delivered;
- never mutates Full Plan state.

No live transport configured means `ATTENTION_DELIVERY_UNCONFIGURED`; the Harness may still persist incidents but may not claim production notification readiness.

### 10.2 Historical supersession

Obsolete notification suppression requires an immutable `RunSupersessionRecord` or equivalent canonical successor evidence. Mere timestamp ordering is insufficient.

A pending historical event becomes `ARCHIVED_SUPERSEDED` only when:

- the event's run is terminal/non-current;
- an explicitly bound successor/superseding run exists for the same project authority lineage;
- the newer run has verified semantic progress or terminal closure that supersedes the incident;
- the archival record binds both run IDs, authority digests, reason, and evidence refs.

Archived events remain auditable and are never deleted merely to reduce notification count.

## 11. Full MCP Effect Evidence in AUTO Attestation

DCC v1 permits no arbitrary external/system/network/package/credential effects.

For `GOVERNED_REPOSITORY_EFFECTS_ONLY`, AUTO continuation requires a registered verifier that consumes canonical `ToolEffectJournal` / `effect_evidence_bridge` evidence and proves:

- intent/receipt pair exists and matches the sealed operation/scope;
- effect is authorized;
- mutation and security status are consistent;
- no unmatched/ambiguous begun effect exists;
- retry reconciliation is `NO_EFFECT`, `COMPLETED`, or another explicitly safe idempotent disposition;
- evidence digest is included in `VerifiedGateAttestation.required_evidence_classes`.

Missing/ambiguous effect evidence returns `USER_DECISION_REQUIRED` or `BLOCKED` according to User Decision Policy R2. Git tree equality alone is never sufficient proof of governed-effect completion.

## 12. Lock and Ownership Hierarchy

Canonical mutation lock order is:

```text
1. Full Plan run lock
2. DCC continuation transaction lock
3. immutable receipt/attestation write serialization for the same Gate
```

Rules:

- never acquire the run lock while holding a transaction/receipt lock;
- effect journal is read-only to DCC and is not acquired as a mutation lock;
- Git ref mutation occurs only while the run owner epoch and DCC transaction owner are both current;
- stale epoch detection is repeated immediately before Git commit, receipt sealing, and Full Plan resume;
- lock acquisition is bounded; timeout produces durable recovery evidence, not indefinite wait;
- reconciler and foreground controller enter the same ownership function and cannot create parallel schedulers.

## 13. Continuation Transaction Dispositions

Success path remains:

```text
PREPARED -> EXECUTION_OBSERVED -> VERIFIED -> COMMIT_INTENT -> COMMITTED -> RECEIPT_SEALED -> ADVANCED
```

Durable dispositions are first-class:

```text
BLOCKED
USER_DECISION_REQUIRED
DELEGATED_RUNTIME_MIGRATION
ROLLED_BACK
```

Every disposition records reason taxonomy, binding digests, prior phase, and recovery eligibility. A delegated migration cannot be resumed by generic DCC until the migration successor is verified under canonical migration authority.

## 14. Validation, Closure, and Publication Identity

The release process records three distinct identities:

```text
validated_code_head  = exact code/executable tree measured by final EDP
closure_head         = docs/evidence-only descendant that seals EDP results
publication_head     = exact pushed/released commit
```

Before publication:

- `validated_code_head` must be an ancestor of `publication_head`;
- `git diff --quiet <validated_code_head>..<publication_head> -- runtime tests scripts` and any other executable surface defined by the release manifest must pass;
- any executable drift invalidates EDP and requires revalidation;
- docs-only closure differences are permitted only when independently diff-checked;
- release manifest stores `publication_head` and the EDP evidence stores both `validated_code_head` and `closure_head`.

## 15. Runtime Publication Rollback Window

The existing migration v1 evidence remains readable. New publication that changes the active Harness runtime uses a versioned migration-v2 contract under the same `RuntimeMigrationTransaction` authority. V2 additionally binds the exact **source/last-known-good release** (`source_head`, source tree, source manifest SHA), target release, predecessor/successor identities, and active-runtime qualification evidence.

Publication order is amended to:

```text
build/verify immutable release
-> PREPARED
-> PREDECESSOR_QUIESCED
-> RUNTIME_ACTIVATED
-> SUCCESSOR_REGISTERED
-> SUCCESSOR_VERIFIED
-> ACTIVE_RUNTIME_QUALIFICATION
-> PREDECESSOR_CLOSED
```

`ACTIVE_RUNTIME_QUALIFICATION` is a migration-v2 phase/evidence gate owned by the existing migration authority. It is not a second runtime authority. Rollback remains legal through this phase and becomes illegal only after `PREDECESSOR_CLOSED`.

Required evidence before predecessor closure:

- runtime-current manifest/HEAD matches the target release;
- systemd reconcile service/timer operate from runtime-current;
- cross-domain focused regression passes from active immutable runtime;
- live 3+ Gate AUTO canary passes;
- Attention/Wait recovery smoke passes for configured capabilities;
- no unexpected nonterminal/migration conflict exists;
- immutable qualification evidence digest is recorded in the migration-v2 transaction and predecessor handoff state before `close_migrated_predecessor` is allowed.

A qualification failure uses an explicit **reverse activation** sequence, not the current bookkeeping-only `MigrationStore.rollback()` by itself:

```text
qualification FAIL
-> quiesce/fence the exact successor and canary owners
-> verify predecessor is still quiesced and source rollback binding is intact
-> atomically retarget runtime-current to the sealed source/last-known-good release
-> verify restored source runtime manifest/systemd entry
-> mark failed successor as rollback-cancelled
-> record migration ROLLED_BACK with restored-runtime evidence
-> resume the predecessor only under the restored runtime
```

The reverse activation API may exempt only the exact migration-bound, quiesced predecessor/successor set from active-job blocking. Any unrelated active job, identity drift, missing source release, or non-quiesced successor blocks rollback and raises immediate recovery Attention. Predecessor closure is forbidden until qualification succeeds.

## 16. Live AUTO Canary

The publication candidate must run a harmless production-shape canary from the active immutable runtime:

1. create a dedicated isolated canary Git workspace under the stable state root;
2. register a FULL_PLAN with at least three AUTO Gates and no external/network/system/package/credential effect;
3. Gate A establishes a bounded local canary artifact and verified receipt;
4. terminate/lose the initiating foreground Operator after Gate A;
5. systemd periodic reconciler discovers the pending continuation;
6. the same canonical Full Plan/DCC ownership path advances Gates B and C;
7. final state is `COMPLETED / ALL_GATES_COMPLETED` with v2 receipts, one owner epoch at a time, no duplicate commit/effect, and no chat resume command;
8. canary state/evidence is retained under stable state root and the temporary Git workspace can be removed only after evidence hashes are sealed.

This canary proves runtime-current/search-root/systemd/permissions/wait-recovery wiring rather than only unit-test semantics.

## 17. Workstream Decomposition

### Workstream A — Continuation Core & Authority

Owns HWO-MUST-001~007, original DCC contract fidelity, builder injection, lineage, receipt/transaction semantics, and executor-runtime separation.

### Workstream B — Wait / Operator / Attention

Owns HWO-MUST-008~011 and HWO-MUST-019: safe-yield checkpointing, provider/resource wait recovery, outbound delivery, historical supersession.

### Workstream C — Evidence / Effects / Persistence

Owns HWO-MUST-012~014 and HWO-MUST-017~018: stable state root, legacy discovery, effect evidence verifier, lock hierarchy, authority negative-space.

### Workstream D — Publication / Rollback / Live Qualification

Owns HWO-MUST-007, 015, 016, 020: code/closure/publication identities, active-runtime qualification while rollback is legal, live canary, final Harness-wide EDP.

Implementation planning after approval must use one coordination plan plus four bounded subplans or an equivalent dependency-ordered plan set. No plan may start Workstream D before A-C integration regression is green.

## 18. Finding-to-Requirement Traceability

| Finding | Remediation requirement(s) |
|---|---|
| DCC-ORCH-F001 | HWO-MUST-001 |
| DCC-ORCH-F002 | HWO-MUST-002 |
| DCC-ORCH-F003 | HWO-MUST-003 |
| DCC-ORCH-F004 | HWO-MUST-004 |
| DCC-ORCH-F005 | HWO-MUST-005 |
| DCC-ORCH-F006 | HWO-MUST-006 |
| DCC-ORCH-F007 | HWO-MUST-007 |
| DCC-HW-F008 | HWO-MUST-008 |
| DCC-HW-F009 | HWO-MUST-009, HWO-MUST-019 |
| DCC-HW-F010 | HWO-MUST-010 |
| DCC-HW-F011 | HWO-MUST-011 |
| DCC-HW-F012 | HWO-MUST-012 |
| DCC-HW-F013 | HWO-MUST-013, HWO-MUST-017 |
| DCC-HW-F014 | HWO-MUST-014 |
| DCC-HW-F015 | HWO-MUST-015 |
| DCC-HW-F016 | HWO-MUST-016 |

## 19. Acceptance Criteria

- **HWO-AC-001:** implementation Full Plan can mutate its project worktree across multiple commits while executor runtime identity remains fixed to one immutable release.
- **HWO-AC-002:** exact original DCC Gate contract wire schema is preserved and production builder can seal AUTO on explicitly named Gates only.
- **HWO-AC-003:** non-descendant/wrong-parent/wrong-previous-receipt source lineage fails closed; valid descendant chain passes.
- **HWO-AC-004:** each wait class has exactly one authorized recovery owner; provider/resource recovery can resume autonomously while approval/migration waits cannot.
- **HWO-AC-005:** loss of GPT Operator at an execution handoff leaves either autonomous ownership or a durable checkpoint plus notification path; no silent unowned state remains.
- **HWO-AC-006:** Attention production delivery produces an immutable delivery receipt, and historical superseded events are archived without being delivered as current.
- **HWO-AC-007:** governed repository effects are accepted for AUTO only with canonical ToolEffectJournal reconciliation; ambiguous effect evidence blocks.
- **HWO-AC-008:** worktree deletion cannot delete new canonical run/receipt/migration/Attention/DCC evidence.
- **HWO-AC-009:** forced reconciler/controller lock races produce one owner and no deadlock/double commit/double receipt/double advance.
- **HWO-AC-010:** validated code, closure, and publication identities are independently bound and executable drift after EDP invalidates publication.
- **HWO-AC-011:** active-runtime qualification failure before predecessor close can legally reverse-activate the sealed last-known-good runtime and resume the predecessor without an unrelated active-job bypass.
- **HWO-AC-012:** live active-runtime 3+ Gate AUTO canary completes after foreground Operator loss through systemd/reconciler with no chat resume.
- **HWO-AC-013:** legacy jobs/receipts/states/migrations remain readable/manual and are never reinterpreted as AUTO.
- **HWO-AC-014:** Router/MPRF/Full MCP/runtime-migration/user-approval/next-Gate authority negative-space remains unchanged.
- **HWO-AC-015:** final focused/full regression, chaos/race/reboot tests, live notification/canary evidence, and EDP close `ALL_PASS` with no blocker/major.

## 20. Rollout and Backward Compatibility

1. Introduce stable state-root support and legacy read compatibility before moving any new DCC evidence.
2. Introduce contract/builder/lineage/transaction additions with AUTO disabled by default.
3. Add effect verifier and wait recovery under synthetic tests.
4. Add Operator checkpoint and Attention delivery with production delivery disabled until explicit transport authorization/configuration.
5. Enable AUTO only for synthetic/local canaries.
6. Run crash/race/reboot and historical compatibility tests.
7. Integrate A-C and reach Harness-wide EDP pre-publication PASS.
8. After separate publication authorization, activate an immutable runtime but keep the predecessor rollback window open.
9. Run active-runtime qualification and live AUTO canary.
10. Close predecessor and declare a new stable baseline only after every required evidence class passes.

Rollback preserves all evidence. Disabling AUTO reverts future Gates to manual behavior; it never rewrites historical transactions or receipts.

## 21. Non-Goals

This amendment does not:

- make ChatGPT itself a background process;
- grant Attention inbound control authority;
- permit automatic push/merge/system/package/credential/network work outside separately approved notification transport;
- replace Provider Router/MPRF/Full MCP;
- replace RuntimeMigrationTransaction;
- convert `GATE_BY_GATE` to FULL_PLAN;
- infer supersession from timestamps alone;
- move or rewrite historical state without an explicit migration plan;
- declare the existing DCC implementation Plan executable.

## 22. Success Definition

This amendment is successful when the Harness can lose the initiating GPT/operator execution turn, recover from provider/resource availability changes, reconcile governed effects, survive worktree cleanup and process/server restart, notify the user when autonomous progress is impossible, and publish/rollback runtime changes without creating a second orchestration authority or weakening user/provider/effect/migration boundaries.

Implementation is not authorized by this document. After this Amendment is diagnosed and explicitly approved, the current DCC implementation Plan must be superseded by dependency-ordered workstream plans and re-diagnosed before execution approval.
