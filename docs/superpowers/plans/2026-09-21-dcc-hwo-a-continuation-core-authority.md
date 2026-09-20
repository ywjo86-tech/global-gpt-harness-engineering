# Workstream A — Continuation Core & Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement exact AUTO continuation authority, production builder injection, deterministic source lineage, receipt v2, complete transaction dispositions, and Full Plan-owned mechanical continuation.

**Architecture:** Preserve the exact GateContinuationContract wire schema, separate mutable project from immutable executor runtime, bind Git lineage/verified tree into attestation, and let only Full Plan consume mechanical continuation evidence.

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
- Owns: HWO-MUST-001~007 plus original DCC continuation requirements.

## Review Focus

1. Exact wire fields cannot be omitted/renamed/aliased.
2. Wrong previous receipt/non-descendant history must fail closed.
3. Verified tree must equal committed tree; TOCTOU is forbidden.
4. Crash after commit before journal persistence must reconcile without duplicate commit.
5. Legacy v1 receipt and contract-less jobs remain manual.

---

### Task A0: Three-Root Job Binding and Immutable Executor Runtime

**Requirements:** HWO-MUST-001,017.

**Files:**
- Modify `runtime/orchestrator/production_run_authority.py`
- Modify `runtime/orchestrator/production_full_plan_entry.py`
- Modify `runtime/orchestrator/operator_plan_execution.py`
- Test `tests/test_production_full_plan_entry.py`

**Interfaces:**
- Consumes: C0 stable-root resolver
- Produces: sealed project/runtime/state root identities

- [ ] **Step 1: Write failing tests**

```python
def test_project_head_may_advance_while_runtime_release_identity_stays_fixed():
    job, runtime_identity = fixture_registered_three_root_job()
    fixture_commit_project_change(Path(job["project_root"]), "project-only.txt")
    registered = load_registered_job(job["canonical_path"])
    validate_executor_runtime(registered)
    assert registered["executor_runtime_identity"] == runtime_identity
```
Also add exact negative assertions that mutating `runtime_code_root` raises `FullPlanJobError` and a state root nested under `project_root` is rejected.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -v tests.test_production_full_plan_entry
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Add a `JobRoots` validation projection. Executor identity is computed from immutable `runtime_code_root`; project Git lineage is validated separately. New jobs require stable state root; legacy jobs keep historical root behavior.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_production_full_plan_entry tests.test_operator_plan_execution
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/production_run_authority.py runtime/orchestrator/production_full_plan_entry.py runtime/orchestrator/operator_plan_execution.py tests/test_production_full_plan_entry.py && git commit -m 'feat(full-plan): separate project runtime and state roots'
```

---

### Task A1: Exact GateContinuationContract + Builder Injection

**Requirements:** HWO-MUST-002,003,017.

**Files:**
- Create `runtime/orchestrator/gate_continuation_contract.py`
- Modify `runtime/orchestrator/operator_plan_execution.py`
- Modify `runtime/orchestrator/production_run_authority.py`
- Create `tests/test_gate_continuation_contract.py`

**Interfaces:**
- Consumes: A0 root/job authority
- Produces: closed contract parser/digest and `continuation_contracts_by_gate` builder parameter

- [ ] **Step 1: Write failing tests**

```python
EXPECTED = {"schema_version","gate_id","continuation_policy","approved_base_head",
            "source_lineage_policy","allowed_write_paths","forbidden_paths",
            "required_verifiers","required_evidence_classes","commit_policy",
            "risk_classes","approval_coverage_ref","approval_coverage_digest",
            "external_effect_policy","runtime_migration_policy"}

def test_wire_schema_has_exact_approved_fields():
    contract = GateContinuationContract.from_mapping(fixture_auto_contract_mapping("TASK-001"))
    assert set(contract.canonical_projection()) == EXPECTED
```
Also add unknown-Gate, mismatched-`gate_id`, unknown-enum, authority-digest drift, and omitted-Gate=>MANUAL assertions.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -v tests.test_gate_continuation_contract
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Implement exact schema fields from Amendment §6 and closed enums. `build_operator_plan_job(*, project_root, harness_state_root, runtime_code_root, project_id, run_id, task_ids, approved_plan_path, approved_spec_path, approval_ref, continuation_contracts_by_gate=None)` accepts only declared Gates; no mapping means manual.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_gate_continuation_contract tests.test_operator_plan_execution
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/gate_continuation_contract.py runtime/orchestrator/operator_plan_execution.py runtime/orchestrator/production_run_authority.py tests/test_gate_continuation_contract.py && git commit -m 'feat(full-plan): seal per-gate continuation authority'
```

---

### Task A2: Source Lineage + Verified Gate Attestation

**Requirements:** HWO-MUST-004,007.

**Files:**
- Create `runtime/orchestrator/source_lineage.py`
- Create/modify `runtime/orchestrator/verified_gate_attestation.py`
- Create `tests/test_source_lineage.py`
- Modify `tests/test_verified_gate_attestation.py`

**Interfaces:**
- Consumes: A1 contract
- Produces: `verify_source_lineage()` and immutable attestation evidence

- [ ] **Step 1: Write failing tests**

```python
def test_descendant_chain_rejects_wrong_previous_receipt():
    repo, base, child = fixture_repo_with_linear_commits()
    contract = fixture_descendant_contract(approved_base_head=base)
    wrong = fixture_v2_receipt(source_head=fixture_unrelated_commit(repo))
    with pytest.raises(SourceLineageError, match="previous receipt lineage"):
        verify_source_lineage(contract, repo, previous_receipt=wrong, current_head=child)
```
Also assert EXACT_BASE rejects any other head, non-descendant history fails, and the attestation binds verified tree + changed-path digest.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -v tests.test_source_lineage tests.test_verified_gate_attestation
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Use argument-vector Git calls for `merge-base --is-ancestor`, `rev-parse HEAD^{tree}`, changed paths and parent checks. Persist evidence under stable state root; attestation cannot broaden authority.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_source_lineage tests.test_verified_gate_attestation
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/source_lineage.py runtime/orchestrator/verified_gate_attestation.py tests/test_source_lineage.py tests/test_verified_gate_attestation.py && git commit -m 'feat(dcc): bind source lineage and verified attestation'
```

---

### Task A3: Attested Receipt v2 + Complete Transaction Dispositions

**Requirements:** HWO-MUST-005,006,017.

**Files:**
- Create/modify `runtime/orchestrator/gate_continuation_transaction.py`
- Modify `runtime/orchestrator/operator_plan_execution.py`
- Create `tests/test_gate_continuation_transaction.py`

**Interfaces:**
- Consumes: A2 attestation
- Produces: manual v1 unchanged; AUTO v2 receipt; success path + BLOCKED/USER_DECISION_REQUIRED/DELEGATED_RUNTIME_MIGRATION/ROLLED_BACK

- [ ] **Step 1: Write failing tests**

```python
def test_auto_path_cannot_mint_v1_receipt():
    store = fixture_operator_receipt_store()
    attestation = fixture_verified_attestation()
    receipt = store.create_attested_pass_receipt(attestation=attestation, **fixture_v2_receipt_bindings())
    assert receipt["schema_version"] == "orchestration.operator-plan-receipt.v2"
    assert "tests" not in receipt
```
Also round-trip `BLOCKED`, `USER_DECISION_REQUIRED`, `DELEGATED_RUNTIME_MIGRATION`, and `ROLLED_BACK` through a fresh transaction-store instance and reject unknown schema versions.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -v tests.test_gate_continuation_transaction tests.test_operator_plan_execution
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Add v2 attested receipt validator/creator and versioned transaction store. Every disposition binds prior phase, reason taxonomy, authority/evidence digests and recovery eligibility.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_gate_continuation_transaction tests.test_operator_plan_execution
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/gate_continuation_transaction.py runtime/orchestrator/operator_plan_execution.py tests/test_gate_continuation_transaction.py && git commit -m 'feat(dcc): add attested receipt and complete transaction states'
```

---

### Task A4: Full Plan-Owned Mechanical Continuation

**Requirements:** HWO-MUST-005,006,018.

**Files:**
- Create/modify `runtime/orchestrator/durable_continuation.py`
- Modify `runtime/orchestrator/production_full_plan_runner.py`
- Modify `runtime/orchestrator/production_full_plan_boot.py`
- Create/modify `tests/test_durable_continuation.py`
- Create `tests/test_durable_continuation_failure_injection.py`

**Interfaces:**
- Consumes: A1-A3 + C lock API
- Produces: pure eligibility + Full Plan-owned resume under current epoch

- [ ] **Step 1: Write failing tests**

```python
def test_dcc_cannot_resume_non_receipt_waits():
    for state, reason in [("WAITING_APPROVAL","USER_DECISION_REQUIRED"),
                          ("WAITING_PROVIDER","PROVIDER_UNAVAILABLE"),
                          ("WAITING_RESOURCE","LOW_RESOURCE_BACKPRESSURE"),
                          ("WAITING_RESOURCE","RUNTIME_MIGRATION_QUIESCED")]:
        assessment = evaluate_continuation_eligibility(fixture_state(state, reason), fixture_auto_context())
        assert assessment.eligible is False
```
Also inject crash-after-commit-before-journal and stale-epoch cases; assert one commit, one v2 receipt, one Gate advance.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -v tests.test_durable_continuation tests.test_durable_continuation_failure_injection
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

DCC may only consume Full Plan authority and current owner token; no second scheduler. Reconciler wakes the canonical path, never performs provider/effect/migration selection itself.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_durable_continuation tests.test_durable_continuation_failure_injection tests.test_production_full_plan_runner tests.test_production_full_plan_boot tests.test_runtime_migration_authority_negative_space
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/durable_continuation.py runtime/orchestrator/production_full_plan_runner.py runtime/orchestrator/production_full_plan_boot.py tests/test_durable_continuation.py tests/test_durable_continuation_failure_injection.py && git commit -m 'feat(dcc): continue attested gates under full-plan ownership'
```

---
