# OCPv2 Canonical Result Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover a proven canonical Full Plan mutation after an OCP process/publish interruption without re-executing the mutation, and durably publish the result through the existing outbox.

**Architecture:** Persist a non-authoritative OCP execution binding immediately before canonical mutation dispatch, while also sealing the same message/directive identity into the canonical continuation-owner claim. On each one-shot startup, reconcile unresolved bindings against the registered Full Plan state; only exact canonical evidence may enqueue a `CANONICAL_ACTION_COMPLETED` result. Pending outbox items are retried without entering the canonical execution path. Ambiguous or mismatched evidence remains fail-closed.

**Tech Stack:** Python 3.12, unittest, durable JSON helpers, existing Full Plan supervisor, OCP receipt/outbox, GitHub control adapter.

**Spec:** `OPERATOR_CONTROL_PLANE_V2_R2.1_IMPLEMENTATION_PLAN_ALL_PASS.md`

## Global Constraints

- OCP transport remains non-authoritative and may not register Full Plan jobs.
- OCP may not select provider/model or directly invoke shell/tool execution.
- State-changing execution remains only through `execute_registered_full_plan_continuation`.
- Missing, stale, ambiguous, or mismatched recovery evidence must fail closed and must never re-execute canonical mutation.
- `ACTIVE` is outside this remediation scope.
- Existing OBSERVE_ONLY and read-only behavior must remain unchanged.

## Review Focus

- Crash after canonical Gate completion but before OCP projection: recover result with zero re-execution.
- Publish failure after durable outbox enqueue: retry only the outbox item on the next one-shot.
- Binding mismatch or owner drift: return reconciliation-required behavior and do not infer completion.
- Successful direct projection followed by process loss: do not publish a duplicate recovered result.
- Recovery wiring must not introduce job registration, provider routing, subprocess, shell, or tool authority into OCP runtime.

---

### Task 1: Durable execution binding and canonical owner attribution

**Files:**
- Create: `runtime/orchestrator/remote_operator_recovery_binding.py`
- Modify: `runtime/orchestrator/ocpv2_canonical_resume.py`
- Modify: `runtime/orchestrator/ocpv2_runtime_service.py`
- Test: `tests/test_ocpv2_live_recovery_composition.py`
- Test: `tests/test_ocpv2_registered_full_plan_resume.py`

**Interfaces:**
- Produces: `RemoteExecutionBindingV1`, `RemoteExecutionBindingStore.record()`, `pending()`, `mark_outboxed()`, `mark_projected()`.
- Produces: canonical continuation-owner fields `source=OCPV2`, `message_id`, `directive_digest`, and `task_execution_id` when called by OCP.
- Consumes: exact envelope identity and existing registered Full Plan CAS bindings.

- [ ] **Step 1: Write failing tests**

```python
store.record(envelope)
self.assertEqual(store.pending()[0].message_id, envelope.message_id)
self.assertEqual(supervisor.state["continuation_owner"]["message_id"], envelope.message_id)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m unittest -v tests.test_ocpv2_live_recovery_composition tests.test_ocpv2_registered_full_plan_resume`

Expected: FAIL because recovery binding interfaces / canonical owner attribution are not implemented.

- [ ] **Step 3: Implement the minimal durable binding**

Binding records contain message/envelope/directive identity, project/run/gate/task/task-execution identity, exact expected Full Plan state SHA, expected owner epoch, source HEAD, runtime release digest, lifecycle status, and projection ID. Conflicting reuse of a message ID is rejected.

`execute_authorized_canonical()` passes `remote_message_id` and `remote_directive_digest` into the canonical resume adapter. The canonical owner claim seals those fields before `_run_locked()` begins.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python3 -m unittest -v tests.test_ocpv2_live_recovery_composition tests.test_ocpv2_registered_full_plan_resume`

Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat(ocpv2): persist canonical recovery binding`

---

### Task 2: Canonical completion resolver and durable outbox recovery

**Files:**
- Create: `runtime/orchestrator/ocpv2_canonical_recovery.py`
- Modify: `runtime/orchestrator/ocpv2_runtime_service.py`
- Modify: `runtime/operator_transport/github_control_adapter.py`
- Modify: `runtime/orchestrator/remote_operator_service.py`
- Test: `tests/test_ocpv2_live_recovery_composition.py`

**Interfaces:**
- Consumes: unresolved `RemoteExecutionBindingV1` records and registered Full Plan durable state.
- Produces: `CanonicalCompletionEvidence` only when completed Gate, gate-run ID, owner epoch, OCP source, message ID, directive digest, and task execution all match.
- Produces: durable `RemoteResultProjectionV1` outbox item with result class `CANONICAL_ACTION_COMPLETED`.

- [ ] **Step 1: Add failing crash/publish tests**

```python
# Canonical action already happened once.
execution_count = 1
recover_pending_canonical_results(...)
self.assertEqual(execution_count, 1)
self.assertEqual(len(outbox.pending()), 1)
```

Also assert wrong message/directive/owner binding yields no outbox item and no execution callback.

- [ ] **Step 2: Verify RED**

Run: `python3 -m unittest -v tests.test_ocpv2_live_recovery_composition`

Expected: FAIL until startup recovery is wired.

- [ ] **Step 3: Implement exact canonical evidence resolution**

Load only the already-registered job and existing durable Full Plan state. Verify the requested Gate is in `completed_gates`, its queue item is `COMPLETED` with the exact `task_execution_id`, and `continuation_owner` carries the exact OCP message/directive/epoch binding. Never call the executor from recovery.

- [ ] **Step 4: Wire startup reconciliation**

Before polling new GitHub controls, inspect unresolved execution bindings. If canonical completion is proven, enqueue a deterministic recovery projection and update OCP receipt bookkeeping. Publish pending outbox items; after successful publish mark the binding projected. If evidence is ambiguous, leave the binding unresolved and block duplicate ingress rather than acknowledging an idempotent replay.

- [ ] **Step 5: Handle publish-failure retry**

A failed GitHub publish leaves the projection in `outbox/pending`; the next one-shot retries it and performs zero canonical execution. Expose a read-only durable-ack query on the GitHub adapter so a crash after successful publish but before local lifecycle update does not create a duplicate projection.

- [ ] **Step 6: Verify GREEN**

Run: `python3 -m unittest -v tests.test_ocpv2_live_recovery_composition tests.test_remote_operator_recovery tests.test_remote_operator_outbox tests.test_github_control_adapter_delivery_ack tests.test_remote_operator_service`

Expected: PASS.

- [ ] **Step 7: Commit**

Commit message: `fix(ocpv2): recover canonical completion through outbox`

---

### Task 3: Full regression and deployment handoff

**Files:**
- Modify: `.github/workflows/ocpv2-r2-ci.yml`
- Modify: PR #5 operational ledger/comment only after verification.

**Interfaces:**
- Consumes: all recovery tests from Tasks 1-2.
- Produces: a verified branch SHA suitable for OBSERVE_ONLY redeployment and a fresh Gate E sequence; does not activate ACTIVE.

- [ ] **Step 1: Add the new recovery integration test to focused CI**

```yaml
- run: python3 -m unittest -v tests.test_ocpv2_live_recovery_composition
```

- [ ] **Step 2: Run complete CI**

Expected: `focused=PASS`, `full-regression=PASS`, `regression-delta=PASS`.

- [ ] **Step 3: Negative-space review**

Verify OCP runtime still contains no job registration, provider selection, direct shell, or direct tool execution authority.

- [ ] **Step 4: Record verified SHA and Gate E disposition**

Gate E remains BLOCKED until a fresh live crash/recovery/outbox retry canary passes on Jarvis. ACTIVE remains unauthorized.
