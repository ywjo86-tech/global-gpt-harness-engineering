# Workstream B — Wait / Operator / Attention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate silent provider/resource waits and Operator handoff gaps while adding real outbound Attention delivery semantics without inbound control authority.

**Architecture:** Classify waits by exact reason/owner, re-evaluate provider/resource recovery under canonical authorities, persist evidence-only Operator checkpoints, and add idempotent outbound delivery plus explicit run supersession.

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
- Owns: HWO-MUST-008~011,019.

## Review Focus

1. Generic WAITING_RESOURCE resume is forbidden.
2. Provider recovery must replay the sealed Router request/eligibility/output contract.
3. Operator checkpoint remains evidence-only.
4. Supersession requires explicit successor lineage, never time ordering alone.
5. Live notification transport remains disabled without separate deployment approval.

---

### Task B0: Typed Wait Reason + Recovery Owner Classification

**Requirements:** HWO-MUST-005,011,018.

**Files:**
- Create `runtime/orchestrator/wait_recovery.py`
- Modify `runtime/orchestrator/production_full_plan_runner.py`
- Create `tests/test_full_plan_wait_recovery.py`

**Interfaces:**
- Consumes: A wait taxonomy compatibility
- Produces: closed wait reason -> recovery owner assessment

- [ ] **Step 1: Write failing tests**

```python
def test_each_wait_reason_has_exact_owner():
    expected = {"OPERATOR_TASK_RECEIPT_PENDING":"DCC_OR_OPERATOR",
                "CONTINUATION_RECOVERY_PENDING":"DCC_RECONCILER",
                "LOW_RESOURCE_BACKPRESSURE":"RESOURCE_RECOVERY",
                "RUNTIME_MIGRATION_QUIESCED":"RUNTIME_MIGRATION",
                "PROVIDER_UNAVAILABLE":"PROVIDER_RECOVERY",
                "PROVIDER_RECOVERY_PENDING":"PROVIDER_RECOVERY"}
    for reason, owner in expected.items():
        assert classify_wait_recovery(fixture_wait_state(reason)).owner == owner
```
Also assert unknown `WAITING_RESOURCE`, `WAITING_APPROVAL`, and incompatible state/reason pairs fail closed.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -v tests.test_full_plan_wait_recovery
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Persist typed reason/substate while keeping top-level state compatible. Receipt, continuation-recovery, low-resource, migration, provider and approval waits remain distinguishable.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_full_plan_wait_recovery tests.test_production_full_plan_runner
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/wait_recovery.py runtime/orchestrator/production_full_plan_runner.py tests/test_full_plan_wait_recovery.py && git commit -m 'feat(full-plan): classify typed wait recovery ownership'
```

---

### Task B1: Autonomous Provider + Resource Recovery

**Requirements:** HWO-MUST-011,018.

**Files:**
- Modify `runtime/orchestrator/wait_recovery.py`
- Modify `runtime/orchestrator/production_full_plan_boot.py`
- Modify provider adapter only if existing public Router API needs binding
- Modify `tests/test_full_plan_wait_recovery.py`
- Modify `tests/test_production_full_plan_boot.py`

**Interfaces:**
- Consumes: B0 typed wait + original sealed provider/resource facts
- Produces: CAS resume decision without provider selection bypass

- [ ] **Step 1: Write failing tests**

```python
def test_provider_recovery_reuses_sealed_request_contract():
    state, sealed = fixture_provider_wait_with_sealed_request()
    fresh = fixture_fresh_mprf_health()
    decision = evaluate_provider_wait_recovery(state, fresh_facts=fresh)
    assert decision.router_request_sha256 == sealed.router_request_sha256
    assert decision.output_contract_sha256 == sealed.output_contract_sha256
```
Also assert changed risk/output contract returns decision/revision-required and low-resource recovery requires fresh probe + expected state SHA + epoch.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -v tests.test_full_plan_wait_recovery tests.test_production_full_plan_boot
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Reconciler requests evaluation; MPRF supplies fresh facts; Router alone chooses provider/model; Full Plan CAS-resumes exact wait. Resource evaluator uses sealed thresholds and fresh probe.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_full_plan_wait_recovery tests.test_production_full_plan_boot tests.test_provider_router tests.test_production_provider_router_integration
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/wait_recovery.py runtime/orchestrator/production_full_plan_boot.py tests/test_full_plan_wait_recovery.py tests/test_production_full_plan_boot.py && git commit -m 'feat(full-plan): recover provider and resource waits autonomously'
```

---

### Task B2: OperatorTurnCheckpoint + Safe Yield

**Requirements:** HWO-MUST-008,018.

**Files:**
- Create `runtime/orchestrator/operator_turn_checkpoint.py`
- Modify `runtime/orchestrator/operator_exit_guard.py`
- Modify `docs/harness/operator-turn-execution-policy.md`
- Create `tests/test_operator_turn_checkpoint.py`
- Modify `tests/test_operator_exit_guard.py`

**Interfaces:**
- Consumes: current Full Plan/operator-exit facts
- Produces: digest-bound evidence-only checkpoint store

- [ ] **Step 1: Write failing tests**

```python
def test_checkpoint_is_evidence_only():
    checkpoint = OperatorTurnCheckpoint.create(**fixture_checkpoint_fields())
    assert checkpoint.control_authority == "NONE"
    assert not hasattr(checkpoint, "resume")
    assert not hasattr(checkpoint, "dispatch")
```
Also assert an Operator yield without terminal completion, explicit decision wait, autonomous owner, or durable handoff checkpoint is not completion-eligible.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -v tests.test_operator_turn_checkpoint tests.test_operator_exit_guard
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Checkpoint binds project/run/gate, authority digest, kind, owner kind/ref, resume-contract digest and semantic progress. Exit guard consumes evidence; checkpoint performs no action.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_operator_turn_checkpoint tests.test_operator_exit_guard tests.test_user_interaction_policy
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/operator_turn_checkpoint.py runtime/orchestrator/operator_exit_guard.py docs/harness/operator-turn-execution-policy.md tests/test_operator_turn_checkpoint.py tests/test_operator_exit_guard.py && git commit -m 'feat(operator): persist safe-yield checkpoints'
```

---

### Task B3: Outbound Attention Delivery + Durable Receipt

**Requirements:** HWO-MUST-009,019.

**Files:**
- Create `runtime/orchestrator/attention_delivery.py`
- Modify `runtime/orchestrator/production_attention.py`
- Create `tests/test_attention_delivery.py`

**Interfaces:**
- Consumes: R2 delivery eligibility + Attention event
- Produces: capture adapter and gated HTTPS_WEBHOOK_V1 contract with immutable delivery receipt

- [ ] **Step 1: Write failing tests**

```python
def test_capture_delivery_is_exactly_once_per_event_id():
    adapter = CaptureAttentionDeliveryAdapter()
    event = fixture_r2_eligible_attention_event(event_id="e"*64)
    first = adapter.send(event)
    second = adapter.send(event)
    assert first.receipt_sha256 == second.receipt_sha256
    assert adapter.delivery_count(event["event_id"]) == 1
```
Also assert no live transport => `ATTENTION_DELIVERY_UNCONFIGURED`, ordinary incidents before the R2 threshold are not sent, and receipt persistence precedes delivered marking.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -v tests.test_attention_delivery
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Implement capture adapter for tests. Production HTTPS adapter accepts only allowlisted HTTPS endpoint + approved secret ref, bounded timeout/retry and event_id idempotency; leave live config disabled.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_attention_delivery tests.test_production_attention_watch tests.test_user_interaction_policy
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/attention_delivery.py runtime/orchestrator/production_attention.py tests/test_attention_delivery.py && git commit -m 'feat(attention): add outbound delivery receipts'
```

---

### Task B4: Historical Run Supersession

**Requirements:** HWO-MUST-010,017.

**Files:**
- Create `runtime/orchestrator/run_supersession.py`
- Modify `runtime/orchestrator/production_attention_watch.py`
- Create `tests/test_attention_supersession.py`

**Interfaces:**
- Consumes: legacy/stable run discovery
- Produces: `evaluate_supersession(event, candidate_run, record) -> SupersessionAssessment`, immutable `RunSupersessionRecord`, and archived-not-delivered disposition

- [ ] **Step 1: Write failing tests**

```python
def test_timestamp_alone_never_supersedes():
    old_event = fixture_terminal_pending_event(created_at="2026-09-18T00:00:00+00:00")
    newer_run = fixture_unrelated_newer_run(created_at="2026-09-19T00:00:00+00:00")
    assert evaluate_supersession(old_event, newer_run, record=None).archived is False
```
Also assert a digest-bound successor record archives but never deletes the old event, while an unrelated newer run cannot suppress it.

- [ ] **Step 2: Run RED verification**

```bash
python3 -m unittest -v tests.test_attention_supersession
```
Expected: at least the new behavior tests fail for the intended missing contract/implementation.

- [ ] **Step 3: Implement the minimal approved behavior**

Bind predecessor/successor run IDs, authority digests, reason and evidence refs. Never delete historical events merely to reduce backlog.

- [ ] **Step 4: Run focused + adjacent-authority GREEN verification**

```bash
python3 -m unittest -q tests.test_attention_supersession tests.test_production_attention_watch
```
Expected: PASS with no authority-boundary relaxation.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/run_supersession.py runtime/orchestrator/production_attention_watch.py tests/test_attention_supersession.py && git commit -m 'feat(attention): archive superseded run incidents'
```

---
