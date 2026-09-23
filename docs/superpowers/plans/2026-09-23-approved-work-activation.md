# Approved Work Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let GPT start a new already-approved Full Plan job through OCP + AI Office/Harness without local terminal/RDC access and without giving OCP planning or execution authority.

**Architecture:** A pure Approved Work Binding Validator derives request-local immutable approval/context bindings from committed project artifacts and explicit approval evidence. AI Office consumes only refs/digests, and a narrow Plan Activation Adapter calls existing `build_operator_plan_job()` and `register_job()` contracts. Registered jobs are launched by the existing Full Plan boot/reconcile path; OCP never shells out to start them.

**Tech Stack:** Python 3, unittest/pytest, AI Office contracts/state, Full Plan operator-plan job builder, production job registry, OCPv2 transport/outbox.

**Spec:** `docs/superpowers/specs/2026-09-23-ocp-observation-gateway-design.md`

## Global Constraints

- Raw GPT instructions cannot become Full Plan jobs without committed approved spec/plan and explicit approval binding.
- Do not create a second persistent approved-requirement database; derive request-local bindings from canonical committed evidence.
- Full Plan remains planning/task/Gate/fan-in authority; AI Office remains workflow/governance only.
- OCP may request activation but may not invent tasks, provider/model choices, editable scope, approvals, or execution packages.
- Activation writes Harness control state only; product/source mutation still occurs only downstream through Full Plan → Gateway → Full MCP.
- New activation is create-once/replay-safe and disabled by default until separately qualified.
- Existing registered-run OCP resume behavior must remain unchanged.

## Review Focus

1. Spec/plan path is committed but digest or HEAD changed after approval: activation must fail closed before job registration.
2. Request reuses an activation ID with different evidence: conflict must be rejected rather than overwrite prior binding.
3. Required canonical requirement artifact is absent/malformed: return `APPROVED_BINDING_REQUIRED`, never synthesize it.
4. AI Office state exists with conflicting workflow identity/revision: activation must not create a parallel workflow truth.
5. Job registers successfully but runtime launch is delayed/crashes: existing boot/reconcile path must recover it without OCP re-registering the run.

---

### Task 1: Approved Work Binding Contract and Validator



**Files:**
- Create: `runtime/orchestrator/approved_work_binding.py`
- Test: `tests/test_approved_work_binding.py`

**Interfaces:**
- Produces: `ApprovedWorkBindingV1`, `validate_approved_work_binding(request, *, registry, runtime_release) -> ApprovedWorkBindingV1`.
- Reuses: `OnboardingRegistry.entries()`, Git committed-file checks patterned after `operator_plan_execution._committed_regular_file`, and canonical requirement validation where supplied.

- [ ] **Step 1: Write failing validator tests**

```python
binding = validate_approved_work_binding(request, registry=registry, runtime_release=release)
self.assertEqual(binding.project_id, "project")
self.assertEqual(binding.approved_plan_sha256, sha(plan))
self.assertEqual(binding.expected_head, git(root, "rev-parse", "HEAD"))
```

Add RED cases for uncommitted/symlink plan or spec, SHA drift, branch/HEAD mismatch, missing approval ref, malformed requirement artifact, unknown alias, and caller-supplied provider/model fields.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_approved_work_binding -v`
Expected: module missing.

- [ ] **Step 3: Implement pure validation only**

The validator returns a frozen dataclass/digest and performs no job registration, AI Office state write, process launch, or network access.

- [ ] **Step 4: Run GREEN**

Run: `python -m unittest tests.test_approved_work_binding tests.test_project_onboarding tests.test_operator_plan_execution -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/approved_work_binding.py tests/test_approved_work_binding.py
git commit -m "feat(harness): validate approved work bindings"
```

### Task 2: Request-Local AI Office Activation Coordination



**Files:**
- Create: `runtime/ai_office/activation.py`
- Modify: `runtime/ai_office/requirement_intake.py` only if a public helper is needed; do not add a persistent register.
- Test: `tests/test_ai_office_activation.py`

**Interfaces:**
- Consumes: `ApprovedWorkBindingV1`, existing `intake_requirement()`, `AIOfficeStateStore`, `WorkflowCoordinator`.
- Produces: `AIActivationContextV1` containing only requirement/workflow/governance refs/digests required for activation.

- [ ] **Step 1: Write failing tests for request-local approved-register derivation**

```python
context = coordinate_approved_activation(binding, office_store=store)
self.assertEqual(context.full_plan_plan_digest, binding.approved_plan_sha256)
self.assertTrue(context.requirement_envelope_digest)
self.assertNotIn("provider", context.to_dict())
```

Test that a conflicting existing workflow identity/revision blocks rather than creating a second office run.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_ai_office_activation -v`
Expected: module missing.

- [ ] **Step 3: Implement coordinator using in-memory approved mapping**

The helper constructs the `approved_register` argument from `ApprovedWorkBindingV1` for the single request and passes it to `intake_requirement()`; it persists only normal AI Office workflow state/refs, never an approval source-of-truth copy.

- [ ] **Step 4: Run GREEN and AI Office authority tests**

Run: `python -m unittest tests.test_ai_office_activation tests.test_ai_office_requirement_context tests.test_ai_office_workflow tests.test_ai_office_authority_negative_space -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/ai_office/activation.py tests/test_ai_office_activation.py
git commit -m "feat(ai-office): coordinate approved work activation refs"
```

### Task 3: Plan Activation Adapter Around Existing Job Contracts



**Files:**
- Create: `runtime/orchestrator/plan_activation.py`
- Test: `tests/test_plan_activation.py`

**Interfaces:**
- Consumes: `ApprovedWorkBindingV1`, `AIActivationContextV1`, `build_operator_plan_job()`, `register_job()`.
- Produces: `PlanActivationResultV1` with canonical job path, run ID, authority digest, and status `REGISTERED`/`ALREADY_REGISTERED`/`BLOCKED`.

- [ ] **Step 1: Write failing registration/idempotency tests**

```python
result = activate_approved_work(binding, ai_context=context, harness_state_root=state, runtime_code_root=release)
self.assertEqual(result.status, "REGISTERED")
self.assertTrue(Path(result.canonical_job_path).is_file())
second = activate_approved_work(binding, ai_context=context, harness_state_root=state, runtime_code_root=release)
self.assertEqual(second.canonical_job_path, result.canonical_job_path)
```

Test same activation identity with changed plan/spec/HEAD returns `ACTIVATION_CONFLICT`; no second job is created.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_plan_activation -v`
Expected: module missing.

- [ ] **Step 3: Implement adapter with no process launch**

Call `build_operator_plan_job()` with the exact validated task IDs/plan/spec/approval/source/runtime bindings, then `register_job()`. Do not invoke `systemd-run`, `subprocess`, provider code, Full MCP, or `run_job()`; existing boot/reconcile owns launch/recovery.

- [ ] **Step 4: Run GREEN plus production entry tests**

Run: `python -m unittest tests.test_plan_activation tests.test_operator_plan_execution tests.test_production_full_plan_entry tests.test_production_full_plan_boot -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/plan_activation.py tests/test_plan_activation.py
git commit -m "feat(harness): register approved work without terminal access"
```

### Task 4: Create-Once Activation Receipt and Replay Guard

**Files:**
- Modify: `runtime/orchestrator/plan_activation.py`
- Test: `tests/test_plan_activation.py`

**Interfaces:**
- Produces: durable `PlanActivationStore` keyed by activation request ID and exact binding digest.
- Preserves: `register_job()` run-ID rebinding protection as the downstream authority guard.

- [ ] **Step 1: Write failing crash/replay tests**

```python
first = store.record_or_load(request_id="ACT-1", binding=binding, registrar=registrar)
restarted = PlanActivationStore(state_root)
second = restarted.record_or_load(request_id="ACT-1", binding=binding, registrar=registrar)
self.assertEqual(first.activation_digest, second.activation_digest)
self.assertEqual(registrar.calls, 1)
```

Test `ACT-1` with a different binding digest raises `ACTIVATION_REPLAY_CONFLICT`.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_plan_activation.PlanActivationReplayTests -v`
Expected: store missing.

- [ ] **Step 3: Implement atomic durable receipt**

Use existing `durable_io` helpers or an equivalent create-once atomic JSON pattern. Persist refs/digests only; no raw secrets or provider/model data.

- [ ] **Step 4: Run GREEN**

Run: `python -m unittest tests.test_plan_activation -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/plan_activation.py tests/test_plan_activation.py
git commit -m "feat(harness): make approved activation replay safe"
```

### Task 5: Extend Remote Control Contract With `APPROVED_WORK_ACTIVATION`

**Files:**
- Modify: `runtime/orchestrator/remote_control_envelope.py`
- Modify: `runtime/orchestrator/ocpv2_runtime_service.py`
- Test: `tests/test_remote_control_envelope.py`
- Test: `tests/test_ocpv2_runtime_service.py`

**Interfaces:**
- Adds request kind: `APPROVED_WORK_ACTIVATION`.
- Consumes: approved plan/spec/requirement/approval/source/runtime bindings only.

- [ ] **Step 1: Write failing activation-envelope tests**

```python
envelope = validate_remote_control_envelope(seal_remote_control_envelope(payload), now=now)
self.assertEqual(envelope.request_kind, "APPROVED_WORK_ACTIVATION")
self.assertEqual(envelope.payload["activation_request_id"], "ACT-1")
```

Reject missing approval ref, missing plan/spec digest, caller task outside the approved set, provider/model/backend fields, and mutable `state_change_required` ambiguity.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_remote_control_envelope -v`
Expected: activation kind rejected.

- [ ] **Step 3: Add exact typed activation payload**

Do not reinterpret V2 `state_change_required`; request kind determines semantics. Existing V2 and `HOST_INSPECTION` parsing remain byte/digest compatible.

- [ ] **Step 4: Run GREEN/V2 regression**

Run: `python -m unittest tests.test_remote_control_envelope tests.test_remote_operator_envelope tests.test_ocpv2_runtime_service -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/remote_control_envelope.py runtime/orchestrator/ocpv2_runtime_service.py tests/test_remote_control_envelope.py tests/test_ocpv2_runtime_service.py
git commit -m "feat(ocpv2): add approved work activation request kind"
```

### Task 6: Runtime Mode Gating and Activation Result Projection



**Files:**
- Modify: `runtime/orchestrator/remote_operator_service.py`
- Modify: `runtime/orchestrator/ocpv2_runtime_service.py`
- Modify: `runtime/orchestrator/remote_operator_outbox.py`
- Test: `tests/test_remote_operator_service.py`
- Test: `tests/test_ocpv2_runtime_service.py`
- Test: `tests/test_remote_operator_outbox.py`

**Interfaces:**
- Consumes: `validate_approved_work_binding()`, AI Office activation coordination, `activate_approved_work()`.
- Produces: typed activation result projection through the existing outbox.

- [ ] **Step 1: Write failing mode tests**

Assert activation is blocked in `DISABLED`, `OBSERVE_ONLY`, `CONTROL_READ_ONLY`, and by default in `CONTROL_MUTATION_CANARY`; it is allowed in `ACTIVE` only when `OCP_WORK_ACTIVATION_ENABLED=1` and exact activation authorization is present.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_remote_operator_service tests.test_ocpv2_runtime_service -v`
Expected: activation callback/feature flag missing.

- [ ] **Step 3: Wire activation as a separate callback**

Do not reuse `execute_authorized_canonical()` and do not alter existing-run CAS semantics. Activation failure must not fall through to resume, Manual Action, Host Inspection, or RDC.

- [ ] **Step 4: Add result projection/replay tests and run GREEN**

Run: `python -m unittest tests.test_remote_operator_service tests.test_ocpv2_runtime_service tests.test_remote_operator_outbox -v`
Expected: PASS; a transport retry republishes the sealed activation result without re-registering the job.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/remote_operator_service.py runtime/orchestrator/ocpv2_runtime_service.py runtime/orchestrator/remote_operator_outbox.py tests/test_remote_operator_service.py tests/test_ocpv2_runtime_service.py tests/test_remote_operator_outbox.py
git commit -m "feat(ocpv2): wire gated approved work activation"
```

### Task 7: Activation Integration and Boot-Reconcile Qualification

**Files:**
- Create: `tests/test_ocpv2_approved_work_activation_integration.py`
- Create: `docs/harness/ocpv2-approved-work-activation-runbook.md`

**Interfaces:**
- Depends on: Tasks 1-6 and existing `production_full_plan_boot.reconcile_job()` behavior.
- Produces: proof that registration requires no local terminal and runtime launch/recovery remains owned by existing boot reconciliation.

- [ ] **Step 1: Write integration test before live activation**

The test builds a temporary Git project with committed approved spec/plan/requirement evidence, registers it in `OnboardingRegistry`, sends a typed activation request, asserts exactly one canonical job is registered, then invokes the existing boot reconciler and verifies it discovers that job.

- [ ] **Step 2: Add negative-space assertions**

```python
for forbidden in ("subprocess", "systemctl", "FullMCPRuntime", "provider_router"):
    self.assertNotIn(forbidden, inspect.getsource(plan_activation))
```

Also assert raw unapproved instruction, stale HEAD, changed approval digest, conflicting activation ID, and missing requirement evidence register zero jobs.

- [ ] **Step 3: Run focused and broad regression**

Run:
```bash
python -m unittest tests.test_ocpv2_approved_work_activation_integration -v
python -m unittest tests.test_approved_work_binding tests.test_ai_office_activation tests.test_plan_activation tests.test_operator_plan_execution tests.test_production_full_plan_boot -v
python -m unittest tests.test_ocpv2_single_execution_owner tests.test_ocpv2_authority_negative_space -v
python -m unittest discover -s tests -v
```
Expected: PASS, with zero authority regression.

- [ ] **Step 4: Write feature-OFF deployment/canary/rollback runbook**

First successor runtime must use `OCP_WORK_ACTIVATION_ENABLED=0`; activation requires separate explicit canary approval. Rollback is feature OFF and leaves already-registered canonical jobs to existing Full Plan/boot recovery semantics.

- [ ] **Step 5: Commit**

```bash
git add tests/test_ocpv2_approved_work_activation_integration.py docs/harness/ocpv2-approved-work-activation-runbook.md
git commit -m "test(ocpv2): qualify terminal-free approved work activation"
```

## Plan Self-Review Result

- Spec coverage: approval binding, AI Office coordination, existing job-builder reuse, replay protection, typed OCP activation request, mode gating, boot-reconcile ownership and rollback map to Tasks 1-7.
- Placeholder scan: no deferred implementation steps.
- Type consistency: `ApprovedWorkBindingV1` → `AIActivationContextV1` → `PlanActivationResultV1` is the only activation data chain.
- Review Focus coverage: drift Task 1; replay conflict Task 4; missing requirement evidence Task 1; AI Office conflict Task 2; delayed/crashed launch Task 7.
- This plan does not implement host inspection; it depends only on the common remote-control/outbox contracts established by the Host Inspection plan.