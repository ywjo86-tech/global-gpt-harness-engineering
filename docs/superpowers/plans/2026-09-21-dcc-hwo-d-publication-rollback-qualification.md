# Workstream D — Publication / Rollback / Live Qualification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the remediated Harness with distinct validation/publication identities, a real reverse-activation rollback window, and a live systemd-driven AUTO canary before predecessor closure.

**Architecture:** D is effect-gated and starts only after A-C integration EDP is green. It adds publication identity evidence, migration-v2 active qualification, exact reverse activation to sealed last-known-good runtime, and production-shape live canary evidence.

**Tech Stack:** Python 3.12, stdlib, Git, unittest, existing Global GPT Harness orchestration/runtime infrastructure.

**Spec:** `docs/superpowers/specs/2026-09-21-dcc-harness-wide-operational-remediation-design.md`
**Parent Spec:** `docs/superpowers/specs/2026-09-20-durable-continuation-controller-design.md`
**Approved Spec SHA256:** `6a46268f1b0b4a7e23b5be62642bbe8973d2ad6dd9f17534a0032aac56edad03`
**Plan Status:** REVIEWED-CANDIDATE / EXECUTION-APPROVAL-PENDING

## Global Constraints

- Stable executable predecessor is `a40626c31353f90c0d4c9e677d3886ea5ccce393` until an explicitly approved runtime migration occurs.
- `project_root`, immutable `runtime_code_root`, and durable `harness_state_root` are distinct bindings.
- Full Plan remains sole Task/Gate/fan-in/next-state authority; DCC/wait recovery/Attention/checkpoints gain no alternate authority.
- Router/MPRF remains provider selection/runtime-fact authority; Full MCP remains effect authority; RuntimeMigrationTransaction remains runtime activation authority.
- `GATE_BY_GATE` and genuine `WAITING_APPROVAL` boundaries never auto-resume.
- Legacy jobs/receipts/state/migrations remain readable/manual and never acquire AUTO by inference.
- Every source task uses RED -> minimal GREEN -> focused regression -> adjacent authority regression -> local commit.
- Push, runtime activation, live notification transport, credentials, network effects, and publication remain explicit effect boundaries.
- Owns: HWO-MUST-007,015,016,020.

## Review Focus

1. Executable drift after EDP invalidates publication.
2. Bookkeeping-only ROLLED_BACK is not runtime rollback.
3. Reverse activation cannot bypass unrelated active-job guards.
4. Canary must lose initiating foreground Operator and finish via systemd/reconciler.
5. Predecessor closure requires sealed active-runtime qualification digest.

---

### Task D0: Validated / Closure / Publication Identity

**Requirements:** HWO-MUST-007,020.

**Files:**
- Create `runtime/orchestrator/publication_identity.py`
- Modify `runtime/orchestrator/runtime_release.py`
- Create `tests/test_publication_identity.py`

**Interfaces:**
- Consumes: A-C validated code candidate
- Produces: `verify_publication_identity(repo, validated_code_head, closure_head, publication_head) -> PublicationIdentity` with executable no-drift proof

- [ ] **Step 1: Write failing tests**

```python
def test_executable_drift_invalidates_publication():
    repo, validated, closure = fixture_docs_only_closure_repo()
    publication = fixture_commit_change(repo, "runtime/orchestrator/example.py", "changed\n")
    result = verify_publication_identity(repo, validated, closure, publication)
    assert result.eligible is False
    assert result.reason == "EXECUTABLE_SURFACE_DRIFT"
```
Also assert docs-only descendant is accepted and non-descendant publication head is rejected.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -v tests.test_publication_identity
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Bind `validated_code_head`, `closure_head`, `publication_head` separately and hash the executable-surface diff proof defined by release manifest.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_publication_identity tests.test_runtime_release
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/publication_identity.py runtime/orchestrator/runtime_release.py tests/test_publication_identity.py && git commit -m 'feat(release): bind validation closure and publication identities'
```

---

### Task D1: Migration v2 + ACTIVE_RUNTIME_QUALIFICATION

**Requirements:** HWO-MUST-015,017,018.

**Files:**
- Modify `runtime/orchestrator/runtime_migration_handoff.py`
- Modify `runtime/orchestrator/production_full_plan_runner.py`
- Modify `tests/test_runtime_migration_handoff.py`

**Interfaces:**
- Consumes: v1 migration reader + source/target release manifests
- Produces: versioned v2 source rollback bindings + qualification phase/digest

- [ ] **Step 1: Write failing tests**

```python
def test_predecessor_close_requires_active_runtime_qualification_digest():
    store, tx = fixture_migration_v2_store_at_successor_verified()
    with pytest.raises(MigrationHandoffError, match="qualification"):
        store.advance(tx.migration_id, MigrationPhase.PREDECESSOR_CLOSED)
```
Also prove v1 stays readable, v2 binds source last-known-good release, and rollback remains legal through qualification but not after close.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -v tests.test_runtime_migration_handoff
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Add migration-v2 under same RuntimeMigrationTransaction authority. Source head/tree/manifest and target bindings are immutable. `ACTIVE_RUNTIME_QUALIFICATION` precedes predecessor close.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_runtime_migration_handoff tests.test_runtime_migration_authority_negative_space
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/runtime_migration_handoff.py runtime/orchestrator/production_full_plan_runner.py tests/test_runtime_migration_handoff.py && git commit -m 'feat(runtime): add active qualification migration phase'
```

---

### Task D2: Reverse Activate Sealed Last-Known-Good Runtime

**Requirements:** HWO-MUST-015,020.

**Files:**
- Modify `runtime/orchestrator/runtime_release.py`
- Modify `runtime/orchestrator/runtime_migration_handoff.py`
- Modify `tests/test_runtime_release.py`
- Modify `tests/test_runtime_migration_handoff.py`

**Interfaces:**
- Consumes: D1 migration-v2 in pre-close phase
- Produces: guarded `reverse_activate_runtime_release(source_manifest, runtime_link, *, job_search_root, migration_transaction)` + restored-runtime evidence

- [ ] **Step 1: Write failing tests**

```python
def test_reverse_activation_restores_bound_source_release(tmp_path):
    source, target, link, tx = fixture_active_target_with_quiesced_migration(tmp_path)
    restored = reverse_activate_runtime_release(source, link, job_search_root=tmp_path, migration_transaction=tx)
    assert restored.resolve() == Path(source.release_path).resolve()
    assert link.resolve() == Path(source.release_path).resolve()
```
Also block unrelated active jobs, wrong source manifest, and non-quiesced successor; require restored-runtime evidence before ROLLED_BACK.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -v tests.test_runtime_release tests.test_runtime_migration_handoff
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Atomically retarget runtime-current to exact bound source release only for the migration-bound quiesced owner set, verify source manifest/systemd entry, then record ROLLED_BACK. Never use bookkeeping rollback alone.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_runtime_release tests.test_runtime_migration_handoff
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/runtime_release.py runtime/orchestrator/runtime_migration_handoff.py tests/test_runtime_release.py tests/test_runtime_migration_handoff.py && git commit -m 'feat(runtime): reverse activate last-known-good release'
```

---

### Task D3: Live Active-Runtime AUTO Canary

**Requirements:** HWO-MUST-016,020.

**Files:**
- Create `runtime/orchestrator/live_auto_canary.py`
- Create `tests/test_live_auto_canary.py`

**Interfaces:**
- Consumes: active immutable runtime + stable state root + A-C functionality
- Produces: harmless 3+ Gate AUTO canary spec/evidence collector

- [ ] **Step 1: Write failing tests**

```python
def test_canary_completes_after_foreground_owner_loss():
    canary = fixture_three_gate_auto_canary()
    canary.run_gate_a_then_drop_foreground_owner()
    canary.run_periodic_reconciler_until_idle()
    state = canary.load_state()
    assert state["state"] == "COMPLETED"
    assert state["terminal_reason"] == "ALL_GATES_COMPLETED"
    assert canary.chat_resume_count == 0
```
Also assert no external/system/network/package/credential effects and no duplicate owner/commit/receipt.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -v tests.test_live_auto_canary
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Build isolated canary workspace below stable state root. Gate A may create a bounded local artifact; after Gate A terminate initiating foreground owner; systemd/reconciler must finish B/C with v2 receipts and no chat resume.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_live_auto_canary tests.test_production_full_plan_boot tests.test_durable_continuation
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/live_auto_canary.py tests/test_live_auto_canary.py && git commit -m 'feat(runtime): add live AUTO canary qualification'
```

---

### Task D4: Explicitly Approved Publication + Final EDP

**Requirements:** HWO-MUST-007,015,016,019,020.

**Files:**
- Git refs/remotes
- Immutable runtime release/migration evidence
- No source modification except separately diagnosed blocker

**Interfaces:**
- Consumes: A-C ALL PASS + D0-D3 + explicit publication effect approval
- Produces: new stable baseline or legal rollback to last-known-good

- [ ] **Step 1: Write failing tests**

```python
def test_predecessor_cannot_close_before_live_qualification():
    supervisor, migration, successor_sha = fixture_migration_v2_at_successor_verified()
    assert migration.qualification_evidence_sha256 == ""
    with pytest.raises(ProductionFullPlanError, match="qualification"):
        supervisor.close_migrated_predecessor(migration.migration_id, successor_sha)
```
Also assert publication path refuses push/runtime activation without explicit effect-approval evidence.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -q tests.test_publication_identity tests.test_runtime_release tests.test_runtime_migration_handoff tests.test_live_auto_canary
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

After explicit approval: record validated code head; docs-only closure; ff-only branch/main push; build target release; migration-v2 activate; successor verify; active-runtime regression + systemd + 3-Gate canary + wait/Attention smoke; if any fail reverse activate; only PASS seals qualification digest and closes predecessor; then final Harness-wide EDP.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest discover -s tests -p 'test*.py' && python3 -m compileall -q runtime tests && git diff --check
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git status --short && git log -5 --oneline
```

---
