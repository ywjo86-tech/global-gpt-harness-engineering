# Full Plan User Decision & Attention R2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep approved Full Plan work running automatically while requesting user decisions only at real approval boundaries and delaying ordinary runtime notifications until recovery has made no semantic progress for 300 seconds.

**Architecture:** Add pure policy evaluators that never own orchestration transitions. Keep incident evidence durable at occurrence time, add delivery metadata to attention records, and make the read-only watcher decide when an incident is user-visible. Preserve FULL_PLAN/GATE_BY_GATE semantics and keep dangerous retries fail-closed unless existing approval coverage and effect reconciliation prove safe reuse.

**Tech Stack:** Python 3.12, unittest, existing durable Full Plan/Attention/approval contracts.

**Spec:** `docs/history/governance/2026-09-19/USER_DECISION_ATTENTION_POLICY_R2_APPROVED_DESIGN.md`

## Global Constraints

- Full Plan remains sole Task/Gate/fan-in/next-state authority.
- Router, MPRF, Full MCP, and AI Office authority boundaries do not move.
- Attention remains `OUTBOUND_ONLY` with `control_authority=NONE`.
- Ordinary user notification threshold is exactly 300 seconds without semantic/recovery progress.
- Genuine user-decision events are immediately delivery-eligible.
- No historical approval or attention evidence is rewritten.
- No provider expansion or AI Office Phase 7 activation.

## Review Focus

- An old unresolved incident must not notify after the run recovered and moved to a different reason.
- Heartbeats must not reset semantic-stall timing.
- A recurring same-root incident after recovery progress must restart its effective 300-second timer.
- Dangerous retries must remain blocked when effect evidence is absent or ambiguous.
- GATE_BY_GATE and FULL_PLAN transition behavior must remain byte-for-byte equivalent in meaning.

### Task 1: Pure User Interaction Policy

**Files:**
- Create: `runtime/orchestrator/user_interaction_policy.py`
- Create: `tests/test_user_interaction_policy.py`

**Interfaces:**
- Produces: `ApprovalCoverageEvidence`, `UserDecisionAssessment`, `AttentionDeliveryAssessment`, `evaluate_user_decision(...)`, `evaluate_attention_delivery(...)`.
- Consumes: plain mappings and timestamps only; no Full Plan mutation API.

- [ ] **Step 1: Write failing policy tests**

Tests must cover initial approval, material contract change, risk escalation, ambiguous dangerous effect, same-scope no-decision recovery, immediate decision delivery, deferred incident before/after 300s, progress reset, completed/cancelled suppression, and legacy event defaults.

- [ ] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest -v tests.test_user_interaction_policy`
Expected: FAIL because `runtime.orchestrator.user_interaction_policy` does not exist.

- [ ] **Step 3: Implement minimal pure policy module**

Required signatures:

```python
def evaluate_user_decision(*, approval_coverage: ApprovalCoverageEvidence | None,
                           material_contract_change: bool, requested_risk_class: str,
                           requested_operation: str, dangerous_reexecution: bool,
                           effect_reconciliation: str = "UNKNOWN") -> UserDecisionAssessment: ...

def evaluate_attention_delivery(event: Mapping[str, Any], state: Mapping[str, Any], *,
                                now: datetime, threshold_seconds: int = 300) -> AttentionDeliveryAssessment: ...
```

No function in this module may mutate a run, dispatch work, select provider/model, or execute an effect.

- [ ] **Step 4: Run GREEN and compile**

Run the focused test plus `python -m py_compile runtime/orchestrator/user_interaction_policy.py`.

- [ ] **Step 5: Commit**

Commit message: `feat(orchestrator): add user interaction policy evaluators`.

### Task 2: Durable Incident, Deferred User Delivery

**Files:**
- Modify: `runtime/orchestrator/production_attention.py`
- Modify: `runtime/orchestrator/production_attention_watch.py`
- Modify: `tests/test_production_attention_watch.py`
- Modify: `tests/test_full_plan_continuity_r2.py`

**Interfaces:**
- Consumes: `evaluate_attention_delivery(...)` from Task 1.
- Produces: attention records with optional `delivery_class` while preserving `schema_version=orchestration.user-attention.v1` and historical readability.

- [ ] **Step 1: Add failing tests**

Add tests proving immediate durable record creation, deferred ordinary delivery before 300s, delivery at/after 300s, semantic-progress timer reset, stale incident suppression after recovery, completed/cancelled suppression, immediate `WAITING_APPROVAL`, and historical v1 records without `delivery_class` remaining readable and receiving deterministic R2 class inference without file rewrite.

- [ ] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest -v tests.test_production_attention_watch tests.test_full_plan_continuity_r2`
Expected: new delivery-policy tests FAIL while existing tests remain green.

- [ ] **Step 3: Implement minimal metadata + watcher filter**

`AttentionOutbox.publish(...)` accepts optional `delivery_class` with allowed values `DEFERRED_INCIDENT`, `IMMEDIATE_DECISION`, `STALL_CONFIRMED`; missing historical value remains valid.

`discover_pending_attention(...)` retains read-only discovery and applies Task 1 delivery evaluation. It must never mark, resume, or mutate the source run.

- [ ] **Step 4: Run GREEN**

Run the two focused test modules and verify `control_authority=NONE` remains unchanged.

- [ ] **Step 5: Commit**

Commit message: `fix(attention): defer ordinary incident delivery until stalled`.

### Task 3: Full Plan Incident Classification and Dangerous Retry

**Files:**
- Modify: `runtime/orchestrator/production_full_plan_runner.py`
- Modify: `runtime/orchestrator/retry_policy.py`
- Modify: `tests/test_production_full_plan_runner.py`
- Modify: `tests/test_jarvis_bridge_support.py`
- Create: `tests/test_retry_policy_r2.py`

**Interfaces:**
- Consumes: Task 1 user-decision evaluator and Task 2 attention delivery classes.
- Produces: correct incident classification only; Full Plan retains all state transitions.

- [ ] **Step 1: Add failing tests**

Prove `WAITING_APPROVAL` is tagged `IMMEDIATE_DECISION`; provider/resource/preflight/dead-letter/artifact incidents are `DEFERRED_INCIDENT`; `STALLED_SUSPECTED` is `STALL_CONFIRMED`; ordinary FULL_PLAN next-Gate transition remains automatic; dangerous retry defaults to blocked, becomes allowed only with exact-compatible `ApprovalCoverageEvidence` plus `effect_reconciliation` in `NO_EFFECT` or `RECONCILED`, and stays blocked for `AMBIGUOUS`/missing evidence.

- [ ] **Step 2: Run RED**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest -v tests.test_production_full_plan_runner tests.test_retry_policy_r2`
Expected: new R2 assertions FAIL against current behavior.

- [ ] **Step 3: Implement minimal integration**

Keep `_handle_failure`, successor enqueue, Gate classification, and Router/MPRF/Full MCP contracts unchanged. Only pass delivery classification to the attention record and extend `should_retry(...)` with fail-closed, evidence-bound optional approval/effect arguments.

Required retry signature:

```python
def should_retry(item: TaskQueueItem, *, max_retries: int = 2,
                 approval_coverage: ApprovalCoverageEvidence | None = None,
                 effect_reconciliation: str = "UNKNOWN") -> RetryDecision: ...
```

- [ ] **Step 4: Run GREEN + mode regression**

Run Task 3 tests plus `tests.test_gate_orchestrator` and `tests.test_gate_supervisor`.

- [ ] **Step 5: Commit**

Commit message: `fix(full-plan): separate approval decisions from incident attention`.

### Task 4: Qualification, Negative-Space, and EDP Closure

**Files:**
- Create: `docs/history/governance/2026-09-19/USER_DECISION_ATTENTION_POLICY_R2_EDP_ALL_PASS.md`
- Create: `docs/history/governance/2026-09-19/USER_DECISION_ATTENTION_POLICY_R2_EDP_ALL_PASS.json`

**Interfaces:**
- Consumes: Tasks 1–3 implementation and all TEST-UDAP evidence.
- Produces: immutable qualification evidence for the refreshed Harness baseline.

- [ ] **Step 1: Run focused qualification**

Run all R2 policy/attention/retry tests plus Full Plan, Gate, operator-resume, approval, Router/MPRF/Full MCP authority regression surfaces.

- [ ] **Step 2: Run full regression**

Run: `/tmp/gch-edp-allpass-venv/bin/python -m unittest discover -s tests -q`
Expected: RC=0.

- [ ] **Step 3: Run static verification**

Run `python -m compileall -q runtime tests`, `git diff --check`, and AST/grep negative-space checks proving no new provider/model selection, Full MCP effect execution, or alternate next-state authority in the new policy module.

- [ ] **Step 4: Execute EDP-1.0 primary, negative-space, cross-document, adversarial, and PASS challenge passes**

Require `BLOCKER_COUNT=0`, `UNRESOLVED_MAJOR_COUNT=0`, `MUST_REQUIREMENT_COVERAGE=100%`, `MUST_TRACEABILITY_COVERAGE=100%`, `DOMAIN_EVIDENCE_COVERAGE=100%`, `ADVERSARIAL_NEW_BLOCKER_MAJOR=0`, and `MATERIAL_DEFECT_SEARCH=EXHAUSTED_FOR_AVAILABLE_EVIDENCE`.

- [ ] **Step 5: Seal closure commit**

Commit message: `docs(edp): close user decision attention policy r2`.

## Self-Review Result

- Spec coverage: UDAP-MUST-001~018 all map to Tasks 1–4 and TEST-UDAP-001~018.
- Placeholder scan: no unresolved placeholder markers remain.
- Interface consistency: Task 1 evaluators are consumed by Tasks 2–3; Task 4 consumes only public behavior/evidence.
- Scope protection: no planned modification to Router, MPRF, Full MCP, AI Office, or ordinary Gate transition semantics.
- Execution method: Full Plan Hybrid / inline execution already approved by the user.