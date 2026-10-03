# Harness Lifecycle V2 — Gate 4 Canary Qualification

Date: 2026-09-24
Status: PASS
Scope: successor-only qualification; no active project migration

## Purpose

Prove that Lifecycle V2 closes the approved-plan-to-durable-continuation gap while preserving existing Legacy runs and authority boundaries.

## Qualified successor

- Branch: `impl/harness-lifecycle-v2-compat-20260924`
- Gate 4 GREEN implementation commit: `22b32987d118da5578ffed8b24aa709fcdabe0b0`
- GitHub Actions run: `36011186409`

## Canary A — Legacy Preservation

PASS.

A legacy GPT operator job with no lifecycle binding resolves to `LEGACY`, keeps the existing `OPERATOR_TASK_RECEIPT_PENDING` behavior, requires no V2 authority bundle, and creates no `operator-dispatch-v2` artifacts.

## Canary B — Existing Run Preservation

PASS.

A durable Legacy run already waiting for its operator receipt is loaded by the V2-capable code without rewriting either its durable state bytes or its job object. Schema absence never migrates an existing run.

## Canary C — New V2 Closed Loop

PASS.

A synthetic three-Task V2 run proves:

1. Task 1 creates one durable dispatch and waits for operator ACK.
2. Supervisor/store restart between dispatch and receipt reuses the exact dispatch identity and record digest.
3. ACK transitions to receipt wait without duplicate dispatch.
4. Existing operator receipt v1 is sealed to the acknowledged dispatch through a separate V2 binding artifact.
5. DCC eligibility is evaluated only after `RECEIPT_SEALED`.
6. Continuation reopens only the exact waiting Full Plan state generation through `resume_wait_cas`.
7. Task 1 -> Task 2 -> Task 3 completes without duplicate dispatch files.

## Harness-wide recovery fix included

During Gate 4 qualification, `OPERATOR_DISPATCH_ACK_PENDING` was found to be missing from the shared wait/recovery taxonomy. The issue was reproduced RED and repaired without changing the stable Legacy supervisor semantics:

- common `wait_recovery` now classifies ACK wait as `DCC_OR_OPERATOR`;
- ACK wait is **not** added to DCC receipt auto-continuation reasons;
- `LifecycleV2FullPlanSupervisor` preserves the V2 ACK wait reason in a V2-only seam;
- the stable `DurableFullPlanSupervisor` remains unchanged for in-flight Legacy runs.

The interruption/root-cause record is also preserved on draft PR #15, comment `5815604850`.

## Verification

GitHub Actions run `36011186409`:

- focused: PASS
- full-regression: PASS
- regression-delta: PASS
- current-only regression: none

## Authority negative space

Lifecycle V2 does not create or absorb:

- user approval authority;
- provider/model selection authority;
- final assignee authority;
- completion authority;
- direct effect authority.

Production Execution Gateway / Full MCP remain the canonical state-changing path. OCPv2 remains normal remote ingress. RDC remains break-glass only.

## Migration decision

No active project is migrated by this Gate. Existing runs remain pinned to their original lifecycle/runtime semantics. Gate 5 may qualify AI Commerce M6 only at a fresh activation boundary after current project state is re-inspected through OCP.
