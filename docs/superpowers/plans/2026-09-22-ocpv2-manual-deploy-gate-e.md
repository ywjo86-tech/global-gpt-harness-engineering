# OCPv2 Gate E Manual Deployment Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the missing Gate E canonical mutation bridge, verify it cannot bypass Full Plan / WorkerRequest / Production Execution Gateway, and leave a fail-closed manual Jarvis deployment package that stops before service activation.

**Architecture:** OCPv2 remains transport-only until ingress has accepted a sealed directive. A state-changing directive may execute only inside the existing DurableFullPlanSupervisor owner/epoch/transaction boundary, using a canonical WorkerRequest whose production execution backend is HOST_GATEWAY; the production worker then owns Provider Router and Production Execution Gateway / Full MCP dispatch. Deployment preparation may write reviewed user-service files but must not invoke systemd or switch OCPv2 to ACTIVE.

**Tech Stack:** Python 3.12, unittest, GitHub Actions, systemd --user, OCPv2 GitHub control transport.

**Spec:** `docs/superpowers/specs/2026-09-21-operator-control-plane-v2-r2-approved.md`

## Global Constraints

- GPT remains Logical Operator / decision authority.
- Harness remains the persistent execution supervisor.
- Transport must not become a second orchestrator.
- Provider Router remains the sole provider/model selector.
- State-changing actions continue through the existing Production Execution Gateway / Full MCP boundary.
- Existing Full Plan continuation ownership, epoch fencing and transaction locking remain authoritative.
- Migration-v2 state remains owned by its canonical store and legal transition rules.
- RDC is not a runtime dependency of OCPv2.
- No live Jarvis mutation or service activation is performed by this plan; final installation/activation is a separate user terminal action.

## Review Focus

- A stale continuation state, owner epoch, source HEAD, runtime release, or canonical run digest must fail closed before worker execution.
- A WorkerRequest whose project/run/Gate/LV/task-execution identity differs from the directive must never execute.
- A state-changing WorkerRequest must use `HOST_GATEWAY`; `LOCAL_CHILD`, verification-only, read-only, or provider-direct execution must be rejected at the OCP bridge.
- The OCP transport/service modules must not gain direct shell, subprocess, git, systemd, or package-manager authority.
- Manual deployment preparation must not invoke systemd, enable the timer, switch to `ACTIVE`, or expose credentials.

---

### Task 1: Gate E canonical mutation bridge

**Files:**
- Modify: `runtime/orchestrator/remote_operator_ingress.py`
- Create: `tests/test_ocpv2_gate_e_canonical_path.py`
- Modify: `.github/workflows/ocpv2-r2-ci.yml`

**Interfaces:**
- Consumes: `RemoteOperatorEnvelopeV2`, `OperatorDirectiveV1`, `DurableFullPlanSupervisor`, `WorkerRequest`, `execute_production_worker`.
- Produces: `execute_remote_action_through_canonical_full_plan(...) -> Mapping[str, Any]`.

- [ ] **Step 1: Write the failing regression** proving an exact state-changing directive can reach the canonical WorkerRequest executor exactly once, while stale owner epoch, runtime bindings, WorkerRequest identity drift, and non-HOST_GATEWAY backends fail before worker execution.
- [ ] **Step 2: Run hosted CI and verify RED** because `execute_remote_action_through_canonical_full_plan` does not yet exist.
- [ ] **Step 3: Implement the minimum bridge**. It must validate directive/envelope identity, compare optional expected canonical bindings, enter `execute_remote_directive_in_canonical_transaction`, require exact owner epoch, resolve the WorkerRequest inside the transaction, validate WorkerRequest identity and `HOST_GATEWAY`, and call `execute_production_worker` once.
- [ ] **Step 4: Run hosted CI and verify GREEN** for focused Gate E tests and whole repository regression.

### Task 2: Manual deployment preparation boundary

**Files:**
- Modify: `deploy/operator-control-plane-v2/bootstrap.py`
- Modify: `deploy/operator-control-plane-v2/README.md`
- Modify: `tests/test_ocpv2_deploy_package.py`

**Interfaces:**
- Consumes: existing `install_user_service` prepared-file behavior.
- Produces: a reviewable manual activation manifest/command set; no service-manager call.

- [ ] **Step 1: Write failing tests** requiring a manual activation preview to list exact generated paths and the two explicit user commands (`daemon-reload`, `enable --now ocpv2.timer`) while recording `service_manager_invoked=false` and keeping install mode restricted to `DISABLED`/`OBSERVE_ONLY`.
- [ ] **Step 2: Verify RED** in hosted CI.
- [ ] **Step 3: Add the minimal preview helper/CLI output and README procedure** without invoking systemd or widening install modes.
- [ ] **Step 4: Verify GREEN** in focused and full regression.

### Task 3: Closure evidence and deploy-stop record

**Files:**
- Create: `docs/harness/OCPV2_MANUAL_DEPLOY_READY_20260922.md`
- Modify: `docs/harness/OCPV2_R2_IMPLEMENTATION_LEDGER.md`

**Interfaces:**
- Consumes: exact Gate E implementation HEAD and CI evidence.
- Produces: an exact manual-deployment stop record that names the next human terminal action and explicitly states that live activation has not occurred.

- [ ] **Step 1: Record exact tested HEAD and CI run IDs** only after fresh GREEN verification.
- [ ] **Step 2: Record the user terminal deployment/rollback sequence** with no credentials and no hard-coded home path.
- [ ] **Step 3: Re-run exact-HEAD CI after documentation closure** and stop before any Jarvis systemd activation or live mutation canary.
