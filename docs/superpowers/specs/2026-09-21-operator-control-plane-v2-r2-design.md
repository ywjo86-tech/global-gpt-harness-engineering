# OPERATOR_CONTROL_PLANE_V2 R2

**Document ID:** OCPV2-R2  
**Status:** APPROVED DESIGN  
**Approved by:** Project Owner  
**Approval date:** 2026-09-21  
**Source Snapshot:** `main@e2ce97a3741c070e538f817113a1b90845cc53c3`

## Executive Decision

OCPv2 R2 is a **non-authoritative remote control transport extension**. It does not create a new orchestrator, action plane, canonical state machine, provider/model selector, completion authority, or recovery authority.

The authoritative chain remains:

```text
GPT Logical Operator
→ OCPv2 Transport Adapter
→ OCPv2 Ingress Validation / Replay Guard / CAS Guard
→ Existing OperatorDirectiveV1
→ Existing Operator / Approval / Full Plan
→ Existing Continuation Owner Epoch + Transaction Lock
→ Production Execution Gateway
→ SingleToolBroker / Full MCP
→ Canonical Effect Evidence / Checkpoint / Migration State
→ OCPv2 Result Projection / Outbox
→ GPT Logical Operator
```

OCPv2 transport and projection have `control_authority=NONE`, `provider_authority=NONE`, `mutation_authority=NONE`, `completion_authority=NONE`, `recovery_authority=NONE`, and `canonical_state=NONE`.

## Required Outcomes

1. Preserve the existing `GPT_OPERATOR` authority model.
2. Preserve Full Plan as planning/orchestration/next-state authority.
3. Preserve Provider Router as sole provider/model-selection authority.
4. Preserve Execution Backend / Full MCP as action authority.
5. Preserve existing durable continuation and recovery semantics.
6. Prevent duplicate/replayed/stale/out-of-order remote directives.
7. Prevent dual-writer/split-brain mutation.
8. Preserve runtime migration v2 phase and digest invariants.
9. Preserve approval/risk-envelope boundaries.
10. Provide durable receipts/result projection without a second source of truth.
11. Remain transport-pluggable.
12. Make Remote Desktop Commander optional/break-glass rather than required.

## Non-Goals

OCPv2 SHALL NOT create a second Operator state machine, replace `OperatorDirectiveV1`, fork Full Plan, directly call shell/filesystem/Git/build/test/migration mutation/deployment primitives, directly edit migration JSON or continuation state, write ToolEffectJournal directly, select provider/model, treat transport state as canonical state, bypass an Implementation Risk Authorization Envelope, auto-expand permissions/secrets/runtimes, or treat transport delivery as task completion.

## Existing Contracts Reused

- `runtime/orchestrator/operator_control.py`: `OperatorDirectiveV1`, `ManualActionAuthorizationV1`, `ContinuationState`, `OperatorContinuationStore`.
- Full Plan continuation owner epoch + transaction lock: the single-writer boundary.
- `runtime/orchestrator/production_execution_gateway.py`: mandatory state-changing execution entry.
- `runtime/orchestrator/production_tool_transport.py`: closed registry / scope binding / security / effect evidence.
- `runtime/orchestrator/runtime_migration_handoff.py`: authoritative migration v2 state and transition API.

Existing logical stages remain `ENTRY → PREPARE → ACTION → VERIFY → REVIEW → GATE_DECISION`. OCPv2 does not create another stage taxonomy.

## Remote Control Envelope V2

Schema: `orchestration.remote-operator-envelope.v2`.

Required classes of fields: unique message identity, monotonic sequence, issue/expiry timestamps, authenticated transport/channel/source identity, exact project/run/task/execution/gate identity, embedded existing `orchestration.operator-directive.v1`, directive digest, expected continuation/run/migration/source/runtime bindings, approval/risk-envelope references where required, and an envelope digest.

Rules:
- provider/model fields remain forbidden in the embedded operator directive;
- state-changing directives require canonical expected-state bindings;
- migration directives require migration transaction digest + phase;
- expired envelopes fail closed;
- digest mismatch fails closed;
- same message ID with changed digest is tamper detection;
- previously completed same-digest delivery is idempotent;
- lower sequence is replay rejection.

## Compare-and-Set Safety

Every remote mutation is conditional on exact expected canonical identity/state. Minimum CAS includes project/run/task/gate, operator stage, continuation-state digest, and continuation-owner epoch. Migration adds migration ID, transaction digest, phase, and qualification evidence digest when applicable.

Processing order:

```text
receive
→ validate envelope
→ load canonical state
→ compare expected bindings
→ claim/verify current continuation owner
→ enter canonical transaction
→ reload/recompare inside lock
→ invoke existing canonical path
→ capture canonical evidence
→ commit canonical state
→ persist non-authoritative receipt
→ enqueue result projection
```

Any mismatch returns `STALE_DIRECTIVE` with no mutation.

## Single-Writer Rule

OCPv2 never owns a competing run lock. systemd/reconcile and remote request paths MUST converge on the same existing Full Plan continuation-owner epoch and canonical transaction lock. A newer epoch fences older owners. Existing lock order remains run-lock → transaction-lock.

## Replay / Crash / Outbox Rules

- Same ID/same digest → idempotent replay, no second mutation.
- Same ID/different digest → `TAMPER_DETECTED`, no mutation.
- Expired/lower-sequence/stale-state → fail closed, no mutation.
- Canonical mutation success + result-delivery failure → retry outbox projection only, never mutation.
- Crash after mutation but before local receipt → reconstruct from canonical evidence where proven; do not re-mutate merely because the receipt is absent.

## Transport Security

The core is transport-agnostic. A GitHub adapter, if used, must use a dedicated private control channel/repository rather than the public source repository. Runtime credentials remain outside repository content, control and output content contain refs/digests rather than raw credentials, output is secret-scanned/redacted, and permission/credential expansion remains separately governed.

## Runtime Migration v2

OCPv2 never replaces `MigrationStore`. Existing authoritative order remains:

```text
PREPARED
→ PREDECESSOR_QUIESCED
→ RUNTIME_ACTIVATED
→ SUCCESSOR_REGISTERED
→ SUCCESSOR_VERIFIED
→ ACTIVE_RUNTIME_QUALIFICATION
→ PREDECESSOR_CLOSED
```

For an already-qualified active migration: do not recreate qualification, do not recreate successor registration, and do not create a new migration. Verify the existing transaction + qualification digest, then close predecessor through the existing API when legal and continue the approved post-close sequence.

## Approval / Risk Boundary

OCPv2 transports approval references; it does not manufacture them. Implementation Authorization, Implementation Risk Authorization Envelope, Production Deployment, Secret/Credential Expansion, Critical Permission Expansion, Paid Service Activation, Material Re-scope, and Production Activation remain separate gates where applicable. Scope excess returns `AUTHORIZATION_SCOPE_MISMATCH` with no mutation.

## Dashboard / Operator Console Boundary

An early Harness Operator Console may be an operations/diagnostic client of the same transport but is not the formal Advancement Dashboard and never becomes canonical run state, orchestrator, provider selector, or action plane. Future List Operations and 3D views consume the same authorization-filtered read model and remain downstream of Governance → Full Plan → Execution Backend / Full MCP.

## Roadmap Ordering

Canonical order is unchanged:

```text
PHASE 5 AI OFFICE Harness Upgrade → AI_OFFICE_STABLE_BASELINE
PHASE 6 Jarvis Upgrade → JARVIS_STABLE_BASELINE
```

Operational priority may be:

```text
P0-A OCPv2 transport extension
P0-B finish the existing approved Harness migration sequence
P1 Harness Operator Console v0 (non-authoritative client)
P2 Jarvis Upgrade
P3 Formal Unified Operations Dashboard + 3D Office View
P4 Remaining approved Harness / AI Office Advancement work
```

P1 is not a new canonical phase.

## Implementation Completion Gate

Implementation may be declared complete only after unit/contract, replay/tamper, single-writer/epoch, gateway-boundary, Full MCP regression, migration v2 regression, crash/recovery, security, EDP regression, code-intelligence impact review, observe-only live qualification, and controlled mutation canary all pass with 0 BLOCKER and 0 unresolved MAJOR.

Deployment state must progress `DISABLED → OBSERVE_ONLY → CONTROL_READ_ONLY → CONTROL_MUTATION_CANARY → ACTIVE`; direct jump to active mutation is prohibited. Disabling OCPv2 must leave canonical Harness operation intact.

## EDP Design Re-Diagnosis

The approved R2 design closed the previous 6 BLOCKER and 3 MAJOR findings by: reusing the existing Operator contract, forcing mutation through Full Plan/Execution Gateway/Full MCP, adding message identity/digest/sequence/expiry/CAS/idempotency, converging all mutation sources on the existing continuation-owner/transaction boundary, making the transport core vendor-agnostic, separating bootstrap authorization, preserving the PHASE 5→6 roadmap, keeping Dashboard non-authoritative, and requiring canonical evidence before completion projection.

Design-level EDP closure:

```text
BLOCKER_COUNT                           = 0
UNRESOLVED_MAJOR_COUNT                 = 0
UNRESOLVED_MINOR_COUNT                 = 0
MUST_REQUIREMENT_COVERAGE               = 100%
MUST_TRACEABILITY_COVERAGE              = 100%
DOMAIN_EVIDENCE_COVERAGE                = 100%
NEGATIVE_SPACE_OPEN_MATERIAL_COUNT      = 0
CROSS_DOCUMENT_CONFLICT_COUNT           = 0
BROKEN_REFERENCE_COUNT                  = 0
UNRESOLVED_MATERIAL_TBD_COUNT           = 0
UNRESOLVED_MATERIAL_OPEN_QUESTION_COUNT = 0
ADVERSARIAL_NEW_BLOCKER_MAJOR           = 0
PASS_CHALLENGE_OPEN_COUNT               = 0
REGRESSION_REDIAGNOSIS_STATUS           = PASS
MATERIAL_DEFECT_SEARCH                  = EXHAUSTED_FOR_AVAILABLE_EVIDENCE
EDP-1.0                                = ALL PASS
DECISION                               = PASS
```

This PASS is design/architecture approval readiness only; it is not implementation, deployment, activation, or live-runtime qualification PASS.
