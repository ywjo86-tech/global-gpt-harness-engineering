# Harness Lifecycle V2 Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the approved-plan-to-durable-execution lifecycle gap without changing the semantics of any existing in-flight project run.

**Architecture:** Implement Lifecycle V2 as an activation-bound compatibility envelope over existing authority contracts. Legacy runs stay legacy; new V2 runs add a lifecycle binding, normalized execution-authority bundle, durable operator dispatch, dispatch-bound receipt, and DCC auto-continuation while Production Execution Gateway / Full MCP retain effect authority.

**Tech Stack:** Python 3.12, unittest, existing OCPv2/Full Plan/DCC/operator-plan receipt contracts.

**Spec:** `design/harness-lifecycle-v2-compat-20260924@76efd93f39c43b2f95590e75874fde73d8e2e94d:docs/superpowers/specs/2026-09-24-harness-lifecycle-v2-compat-design.md`

## Global Constraints

- Missing lifecycle binding resolves to LEGACY and never rewrites an existing job.
- Existing runs never migrate because new code is deployed.
- V2 references existing authority; it never creates approval/provider/model/effect/completion authority.
- GPT_OPERATOR remains the logical operator.
- Production Execution Gateway / Full MCP remain the only canonical effect path.
- OCPv2 remains normal ingress; RDC remains break-glass only.
- First implementation slice performs no migration of the eight active projects.
- Rollback is `NEW_ACTIVATION_DEFAULT_DISABLE`.

## Review Focus

- A legacy job loaded by V2-capable code must remain byte/semantic compatible and require no V2 artifact.
- Replayed/restarted V2 dispatch must reuse the same dispatch identity and never create a duplicate task.
- A V2 receipt without matching dispatch evidence must fail closed.
- Legacy `task_lv_authority_projection` must be adapted read-only and never rewritten.
- Forbidden authority fields (`final_assignee`, provider/model choice, completion/effect authority) must never enter V2 artifacts.

---

### Task 1: Lifecycle binding and execution-authority bundle contracts

**Files:**
- Create: `runtime/orchestrator/execution_lifecycle_v2.py`
- Test: `tests/test_harness_lifecycle_v2_compat.py`

**Interfaces:**
- Consumes: `build_operator_plan_job(...)` and existing immutable Full Plan job fields.
- Produces: `resolve_lifecycle_binding(job)`, `build_v2_operator_plan_job(...)`, `validate_execution_authority_bundle(job)`.

- [x] **Step 1: Write failing contract tests**
- [x] **Step 2: Verify RED in PR CI** — expected missing V2 module/API.
- [x] **Step 3: Implement minimal V2 data-contract module**
- [x] **Step 4: Run full repository regression and confirm zero current-only regression** — CI #325: focused PASS, full-regression PASS, regression-delta PASS; `current_only=0`.
- [x] **Step 5: Commit GREEN** — `b8dc40ed0043fd391953e5820328395dfbd37f77`.

### Task 2: LegacyAuthorityAdapter

**Files:**
- Modify: `runtime/orchestrator/execution_lifecycle_v2.py`
- Test: `tests/test_harness_lifecycle_v2_compat.py`

**Interfaces:**
- Consumes: existing `task_lv_authority_projection` validation/resolution functions.
- Produces: read-only normalized gate authority references suitable for an ExecutionAuthorityBundle.

- [x] **Step 1: Add RED tests for Family-style TASK/LV projection adaptation and mismatch rejection**
- [x] **Step 2: Implement read-only adapter with no artifact rewrite**
- [x] **Step 3: Verify focused + full regression**
- [x] **Step 4: Commit**

### Task 3: Durable operator dispatch and ACK state

**Files:**
- Create: `runtime/orchestrator/operator_dispatch_v2.py`
- Modify: `runtime/orchestrator/operator_plan_execution.py` only at the explicit V2 seam
- Test: `tests/test_operator_dispatch_v2.py`

**Interfaces:**
- Consumes: lifecycle binding + authority bundle digest.
- Produces: create-once dispatch record with `DISPATCH_PREPARED`, `OPERATOR_DISPATCHED`, `OPERATOR_ACKNOWLEDGED` transitions.

- [x] **Step 1: RED idempotency/conflict/restart tests**
- [x] **Step 2: Implement create-once durable dispatch store**
- [x] **Step 3: Make V2 operator executor return ACK-pending before receipt-pending**
- [x] **Step 4: Verify legacy executor behavior unchanged**
- [x] **Step 5: Commit**

### Task 4: Bind receipt and continuation to dispatch

**Files:**
- Modify: `runtime/orchestrator/operator_plan_execution.py`
- Modify: `runtime/orchestrator/durable_continuation.py` or the smallest existing continuation seam proven by tests
- Test: `tests/test_operator_dispatch_v2.py`

**Interfaces:**
- Consumes: acknowledged dispatch identity and existing operator receipt v1/v2.
- Produces: V2 receipt/dispatch binding and automatic eligible continuation without granting DCC mutation authority.

- [x] **Step 1: RED receipt-without-dispatch and mismatched-dispatch tests**
- [x] **Step 2: Implement smallest compatible dispatch attestation/binding**
- [x] **Step 3: RED auto-continuation test**
- [x] **Step 4: Implement continuation trigger through existing approved execution path**
- [x] **Step 5: Verify legacy receipt v1/v2 behavior remains green**
- [x] **Step 6: Commit**

### Task 5: Canary A/B/C

**Files:**
- Create: `tests/test_harness_lifecycle_v2_canary.py`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: Legacy Preservation, Existing Run Preservation, and three-task V2 Closed Loop qualification.

- [x] **Step 1: Canary A — legacy TASK/LV path unchanged**
- [x] **Step 2: Canary B — pre-existing run remains LEGACY and is not rewritten**
- [x] **Step 3: Canary C — Task1→Task2→Task3 with restart between dispatch and receipt, no duplicate dispatch**
- [x] **Step 4: Run canonical full regression and regression delta**
- [x] **Step 5: Commit qualification evidence**

### Task 6: Compatibility release gate

**Files:**
- Create: `docs/history/upgrades/20260924-harness-lifecycle-v2/HARNESS_LIFECYCLE_V2_QUALIFICATION.md`

**Interfaces:**
- Consumes: all canary and regression evidence.
- Produces: successor qualification only; no active-project migration.

- [x] **Step 1: Record eight-project non-migration matrix**
- [x] **Step 2: Record authority negative-space evidence**
- [x] **Step 3: Record rollback/default-disable evidence**
- [x] **Step 4: Leave AI Commerce/SFT/AI Office/Family/Ruflo/JEV/JARVIS/OCP migration as later gates, not part of this PR**

## Completion record

Implementation tasks 1–6 are complete on the successor branch. Final compatibility qualification was sealed after additional rollout-readiness gates and full-branch review fixes.

- G13 authority-seal qualification: PASS.
- G14 exact-head successor release qualification: PASS.
- G15 `NEW_ACTIVATION_DEFAULT_DISABLE` production composition/deploy rollback seam: PASS.
- Final full-branch review: project-onboarding canonical mapping-root authority binding fixed and requalified.
- G16 final compatibility qualification head: `68b376c3fd6884359f185ca4f276a1e214280918`.
- G16 CI run: `36095889124` — focused PASS, successor-release-qualification PASS, full-regression PASS, regression-delta PASS.
- Durable qualification record: `docs/history/upgrades/20260924-harness-lifecycle-v2/HARNESS_LIFECYCLE_V2_QUALIFICATION.md`.

This completion record does not authorize merge, `runtime-current` promotion, side-by-side production deploy, or migration of an existing registered run. Those remain separate controlled rollout operations under normal OCP authority.
