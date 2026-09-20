# Full Plan Durable Continuation Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove chat-turn dependency from already-approved FULL_PLAN continuation while preserving Full Plan authority, user-decision boundaries, runtime-migration ownership, governed effects, and complete backward compatibility.

**Architecture:** Add a Full Plan-owned continuation layer built from four focused modules: a sealed Gate continuation contract, deterministic verified attestation, crash-safe continuation transaction, and a controller that only executes mechanical transitions already authorized by Full Plan. Existing jobs remain `MANUAL_OPERATOR`; only explicitly sealed `AUTO_WITHIN_APPROVED_CONTRACT` Gates can use attested v2 receipts and autonomous continuation.

**Tech Stack:** Python 3.12, stdlib dataclasses/enum/hashlib/json/pathlib/subprocess/fcntl, existing durable JSON helpers, unittest, Git worktrees, user-systemd reconciler, existing Full Plan/RuntimeMigration/Attention infrastructure.

**Spec:** `docs/superpowers/specs/2026-09-20-durable-continuation-controller-design.md`
**Spec Approval:** 2026-09-21 user confirmation `Goal 승인`
**Plan Status:** REVIEWED-CANDIDATE / EXECUTION-APPROVAL-PENDING

## Global Constraints

- Stable predecessor baseline is `a40626c31353f90c0d4c9e677d3886ea5ccce393`; implementation begins from a fresh implementation branch/worktree derived from this reviewed design lineage.
- Full Plan remains the sole Task/Gate/fan-in/next-state authority; DCC is an internal execution/recovery mechanism and has no independent orchestration authority.
- Automatic continuation is FULL_PLAN-only and opt-in through `AUTO_WITHIN_APPROVED_CONTRACT`; legacy or contract-less jobs remain `MANUAL_OPERATOR`.
- `GATE_BY_GATE` next-Gate approval behavior is unchanged.
- User Decision Policy R2 remains authoritative for initial risky execution, material contract revision, risk-envelope escalation, and ambiguous dangerous effects.
- Router/MPRF selection authority, Full MCP effect authority, RuntimeMigrationTransaction ownership, and Attention `control_authority=NONE` remain unchanged.
- Automatic continuation may create only a bounded local Git commit when the sealed `commit_policy` explicitly permits it; Git push, destructive Git, system changes, network/external actions, package installation, credential actions, and equivalent effects remain separately authorized.
- Historical `orchestration.operator-plan-receipt.v1` remains manual/operator evidence only; DCC never mints v1 automatically.
- Auto continuation uses `orchestration.operator-plan-receipt.v2` bound to an immutable verified attestation and the exact job/Gate/authority/source lineage.
- Unknown job/contract/attestation/transaction/receipt schema versions fail closed.
- No runtime code change may weaken existing Full Plan state digest, authority digest, lease/epoch/idempotency, effect reconciliation, or runtime migration invariants.
- Every source-code Task follows RED -> minimal GREEN -> focused regression -> adjacent authority regression -> local commit.
- Runtime activation/push/systemd publication are not implementation-task side effects; they remain an explicit final execution approval boundary after EDP ALL PASS.

## Review Focus

1. **Crash after actual Git commit but before COMMITTED journal persistence:** recovery must discover the existing exact commit/tree and record it without creating another commit or rerunning the Gate.
2. **Reconciler wakeup races foreground continuation:** one fencing epoch owns continuation; stale owners cannot seal a receipt or advance the Gate.
3. **A WAITING_RESOURCE reason that is not operator receipt wait:** low resource or runtime-migration quiescence must never be auto-resumed by DCC.
4. **Legacy v1 receipt and historical job compatibility:** old jobs/receipts remain readable and manual; no historical object gains AUTO authority by inference.
5. **Approval/effect ambiguity after otherwise-successful verification:** attestation/commit success must not bypass `USER_DECISION_REQUIRED`, source/scope/risk drift, or ambiguous dangerous-effect boundaries.

Review Focus test ownership is explicit: item 1 is pinned in Tasks 6 and 11; item 2 in Tasks 9 and 11; item 3 in Tasks 3 and 8; item 4 in Tasks 1, 4, and 12; item 5 in Tasks 3, 7, and 12.

---

## File Structure

### New production modules

- `runtime/orchestrator/gate_continuation_contract.py` — closed/versioned GateContinuationContract schema, continuation/commit policies, validation, digesting, and legacy manual default helpers.
- `runtime/orchestrator/verified_gate_attestation.py` — closed verifier registry, deterministic verification result/attestation schemas, immutable evidence store, and validation against exact authority/source bindings.
- `runtime/orchestrator/gate_continuation_transaction.py` — durable transaction state machine (`PREPARED` through `ADVANCED`), legal transitions, crash recovery bindings, and transaction store.
- `runtime/orchestrator/durable_continuation.py` — pure eligibility classification plus Full Plan-owned mechanical continuation controller; no provider/effect/migration authority.

### Controlled production modifications

- `runtime/orchestrator/operator_plan_execution.py` — opt-in continuation contract construction/validation, dual v1/v2 receipt reader, v2 auto receipt creation from validated attestation only, manual compatibility.
- `runtime/orchestrator/production_run_authority.py` — explicit continuation-contract authority validation and rejection of runtime-overlay mutation of continuation authority.
- `runtime/orchestrator/production_full_plan_runner.py` — typed wait-reason/substate persistence, canonical lock/fencing hooks used by DCC, and safe mechanical resume entrypoint.
- `runtime/orchestrator/production_full_plan_entry.py` — additive schema validation/preflight for continuation contracts without reinterpreting old jobs.
- `runtime/orchestrator/production_full_plan_boot.py` — reconciler detection/relaunch of eligible pending continuation transactions while preserving approval/provider/resource/migration waits.
- `runtime/orchestrator/operator_exit_guard.py` — recognize durable autonomous ownership versus chat-turn-required pending work.
- `runtime/orchestrator/user_interaction_policy.py` — pure continuation eligibility/user-decision classification integration only; no dispatch authority.
- `runtime/orchestrator/production_attention.py` and `runtime/orchestrator/production_attention_watch.py` — only if required to classify unresolved DCC stall evidence; remain outbound-only.

### New tests

- `tests/test_gate_continuation_contract.py`
- `tests/test_verified_gate_attestation.py`
- `tests/test_gate_continuation_transaction.py`
- `tests/test_durable_continuation.py`
- `tests/test_durable_continuation_failure_injection.py`
- `tests/test_durable_continuation_e2e.py`

### Existing regression surfaces

- `tests/test_operator_plan_execution.py`
- `tests/test_production_full_plan_entry.py`
- `tests/test_production_full_plan_runner.py`
- `tests/test_production_full_plan_boot.py`
- `tests/test_runtime_migration_handoff.py`
- `tests/test_runtime_migration_authority_negative_space.py`
- `tests/test_user_interaction_policy.py`
- `tests/test_operator_exit_guard.py`
- `tests/test_production_attention_watch.py`

---

### Task 0: Execution Baseline and Fresh Full Plan Namespace

**Requirements:** DCC-MUST-019, DCC-MUST-020; DCC-AC-013.

**Files:**
- Read: `docs/superpowers/specs/2026-09-20-durable-continuation-controller-design.md`
- Read: `docs/history/upgrades/2026-09-20-DURABLE-CONTINUATION-CONTROLLER/EDP_PRE_IMPLEMENTATION_PLAN_DIAGNOSIS.md`
- No source modification.

**Interfaces:**
- Consumes: reviewed design commit containing this plan and Spec.
- Produces: a fresh implementation worktree/branch and Full Plan run namespace bound to exact Plan/Spec SHA256 values.

- [ ] **Step 1: Create an isolated implementation worktree from the reviewed plan commit**

Run after plan approval:

```bash
git worktree add ../DURABLE-CONTINUATION-CONTROLLER-IMPL-20260921 \
  -b upgrade/durable-continuation-controller-20260921 HEAD
```

Expected: new worktree branch points to the exact reviewed planning commit and the design worktree remains untouched.

- [ ] **Step 2: Freeze source identities**

Run:

```bash
cd ../DURABLE-CONTINUATION-CONTROLLER-IMPL-20260921
git rev-parse HEAD
git status --short --branch
sha256sum docs/superpowers/specs/2026-09-20-durable-continuation-controller-design.md \
  docs/superpowers/plans/2026-09-21-durable-continuation-controller.md
```

Expected: clean tree, explicit Spec SHA, explicit Plan SHA.

- [ ] **Step 3: Run predecessor focused regression before any source edit**

Run:

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v \
  tests.test_operator_plan_execution \
  tests.test_production_full_plan_runner \
  tests.test_production_full_plan_entry \
  tests.test_production_full_plan_boot \
  tests.test_runtime_migration_handoff \
  tests.test_runtime_migration_authority_negative_space \
  tests.test_user_interaction_policy \
  tests.test_operator_exit_guard \
  tests.test_production_attention_watch
```

Expected: RC 0. Record exact test count in the Full Plan evidence ledger rather than copying a historical count.

- [ ] **Step 4: Register a fresh Full Plan implementation job**

After the user approves this implementation Plan, run from the fresh implementation worktree:

```bash
python3 - <<'PYJOB'
from pathlib import Path
from runtime.orchestrator.operator_plan_execution import build_operator_plan_job
from runtime.orchestrator.production_full_plan_entry import register_job

root = Path.cwd().resolve()
job = build_operator_plan_job(
    project_root=root,
    harness_root=root,
    runtime_code_root=root,
    project_id="DURABLE-CONTINUATION-CONTROLLER",
    run_id="DCC-IMPL-20260921-R1",
    task_ids=(
        "TASK-001-CONTRACT", "TASK-002-ATTESTATION", "TASK-003-ELIGIBILITY",
        "TASK-004-RECEIPT-V2", "TASK-005-TRANSACTION", "TASK-006-GIT-BINDING",
        "TASK-007-CONTROLLER", "TASK-008-TYPED-WAIT", "TASK-009-RECONCILER",
        "TASK-010-EXIT-ATTENTION", "TASK-011-FAILURE-INJECTION", "TASK-012-E2E",
        "TASK-013-EDP-CLOSURE", "TASK-014-PUBLICATION",
    ),
    approved_plan_path="docs/superpowers/plans/2026-09-21-durable-continuation-controller.md",
    approved_spec_path="docs/superpowers/specs/2026-09-20-durable-continuation-controller-design.md",
    approval_ref="USER_APPROVED_DCC_IMPLEMENTATION_PLAN_20260921",
)
print(register_job(job))
PYJOB
```

Expected: one new canonical registered job for `DCC-IMPL-20260921-R1`. Do not reuse the R7/R8 AI Office final-operational run IDs. Task 14 remains receipt-blocked until its separate publication approval boundary is satisfied.

- [ ] **Step 5: Commit nothing in this task**

This Task is preflight evidence only. Any baseline failure is a blocker before Task 1.

---

### Task 1: GateContinuationContract Schema and Manual-Default Compatibility

**Requirements:** DCC-MUST-002, 003, 004, 005, 011, 019; DCC-AC-002, 003, 008.

**Files:**
- Create: `runtime/orchestrator/gate_continuation_contract.py`
- Create: `tests/test_gate_continuation_contract.py`
- Modify: `runtime/orchestrator/operator_plan_execution.py`
- Modify: `runtime/orchestrator/production_full_plan_entry.py`
- Modify: `runtime/orchestrator/production_run_authority.py`
- Test: `tests/test_operator_plan_execution.py`
- Test: `tests/test_production_full_plan_entry.py`

**Interfaces:**
- Produces: `ContinuationMode`, `CommitPolicy`, `GateContinuationContract`, `seal_gate_continuation_contract(*, allowed_write_paths: Sequence[str], forbidden_paths: Sequence[str], required_verifier_ids: Sequence[str], commit_policy: CommitPolicy, risk_classes: Sequence[str], approval_coverage_digest: str, source_lineage_policy: str, mode: ContinuationMode = ContinuationMode.AUTO_WITHIN_APPROVED_CONTRACT) -> GateContinuationContract`, `validate_gate_continuation_contract(value: Mapping[str, Any]) -> GateContinuationContract`, `continuation_contract_digest(contract: GateContinuationContract) -> str`, `gate_continuation_mode(gate: Mapping[str, Any]) -> ContinuationMode`.
- Consumes later: Tasks 2-10 use the validated contract and digest; no later task may parse raw Gate continuation fields independently.

- [ ] **Step 1: Write RED closed-schema tests**

Add tests equivalent to:

```python
from dataclasses import asdict
from runtime.orchestrator.gate_continuation_contract import (
    CommitPolicy, ContinuationMode, GateContinuationContract,
    seal_gate_continuation_contract, validate_gate_continuation_contract,
)


def valid_auto_contract_payload():
    contract = seal_gate_continuation_contract(
        allowed_write_paths=("runtime/orchestrator/example.py",),
        forbidden_paths=(".git", "secrets"),
        required_verifier_ids=("GIT_CHANGED_SCOPE", "GIT_TREE_BINDING"),
        commit_policy=CommitPolicy.LOCAL_COMMIT_ALLOWED,
        risk_classes=("REPOSITORY_LOCAL_WRITE",),
        approval_coverage_digest="a" * 64,
        source_lineage_policy="EXACT_BASE_DESCENDANT",
    )
    return asdict(contract)


def test_legacy_gate_defaults_to_manual_operator():
    assert ContinuationMode.MANUAL_OPERATOR.value == "MANUAL_OPERATOR"


def test_auto_contract_rejects_unknown_field():
    payload = valid_auto_contract_payload()
    payload["unexpected"] = True
    with self.assertRaisesRegex(ValueError, "fields mismatch"):
        validate_gate_continuation_contract(payload)


def test_auto_contract_requires_closed_write_verifier_risk_and_approval_sets():
    payload = valid_auto_contract_payload()
    payload["allowed_write_paths"] = []
    with self.assertRaises(ValueError):
        validate_gate_continuation_contract(payload)
```

The canonical contract fields must include at minimum:

```text
schema_version
mode
allowed_write_paths[]
forbidden_paths[]
required_verifier_ids[]
commit_policy
risk_classes[]
approval_coverage_digest
source_lineage_policy
continuation_contract_sha256
```

- [ ] **Step 2: Run RED tests**

Run:

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v tests.test_gate_continuation_contract
```

Expected: FAIL because the new module/types do not exist.

- [ ] **Step 3: Implement the minimal closed/versioned contract module**

Use immutable dataclasses/enums with exact modes:

```python
class ContinuationMode(str, Enum):
    MANUAL_OPERATOR = "MANUAL_OPERATOR"
    AUTO_WITHIN_APPROVED_CONTRACT = "AUTO_WITHIN_APPROVED_CONTRACT"

class CommitPolicy(str, Enum):
    NONE = "NONE"
    LOCAL_COMMIT_ALLOWED = "LOCAL_COMMIT_ALLOWED"
```

`validate_gate_continuation_contract()` must reject unknown versions, unknown fields, empty verifier/risk/approval bindings for AUTO, absolute/traversal paths, and any commit policy other than the two sealed values.

- [ ] **Step 4: Add legacy/manual behavior to job construction and loading**

`build_operator_plan_job()` must omit AUTO authority unless explicitly supplied by the approved plan builder. `load_job()` and `validate_operator_plan_job()` must treat a missing contract as MANUAL without mutating the historical job JSON.

- [ ] **Step 5: Prove the contract is in immutable authority and not runtime overlay**

Add tests that:

```python
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    spec, plan = self.make_repo(root)
    job = self.build_job(root, spec, plan)
    job["gates"][0]["continuation_contract"] = valid_auto_contract_payload()
    sealed = seal_authority_core(job)
    changed = deepcopy(sealed)
    changed["gates"][0]["continuation_contract"]["allowed_write_paths"].append("other.py")
    with self.assertRaisesRegex(RunAuthorityError, "RUN_AUTHORITY_DRIFT"):
        validate_authority_core(changed)
```

and ensure `extract_runtime_bindings()` never extracts `continuation_contract`.

- [ ] **Step 6: Run focused and adjacent regression**

Run:

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v \
  tests.test_gate_continuation_contract \
  tests.test_operator_plan_execution \
  tests.test_production_full_plan_entry
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add runtime/orchestrator/gate_continuation_contract.py \
  runtime/orchestrator/operator_plan_execution.py \
  runtime/orchestrator/production_full_plan_entry.py \
  runtime/orchestrator/production_run_authority.py \
  tests/test_gate_continuation_contract.py \
  tests/test_operator_plan_execution.py \
  tests/test_production_full_plan_entry.py
git commit -m "feat(full-plan): seal continuation gate contracts"
```

---

### Task 2: Deterministic VerifiedGateAttestation and Closed Verifier Registry

**Requirements:** DCC-MUST-006, 007, 009, 015, 020; DCC-AC-004, 005, 008, 012.

**Files:**
- Create: `runtime/orchestrator/verified_gate_attestation.py`
- Create: `tests/test_verified_gate_attestation.py`

**Interfaces:**
- Consumes: `GateContinuationContract` and its digest from Task 1.
- Produces: `VerificationContext`, `AttestationBinding`, `VerifierResult`, `VerifiedGateAttestation`, `VerifiedGateAttestationStore`, `build_verified_gate_attestation(context: VerificationContext, results: Sequence[VerifierResult]) -> VerifiedGateAttestation`, `run_registered_verifiers(contract: GateContinuationContract, context: VerificationContext) -> tuple[VerifierResult, ...]`, `validate_attestation(attestation: VerifiedGateAttestation, expected: AttestationBinding) -> None`.

- [ ] **Step 1: Write RED schema, forgery, and negative-space tests**

Required tests include:

```python
def test_free_form_pass_string_cannot_become_attestation():
    with self.assertRaises(AttestationError):
        VerifiedGateAttestation.from_mapping({"tests": ["PASS"]})


def test_attestation_rejects_changed_path_digest_mismatch():
    context = VerificationContext(
        project_id="proj", run_id="run", gate_id="G1",
        authority_core_sha256="1" * 64, continuation_contract_sha256="2" * 64,
        base_head="a" * 40, verified_tree_sha="b" * 40,
        changed_paths_sha256="0" * 64, risk_coverage_digest="3" * 64,
        approval_coverage_digest="4" * 64, evidence_refs=("evidence.json",),
    )
    att = build_verified_gate_attestation(
        context, (VerifierResult("GIT_CHANGED_SCOPE", "v1", "PASS", "5" * 64),)
    )
    expected = AttestationBinding(
        project_id="proj", run_id="run", gate_id="G1",
        authority_core_sha256="1" * 64, continuation_contract_sha256="2" * 64,
        base_head="a" * 40, verified_tree_sha="b" * 40,
        changed_paths_sha256="9" * 64, risk_coverage_digest="3" * 64,
        approval_coverage_digest="4" * 64,
    )
    with self.assertRaisesRegex(AttestationError, "changed path"):
        validate_attestation(att, expected=expected)


def test_verifier_module_has_no_control_authority_imports():
    text = Path("runtime/orchestrator/verified_gate_attestation.py").read_text()
    for forbidden in ("create_pass_receipt", "resume_operator_plan_after_receipt",
                      "activate_runtime_release", "route_request"):
        self.assertNotIn(forbidden, text)
```

- [ ] **Step 2: Run RED test**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v tests.test_verified_gate_attestation
```

Expected: FAIL due missing module.

- [ ] **Step 3: Implement immutable result/attestation schemas**

The attestation must bind exactly:

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

Each `VerifierResult` must carry a registered verifier ID, version/identity digest, deterministic status, and evidence digest; no shell command string becomes authority.

- [ ] **Step 4: Implement a closed verifier registry**

Use explicit registered IDs such as:

```python
VERIFIER_REGISTRY = {
    "GIT_CHANGED_SCOPE": verify_git_changed_scope,
    "GIT_TREE_BINDING": verify_git_tree_binding,
    "APPROVAL_RISK_BINDING": verify_approval_risk_binding,
}
```

Unknown verifier IDs fail closed. Do not add arbitrary shell execution to the registry API.

- [ ] **Step 5: Implement atomic attestation storage**

Store beneath:

```text
_workspace/gate-attestations/<project_id>/<run_id>/<gate_id>.json
```

Use existing `atomic_write_json`; reject symlink/non-regular existing paths and conflicting immutable rewrites.

- [ ] **Step 6: Run focused tests**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v \
  tests.test_verified_gate_attestation \
  tests.test_gate_continuation_contract
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add runtime/orchestrator/verified_gate_attestation.py tests/test_verified_gate_attestation.py
git commit -m "feat(full-plan): add verified gate attestations"
```

---

### Task 3: Pure Continuation Eligibility Evaluator

**Requirements:** DCC-MUST-001, 002, 003, 007, 012, 015, 016, 017; DCC-AC-002, 008, 010, 012.

**Files:**
- Create: `runtime/orchestrator/durable_continuation.py` with evaluator only initially.
- Create: `tests/test_durable_continuation.py`
- Modify: `runtime/orchestrator/user_interaction_policy.py` only if reuse of `ApprovalCoverageEvidence` requires a pure adapter.

**Interfaces:**
- Consumes: validated job/Gate contract, `ApprovalCoverageEvidence`, typed wait reason, optional effect reconciliation fact.
- Produces: `ContinuationEligibilityAssessment` with fields `eligible: bool`, `disposition`, `reason`, `control_authority="NONE"`.
- Task 7 later adds the controller class to this same focused module.

- [ ] **Step 1: Write RED eligibility matrix tests**

Pin at least these cases:

```text
FULL_PLAN + valid AUTO contract + exact approval/risk/source -> ELIGIBLE
GATE_BY_GATE -> INELIGIBLE_MODE
missing contract -> MANUAL_OPERATOR
WAITING_APPROVAL -> USER_DECISION_REQUIRED
scope drift -> PLAN_REVISION_REQUIRED
risk escalation -> USER_DECISION_REQUIRED
ambiguous dangerous effect -> USER_DECISION_REQUIRED
push/system/network/package/credential action class -> EXPLICIT_AUTHORITY_REQUIRED
RUNTIME_MIGRATION_QUIESCED -> MIGRATION_DELEGATION_REQUIRED
LOW_RESOURCE -> RESOURCE_WAIT
```

- [ ] **Step 2: Verify RED**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v tests.test_durable_continuation
```

Expected: FAIL because evaluator symbols are missing.

- [ ] **Step 3: Implement `ContinuationEligibilityEvaluator` as a pure classifier**

It must not import or call Full Plan resume/dispatch, receipt stores, Git mutation, provider routing, runtime activation, or tool effect APIs.

- [ ] **Step 4: Add source-level negative-space test**

Reject accidental imports/calls of:

```text
resume_wait
create_pass_receipt
activate_runtime_release
RuntimeMigrationTransaction.advance
ToolEffectJournal mutation
route_request
```

- [ ] **Step 5: Run policy regression**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v \
  tests.test_durable_continuation \
  tests.test_user_interaction_policy
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runtime/orchestrator/durable_continuation.py \
  runtime/orchestrator/user_interaction_policy.py \
  tests/test_durable_continuation.py tests/test_user_interaction_policy.py
git commit -m "feat(full-plan): classify bounded continuation eligibility"
```

---

### Task 4: Attestation-Bound Operator Receipt v2 with v1 Manual Compatibility

**Requirements:** DCC-MUST-006, 019; DCC-AC-003, 004.

**Files:**
- Modify: `runtime/orchestrator/operator_plan_execution.py`
- Modify: `tests/test_operator_plan_execution.py`
- Test: `tests/test_verified_gate_attestation.py`

**Interfaces:**
- Consumes: immutable `VerifiedGateAttestation` from Task 2.
- Produces: `OperatorPlanReceiptStore.create_attested_pass_receipt(*, gate_id: str, plan_sha256: str, spec_sha256: str, authority_core_sha256: str, continuation_contract_sha256: str, branch: str, source_head: str, source_tree_sha: str, attestation: VerifiedGateAttestation) -> dict[str, Any]` and `validate_attested_receipt_for_job(job: Mapping[str, Any], gate_id: str, receipt: Mapping[str, Any], attestation_store: VerifiedGateAttestationStore) -> None`; existing `create_pass_receipt(*, gate_id: str, plan_sha256: str, spec_sha256: str, branch: str, source_head: str, tests: Sequence[str]) -> dict[str, Any]` continues to produce manual v1 only.

- [ ] **Step 1: Write RED dual-schema tests**

Required assertions:

```python
def test_manual_create_pass_receipt_remains_v1():
    receipt = store.create_pass_receipt(
        gate_id="TASK-001-CONTRACT",
        plan_sha256="1" * 64,
        spec_sha256="2" * 64,
        branch="upgrade/test",
        source_head="a" * 40,
        tests=("focused regression: PASS",),
    )
    self.assertEqual(receipt["schema_version"], "orchestration.operator-plan-receipt.v1")


def test_auto_receipt_requires_existing_valid_attestation():
    context = VerificationContext(
        project_id="proj", run_id="run-final-op", gate_id="TASK-001-CONTRACT",
        authority_core_sha256="9" * 64, continuation_contract_sha256="4" * 64,
        base_head="a" * 40, verified_tree_sha="b" * 40, changed_paths_sha256="5" * 64,
        risk_coverage_digest="6" * 64, approval_coverage_digest="7" * 64,
        evidence_refs=("verification.json",),
    )
    mismatched_attestation = build_verified_gate_attestation(
        context, (VerifierResult("GIT_TREE_BINDING", "v1", "PASS", "8" * 64),)
    )
    with self.assertRaisesRegex(OperatorPlanExecutionError, "attestation"):
        store.create_attested_pass_receipt(
            gate_id="TASK-001-CONTRACT",
            plan_sha256="1" * 64,
            spec_sha256="2" * 64,
            authority_core_sha256="3" * 64,
            continuation_contract_sha256="4" * 64,
            branch="upgrade/test",
            source_head="a" * 40,
            source_tree_sha="b" * 40,
            attestation=mismatched_attestation,
        )


def test_v1_cannot_satisfy_auto_attested_gate():
    receipt = store.create_pass_receipt(
        gate_id="TASK-001-CONTRACT",
        plan_sha256="1" * 64,
        spec_sha256="2" * 64,
        branch="upgrade/test",
        source_head="a" * 40,
        tests=("focused regression: PASS",),
    )
    with self.assertRaisesRegex(OperatorPlanExecutionError, "AUTO_ATTESTED"):
        validate_attested_receipt_for_job(job, gate_id, receipt, attestation_store)
```

- [ ] **Step 2: Run RED**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v tests.test_operator_plan_execution
```

Expected: new v2 tests FAIL.

- [ ] **Step 3: Implement v1/v2 reader and strict v2 schema**

v2 must include:

```text
receipt_mode=AUTO_ATTESTED
authority_core_sha256
continuation_contract_sha256
attestation_sha256
source_tree_sha
```

Unknown versions fail closed. Historical v1 reader semantics remain unchanged for manual Gates.

- [ ] **Step 4: Bind v2 validation back to the attestation store**

The consumer must load the attestation by immutable identity and independently validate its digest plus job/Gate/authority/source bindings before accepting the receipt.

- [ ] **Step 5: Run regression**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v \
  tests.test_operator_plan_execution \
  tests.test_verified_gate_attestation
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runtime/orchestrator/operator_plan_execution.py \
  tests/test_operator_plan_execution.py tests/test_verified_gate_attestation.py
git commit -m "feat(full-plan): add attested operator receipt v2"
```

---

### Task 5: Crash-Safe GateContinuationTransaction

**Requirements:** DCC-MUST-008, 010, 013, 019, 020; DCC-AC-006, 007.

**Files:**
- Create: `runtime/orchestrator/gate_continuation_transaction.py`
- Create: `tests/test_gate_continuation_transaction.py`

**Interfaces:**
- Produces: `ContinuationPhase`, `GateContinuationTransaction`, `GateContinuationTransactionStore` with `create`, `load`, `advance`, `block`.
- Consumes later: controller/reconciler Tasks 7-9.

- [ ] **Step 1: Write RED legal-transition and immutable-binding tests**

Canonical phases:

```python
class ContinuationPhase(str, Enum):
    PREPARED = "PREPARED"
    EXECUTION_OBSERVED = "EXECUTION_OBSERVED"
    VERIFIED = "VERIFIED"
    COMMIT_INTENT = "COMMIT_INTENT"
    COMMITTED = "COMMITTED"
    RECEIPT_SEALED = "RECEIPT_SEALED"
    ADVANCED = "ADVANCED"
    BLOCKED = "BLOCKED"
```

Test illegal phase skips, duplicate conflicting transaction creation, binding mutation, symlink store path, digest tamper, and idempotent replay of already-durable same transition.

- [ ] **Step 2: Run RED**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v tests.test_gate_continuation_transaction
```

Expected: FAIL due missing module.

- [ ] **Step 3: Implement transaction schema/store using existing durable IO patterns**

Identity key must include:

```text
project_id
run_id
gate_id
authority_core_sha256
continuation_contract_sha256
base_head
```

Dynamic phase evidence may add verified tree, attestation SHA, commit SHA/tree, receipt SHA, advancement state SHA, but cannot mutate authority identity.

- [ ] **Step 4: Add file-lock/fencing-safe store operations**

Use an O_NOFOLLOW regular lock file under the transaction root and atomic writes. Conflicting owners must fail closed, not last-write-wins.

- [ ] **Step 5: Run focused tests**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v \
  tests.test_gate_continuation_transaction \
  tests.test_runtime_migration_handoff
```

The migration suite is included to catch accidental phase/transaction pattern regressions.

- [ ] **Step 6: Commit**

```bash
git add runtime/orchestrator/gate_continuation_transaction.py \
  tests/test_gate_continuation_transaction.py
git commit -m "feat(full-plan): add durable gate continuation transaction"
```

---

### Task 6: Verified Git Tree and Bounded Local Commit Semantics

**Requirements:** DCC-MUST-004, 009, 010, 016; DCC-AC-005, 008, 010.

**Files:**
- Modify: `runtime/orchestrator/durable_continuation.py`
- Modify: `tests/test_durable_continuation.py`
- Create or extend: `tests/test_durable_continuation_failure_injection.py`

**Interfaces:**
- Produces internal helpers `snapshot_git_evidence(project_root: Path, contract: GateContinuationContract, base_head: str) -> GitVerificationEvidence`, `prepare_local_commit(project_root: Path, evidence: GitVerificationEvidence, gate_id: str, expected_branch: str) -> CommitEvidence`, and `reconcile_existing_commit(project_root: Path, evidence: GitVerificationEvidence, gate_id: str, expected_branch: str) -> CommitEvidence | None` used only by the controller.
- No interface may expose arbitrary Git argv.

- [ ] **Step 1: Write RED scope/tree/TOCTOU tests**

Tests must construct temporary Git repositories and prove:

```text
changed path outside allowed_write_paths -> BLOCK
forbidden path touched -> BLOCK
verified_tree_sha changes after verification -> BLOCK
branch/base-head drift -> BLOCK
commit_policy NONE with changes -> BLOCK
LOCAL_COMMIT_ALLOWED -> exact verified tree becomes one local commit
pre-existing exact commit after simulated crash -> reconcile, do not commit again
```

- [ ] **Step 2: Run RED**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v \
  tests.test_durable_continuation \
  tests.test_durable_continuation_failure_injection
```

Expected: new Git tests FAIL.

- [ ] **Step 3: Implement closed Git operations**

Allowed subprocess operations are fixed code paths only, for example:

```text
git rev-parse HEAD
git rev-parse HEAD^{tree}
git status --porcelain=v1 -uall
git diff --name-only --cached
git add -- <exact approved changed paths>
git write-tree
git commit-tree <verified_tree_sha> -p <base_head> -m <deterministic gate message>
git update-ref refs/heads/<expected_branch> <new_commit> <base_head>
```

The controller constructs these argv lists itself from already-validated branch/path/Gate identity. It must not accept arbitrary user/model-provided Git subcommands. `git update-ref` uses the sealed `base_head` as the expected old value so branch movement is compare-and-swap. Never run push/reset --hard/rebase/remote mutation.

- [ ] **Step 4: Enforce verified-tree equality immediately before commit**

The committed tree SHA must equal the attested `verified_tree_sha`; any mismatch blocks and invalidates the pending mechanical commit.

- [ ] **Step 5: Add commit-before-journal crash reconciliation test**

Simulate:

```text
COMMIT_INTENT durable
actual Git commit exists
COMMITTED phase absent
restart controller
```

Expected: controller recognizes the exact parent/tree/message binding, records COMMITTED, and creates no second commit.

- [ ] **Step 6: Run focused tests**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v \
  tests.test_durable_continuation \
  tests.test_durable_continuation_failure_injection
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add runtime/orchestrator/durable_continuation.py \
  tests/test_durable_continuation.py \
  tests/test_durable_continuation_failure_injection.py
git commit -m "feat(full-plan): bind continuation to verified git trees"
```

---

### Task 7: Full Plan-Owned Durable Continuation Controller

**Requirements:** DCC-MUST-001, 002, 005, 006, 008, 012, 013, 015, 017; DCC-AC-001, 006, 007, 008.

**Files:**
- Modify: `runtime/orchestrator/durable_continuation.py`
- Modify: `runtime/orchestrator/operator_plan_execution.py`
- Modify: `tests/test_durable_continuation.py`
- Modify: `tests/test_durable_continuation_failure_injection.py`

**Interfaces:**
- Adds `DurableContinuationController.continue_gate(job_path, gate_id) -> ContinuationResult`.
- Controller consumes, but never replaces: `ContinuationEligibilityEvaluator`, attestation store, transaction store, receipt store, canonical Full Plan supervisor APIs.

- [ ] **Step 1: Write RED end-to-end mechanical-phase test using fakes**

The happy path must prove this exact order:

```text
eligibility PASS
PREPARED
EXECUTION_OBSERVED
registered verifiers run
VERIFIED
optional bounded local commit
COMMITTED or verified no-commit disposition
v2 receipt created
RECEIPT_SEALED
canonical Full Plan resume/advance
ADVANCED
```

- [ ] **Step 2: Write RED fail-closed tests for each boundary**

Any failure before receipt leaves no Gate completion; any failure after receipt but before advance resumes from receipt without recreating it. Approval/risk/scope/effect ambiguity must never be converted to auto PASS.

- [ ] **Step 3: Run RED**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v \
  tests.test_durable_continuation \
  tests.test_durable_continuation_failure_injection
```

Expected: controller tests FAIL.

- [ ] **Step 4: Implement the controller with explicit dependency injection**

Constructor shape:

```python
DurableContinuationController(
    *,
    eligibility_evaluator,
    attestation_store,
    transaction_store,
    receipt_store_factory,
)
```

The controller must not choose a next Gate; it calls only the existing canonical Full Plan resume/transition API after receipt validation.

- [ ] **Step 5: Ensure v1 manual path is untouched**

`build_operator_plan_executor()` retains current v1 behavior for manual Gates. Auto Gates return a typed pending-continuation result consumed by DCC, not a forged manual PASS.

- [ ] **Step 6: Run focused + manual regression**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v \
  tests.test_durable_continuation \
  tests.test_durable_continuation_failure_injection \
  tests.test_operator_plan_execution
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add runtime/orchestrator/durable_continuation.py \
  runtime/orchestrator/operator_plan_execution.py \
  tests/test_durable_continuation.py \
  tests/test_durable_continuation_failure_injection.py
git commit -m "feat(full-plan): continue attested gates durably"
```

---

### Task 8: Typed Wait Reasons and Canonical Full Plan Runner Integration

**Requirements:** DCC-MUST-011, 012, 013, 014, 015; DCC-AC-002, 007, 008, 009.

**Files:**
- Modify: `runtime/orchestrator/production_full_plan_runner.py`
- Modify: `tests/test_production_full_plan_runner.py`
- Modify: `tests/test_durable_continuation.py`
- Test: `tests/test_runtime_migration_handoff.py`

**Interfaces:**
- Existing top-level states remain unchanged.
- Adds explicit `wait_reason`/`wait_substate` semantics so `OPERATOR_TASK_RECEIPT_PENDING`, `LOW_RESOURCE_BACKPRESSURE`, and `RUNTIME_MIGRATION_QUIESCED` are distinguishable without changing top-level WAITING_RESOURCE compatibility.
- Adds `claim_attested_continuation_owner(expected_gate_id: str) -> dict[str, object]`, which acquires the canonical run lock, increments the existing fencing epoch, persists a DCC lease with `kind="DURABLE_CONTINUATION"`, and returns the sealed owner token used by `resume_attested_continuation`.

- [ ] **Step 1: Write RED wait-reason matrix tests**

Assert:

```text
manual receipt pending -> WAITING_RESOURCE / OPERATOR_TASK_RECEIPT_PENDING
AUTO eligible receipt pending -> WAITING_RESOURCE / AUTO_CONTINUATION_PENDING
low resource -> WAITING_RESOURCE / LOW_RESOURCE_BACKPRESSURE
migration quiesced -> WAITING_RESOURCE / RUNTIME_MIGRATION_QUIESCED
```

Only `AUTO_CONTINUATION_PENDING` is DCC auto-recoverable.

- [ ] **Step 2: Run RED**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v \
  tests.test_production_full_plan_runner tests.test_durable_continuation
```

- [ ] **Step 3: Add additive wait-reason validation/persistence**

Keep state schema compatibility. Historical state without `wait_reason` remains readable and never becomes AUTO by inference.

- [ ] **Step 4: Add the narrow canonical resume entrypoint**

Add this explicit supervisor API:

```python
def resume_attested_continuation(
    self, *, expected_gate_id: str, receipt_sha256: str, owner_epoch: int
) -> dict[str, object]:
    handle = self._acquire_run_lock()
    try:
        state, _ = self.load()
        item = self._active_item(state)
        lease = dict(state.get("lease") or {})
        if state.get("state") != "WAITING_RESOURCE":
            raise ProductionFullPlanError("attested continuation requires WAITING_RESOURCE")
        if state.get("wait_reason") != "AUTO_CONTINUATION_PENDING":
            raise ProductionFullPlanError("attested continuation wait reason mismatch")
        if item is None or item.get("gate_id") != expected_gate_id:
            raise ProductionFullPlanError("attested continuation Gate mismatch")
        if state.get("migration_id") or state.get("migration_handoff"):
            raise ProductionFullPlanError("attested continuation cannot cross runtime migration")
        if lease.get("kind") != "DURABLE_CONTINUATION" or int(lease.get("epoch", -1)) != int(owner_epoch):
            raise ProductionFullPlanError("attested continuation fencing lease mismatch")
        state["attested_receipt_sha256"] = receipt_sha256
        state["lease"] = None
        return self._resume_wait_locked("WAITING_RESOURCE")
    finally:
        self._release_run_lock(handle)
```

The final implementation may factor the repeated validation into a private helper, but these checks and this public signature are mandatory. No other DCC code may call generic `resume_wait("WAITING_RESOURCE")` directly.

- [ ] **Step 5: Prove runtime migration remains separate**

Run migration tests and add negative-space assertion that DCC never calls `runtime-current` or `activate_runtime_release` directly.

- [ ] **Step 6: Run focused regression**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v \
  tests.test_production_full_plan_runner \
  tests.test_durable_continuation \
  tests.test_runtime_migration_handoff \
  tests.test_runtime_migration_authority_negative_space
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add runtime/orchestrator/production_full_plan_runner.py \
  tests/test_production_full_plan_runner.py \
  tests/test_durable_continuation.py
git commit -m "feat(full-plan): type continuation wait reasons"
```

---

### Task 9: Reconciler Ownership, Lease/Epoch Fencing, and Restart Recovery

**Requirements:** DCC-MUST-008, 013, 018, 020; DCC-AC-006, 007, 011.

**Files:**
- Modify: `runtime/orchestrator/production_full_plan_boot.py`
- Modify: `runtime/orchestrator/durable_continuation.py`
- Modify: `tests/test_production_full_plan_boot.py`
- Modify: `tests/test_durable_continuation_failure_injection.py`

**Interfaces:**
- Reconciler detects a valid pending AUTO transaction and launches/resumes one canonical owner only.
- DCC shares Full Plan run lock/lease/epoch/fencing; it does not introduce a second independent scheduler authority.

- [ ] **Step 1: Write RED race/restart tests**

Required cases:

```text
foreground controller + reconciler simultaneous wake -> one owner
stale epoch tries to seal receipt -> rejected
process dies after VERIFIED -> reconciler resumes from VERIFIED
process dies after RECEIPT_SEALED -> reconciler advances only, no new receipt
terminal run -> no DCC launch
WAITING_APPROVAL/provider/resource/migration waits -> no DCC launch
```

- [ ] **Step 2: Run RED**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v \
  tests.test_production_full_plan_boot \
  tests.test_durable_continuation_failure_injection
```

- [ ] **Step 3: Implement reconciler eligibility detection**

`reconcile_job()` may classify a registered AUTO pending continuation as launchable only after validating authority, transaction, typed wait reason, absence of migration conflict, and ownership state.

- [ ] **Step 4: Reuse canonical locking/fencing**

Do not add a parallel lock namespace that can race `DurableFullPlanSupervisor`. If helper extraction is needed, refactor the existing lock/epoch implementation with regression tests first.

- [ ] **Step 5: Run focused regression**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v \
  tests.test_production_full_plan_boot \
  tests.test_production_full_plan_runner \
  tests.test_durable_continuation_failure_injection
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runtime/orchestrator/production_full_plan_boot.py \
  runtime/orchestrator/durable_continuation.py \
  tests/test_production_full_plan_boot.py \
  tests/test_durable_continuation_failure_injection.py
git commit -m "feat(full-plan): reconcile pending durable continuation"
```

---

### Task 10: Operator Exit Guard and Attention as Safety Net

**Requirements:** DCC-MUST-018, 019; DCC-AC-011.

**Files:**
- Modify: `runtime/orchestrator/operator_exit_guard.py`
- Modify: `tests/test_operator_exit_guard.py`
- Modify only if required: `runtime/orchestrator/production_attention.py`
- Modify only if required: `runtime/orchestrator/production_attention_watch.py`
- Modify only if required: `tests/test_production_attention_watch.py`

**Interfaces:**
- Operator Exit Guard distinguishes `durable autonomous owner proven` from `chat-turn-required continuation missing`.
- Attention remains read/outbound-only and reports only unresolved/stalled DCC conditions according to existing timing policy.

- [ ] **Step 1: Write RED exit-guard tests**

Required behavior:

```text
AUTO pending + valid durable transaction + eligible reconciler ownership -> chat turn may end with autonomous continuation evidence
AUTO pending but no transaction/owner -> CONTINUE_EXECUTION, final response prohibited
DCC blocked/inconsistent > stall threshold -> Attention eligible
WAITING_APPROVAL -> immediate user decision notification
recovered/advanced transaction -> stale DCC stall suppressed
```

- [ ] **Step 2: Run RED**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v \
  tests.test_operator_exit_guard tests.test_production_attention_watch
```

- [ ] **Step 3: Implement minimal exit/attention integration**

Do not let Attention mutate state, call DCC, or resume a job. Prefer deriving delivery eligibility from durable state/transaction evidence rather than adding new control callbacks.

- [ ] **Step 4: Source-level negative-space assertions**

Ensure attention modules still contain no imports/calls granting orchestration authority.

- [ ] **Step 5: Run regression**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v \
  tests.test_operator_exit_guard \
  tests.test_production_attention_watch \
  tests.test_user_interaction_policy
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runtime/orchestrator/operator_exit_guard.py tests/test_operator_exit_guard.py
# Add attention files only if actually modified.
git commit -m "feat(full-plan): guard durable autonomous continuation"
```

---

### Task 11: Crash/Fault Injection Across Every Continuation Boundary

**Requirements:** DCC-MUST-008, 009, 010, 012, 013, 015, 017, 020; DCC-AC-006, 007, 008.

**Files:**
- Expand: `tests/test_durable_continuation_failure_injection.py`
- Modify production files only if a demonstrated defect requires a bounded remediation.

**Interfaces:**
- No new architecture. This Task attempts to break Tasks 1-10.

- [ ] **Step 1: Parameterize crash injection at every transaction phase**

Inject process interruption immediately after:

```text
PREPARED
EXECUTION_OBSERVED
VERIFIED
COMMIT_INTENT
actual commit before COMMITTED persistence
COMMITTED
actual v2 receipt before RECEIPT_SEALED persistence
RECEIPT_SEALED
actual Full Plan advance before ADVANCED persistence
```

- [ ] **Step 2: Assert exactly-once durable outcomes**

For every injection point, after restart/reconcile assert:

```text
Git commit count <= 1 for the Gate
v2 receipt count == 1 after successful closure
Gate completion count == 1
next-Gate enqueue count == 1
no duplicated governed effect
transaction ends ADVANCED or explicit BLOCKED
```

- [ ] **Step 3: Add malformed/torn evidence cases**

Test corrupted current transaction with valid previous-good generation, tampered attestation digest, symlink evidence path, missing commit object, conflicting receipt, and source HEAD rewritten after verification.

- [ ] **Step 4: Run the failure-injection suite repeatedly**

```bash
for i in 1 2 3 4 5; do
  /tmp/gch-edp-allpass-venv/bin/python -m unittest -v \
    tests.test_durable_continuation_failure_injection || exit 1
done
```

Expected: five clean runs.

- [ ] **Step 5: If defects are found, remediate with a new RED case first**

Do not silently edit around a failure. Record the finding in the implementation ledger, add the reproducing test, implement the minimal correction, and rerun Tasks 1-10 affected regressions.

- [ ] **Step 6: Commit test/remediation changes**

```bash
git add tests/test_durable_continuation_failure_injection.py runtime/orchestrator
git commit -m "test(full-plan): harden durable continuation crash recovery"
```

Only include production files actually changed by demonstrated failure remediation.

---

### Task 12: Production-Shape Multi-Gate E2E Without Chat Continuation

**Requirements:** DCC-MUST-001-020 collectively; DCC-AC-001-012.

**Files:**
- Create: `tests/test_durable_continuation_e2e.py`
- Modify production files only for demonstrated E2E defects.

**Interfaces:**
- Exercises the real registered-job, Full Plan runner, DCC, v2 receipt, reconciler, and local Git commit path using isolated temporary repositories/harness roots.

- [ ] **Step 1: Write RED three-Gate FULL_PLAN fixture**

Use three Gates:

```text
GATE-A: local file edit + deterministic verifier + LOCAL_COMMIT_ALLOWED
GATE-B: no-commit verification Gate
GATE-C: final local file edit + deterministic verifier + LOCAL_COMMIT_ALLOWED
```

Every Gate has a sealed AUTO contract and the run is `FULL_PLAN`.

- [ ] **Step 2: Simulate loss of initiating GPT/chat owner after GATE-A verification**

Stop invoking the foreground operator after GATE-A reaches the pending AUTO continuation point. Invoke only the production reconciler path thereafter.

Expected: GATE-A v2 receipt seals, GATE-B and GATE-C execute/close through durable Full Plan ownership, and run reaches COMPLETED without another manual receipt/resume command.

- [ ] **Step 3: Add protected negative E2E variants**

Verify:

```text
same fixture in GATE_BY_GATE stops before next Gate
scope drift blocks
WAITING_APPROVAL blocks and notifies
push action request blocks before effect
runtime migration condition delegates instead of continuing
legacy MANUAL job still waits for manual v1 receipt
```

- [ ] **Step 4: Run production-shape E2E**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v tests.test_durable_continuation_e2e
```

Expected: PASS.

- [ ] **Step 5: Run adjacent authority suites**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest -v \
  tests.test_operator_plan_execution \
  tests.test_production_full_plan_runner \
  tests.test_production_full_plan_entry \
  tests.test_production_full_plan_boot \
  tests.test_runtime_migration_handoff \
  tests.test_runtime_migration_authority_negative_space \
  tests.test_user_interaction_policy \
  tests.test_operator_exit_guard \
  tests.test_production_attention_watch
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/test_durable_continuation_e2e.py runtime/orchestrator
git commit -m "test(full-plan): prove chat-independent durable continuation"
```

Only include production files if a reproduced E2E defect required a bounded fix.

---

### Task 13: Full EDP Qualification and Baseline Candidate Closure

**Requirements:** DCC-MUST-020; DCC-AC-013 plus all prior requirements as closure evidence.

**Files:**
- Create: `docs/history/upgrades/2026-09-21-DURABLE-CONTINUATION-CONTROLLER/EDP_IMPLEMENTATION_ALL_PASS.md`
- Create: `docs/history/upgrades/2026-09-21-DURABLE-CONTINUATION-CONTROLLER/DCC_IMPLEMENTATION_MANIFEST.json`
- Update only after evidence is final: `docs/DEVELOPMENT_PLAN.txt`, `docs/harness/CURRENT_OPERATIONAL_STATE.json` if the project reaches approved operational activation.

**Interfaces:**
- Consumes: final implementation HEAD, all tests/evidence, exact Plan/Spec SHA, Full Plan durable receipts.
- Produces: evidence-scoped EDP verdict and immutable implementation candidate manifest. It does not itself authorize push/runtime activation.

- [ ] **Step 1: Run full repository regression fresh**

```bash
/tmp/gch-edp-allpass-venv/bin/python -m unittest discover -s tests
python3 -m compileall -q runtime tests
git diff --check
test -z "$(git status --porcelain=v1 -uall)"
```

Expected: all commands RC 0 before closure claim. Record exact counts from this run.

- [ ] **Step 2: Run authority negative-space scans**

Search DCC modules for forbidden direct authority:

```bash
grep -RInE 'route_request|activate_runtime_release|runtime-current|ToolEffectJournal\(|subprocess.*push|git.*push' \
  runtime/orchestrator/{durable_continuation.py,verified_gate_attestation.py,gate_continuation_transaction.py,gate_continuation_contract.py}
```

Expected: zero unauthorized production call sites; any legitimate string/test reference must be manually classified in evidence.

- [ ] **Step 3: Build the final EDP matrices**

The report must contain:

```text
20/20 DCC-MUST requirement coverage
13/13 DCC-AC acceptance coverage
mandatory domain evidence matrix
source -> target -> validation RTM
negative-space audit
cross-document audit
adversarial second pass
PASS challenge
regression re-diagnosis for every resolved material finding
closure metrics
exhaustion statement
```

PASS is forbidden unless every EDP-1.0 universal gate is satisfied.

- [ ] **Step 4: Bind implementation manifest to exact source and evidence**

Manifest fields include at minimum:

```text
spec_sha256
plan_sha256
validated_source_head
validated_source_tree
full_regression_result/evidence path
focused regression evidence
failure-injection evidence
E2E evidence
EDP decision
```

- [ ] **Step 5: Commit EDP closure docs**

```bash
git add docs/history/upgrades/2026-09-21-DURABLE-CONTINUATION-CONTROLLER
git commit -m "docs(edp): qualify durable continuation controller"
```

This should be a docs-only closure descendant of the validated runtime-code HEAD. If runtime code changes after EDP, invalidate this closure and rerun Task 13 from Step 1.

---

### Task 14: Explicitly Approved Publication, Immutable Runtime Migration, and Successor Closure

**Requirements:** DCC-MUST-014, 015, 016, 019, 020; DCC-AC-009, 010, 013.

**Files:**
- Git refs/remotes and runtime release/migration evidence only unless a verified publication blocker requires a separately diagnosed source fix.

**Interfaces:**
- Consumes: EDP ALL PASS implementation candidate.
- Produces: exact remote branch/main/runtime convergence through existing `RuntimeMigrationTransaction` successor flow.

**Hard approval boundary:** This Task contains Git push and runtime/system operational effects. Stop at `USER_DECISION_REQUIRED` unless the user has explicitly approved this publication step under the current Plan/HEAD/risk envelope.

- [ ] **Step 1: Verify no code drift since EDP**

```bash
git status --short --branch
git diff --check
git log -1 --oneline
```

Compare runtime-code HEAD/tree to Task 13 validated values. Any runtime code drift invalidates Task 13.

- [ ] **Step 2: After explicit publication approval, push the implementation branch without force**

```bash
git push origin HEAD:upgrade/durable-continuation-controller-20260921
```

- [ ] **Step 3: Integrate main in a temporary worktree with ff-only semantics and rerun full regression**

Use a temporary integration worktree; do not rewrite history. Run the same full regression/compile/diff/clean commands from Task 13.

- [ ] **Step 4: Push main only after integration regression PASS**

```bash
git push origin main
```

No force push.

- [ ] **Step 5: Build the exact immutable runtime release**

Use `build_runtime_release()` from the exact pushed closure HEAD and verify the release manifest source head/tree/entry digest.

- [ ] **Step 6: Migrate the active Full Plan owner only through `RuntimeMigrationTransaction`**

Required order:

```text
PREPARED
PREDECESSOR_QUIESCED
RUNTIME_ACTIVATED
SUCCESSOR_REGISTERED
SUCCESSOR_VERIFIED
PREDECESSOR_CLOSED
```

DCC must not alter this sequence.

- [ ] **Step 7: Verify exact convergence and successor closure**

Prove:

```text
origin/main == origin/upgrade == runtime-current manifest source_head
reconciler blocked=0
systemd reconcile timer active/enabled
successor Full Plan eligible/completed as intended
predecessor closed with migrated-to-successor evidence
```

- [ ] **Step 8: Final fresh regression from active immutable runtime source**

Run focused authority/continuity/migration/DCC suites and final full regression. Record fresh evidence; do not reuse Task 13 counts as operational proof.

---

## Requirements-to-Task Traceability

| Requirement | Owning Tasks | Primary proof |
|---|---|---|
| DCC-MUST-001 | 3, 7, 12 | evaluator/controller negative-space + 3-Gate E2E |
| DCC-MUST-002 | 1, 3, 12 | FULL_PLAN AUTO positive / GATE_BY_GATE negative |
| DCC-MUST-003 | 1, 4, 12 | legacy manual fixtures |
| DCC-MUST-004 | 1, 6 | closed contract + write/forbidden scope tests |
| DCC-MUST-005 | 1, 7 | authority digest and dynamic evidence separation |
| DCC-MUST-006 | 2, 4, 7 | deterministic attestation + v2 receipt |
| DCC-MUST-007 | 2, 3 | source-level control-authority negative-space |
| DCC-MUST-008 | 5, 7, 11 | durable phases + crash injection |
| DCC-MUST-009 | 2, 6, 11 | tree/path evidence + TOCTOU crash tests |
| DCC-MUST-010 | 5, 6, 11 | dynamic lineage + commit reconciliation |
| DCC-MUST-011 | 1, 8 | additive typed wait compatibility |
| DCC-MUST-012 | 3, 8, 12 | wait-cause eligibility matrix |
| DCC-MUST-013 | 5, 8, 9, 11 | canonical lock/fencing/race tests |
| DCC-MUST-014 | 8, 12, 14 | migration delegation negative-space + successor migration |
| DCC-MUST-015 | 3, 7, 8, 12 | user decision/drift/effect hard stops |
| DCC-MUST-016 | 3, 6, 12, 14 | external-effect negative-space + publication approval gate |
| DCC-MUST-017 | 3, 7, 11 | effect reconciliation/ambiguity tests |
| DCC-MUST-018 | 9, 10 | recovery ownership + outbound-only Attention |
| DCC-MUST-019 | 1, 4, 5, 8, 10 | additive schemas and legacy fixtures |
| DCC-MUST-020 | 0, 11, 12, 13, 14 | baseline, chaos, E2E, EDP, operational convergence |

## Acceptance-to-Task Traceability

| Acceptance | Owning Tasks |
|---|---|
| DCC-AC-001 | 7, 12 |
| DCC-AC-002 | 1, 3, 8, 12 |
| DCC-AC-003 | 1, 4, 12 |
| DCC-AC-004 | 2, 4 |
| DCC-AC-005 | 2, 6 |
| DCC-AC-006 | 5, 7, 11 |
| DCC-AC-007 | 5, 9, 11 |
| DCC-AC-008 | 1, 3, 6, 7, 12 |
| DCC-AC-009 | 8, 12, 14 |
| DCC-AC-010 | 3, 6, 12, 14 |
| DCC-AC-011 | 9, 10 |
| DCC-AC-012 | 2, 3, 12, 13 |
| DCC-AC-013 | 13, 14 |

## Execution Gate Policy

- Tasks 0-13 are implementation/verification work inside the approved implementation contract once the user separately approves execution of this Plan.
- Task 14 is a distinct effect boundary because it includes Git push and immutable runtime activation. Even during an approved Full Plan, it requires explicit publication approval unless that exact effect class has already been approved under the current authority lineage.
- Any material change to Spec requirements, owned scope, success criteria, authority boundaries, or risk class stops execution for Plan revision/user decision.
- Ordinary test failures and bounded same-scope remediation do not require a new user decision; they require evidence-preserving TDD remediation and re-diagnosis.

## Plan Completion Criteria

This implementation Plan is complete only when:

```text
Tasks 0-13 complete under one evidence-preserving Full Plan lineage
DCC-MUST 20/20 proven
DCC-AC 13/13 proven
failure injection passes at every transaction boundary
production-shape 3+ Gate E2E completes without a chat-driven receipt/resume after Gate A
legacy/GATE_BY_GATE/approval/migration/effect boundaries remain unchanged
full repository regression/compile/diff/clean checks PASS
EDP-1.0 = ALL_PASS
Task 14 publication is either explicitly approved and converged, or remains an explicit USER_DECISION_REQUIRED boundary without false completion claim
```
