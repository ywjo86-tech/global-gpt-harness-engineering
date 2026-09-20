# Full Plan Continuity + Design Skill Root-Cause Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the design-time and runtime root cause that allowed `FINAL-OP-20260920-R2` to terminate during runtime migration without a durable successor or user Attention, then resume the interrupted final operationalization and reach measured EDP ALL PASS.

**Architecture:** Add a design-time Stateful Continuity Review, a digest-bound `RuntimeMigrationTransaction`, transaction-bound activation exemption, deterministic migration recovery, and terminal-orphan Attention. Preserve all existing Full Plan, Provider Router, Tool/Effect, Completion, and Attention authority boundaries. Historical R2 remains immutable incident evidence; continuation proceeds through a new successor run.

**Tech Stack:** Python 3.12, unittest, JSON durable state/evidence, existing Full Plan supervisor/reconciler, systemd user services, Git, Markdown skill contracts.

**Specs:** `docs/superpowers/specs/2026-09-20-full-plan-continuity-skill-remediation-design.md`; `docs/superpowers/specs/2026-09-20-final-operational-scope-integrity-amendment-design.md`

## Global Constraints

- Protocol: `EXHAUSTIVE_DIAGNOSIS_PROTOCOL / EDP-1.0`.
- Never synthesize or rewrite an R2 `TASK-014` PASS receipt.
- A migration transaction may replay only already-approved identities and digests; it has no approval/provider/effect/completion authority.
- Attention stays outbound-only and cannot resume, approve, reroute, or mutate execution.
- No generic active-job bypass is allowed; activation exemption must bind the exact quiesced predecessor and sealed migration transaction.
- A predecessor cannot be closed as migrated until the successor durable job is registered and verified.
- `COMPLETED` remains reserved for actual Full Plan completion, never migration success.
- Runtime releases remain immutable and `runtime-current` must never point to a disposable worktree.
- CLI-Anything is a bounded Tool Implementation mechanism only; upstream baseline `HKUDS/CLI-Anything@810c18b0d1ab9b234bc996c9fd999318523a3ef0` must be re-verified before qualification.
- No generic `exec`/`shell`/`command` surface, no `shell=True`, and no generated tool/skill may self-authorize or self-register.
- State-changing CLI execution must remain `Full Plan -> Tool Authorization -> ClosedOperationRegistry -> SingleToolBroker -> qualified adapter -> EffectJournal -> verification`.
## Review Focus

1. Self-reference paradox: the running Full Plan itself satisfies an `active_jobs > 0` guard; migration must resolve this without weakening unrelated-job protection. Covered in Tasks 2-3.
2. Crash after old runtime activation but before successor registration: the sealed transaction must make restart recovery deterministic. Covered in Tasks 3-4.
3. `CANCELLED` terminal state with no successor: reconciler must publish idempotent orphan Attention rather than silently skip. Covered in Task 5.
4. Skill regression: future runtime/service/worktree/supervisor replacement designs must be rejected when owner/successor/rollback answers are missing. Covered in Task 1.
5. Authority expansion: migration/Attention/CLI-Anything paths must not acquire provider, approval, completion, arbitrary-shell, or resume authority; CLI effects must stay broker/journal-bound. Covered in Tasks 4-6, 10-12, and final EDP.

## File Map

- `.agents/skills/harness-design/SKILL.md` — mandatory Stateful Continuity Review and NOT READY gate.
- `docs/harness/skill-design-guide.md` — reusable continuity standard and invariants.
- `.agents/skills/new-project-orchestrator/SKILL.md` — trigger/reference only, no duplicated standard.
- `runtime/orchestrator/runtime_migration_handoff.py` — immutable/digest-bound transaction model, persistence, recovery inspection.
- `runtime/orchestrator/runtime_release.py` — exact transaction-bound activation exemption.
- `runtime/orchestrator/production_full_plan_runner.py` — explicit migration quiesce / migrated disposition only.
- `runtime/orchestrator/production_full_plan_boot.py` — migration reconciliation and orphan Attention repair.
- `tests/test_harness_design_continuity_skill.py` — deterministic skill-contract pressure fixtures.
- `tests/test_runtime_migration_handoff.py` — transaction lifecycle and crash-point tests.
- `tests/test_runtime_release.py` — exact activation-exemption tests.
- `tests/test_full_plan_continuity_r2.py` — terminal orphan / successor regression.
- `runtime/tool_implementation/manifest.py` — immutable digest-bound candidate/qualified tool manifest.
- `runtime/tool_implementation/cli_anything_adapter.py` — allowlisted CLI-Anything-generated adapter execution, never generic shell.
- `runtime/tool_implementation/qualification.py` — candidate qualification and generated-skill boundary.
- `tests/test_cli_anything_tool_implementation.py` — TI-01..TI-08 and TI-INV-01..07 coverage.
- `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/` — diagnosis, remediation, CLI qualification, recovery, and final EDP evidence.

---
### Task 0: Promote the Approved Remediation Plan to Durable Full Plan R3 Before Any Implementation

**Files:**
- Operational: `_workspace/production-full-plan-jobs/AI-OFFICE-HARNESS-FINAL-OPERATIONAL/FINAL-OP-20260920-R3.job.json`
- Operational: corresponding durable Full Plan state/receipt roots under `_workspace/`.

**Interfaces:**
- Uses existing `build_operator_plan_job()` / `register_job()` / `production_full_plan_entry`.
- Project ID: `AI-OFFICE-HARNESS-FINAL-OPERATIONAL`; run ID: `FINAL-OP-20260920-R3`.
- Task IDs: `TASK-001` through `TASK-016`, mapping one-to-one to Tasks 1-16 below.
- Approved plan path is this committed plan; approved spec path is the committed continuity Spec. The approved plan itself explicitly binds the companion CLI-Anything amendment, so its SHA carries both approved scopes.

- [ ] **Step 1: Verify there is no pre-existing R3 job and bind current approvals**

Require R2 remains terminal historical evidence, R3 path absent, both approved Spec files committed, this plan committed, branch identity unchanged, and `runtime-current` resolvable.

- [ ] **Step 2: Build and register R3**

```python
job = build_operator_plan_job(
    project_root=PROJECT_ROOT, harness_root=PROJECT_ROOT,
    runtime_code_root=Path.home()/".local/share/global-gpt-harness/runtime-current",
    project_id="AI-OFFICE-HARNESS-FINAL-OPERATIONAL",
    run_id="FINAL-OP-20260920-R3",
    task_ids=[f"TASK-{i:03d}" for i in range(1, 17)],
    approved_plan_path="docs/superpowers/plans/2026-09-20-full-plan-continuity-skill-remediation.md",
    approved_spec_path="docs/superpowers/specs/2026-09-20-full-plan-continuity-skill-remediation-design.md",
    approval_ref="USER_APPROVED_2026-09-20_CONTINUITY_AND_SCOPE_AMENDMENT",
)
registered = register_job(job)
```

- [ ] **Step 3: Launch and verify durable ownership**

Launch through `production_full_plan_entry --launch-transient`; require R3 reaches `WAITING_RESOURCE / TASK-001`, is discoverable from `runtime-current`, and Attention/Reconciler can observe it. No source mutation begins before this state is verified.

- [ ] **Step 4: Keep `_workspace` uncommitted**

Verify `git status --short` contains no tracked `_workspace` mutation. The durable R3 state is operational evidence, not repository source.

### Task 1: Make Stateful Continuity Review a Required Design-Skill Contract

**Files:**
- Modify: `.agents/skills/harness-design/SKILL.md`
- Modify: `docs/harness/skill-design-guide.md`
- Modify: `.agents/skills/new-project-orchestrator/SKILL.md`
- Create: `tests/test_harness_design_continuity_skill.py`

**Interfaces:**
- Consumes: approved continuity Spec invariants `CI-CONT-01..05`.
- Produces: deterministic text-contract checks requiring owner, successor, self-reference, interruption, Attention, and rollback analysis before READY.

- [ ] **Step 1: Write RED skill-contract tests**

Create tests that load the three skill/guide files and require these exact concepts: `Stateful Continuity Review`, `CI-CONT-01`, `CI-CONT-05`, `self-reference`, `successor`, `rollback`, `NOT READY`. Add a scenario fixture describing “active Full Plan retargets its own runtime while activation requires zero active jobs” and assert the skill contract requires explicit paradox resolution.

- [ ] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_harness_design_continuity_skill -v`
Expected: FAIL because the current skill lacks the required continuity contract.

- [ ] **Step 3: Add the minimum reusable standard**

In `harness-design/SKILL.md`, require the review when a design includes runtime replacement, restart, migration, worktree/repository replacement, scheduler/reconciler replacement, state-store relocation, deployment activation, or deliberate owner termination. State: “If any applicable continuity answer is absent, output `NOT READY`.”

In `skill-design-guide.md`, define `CI-CONT-01..05` verbatim from the approved Spec and the required sequence `Before -> Quiesce -> Transition -> Successor Verify -> Predecessor Close -> Rollback`.

In `new-project-orchestrator/SKILL.md`, add only a trigger requiring the architecture/implementation planner to invoke the continuity standard for self-replacing stateful designs.

- [ ] **Step 4: Run GREEN and adversarial variants**

Run the same unittest plus fixtures for service restart, supervisor replacement, worktree deletion, server reboot, scheduler replacement, and state-store relocation. Required: every self-replacement fixture maps to the continuity review; unrelated stateless design fixtures do not.

- [ ] **Step 5: Commit**

`git add .agents/skills/harness-design/SKILL.md .agents/skills/new-project-orchestrator/SKILL.md docs/harness/skill-design-guide.md tests/test_harness_design_continuity_skill.py && git commit -m 'docs(skill): require stateful continuity review'`

### Task 2: Add a Digest-Bound Runtime Migration Transaction

**Files:**
- Create: `runtime/orchestrator/runtime_migration_handoff.py`
- Create: `tests/test_runtime_migration_handoff.py`

**Interfaces:**
- Produces: `RuntimeMigrationTransaction`, `MigrationPhase`, `MigrationStore.create()`, `MigrationStore.load()`, `MigrationStore.advance()`, `MigrationStore.block()`, `MigrationStore.rollback()`.
- Transaction binds predecessor/successor run IDs, gate IDs, plan/spec/authority digests, predecessor state SHA/source HEAD, target release HEAD/manifest digest, successor job-spec digest, phase, timestamps, and transaction SHA.
- [ ] **Step 1: Write RED lifecycle tests**

Test allowed phases exactly: `PREPARED`, `PREDECESSOR_QUIESCED`, `RUNTIME_ACTIVATED`, `SUCCESSOR_REGISTERED`, `SUCCESSOR_VERIFIED`, `PREDECESSOR_CLOSED`, `ROLLED_BACK`, `BLOCKED`. Reject phase skipping, digest changes, successor identity changes, unknown fields, symlink store paths, and transaction SHA mismatches.

```python
def test_cannot_skip_from_prepared_to_runtime_activated():
    tx = store.create(valid_spec())
    with self.assertRaises(MigrationHandoffError):
        store.advance(tx.migration_id, MigrationPhase.RUNTIME_ACTIVATED)

def test_tampered_successor_digest_fails_closed():
    tx = store.create(valid_spec())
    payload = json.loads(store.path(tx.migration_id).read_text())
    payload["successor_job_spec_sha256"] = "0" * 64
    store.path(tx.migration_id).write_text(json.dumps(payload))
    with self.assertRaises(MigrationHandoffError):
        store.load(tx.migration_id)
```

- [ ] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_runtime_migration_handoff -v`
Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement minimal immutable transaction persistence**

Use existing durable atomic-write helpers. `advance()` must enforce one-step legal transitions and recompute canonical SHA-256. `block()` records a reason without granting resume authority. `rollback()` is legal only before `PREDECESSOR_CLOSED` and preserves the original authority bindings.

```python
class MigrationPhase(str, Enum):
    PREPARED = "PREPARED"
    PREDECESSOR_QUIESCED = "PREDECESSOR_QUIESCED"
    RUNTIME_ACTIVATED = "RUNTIME_ACTIVATED"
    SUCCESSOR_REGISTERED = "SUCCESSOR_REGISTERED"
    SUCCESSOR_VERIFIED = "SUCCESSOR_VERIFIED"
    PREDECESSOR_CLOSED = "PREDECESSOR_CLOSED"
    ROLLED_BACK = "ROLLED_BACK"
    BLOCKED = "BLOCKED"

@dataclass(frozen=True, slots=True)
class RuntimeMigrationTransaction:
    migration_id: str
    project_id: str
    predecessor_run_id: str
    successor_run_id: str
    current_gate: str
    resume_gate: str
    approved_plan_sha256: str
    approved_spec_sha256: str
    authority_core_sha256: str
    predecessor_state_sha256: str
    source_head: str
    target_release_head: str
    target_manifest_sha256: str
    successor_job_spec_sha256: str
    phase: MigrationPhase
    transaction_sha256: str
```

- [ ] **Step 4: Run GREEN + corruption tests**

Required: create/load/advance round-trip PASS; tampered transaction fails closed; repeated same-phase load is idempotent; illegal forward/backward transitions fail.

- [ ] **Step 5: Commit**

`git add runtime/orchestrator/runtime_migration_handoff.py tests/test_runtime_migration_handoff.py && git commit -m 'feat(full-plan): add durable runtime migration transaction'`

### Task 3: Make Runtime Activation Transaction-Aware Without a Generic Bypass

**Files:**
- Modify: `runtime/orchestrator/runtime_release.py`
- Modify: `tests/test_runtime_release.py`

**Interfaces:**
- Consumes: verified `RuntimeMigrationTransaction` in `PREDECESSOR_QUIESCED` phase.
- Produces: `activate_runtime_release(manifest, runtime_link, *, job_search_root, migration_transaction=None)` where the only excludable active job is the exact predecessor bound by transaction identity and state SHA.

- [ ] **Step 1: Write RED activation-guard tests**

Cover: no transaction + any nonterminal job => block; valid transaction + exact quiesced predecessor only => allow; unrelated nonterminal job => block; predecessor state SHA mismatch => block; target release/manifest mismatch => block; transaction not `PREDECESSOR_QUIESCED` => block; successor already registered as active before activation => block.

- [ ] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_runtime_release -v`
Expected: new transaction-aware cases FAIL.

- [ ] **Step 3: Implement exact participant exemption**

Refactor active-job discovery to return structured identities. Exclude only `(project_id, predecessor_run_id)` when all transaction bindings match the currently loaded quiesced state. Do not add `ignore_active_jobs`, `force`, wildcard exemptions, or reason-string exceptions.

```python
def activate_runtime_release(
    manifest: RuntimeReleaseManifest,
    runtime_link: str | Path,
    *,
    job_search_root: str | Path,
    migration_transaction: RuntimeMigrationTransaction | None = None,
) -> Path:
    active = _active_registered_jobs(job_search_root)
    blockers = _migration_activation_blockers(active, migration_transaction)
    if blockers:
        raise RuntimeReleaseError("cannot retarget runtime link while active Full Plan jobs exist")
    return _atomic_retarget_runtime_link(manifest, runtime_link)
```

- [ ] **Step 4: Run GREEN plus existing runtime-link regression**

Run: `tests.test_runtime_release tests.test_full_plan_continuity_r2`. Required: exact migration case PASS and existing “cannot retarget away from active job” protection still PASS.

- [ ] **Step 5: Commit**

`git add runtime/orchestrator/runtime_release.py tests/test_runtime_release.py tests/test_full_plan_continuity_r2.py && git commit -m 'fix(runtime): bind activation exemption to migration transaction'`
### Task 4: Add Explicit Migration Quiesce and Successor Verification

**Files:**
- Modify: `runtime/orchestrator/production_full_plan_runner.py`
- Modify: `runtime/orchestrator/operator_plan_execution.py`
- Extend: `tests/test_runtime_migration_handoff.py`
- Extend: `tests/test_production_full_plan_runner.py`

**Interfaces:**
- Produces: predecessor migration wait disposition distinct from `CANCELLED`; successor verification binds registered job identity, approved plan/spec SHA, authority-core SHA, resume gate, and durable initial state.
- Predecessor close reason is `MIGRATED_TO_SUCCESSOR`; it is not `COMPLETED`.

- [ ] **Step 1: Write RED quiesce/verify tests**

Require: migration quiesce leaves no active worker lease/effect; quiesced predecessor remains durable/nonterminal for transaction recovery; successor spec is sealed before quiesce; successor cannot change plan/spec/authority digests; successor registration under new runtime is verified before predecessor close; failed verification keeps predecessor recoverable and emits no synthetic PASS.

- [ ] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_runtime_migration_handoff tests.test_production_full_plan_runner -v`
Expected: new quiesce/verify assertions FAIL.

- [ ] **Step 3: Implement minimal state transition support**

Add only the migration-specific wait/disposition needed by the transaction. Reuse existing run lock, durable state SHA, receipt store, and job registration functions. Do not add provider selection, tool launching, approval inference, or completion semantics.

```python
def quiesce_for_runtime_migration(self, migration_id: str, successor_run_id: str) -> dict[str, Any]:
    handle = self._acquire_run_lock()
    try:
        state, _ = self.load()
        state["state"] = "WAITING_RESOURCE"
        state["last_error"] = "RUNTIME_MIGRATION_QUIESCED"
        state["lease"] = None
        state["migration_handoff"] = {"migration_id": migration_id, "successor_run_id": successor_run_id}
        return self._persist(state, {"event": "RUNTIME_MIGRATION_QUIESCED", "migration_id": migration_id})
    finally:
        self._release_run_lock(handle)

def close_migrated_predecessor(self, migration_id: str, successor_state_sha256: str) -> dict[str, Any]:
    state, _ = self.load()
    if state.get("migration_handoff", {}).get("migration_id") != migration_id:
        raise ProductionFullPlanError("migration handoff binding mismatch")
    state["state"] = "CANCELLED"
    state["terminal_reason"] = "MIGRATED_TO_SUCCESSOR"
    state["lease"] = None
    return self._persist(state, {"event": "MIGRATED_TO_SUCCESSOR", "successor_state_sha256": successor_state_sha256})
```

- [ ] **Step 4: Run GREEN and exact crash-point state checks**

Validate state at: after PREPARED, after quiesce, after activation, after successor registration, after successor verification, and after predecessor close. Each checkpoint must be durably reloadable.

- [ ] **Step 5: Commit**

`git add runtime/orchestrator/production_full_plan_runner.py runtime/orchestrator/operator_plan_execution.py runtime/orchestrator/runtime_migration_handoff.py tests/test_runtime_migration_handoff.py tests/test_production_full_plan_runner.py && git commit -m 'feat(full-plan): preserve ownership across runtime migration'`

### Task 5: Detect Terminal Orphans and Repair Missing Attention

**Files:**
- Modify: `runtime/orchestrator/production_full_plan_boot.py`
- Extend: `tests/test_full_plan_continuity_r2.py`
- Extend: `tests/test_production_attention_watch.py`

**Interfaces:**
- Produces idempotent Attention kinds `RUNTIME_MIGRATION_ORPHANED` and `RUNTIME_MIGRATION_RECOVERY_REQUIRED`.
- `COMPLETED` stays silent; `BLOCKED`/`FAILED` keep existing behavior; ordinary explicit user/superseded cancellation is not mislabeled as migration orphan.

- [ ] **Step 1: Write RED orphan-detection tests**

Reproduce the real incident shape: predecessor terminal `CANCELLED / RUNTIME_ACTIVATION_MIGRATION`, no verified successor, migration evidence incomplete. Assert reconciler publishes exactly one orphan Attention and repeat reconcile is idempotent. Add cases for verified successor, user cancel, superseded baseline, BLOCKED/FAILED, and COMPLETED.

- [ ] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_full_plan_continuity_r2 tests.test_production_attention_watch -v`
Expected: real-incident orphan case FAIL because current reconciler skips CANCELLED.

- [ ] **Step 3: Implement terminal disposition validation**

On terminal reconciliation, inspect migration transaction/successor evidence before deciding silence. Publish outbound-only Attention for missing/unverified migration successor or incomplete recoverable transaction. Do not auto-resume from this code path.

```python
if status == "CANCELLED":
    disposition = validate_terminal_migration_disposition(job, state)
    if disposition.kind == "ORPHANED":
        supervisor.attention_outbox.publish(
            kind="RUNTIME_MIGRATION_ORPHANED", state=status,
            reason=disposition.reason, details={"source": "periodic_reconciler"},
        )
    elif disposition.kind == "RECOVERY_REQUIRED":
        supervisor.attention_outbox.publish(
            kind="RUNTIME_MIGRATION_RECOVERY_REQUIRED", state=status,
            reason=disposition.reason, details={"source": "periodic_reconciler"},
        )
```

- [ ] **Step 4: Run GREEN and dedup regression**

Required: repeated reconciliation does not multiply equivalent Attention; Watch still returns read-only JSON and never mutates state.

- [ ] **Step 5: Commit**

`git add runtime/orchestrator/production_full_plan_boot.py tests/test_full_plan_continuity_r2.py tests/test_production_attention_watch.py && git commit -m 'fix(attention): surface orphaned runtime migrations'`
### Task 6: Prove Crash Recovery and Authority Non-Expansion

**Files:**
- Extend: `tests/test_runtime_migration_handoff.py`
- Extend: `tests/test_full_plan_continuity_r2.py`
- Create: `tests/test_runtime_migration_authority_negative_space.py`

**Interfaces:**
- Consumes: Tasks 2-5 migration lifecycle.
- Produces: deterministic restart/reconcile behavior and negative-space evidence for approval/provider/effect/completion/Attention boundaries.

- [ ] **Step 1: Add six crash-point fixtures**

Inject process loss after: `PREPARED`; `PREDECESSOR_QUIESCED`; `RUNTIME_ACTIVATED`; `SUCCESSOR_REGISTERED`; `SUCCESSOR_VERIFIED`; `PREDECESSOR_CLOSED` before evidence publication. On restart, require either idempotent continuation of the same transaction or `BLOCKED` + durable Attention.

- [ ] **Step 2: Add authority-negative tests**

Scan/import the migration module and prove it has no callable path to Provider Router selection, `SingleToolBroker.execute`, approval mutation, completion declaration, or Attention-driven resume. Add poisoned successor digests and arbitrary-run IDs and require fail-closed behavior.

- [ ] **Step 3: Run focused adversarial suite**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_runtime_migration_handoff tests.test_runtime_migration_authority_negative_space tests.test_full_plan_continuity_r2 -v`
Required: all crash and authority tests PASS.

- [ ] **Step 4: Run adjacent authority regression**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_provider_router tests.test_production_provider_router_integration tests.test_tool_authorization tests.test_effect_evidence_bridge tests.test_completion_authority tests.test_recovery_e2e tests.test_production_attention_watch -v`
Required: no authority or recovery regression.

- [ ] **Step 5: Commit**

`git add tests/test_runtime_migration_handoff.py tests/test_runtime_migration_authority_negative_space.py tests/test_full_plan_continuity_r2.py && git commit -m 'test(full-plan): cover migration crash and authority boundaries'`

### Task 7: Record EDP Remediation Evidence and Validate the Skill Change

**Files:**
- Create: `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/EDP_CONTINUITY_PRE_REMEDIATION.json`
- Create: `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/EDP_CONTINUITY_POST_REMEDIATION.json`
- Create: `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/SKILL_CONTINUITY_PRESSURE_TEST.md`

**Interfaces:**
- Records exact evidence for `EDP-CONT-001..005` and `ED-01..09` without changing runtime authority.

- [ ] **Step 1: Bind pre-remediation incident evidence**

Record R2 state SHA, terminal reason, missing TASK-014 receipt, missing R3, existing runtime activation evidence digest, and pre-change skill digest. Decision must be `FAIL / REMEDIATION_REQUIRED`.

- [ ] **Step 2: Record RED/GREEN pressure evidence**

The pressure record must show the original skill lacked explicit self-reference/successor reservation requirements and the modified skill rejects the same design unless continuity answers are present. Include all six adversarial variants and exact test names.

- [ ] **Step 3: Calculate post-remediation findings**

For each `EDP-CONT-001..005`, bind source/test evidence and require `PASS`. Record `BLOCKER_COUNT=0`, `UNRESOLVED_MAJOR_COUNT=0` for this remediation scope only; do not yet claim the whole project final ALL PASS.

- [ ] **Step 4: Commit**

`git add docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/EDP_CONTINUITY_PRE_REMEDIATION.json docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/EDP_CONTINUITY_POST_REMEDIATION.json docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/SKILL_CONTINUITY_PRESSURE_TEST.md && git commit -m 'docs(edp): close continuity root-cause remediation'`
### Task 8: Bind the Historical R2 Incident to the Active R3 Recovery Chain

**Files:**
- Operational: inspect the already-registered R3 Full Plan from Task 0; do not create another run in this task.
- Create: `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/R2_TO_SUCCESSOR_RECOVERY.json`

**Interfaces:**
- Predecessor: `FINAL-OP-20260920-R2`, immutable incident evidence, terminal `CANCELLED / RUNTIME_ACTIVATION_MIGRATION`.
- Successor: `FINAL-OP-20260920-R3`, already registered by Task 0 and bound to the approved remediation plan/spec.
- Resume point: unfinished original `TASK-014` closure followed by original `TASK-015` final EDP.

- [ ] **Step 1: Re-verify predecessor evidence before creating the successor**

Require R2 completed gates `TASK-003..TASK-013`; no `TASK-014.json` receipt; terminal reason exactly `RUNTIME_ACTIVATION_MIGRATION`; runtime activation evidence commit `208afea` remains reachable; current branch ancestry contains the incident and remediation commits.

- [ ] **Step 2: Verify the existing R3 successor without rewriting R2**

Load the canonical R3 `GPT_OPERATOR_PLAN` job, verify its plan/spec SHA-256 values, authority-core digest, `TASK-001..TASK-016` gate list, current completed receipts, and runtime identity. Do not alter R2 or create a parallel active owner.

- [ ] **Step 3: Create the recovery evidence**

`R2_TO_SUCCESSOR_RECOVERY.json` must contain predecessor state SHA, successor job digest/run ID, approved plan/spec/remediation digests, inherited original resume point, and explicit statement `R2_TASK_014_RECEIPT_SYNTHESIZED=false`.

- [ ] **Step 4: Run reconcile dry-run and live resume smoke**

From `runtime-current`, run production boot reconciliation over `/home/ywjo/AI-Workspace/project-workspace`. Required: successor is discoverable, no launch/import error, R2 remains terminal/historical, and no duplicate active owner exists.

- [ ] **Step 5: Commit only durable documentation, never `_workspace`**

`git add docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/R2_TO_SUCCESSOR_RECOVERY.json && git commit -m 'docs(full-plan): bind R2 successor recovery'`

### Task 9: Self-Apply the New Migration Transaction to the Remediation Runtime

**Files:**
- Operational mutation: `~/.local/share/global-gpt-harness/releases/*`
- Operational mutation: `~/.local/share/global-gpt-harness/runtime-current`
- Operational mutation: user systemd reconcile service/timer.
- Create: `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/CONTINUITY_RUNTIME_MIGRATION_EVIDENCE.json`

**Interfaces:**
- Validated code head is a clean commit containing Tasks 1-7.
- Migration uses the new transaction and the Task 8 successor as predecessor owner; any next successor identity is sealed by transaction before quiesce.

- [ ] **Step 1: Run full pre-migration regression**

Run exactly: `/tmp/gch-edp-allpass-venv/bin/python -m unittest discover -s tests -v`, `/tmp/gch-edp-allpass-venv/bin/python -m compileall -q runtime tests`, `git diff --check`, and `git status --short --branch`. Require zero failures/errors, compile/diff rc=0, and clean worktree. Capture test/skip count, HEAD, tree SHA, and full log SHA.

- [ ] **Step 2: Build and verify a new immutable runtime release**

Build from the exact validated code HEAD, verify `RUNTIME_RELEASE_MANIFEST.json`, source/tree binding, boot/attention/runtime migration module digests, and diagnostic configuration compatibility.

- [ ] **Step 3: Execute the transaction in the required order**

Seal successor spec -> create `PREPARED` transaction -> quiesce predecessor -> verify exact participant exemption -> activate runtime -> register successor from new runtime -> verify successor durable state -> close predecessor `MIGRATED_TO_SUCCESSOR`. Record every phase SHA.

- [ ] **Step 4: Prove crash recovery by controlled replay**

Use a non-production fixture transaction to stop/reload at each of the six crash points. Required: same transaction resumes idempotently or blocks with Attention; no duplicate effect/job ownership occurs.

- [ ] **Step 5: Reinstall/reload reconciler and verify Watch code identity**

Reconciler `WorkingDirectory` must remain `runtime-current`; job search root remains `/home/ywjo/AI-Workspace/project-workspace`; diagnostic env remains explicit and safe. Verify timer enabled/active, dry-run rc=0, and `production_attention_watch.py` SHA matches validated source.

- [ ] **Step 6: Commit runtime migration evidence**

Record release manifest digest, transaction phase chain, predecessor/successor identities, systemd verification, Attention SHA equality, and rollback evidence. Commit as `docs(runtime): record continuity-safe runtime migration`.

### Task 10: Add the Harness-Owned CLI-Anything Tool Manifest Contract

**Files:**
- Create: `runtime/tool_implementation/__init__.py`
- Create: `runtime/tool_implementation/manifest.py`
- Create: `tests/test_cli_anything_tool_manifest.py`

**Interfaces:**
- Produces immutable `ToolImplementationManifest` states `CANDIDATE` and `QUALIFIED`.
- Binds upstream source URL/ref/SHA, generated CLI artifact SHA, command allowlist, closed input/output schemas, effect class, verifier SHA, and generated-skill qualification state.

- [ ] **Step 1: Write RED manifest tests**

Require exact digest binding; reject mutable/unknown fields, generic `exec`/`shell`/`command` surfaces, wildcard commands, open schemas, missing verifier digests, and self-qualified generated skills.

- [ ] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_cli_anything_tool_manifest -v`
Expected: FAIL because the Tool Implementation manifest module does not exist.

- [ ] **Step 3: Implement the minimum immutable manifest**

Use canonical JSON SHA-256 and closed enums. `QUALIFIED` requires all source/artifact/allowlist/schema/verifier bindings plus explicit external qualification evidence; no method may grant Tool Authorization or register itself into `ClosedOperationRegistry`.

```python
@dataclass(frozen=True, slots=True)
class ToolImplementationManifest:
    manifest_id: str
    state: Literal["CANDIDATE", "QUALIFIED"]
    upstream_url: str
    upstream_commit: str
    generated_artifact_sha256: str
    allowed_argv0: str
    allowed_subcommands: Sequence[str]
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    effect_class: str
    verifier_sha256: str
    generated_skill_qualified: bool
    manifest_sha256: str
```
- [ ] **Step 4: Run GREEN + security-negative cases**

Required: valid candidate/qualified round-trip PASS; arbitrary shell, path traversal in command identity, bad source SHA, bad generated artifact SHA, and unqualified-skill activation all fail closed.

- [ ] **Step 5: Commit**

`git add runtime/tool_implementation tests/test_cli_anything_tool_manifest.py && git commit -m 'feat(tools): add immutable tool implementation manifest'`

### Task 11: Integrate CLI-Anything as a Qualified Adapter Factory, Not an Authority Layer

**Files:**
- Create: `runtime/tool_implementation/cli_anything_adapter.py`
- Create: `runtime/tool_implementation/qualification.py`
- Create: `tests/test_cli_anything_tool_implementation.py`
- Create: `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/CLI_ANYTHING_SOURCE_QUALIFICATION.json`

**Interfaces:**
- Upstream baseline: `https://github.com/HKUDS/CLI-Anything.git`, observed HEAD `810c18b0d1ab9b234bc996c9fd999318523a3ef0`; re-run `git ls-remote https://github.com/HKUDS/CLI-Anything.git HEAD` before qualification and record the observed SHA.
- Produces only candidate adapter artifacts/manifests and explicit qualification evidence; discovery/generation has `control_authority=NONE`.

- [ ] **Step 1: Write RED adapter/factory tests**

Cover explicit argv construction with `shell=False`, command/argument allowlists, structured path normalization, isolated HOME/XDG, secret-env stripping, bounded stdout/stderr, preflight, dry-run, artifact verification, and CLI-Hub/generator unavailable degradation.
- [ ] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_cli_anything_tool_implementation -v`
Expected: FAIL because no qualified CLI-Anything adapter factory exists.

- [ ] **Step 3: Implement bounded generation/qualification helpers**

The adapter factory may invoke only explicitly approved CLI-Anything generation/preflight commands in an isolated workspace. It must never expose its own generic command runner to Full Plan workers. Generated adapters remain `CANDIDATE` until exact artifact SHA, manifest SHA, verifier SHA, and qualification record all match.

```python
def build_cli_argv(manifest: ToolImplementationManifest, arguments: Mapping[str, Any]) -> list[str]:
    subcommand = str(arguments["subcommand"])
    if subcommand not in manifest.allowed_subcommands:
        raise ToolImplementationError("subcommand is not allowlisted")
    tokens = validate_closed_cli_arguments(manifest.input_schema, arguments)
    return [manifest.allowed_argv0, subcommand, *tokens]

def run_preflight(manifest: ToolImplementationManifest, arguments: Mapping[str, Any], *, cwd: Path) -> QualificationResult:
    argv = build_cli_argv(manifest, arguments)
    return _run_bounded(argv, cwd=cwd, isolated_env=True)
```

- [ ] **Step 4: Re-verify upstream and create source qualification evidence**

Run `git ls-remote https://github.com/HKUDS/CLI-Anything.git HEAD`, compare with the planned baseline, and clone/fetch the exact observed commit into an isolated temporary directory. Record license/source SHA and the subset of CLI-Anything mechanisms actually used. A changed upstream HEAD does not auto-upgrade the qualified baseline; the exact tested commit becomes the sealed qualification identity.

- [ ] **Step 5: Run GREEN and forbidden-surface scans**

Search generated/runtime code for `shell=True`, arbitrary `exec`/`shell`/`command` operation names, uncontrolled environment inheritance, self-registration, and direct Provider/Attention/Completion imports. Required: zero material hits.

- [ ] **Step 6: Commit**

`git add runtime/tool_implementation tests/test_cli_anything_tool_implementation.py docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/CLI_ANYTHING_SOURCE_QUALIFICATION.json && git commit -m 'feat(tools): integrate bounded cli-anything qualification'`
### Task 12: Route Qualified CLI Effects Through the Existing Broker and Effect Journal

**Files:**
- Modify: `runtime/orchestrator/production_tool_transport.py`
- Extend: `runtime/orchestrator/tool_authorization.py` only if a closed operation registration helper is required; do not change authorization semantics.
- Extend: `tests/test_cli_anything_tool_implementation.py`
- Create: `tests/test_cli_anything_broker_integration.py`

**Interfaces:**
- Consumes existing `RegisteredOperation`, `ClosedOperationRegistry`, `OperationIdentity`, `ToolEffectJournal`, and `SingleToolBroker.execute_with_private_result()`.
- Produces qualified launcher registration only for manifest-bound operation classes; generated adapters never call the broker themselves.

- [ ] **Step 1: Write RED end-to-end broker tests**

Test one read-only representative CLI and one sandboxed state-changing fixture. Require exact Tool Authorization contract, closed registry membership, EffectJournal intent/receipt, security scan PASS, artifact verifier PASS, and no launcher call when authorization fails.

- [ ] **Step 2: Add failure-injection RED cases**

Cover duplicate logical operation, crash after intent/before receipt, artifact-verification failure, bad manifest SHA, unsafe argument/path traversal, arbitrary-shell attempt, and unqualified generated-skill invocation. Each must fail closed without changing Full Plan control state.
- [ ] **Step 3: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest tests.test_cli_anything_broker_integration tests.test_cli_anything_tool_implementation -v`
Expected: new broker integration cases FAIL.

- [ ] **Step 4: Implement the minimum qualified launcher registration**

Register only manifest-qualified operation classes and exact launchers. Preserve existing authorization request construction, create-once intent/receipt semantics, ambiguous-recovery blocking, and output security validation. Installation/activation of a generated adapter remains a distinct authorized effect from discovery/generation.

```python
def qualified_cli_registered_operation(manifest: ToolImplementationManifest) -> RegisteredOperation:
    if manifest.state != "QUALIFIED":
        raise ToolAuthorizationError("unqualified tool implementation blocked")
    return RegisteredOperation(
        operation_registration_id=manifest.manifest_id,
        operation_class_id=_operation_class_id(manifest),
        capability_class=_capability_class(manifest),
        operation_intent=_operation_intent(manifest),
        effect_class=manifest.effect_class,
        input_schema=manifest.input_schema,
        output_schema=manifest.output_schema,
    )
```

- [ ] **Step 5: Run GREEN + adjacent authority regression**

Run the CLI integration tests plus `tests.test_tool_authorization tests.test_effect_evidence_bridge tests.test_completion_authority tests.test_production_provider_router_integration`. Required: all PASS; no provider/completion authority movement.

- [ ] **Step 6: Commit**

`git add runtime/orchestrator/production_tool_transport.py runtime/orchestrator/tool_authorization.py tests/test_cli_anything_broker_integration.py tests/test_cli_anything_tool_implementation.py && git commit -m 'feat(tools): broker qualified cli implementations'`

### Task 13: Qualify CLI-Anything TI-01..TI-08 and Close the Scope-Integrity Amendment

**Files:**
- Create: `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/CLI_ANYTHING_EDP_QUALIFICATION.json`
- Create: `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/CLI_ANYTHING_EDP_QUALIFICATION.md`
- Create: `tests/test_cli_anything_authority_negative_space.py`

**Interfaces:**
- Produces measured evidence for `TI-01..TI-08` and `TI-INV-01..07` only; it does not declare the whole project ALL PASS.
- [ ] **Step 1: Run the complete CLI-Anything qualification matrix**

Execute manifest, adapter, broker, failure-injection, and negative-space suites. Bind source SHA, generated artifact SHA, manifest/verifier digests, read-only E2E result, sandboxed state-changing result, duplicate/recovery behavior, and unavailable-degradation evidence.

- [ ] **Step 2: Prove TI-01..TI-08 and TI-INV-01..07 coverage**

For every domain and invariant record exact tests/artifacts and PASS/FAIL. Explicitly bind `TI-INV-01`, `TI-INV-02`, `TI-INV-03`, `TI-INV-04`, `TI-INV-05`, `TI-INV-06`, and `TI-INV-07`; the last proves disable/unavailable CLI-Anything restores pre-integration behavior without changing Full Plan authority. `DOMAIN_EVIDENCE_COVERAGE` for the CLI-Anything amendment must be `100%`; any missing applicable evidence keeps the amendment open.

- [ ] **Step 3: Run authority negative-space scan**

Require zero material evidence of generic arbitrary shell, self-authorization/registration, direct provider selection, direct Attention, direct completion, governance mutation, or Tool Authorization/Broker/EffectJournal bypass.

- [ ] **Step 4: Commit**

`git add docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/CLI_ANYTHING_EDP_QUALIFICATION.* tests/test_cli_anything_authority_negative_space.py && git commit -m 'docs(edp): qualify cli-anything tool implementation'`

### Task 14: Close the Interrupted Original TASK-014 Under the Successor Full Plan

**Files:**
- Create/Update: `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/RUNTIME_ACTIVATION_EVIDENCE.json`
- Create: `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/ORIGINAL_TASK014_SUCCESSOR_CLOSURE.json`
- Operational: successor Full Plan receipt only; historical R2 receipt directory remains unchanged.

**Interfaces:**
- Consumes Tasks 1-13 evidence, the historical `208afea` activation evidence, and the current successor Full Plan state.
- Produces a new successor-run TASK-014 closure receipt/evidence; never creates `FINAL-OP-20260920-R2/TASK-014.json`.- [ ] **Step 1: Re-run final pre-closure regression on the successor branch**

Run full unittest discovery, compileall, `git diff --check`, and `git status --short --branch`. Require zero failures/errors and clean tracked state before generating closure evidence.

- [ ] **Step 2: Verify all original TASK-014 obligations**

Re-check immutable runtime release binding, `runtime-current`, systemd reconciler/timer, explicit diagnostic env, Attention Watch code identity, Graphify 0.9.58, CodeGraph 0.20.1, advisory config, OmniRoute listener/auth smoke, and continuity-safe migration evidence.

- [ ] **Step 3: Verify scope-integrity additions**

Require Graphify production read-only evidence, CodeGraph read-only evidence, Holmes-inspired RCA evidence, CLI-Anything TI-01..TI-08 qualification, and continuity remediation PASS. Missing any item blocks TASK-014 closure.

- [ ] **Step 4: Seal successor TASK-014 closure**

Write `ORIGINAL_TASK014_SUCCESSOR_CLOSURE.json` with all evidence digests and `historical_r2_receipt_preserved_missing=true`. Create the PASS receipt only for the active successor run after the closure artifact digest is fixed.

- [ ] **Step 5: Commit**

`git add docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/RUNTIME_ACTIVATION_EVIDENCE.json docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/ORIGINAL_TASK014_SUCCESSOR_CLOSURE.json && git commit -m 'docs(full-plan): close original task014 through successor'`

### Task 15: Execute Final EDP Re-Diagnosis and Seal the Operational Baseline

**Files:**
- Create: `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/EDP_FINAL_ALL_PASS.json`
- Create: `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/EDP_FINAL_ALL_PASS.md`
- Create: `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/AI_OFFICE_HARNESS_FINAL_OPERATIONAL_BASELINE_DECLARATION.json`
- Create: `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/FINAL_MANIFEST.json`
- Modify: `docs/harness/CURRENT_OPERATIONAL_STATE.json`
- Modify: `docs/DEVELOPMENT_PLAN.txt`
**Interfaces:**
- Final baseline ID: `AI_OFFICE_HARNESS_FINAL_OPERATIONAL_BASELINE`.
- Final decision is `ALL_PASS / GO` only when the Universal EDP gate is satisfied by measured evidence.

- [ ] **Step 1: Run the complete post-remediation verification suite**

Run `/tmp/gch-edp-allpass-venv/bin/python -m unittest discover -s tests -v`, `/tmp/gch-edp-allpass-venv/bin/python -m compileall -q runtime tests`, `git diff --check`, live runtime reconcile dry-run, Attention Watch JSON smoke, Graphify/CodeGraph live smoke, diagnostic config safety validation, CLI-Anything qualified E2E smoke, and OmniRoute listener/auth smoke. Capture exact counts, return codes, HEAD/tree SHA, and log SHA-256.

- [ ] **Step 2: Execute the mandatory EDP evidence matrix and RTM**

Applicable domains must include canonical source/baseline, design-skill continuity, self-reference detection, migration transaction, successor continuity, terminal orphan Attention, recovery, Provider authority, Tool/effect authority, Completion authority, Graphify, CodeGraph, RCA, CLI-Anything TI-01..TI-08, diagnostic freshness/conflict/fallback/security, governance projection, operational restart path, and interrupted TASK-014/TASK-015 closure. Require `MUST_REQUIREMENT_COVERAGE=100%`, `MUST_TRACEABILITY_COVERAGE=100%`, and `DOMAIN_EVIDENCE_COVERAGE=100%`.

- [ ] **Step 3: Run Negative-Space, Cross-Document, Adversarial Second Pass, and PASS Challenge**

Try to falsify at least: no zero-owner migration gap; no orphaned non-COMPLETED terminal without successor/Attention; no generic active-job bypass; no provider/tool/completion authority movement; no arbitrary CLI shell surface; no generated-skill self-activation; no stale diagnostic advisory; no historical R2 receipt fabrication; no stale governance OPEN projection; runtime-current independent of disposable worktrees.
- [ ] **Step 4: Calculate final closure metrics from evidence only**

Required exact values: `BLOCKER_COUNT=0`, `UNRESOLVED_MAJOR_COUNT=0`, `MUST_REQUIREMENT_COVERAGE=100%`, `MUST_TRACEABILITY_COVERAGE=100%`, `DOMAIN_EVIDENCE_COVERAGE=100%`, `NEGATIVE_SPACE_OPEN_MATERIAL_COUNT=0`, `CROSS_DOCUMENT_CONFLICT_COUNT=0`, `BROKEN_REFERENCE_COUNT=0`, `UNRESOLVED_MATERIAL_TBD_COUNT=0`, `UNRESOLVED_MATERIAL_OPEN_QUESTION_COUNT=0`, `ADVERSARIAL_NEW_BLOCKER_MAJOR=0`, `PASS_CHALLENGE_OPEN_COUNT=0`, `SOURCE_AUTHORITY_STATUS=VALID`, `REGRESSION_REDIAGNOSIS_STATUS=PASS`, `MATERIAL_DEFECT_SEARCH=EXHAUSTED_FOR_AVAILABLE_EVIDENCE`.

- [ ] **Step 5: Write final closure artifacts only if Step 4 is satisfied**

`EDP_FINAL_ALL_PASS.*` binds every measured domain. The baseline declaration is emitted only when the JSON EDP decision is `ALL_PASS`. `FINAL_MANIFEST.json` hashes every closure artifact and predecessor/remediation/CLI qualification evidence.

- [ ] **Step 6: Update current-state projection to final GO**

Set `CURRENT_OPERATIONAL_STATE=AI_OFFICE_HARNESS_FINAL_OPERATIONAL_BASELINE`, `FINAL_EDP=ALL_PASS`, `RUNTIME_RELEASE=ACTIVE`, `GRAPHIFY=PRODUCTION_READ_ONLY_ACTIVE`, `CODEGRAPH=PRODUCTION_READ_ONLY_ACTIVE`, `HOLMES_INSPIRED_RCA=ACTIVE_READ_ONLY`, `CLI_ANYTHING=QUALIFIED_TOOL_IMPLEMENTATION`, and `DIAGNOSTIC_INTELLIGENCE=ADVISORY`. Preserve historical records below unchanged.

- [ ] **Step 7: Commit administrative closure**

`git add docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL docs/harness/CURRENT_OPERATIONAL_STATE.json docs/DEVELOPMENT_PLAN.txt && git commit -m 'docs(harness): seal final operational baseline'`

### Task 16: Publish, Fast-Forward Main, and Rebuild the Exact Pushed Runtime

**Files:**
- Git refs/remote only; no new source files unless verification produces a documented blocker.
- Operational: immutable runtime release and `runtime-current`.

**Interfaces:**
- Consumes the final closure HEAD from Task 15.
- Produces origin upgrade branch == origin/main == runtime-current manifest source HEAD.
- [ ] **Step 1: Push the qualified upgrade branch and prove upstream identity**

Run `git push origin upgrade/ai-office-omniroute-ph7-20260920`, then require branch upstream `0/0` and remote branch HEAD equal to the local closure HEAD. Never force-push.

- [ ] **Step 2: Check main ancestry and create a clean integration worktree**

Run `git fetch origin main` and `git merge-base --is-ancestor origin/main <CLOSURE_HEAD>`. Required rc=0. Create a temporary clean main integration worktree and run `git merge --ff-only <CLOSURE_HEAD>`; any non-fast-forward condition is a blocker.

- [ ] **Step 3: Re-run full regression from fast-forwarded main**

Run the exact full unittest discovery, compileall, `git diff --check`, diagnostic/CLI focused suites, and runtime-migration focused suites from the main integration worktree. Required: zero failures/errors and clean worktree.

- [ ] **Step 4: Push main without force and verify remote equality**

Run `git push origin main`; require `git rev-parse origin/main == <CLOSURE_HEAD>` and remote upgrade branch == the same HEAD.

- [ ] **Step 5: Build and activate the exact pushed closure runtime**

Build a new immutable release from `<CLOSURE_HEAD>`, use the continuity-safe migration transaction if an active owner exists, activate `runtime-current`, and re-run reconcile dry-run, Attention Watch JSON smoke, Graphify/CodeGraph versions, CLI-Anything qualified adapter smoke, diagnostic config validation, and systemd timer checks.

- [ ] **Step 6: Final operator evidence**

Require simultaneously: remote upgrade/main == closure HEAD; runtime manifest source HEAD == closure HEAD; boot/attention/migration module SHA equality; timer active; diagnostic config `ADVISORY` with mode 0600; Graphify 0.9.58; CodeGraph 0.20.1 exact qualified hash; CLI-Anything exact qualified source/artifact manifest; OmniRoute loopback/auth PASS; Groq remains `ACTIVE / FREE_TIER_ONLY`; full repository regression PASS. Only then report `AI_OFFICE_HARNESS_FINAL_OPERATIONAL_BASELINE = ALL_PASS / GO`.
