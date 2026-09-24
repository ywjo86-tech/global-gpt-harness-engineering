# Harness Lifecycle V2 Compatibility Design

**Date:** 2026-09-24  
**Status:** DESIGN FOR USER REVIEW  
**Base:** `main@c591b01e8a1d9d9bb2dc438ca85f6c2ffcc79a03`  
**Branch:** `design/harness-lifecycle-v2-compat-20260924`

## 1. Purpose

Add the missing durable execution bridge between an approved Full Plan and continuous task execution without replacing existing project authority contracts or forcing in-flight runs to migrate.

The design must prevent the recurring pattern where a project reaches the next Task/LV, waits for an operator receipt or freshly materialized authority, and remains stopped even though the surrounding Full Plan is approved.

## 2. Success Criteria

Lifecycle V2 is successful only if all of the following are true:

1. Existing in-flight runs continue under their original runtime release, authority contracts, task/LV projections, receipts, and checkpoints.
2. New V2 runs can move from approved plan -> task authority -> operator dispatch -> verification receipt -> checkpoint -> next eligible task without requiring a fresh conversational decision at every step.
3. `GPT_OPERATOR` remains the logical operator. V2 creates no second operator principal.
4. Production Execution Gateway / Full MCP remain the only canonical state-changing effect path.
5. OCPv2 remains the normal external control ingress. RDC remains break-glass recovery only.
6. Existing authority systems are adapted, not replaced: approved Full Plan evidence, Gate/LV authority, `task_lv_authority_projection`, continuation contracts, receipts, Provider Router/MPRF, Tool Authorization, and completion authority remain canonical in their own scopes.
7. No existing project is forced to migrate mid-run.
8. A failure in V2 can disable V2 and return new activations to the existing stable lifecycle without rewriting existing run state.

## 3. Current Problem

The stable runtime already contains the main pieces:

- approved Full Plan/operator job binding;
- Gate/LV execution queues;
- operator-plan receipt v1/v2;
- DCC continuation eligibility;
- checkpoint/recovery and wait-state handling;
- task/LV compatibility projection for legacy TASK/STAGE/GATE contracts.

However, these pieces do not yet form one closed lifecycle for every project shape.

The failure pattern is:

```text
approved work
  -> current Task completes
  -> next Task becomes logically eligible
  -> authority/dispatch handoff is not materialized as one durable transition
  -> WAITING_RESOURCE / OPERATOR_TASK_RECEIPT_PENDING
  -> external conversation/operator must rediscover the next action
```

`OPERATOR_TASK_RECEIPT_PENDING` is valid as a post-dispatch wait condition, but it must not substitute for a durable dispatch state.

## 4. Non-Goals

Lifecycle V2 will not:

- replace Full Plan, OCPv2, DCC, Provider Router, MPRF, Production Execution Gateway, Full MCP, Tool Authorization, or completion authority;
- convert JARVIS or Dashboard into runtime truth or execution authority;
- absorb Ruflo/Jev into Harness Core;
- migrate old receipt files or rewrite historical run state;
- automatically clean/reset project worktrees;
- replay completed Tasks/Gates to manufacture V2 evidence;
- use RDC as the normal execution path;
- activate Ruflo/Jev live external capability without their own qualification evidence;
- merge or mutate the eight active project branches as part of the core implementation.

## 5. Compatibility Principle

Lifecycle V2 is an orchestration envelope over existing authority contracts, not a replacement authority model.

```text
                         Harness Lifecycle
                                |
             +------------------+------------------+
             |                                     |
       Legacy Adapter                           V2 Envelope
             |                                     |
 existing Task/LV projection            authority bundle + dispatch
 existing run/job/receipt                        |
             |                                     |
             +------------ common Gate execution--+
                                |
                   Production Execution Gateway
                                |
                             Full MCP
```

A run selects its lifecycle version at activation time and keeps that version for the life of the run unless an explicit, separately qualified migration checkpoint is executed.

## 6. Lifecycle Version Binding

Introduce a run-level lifecycle binding:

```json
{
  "schema_version": "orchestration.lifecycle-binding.v1",
  "lifecycle_mode": "LEGACY" | "V2",
  "bound_at_activation": true,
  "migration_allowed": false,
  "runtime_release_digest": "..."
}
```

Rules:

- missing lifecycle binding means `LEGACY` for backward compatibility;
- an existing run is never reinterpreted as V2 because new code is deployed;
- V2 activation must record the lifecycle binding before task dispatch;
- lifecycle mode is immutable for ordinary continuation;
- controlled migration is a distinct operation and is out of the initial V2 implementation slice.

## 7. Execution Authority Bundle

For a V2 activation, materialize one immutable authority bundle from already approved evidence.

The bundle does not create authority. It references and normalizes existing authority evidence.

Minimum fields:

```json
{
  "schema_version": "orchestration.execution-authority-bundle.v1",
  "project_id": "...",
  "run_id": "...",
  "approved_plan_sha256": "...",
  "approved_spec_sha256": "...",
  "approval_ref": "...",
  "expected_branch": "...",
  "activation_source_head": "...",
  "runtime_release_digest": "...",
  "lifecycle_mode": "V2",
  "gate_authorities": [
    {
      "gate_id": "...",
      "authority_kind": "TASK_LV_PROJECTION | CONTINUATION_CONTRACT | FULL_PLAN_GATE",
      "authority_ref": "...",
      "authority_sha256": "..."
    }
  ]
}
```

The bundle must not contain or invent:

- `final_assignee`;
- provider/model choice;
- completion authority;
- direct effect authority;
- synthetic approval.

## 8. Legacy Compatibility Adapter

The existing `task_lv_authority_projection` path remains valid.

The adapter converts legacy authority into a normalized V2-readable view without modifying the original artifact.

For legacy runs:

```text
legacy authority -> existing runner behavior
```

For new V2 runs using a legacy project contract:

```text
task_lv_authority_projection
  -> LegacyAuthorityAdapter
  -> normalized gate authority reference
  -> ExecutionAuthorityBundle
```

The adapter is read-only. It may reject malformed or mismatched evidence, but it may not repair or rewrite a project contract.

## 9. Durable Dispatch State

Add explicit operator-dispatch state between task eligibility and receipt wait.

State model:

```text
TASK_READY
  -> DISPATCH_PREPARED
  -> OPERATOR_DISPATCHED
  -> OPERATOR_ACKNOWLEDGED
  -> EXECUTING
  -> VERIFYING
  -> RECEIPT_SEALED
  -> CHECKPOINTED
  -> NEXT_TASK_READY
```

Required properties:

- dispatch identity is create-once/idempotent;
- dispatch binds project/run/gate, source head, plan/spec digests, lifecycle binding, and authority bundle digest;
- receipt must bind the same dispatch identity;
- a receipt without prior dispatch is invalid for V2;
- a second conflicting dispatch for the same gate is rejected;
- restarts reconcile from durable dispatch evidence instead of guessing from conversation history.

## 10. Receipt and Continuation

Existing operator receipt v1/v2 remain supported for legacy runs.

V2 adds dispatch binding either by:

1. a new receipt schema revision, or
2. a separately sealed dispatch-attestation referenced by the existing attested receipt.

The implementation plan must choose the smallest compatible option after tests establish the seam.

DCC auto-continuation becomes eligible only when:

- lifecycle mode is V2;
- authority bundle validates;
- current dispatch validates;
- receipt is sealed and bound to the dispatch;
- existing continuation contract/attestation checks pass;
- owner epoch is current;
- next Gate/Task dependencies are satisfied.

DCC still does not gain mutation authority. It only authorizes continuation of the already approved execution path.

## 11. Failure Handling

V2 must fail closed by category.

### 11.1 Authority mismatch

Result: `BLOCKED / AUTHORITY_BUNDLE_INVALID`.

No receipt is created and no worker executes.

### 11.2 Dispatch exists but operator does not acknowledge

Result: `WAITING_RESOURCE / OPERATOR_DISPATCH_ACK_PENDING`.

Recovery reuses the same dispatch identity; no second task is created.

### 11.3 Operator acknowledged but no receipt exists

Result: `WAITING_RESOURCE / OPERATOR_TASK_RECEIPT_PENDING`.

This is the correct use of the existing wait reason.

### 11.4 Receipt exists but binding differs

Result: quarantine/block. Never reinterpret the receipt.

### 11.5 Runtime restart

Reconcile from durable lifecycle binding + authority bundle + dispatch + receipt state. Conversation history is not required.

### 11.6 V2 defect

Disable V2 for new activations. Existing V2 runs remain pinned for diagnosis; existing legacy runs are unaffected.

## 12. OCP Boundary

OCPv2 remains the external control plane.

Lifecycle V2 does not add a new OCP request kind in the first slice. Existing approved activation paths remain the entry point.

The already observed GitHub ingress publication issue should be hardened separately using the proven two-phase publication pattern:

```text
create inert placeholder
  -> obtain source message ID
  -> update same comment with sealed OCP envelope
```

That transport hardening is related but not required to redefine task authority.

## 13. Project Compatibility Matrix

### 13.1 AI Office

- preserve current in-flight activation/run as LEGACY;
- do not reinterpret current B5 wait state as V2;
- complete or preserve the current checkpoint first;
- any future migration requires a separate compatibility checkpoint.

### 13.2 AI Commerce Intelligence

- preserve current M5/M6 checkpoint;
- after alias/onboarding resolution, M6 is a suitable first real V2 activation candidate;
- no M7 or live activation is implied.

### 13.3 System Financial Trading Office

- Tasks 1-9 remain complete and must not rerun;
- after canonical onboarding, Task 10 may be the first V2 activation boundary.

### 13.4 OCP Upgrade

- stable OCP runtime remains running;
- Lifecycle V2 integration is qualified in a successor runtime/branch;
- no in-place control-plane swap during V2 development.

### 13.5 JARVIS / Dashboard

- consumes read-model state only;
- lifecycle fields are additive/optional for UI compatibility;
- JARVIS does not become execution authority.

### 13.6 Ruflo

- preserve PR #12 qualification evidence;
- no direct edits to the qualified branch during core V2 work;
- rebase/requalify after V2 core is stable;
- live activation remains separately gated.

### 13.7 JEV

- same policy as Ruflo;
- immutable Router/provider/model binding remains unchanged;
- V2 must not add fallback/provider-selection authority.

### 13.8 Family AI English

- preserve existing `FAMILY_AI_ENGLISH_COACH` mapping and `task_lv_authority_projection`;
- existing run/attempts remain LEGACY;
- new activation may opt into V2 through the LegacyAuthorityAdapter;
- no migration by schema absence/presence alone.

## 14. Canary Requirements

Before any active project uses V2, three independent canaries must pass.

### Canary A — Legacy Preservation

Prove a legacy TASK/LV project executes exactly as before with no V2 artifacts required.

### Canary B — Existing Run Preservation

Load an already-created legacy run in a V2-capable runtime and prove its lifecycle remains LEGACY and its state is not rewritten.

### Canary C — New V2 Closed Loop

Synthetic project with at least three tasks:

```text
Task 1 -> dispatch -> receipt -> checkpoint
       -> Task 2 -> dispatch -> receipt -> checkpoint
       -> Task 3 -> complete
```

The canary must survive a supervisor restart between dispatch and receipt and continue from durable state without duplicate execution.

## 15. Test Strategy

TDD is mandatory.

Focused tests must cover:

- missing lifecycle binding defaults to LEGACY;
- V2 lifecycle binding is immutable;
- authority bundle rejects branch/head/digest drift;
- legacy adapter preserves existing Task/LV contract semantics;
- dispatch is idempotent and conflict rejecting;
- receipt without dispatch is invalid in V2;
- restart reconstruction does not duplicate dispatch;
- existing receipt v1/v2 remain valid for LEGACY;
- DCC only auto-continues after receipt-sealed V2 transaction;
- no provider/model/effect/completion authority appears in V2 artifacts;
- all three canaries pass;
- full repository regression has no current-only regression.

## 16. Rollout Gates

```text
G1  Freeze and record compatibility baselines
G2  Add lifecycle binding + data contracts (no behavior change)
G3  Add LegacyAuthorityAdapter
G4  Add durable dispatch store/state machine
G5  Bind receipt/continuation to dispatch
G6  Canary A/B/C
G7  AI Commerce M6 candidate qualification
G8  SFT Task 10 candidate qualification
G9  AI Office migration design checkpoint only
G10 Family new-activation qualification
G11 Ruflo/Jev requalification
G12 JARVIS read-model integration
G13 OCP successor integration qualification
G14 Promote V2 as default for new activations
```

Promotion at G14 changes only the default for **new activations**. Existing runs never change lifecycle mode because of promotion.

## 17. Rollback

Rollback class: `NEW_ACTIVATION_DEFAULT_DISABLE`.

Rollback requirements:

- set V2 default off for new activations;
- preserve all existing run directories and receipts;
- do not rewrite V2 runs as legacy;
- do not revert stable authority systems;
- do not require RDC;
- keep diagnostics sufficient to resume a V2 run after a corrected successor runtime is qualified.

## 18. Implementation Boundary for First Slice

The first implementation slice is deliberately small:

1. lifecycle binding contract;
2. execution authority bundle contract;
3. legacy authority adapter;
4. durable dispatch record/state transitions;
5. focused compatibility tests;
6. Canary A/B/C fixtures/tests.

No active project migration is included in the first slice.

## 19. Design Invariants

- INV-01: existing run lifecycle semantics never change implicitly.
- INV-02: V2 materializes references to authority; it does not create authority.
- INV-03: no dispatch without approved, digest-bound authority.
- INV-04: no V2 PASS receipt without a matching dispatch.
- INV-05: no auto-continuation before receipt sealing and existing continuation checks.
- INV-06: no duplicate dispatch after restart/replay.
- INV-07: legacy receipt and Task/LV contracts remain accepted for legacy runs.
- INV-08: Production Execution Gateway / Full MCP retain effect authority.
- INV-09: GPT_OPERATOR remains the logical operator principal.
- INV-10: OCPv2 remains normal remote control ingress; RDC remains break-glass only.
- INV-11: JARVIS/Dashboard are projections/interaction surfaces, not runtime truth.
- INV-12: Ruflo/JEV remain external advisory capabilities with no authority drift.
- INV-13: project-specific migration is separately qualified and never inferred.

## 20. Decision

Proceed with a side-by-side, activation-bound Lifecycle V2 compatibility layer. Do not replace the stable lifecycle in place and do not migrate any of the eight active projects during the first implementation slice.
