# Workstream C — Evidence / Effects / Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move new canonical Harness evidence out of disposable worktrees, bind AUTO to canonical effect reconciliation, and establish one lock/fencing hierarchy with legacy read compatibility.

**Architecture:** C0 adds stable state-root resolution and dual legacy discovery. Later tasks bind ToolEffectJournal evidence to attestation, enforce run-lock-first ownership, prove worktree-cleanup retention, and seal authority negative-space.

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
- Owns: HWO-MUST-012~014,017~018 plus C0 prerequisite for HWO-MUST-001/013.

## Review Focus

1. Stable state root cannot resolve inside/symlink into a project worktree.
2. Legacy state stays byte-unchanged and readable.
3. Intent without effect receipt is ambiguous and blocks AUTO.
4. Lock order is run -> transaction -> immutable evidence serialization only.
5. Worktree deletion cannot delete new canonical evidence.

---

### Task C0: Stable Harness State Root + Legacy Discovery

**Requirements:** HWO-MUST-001,013,017.

**Files:**
- Create `runtime/orchestrator/harness_state_root.py`
- Modify `runtime/orchestrator/production_full_plan_entry.py`
- Modify `runtime/orchestrator/production_full_plan_boot.py`
- Modify `runtime/orchestrator/production_attention_watch.py`
- Create `tests/test_harness_state_root.py`

**Interfaces:**
- Consumes: XDG/GCH environment and legacy roots
- Produces: stable root resolver + stable/legacy deduplicated discovery

- [ ] **Step 1: Write failing tests**

```python
def test_default_state_root_is_not_project_worktree(monkeypatch, tmp_path):
    monkeypatch.delenv("GCH_STATE_ROOT", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = resolve_harness_state_root(project_root=tmp_path / "project")
    assert root == (tmp_path / "state" / "global-gpt-harness").resolve()
    assert root != (tmp_path / "project").resolve()
```
Also reject worktree-nested/symlinked roots and prove stable+legacy discovery deduplicates `(project_id, run_id, authority_core_sha256)` without rewriting legacy files.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -v tests.test_harness_state_root
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Resolve `${GCH_STATE_ROOT:-${XDG_STATE_HOME:-$HOME/.local/state}/global-gpt-harness}`. New stores use stable root; old jobs retain historical root behavior; discovery reads both without migration.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_harness_state_root tests.test_production_full_plan_entry tests.test_production_full_plan_boot tests.test_production_attention_watch
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/harness_state_root.py runtime/orchestrator/production_full_plan_entry.py runtime/orchestrator/production_full_plan_boot.py runtime/orchestrator/production_attention_watch.py tests/test_harness_state_root.py && git commit -m 'feat(harness): add stable durable state root'
```

---

### Task C1: Canonical Effect Reconciliation for AUTO

**Requirements:** HWO-MUST-012,018.

**Files:**
- Modify `runtime/orchestrator/effect_evidence_bridge.py`
- Modify `runtime/orchestrator/verified_gate_attestation.py`
- Modify `tests/test_effect_evidence_bridge.py`
- Modify `tests/test_verified_gate_attestation.py`

**Interfaces:**
- Consumes: Gate contract external_effect_policy + ToolEffectJournal
- Produces: read-only EffectReconciliationEvidence required by attestation

- [ ] **Step 1: Write failing tests**

```python
def test_intent_without_receipt_is_ambiguous():
    journal, contract, scope = fixture_begun_effect_without_receipt()
    result = verify_auto_effect_reconciliation(journal, contract=contract, expected_scope=scope)
    assert result.status == "BLOCKED"
    assert result.reason_taxonomy == "AMBIGUOUS_EFFECT_EVIDENCE"
```
Also assert `NO_EXTERNAL_EFFECT` requires zero effects and governed repository effect requires one matching authorized intent/receipt with security PASS.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -v tests.test_effect_evidence_bridge tests.test_verified_gate_attestation
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

DCC reads canonical effect bridge only; it never executes effects or mutates journal. Ambiguous/missing evidence blocks or requires decision per R2.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_effect_evidence_bridge tests.test_verified_gate_attestation tests.test_tool_authorization
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/effect_evidence_bridge.py runtime/orchestrator/verified_gate_attestation.py tests/test_effect_evidence_bridge.py tests/test_verified_gate_attestation.py && git commit -m 'feat(dcc): verify governed effect reconciliation'
```

---

### Task C2: Run-Lock-First Hierarchy + Fencing

**Requirements:** HWO-MUST-014,018.

**Files:**
- Modify `runtime/orchestrator/production_full_plan_runner.py`
- Modify `runtime/orchestrator/gate_continuation_transaction.py`
- Modify `runtime/orchestrator/durable_continuation.py`
- Create `tests/test_durable_continuation_locking.py`

**Interfaces:**
- Consumes: A transaction/DCC modules
- Produces: bounded run->transaction->evidence lock hierarchy, `assert_current_epoch(owner_token)`, and `seal_attested_receipt_with_owner(owner_token, attestation)`

- [ ] **Step 1: Write failing tests**

```python
def test_stale_epoch_cannot_seal_receipt():
    supervisor, tx = fixture_contending_continuation_owners()
    stale = tx.owner_token
    current = supervisor.claim_attested_continuation_owner(expected_gate_id="TASK-002")
    assert current.epoch > stale.epoch
    with pytest.raises(ProductionFullPlanError, match="stale.*epoch"):
        seal_attested_receipt_with_owner(stale, fixture_verified_attestation())
```
Also assert reverse lock acquisition fails boundedly and foreground/reconciler contention yields one owner with no deadlock.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -v tests.test_durable_continuation_locking
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Full Plan run lock is outer. Transaction lock is inner. Repeat stale-epoch check immediately before Git commit, receipt seal and Full Plan resume.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_durable_continuation_locking tests.test_production_full_plan_runner tests.test_production_full_plan_boot
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/production_full_plan_runner.py runtime/orchestrator/gate_continuation_transaction.py runtime/orchestrator/durable_continuation.py tests/test_durable_continuation_locking.py && git commit -m 'feat(dcc): fence continuation under canonical run lock'
```

---

### Task C3: Stable Namespace Retention + Worktree Cleanup Proof

**Requirements:** HWO-MUST-013,017.

**Files:**
- Modify new store constructors for jobs/runs/receipts/migrations/attention/DCC/checkpoints
- Create `tests/test_harness_state_retention.py`

**Interfaces:**
- Consumes: C0 stable root + A/B/C stores
- Produces: new canonical namespaces all below stable root

- [ ] **Step 1: Write failing tests**

```python
def test_worktree_cleanup_preserves_canonical_evidence(tmp_path):
    fixture = fixture_new_run_with_all_durable_evidence(tmp_path)
    fixture_remove_project_worktree(fixture.project_root)
    assert fixture.state_path.is_file()
    assert fixture.receipt_path.is_file()
    assert fixture.attention_path.is_file()
    assert fixture.transaction_path.is_file()
```
Also hash legacy evidence before/after and assert it was neither moved nor rewritten.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -v tests.test_harness_state_retention
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Route new object creation to stable root. Do not mass-migrate existing historical `_workspace`; legacy readers remain.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_harness_state_retention tests.test_harness_state_root tests.test_runtime_migration_handoff
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator tests/test_harness_state_retention.py && git commit -m 'feat(harness): retain canonical evidence outside worktrees'
```

---

### Task C4: Harness Authority Negative-Space Seal

**Requirements:** HWO-MUST-018,020.

**Files:**
- Create `tests/test_dcc_harness_authority_negative_space.py`

**Interfaces:**
- Consumes: A-C production modules
- Produces: source/import negative-space proof

- [ ] **Step 1: Write failing tests**

```python
def test_dcc_module_has_no_forbidden_authority_imports():
    source = Path("runtime/orchestrator/durable_continuation.py").read_text(encoding="utf-8")
    for forbidden in ("route_request(", "execute_with_private_result(", "activate_runtime_release(", "create_user_approval("):
        assert forbidden not in source
```
Add equivalent source/call-path assertions for wait recovery, Attention delivery, Operator checkpointing, and next-Gate selection; include a forbidden fixture proving the guard fails.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -v tests.test_dcc_harness_authority_negative_space tests.test_runtime_migration_authority_negative_space
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Assert prohibited symbols/imports/call paths are absent from DCC, wait recovery, Attention delivery and checkpoint modules. Include a deliberately forbidden fixture proving the test can fail.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_dcc_harness_authority_negative_space tests.test_runtime_migration_authority_negative_space tests.test_provider_router tests.test_tool_authorization
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git add tests/test_dcc_harness_authority_negative_space.py && git commit -m 'test(harness): seal DCC authority negative space'
```

---
