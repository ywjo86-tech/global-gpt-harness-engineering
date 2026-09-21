# Operator Control Plane V2 R2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a transport-agnostic GPT↔Harness remote control path that preserves the existing GPT Operator, Full Plan, continuation locking, Production Execution Gateway, Full MCP, migration-v2, approval, and evidence authorities while removing Remote Desktop Commander as a required control-plane dependency.

**Architecture:** OCPv2 is a non-authoritative ingress/egress extension around the existing Harness control path. Remote envelopes are authenticated, schema/digest/expiry/replay/CAS checked, converted into the existing `OperatorDirectiveV1`, then executed only through existing Full Plan continuation ownership and canonical execution boundaries; receipts/outbox projections are downstream evidence references only. The first reference transport is a bounded private GitHub control-channel adapter, but the core contracts remain transport-neutral.

**Tech Stack:** Python 3, stdlib dataclasses/json/hashlib/datetime/pathlib/fcntl-compatible existing Harness primitives, unittest/pytest-compatible repository test suite, existing Full Plan / Production Execution Gateway / SingleToolBroker / MigrationStore contracts.

**Spec:** `docs/superpowers/specs/2026-09-21-operator-control-plane-v2-r2-design.md`

## Global Constraints

- Source baseline for planning is `main@e2ce97a3741c070e538f817113a1b90845cc53c3`; revalidate source before implementation and stop on material drift.
- OCPv2 MUST NOT become a new orchestrator, provider/model selector, execution backend, canonical state store, completion authority, or recovery authority.
- Reuse `OperatorDirectiveV1`; do not create a competing operator-stage state machine.
- Provider/model fields remain forbidden in operator directives.
- All state-changing work must continue through the existing Full Plan → Production Execution Gateway → SingleToolBroker / Full MCP path.
- All competing request sources must converge on the existing continuation-owner epoch and canonical transaction lock; do not introduce a second run lock/lease authority.
- Transport delivery success never equals task/gate/migration completion.
- Runtime Migration v2 phase order and immutable digest bindings remain authoritative.
- For an already-qualified active migration: do not recreate qualification, successor registration, or the migration transaction.
- Remote Desktop Commander is optional/break-glass only after OCPv2 activation.
- Runtime credentials/secrets must never be committed to repository content or emitted into control/result payloads.
- Bootstrap/install/production activation remain separate authorization boundaries.
- Formal rollout order is `DISABLED → OBSERVE_ONLY → CONTROL_READ_ONLY → CONTROL_MUTATION_CANARY → ACTIVE`.
- Final implementation closure requires 0 BLOCKER, 0 unresolved MAJOR, full regression/EDP, observe-only live qualification, and controlled mutation canary PASS.

## Review Focus

- **Crash after canonical mutation but before OCP receipt write:** recovery must reconstruct status from canonical evidence and must not replay the mutation.
- **Concurrent reconcile/systemd and remote OCP requests:** both must fence through the same continuation-owner epoch/transaction boundary so only one mutation commits.
- **Edited/replayed/delayed transport messages:** message identity, digest, sequence, expiry, and state CAS must reject tamper/replay/stale work without mutation.
- **Transport/result delivery outage after successful action:** only the outbox projection may retry; canonical execution must not repeat.
- **Already-qualified migration resume:** existing qualification/successor/migration identity must be preserved while predecessor close uses exact transaction/phase/digest CAS.

---

## File Structure

### New core files

- `runtime/orchestrator/remote_operator_envelope.py` — immutable envelope schema, canonical serialization/digest, validation primitives, error taxonomy.
- `runtime/orchestrator/remote_operator_receipt.py` — non-authoritative durable receipt/replay ledger with atomic persistence.
- `runtime/orchestrator/remote_operator_outbox.py` — durable result-projection queue; retry is projection-only.
- `runtime/orchestrator/remote_operator_ingress.py` — ingress validation, receipt/replay checks, expected-state/CAS projection, bridge into existing `OperatorDirectiveV1`.
- `runtime/orchestrator/remote_operator_transport.py` — transport-neutral adapter protocol/types and bounded result projection model.
- `runtime/operator_transport/github_control_adapter.py` — optional reference adapter for a dedicated private GitHub control channel; no Harness mutation logic.

### Existing authoritative files expected to receive narrow integration hooks only

- `runtime/orchestrator/operator_control.py` — only if a public helper is needed for stable continuation-state digest/projection; do not alter stage authority semantics.
- `runtime/orchestrator/production_full_plan_runner.py` — narrow canonical entrypoint for remote directive execution using existing continuation owner/transaction semantics; no parallel lock model.
- `runtime/orchestrator/runtime_migration_handoff.py` — only if an explicit compare-and-set helper is required; preserve existing transition rules.
- `runtime/orchestrator/production_execution_gateway.py` — no authority expansion; optionally expose/consume correlation metadata already validated upstream.

### New/extended tests

- `tests/test_remote_operator_envelope.py`
- `tests/test_remote_operator_receipt.py`
- `tests/test_remote_operator_outbox.py`
- `tests/test_remote_operator_ingress.py`
- `tests/test_remote_operator_single_writer.py`
- `tests/test_remote_operator_migration.py`
- `tests/test_github_control_adapter.py`
- `tests/test_operator_control.py` — regression only.
- `tests/test_durable_continuation_locking.py` — regression/concurrency extension.
- `tests/test_runtime_migration_handoff.py` — migration CAS/resume regression extension.
- `tests/test_production_execution_gateway.py` or the repository's existing gateway test file — boundary regression; use the actual existing filename discovered at implementation start.
- Full repository regression suite.

---

### Task 1: Freeze Source, Interfaces, and OCPv2 Error Taxonomy

**Files:**
- Create: `runtime/orchestrator/remote_operator_envelope.py`
- Create: `tests/test_remote_operator_envelope.py`
- Read-only verify: `runtime/orchestrator/operator_control.py`
- Read-only verify: `runtime/orchestrator/production_full_plan_runner.py`
- Read-only verify: `runtime/orchestrator/runtime_migration_handoff.py`

**Interfaces:**
- Consumes: `OperatorDirectiveV1.from_mapping(payload: Mapping[str, Any]) -> OperatorDirectiveV1`.
- Produces: `RemoteOperatorEnvelopeV2`, `RemoteOperatorEnvelopeError`, `canonical_envelope_bytes()`, `validate_remote_envelope()`.

- [ ] **Step 1: Revalidate source snapshot and stop on drift**

Run:

```bash
git rev-parse HEAD
git status --short
git diff -- runtime/orchestrator/operator_control.py runtime/orchestrator/production_full_plan_runner.py runtime/orchestrator/runtime_migration_handoff.py
```

Expected: the planned baseline or an explicitly reviewed successor; no unreviewed local change in the three authority files. If HEAD differs from `e2ce97a3741c070e538f817113a1b90845cc53c3`, perform an impact review before continuing and record the new bound HEAD in the implementation evidence.

- [ ] **Step 2: Write failing envelope tests**

Create tests equivalent to:

```python
from runtime.orchestrator.remote_operator_envelope import (
    RemoteOperatorEnvelopeError,
    validate_remote_envelope,
)


def valid_payload():
    return {
        "schema_version": "orchestration.remote-operator-envelope.v2",
        "message_id": "MSG-0001",
        "sequence": 1,
        "issued_at": "2026-09-21T00:00:00+00:00",
        "expires_at": "2026-09-21T00:10:00+00:00",
        "actor": "GPT_OPERATOR",
        "transport": {
            "adapter_id": "GITHUB_CONTROL_V1",
            "channel_id": "CTRL-1",
            "source_actor_id": "GPT-CONNECTOR",
            "source_message_id": "issue-101-comment-1",
        },
        "project_id": "P1",
        "run_id": "R1",
        "task_id": "T1",
        "task_execution_id": "E1",
        "gate_id": "G1",
        "operator_directive": {
            "schema_version": "orchestration.operator-directive.v1",
            "project_id": "P1",
            "run_id": "R1",
            "task_id": "T1",
            "task_execution_id": "E1",
            "current_stage": "PREPARE",
            "requested_next_stage": "ACTION",
            "required_capabilities": ["filesystem_write"],
            "state_change_required": True,
            "input_artifact_digests": ["a" * 64],
            "gate_id": "G1",
            "directive_id": "D1",
        },
        "directive_digest": "",
        "expected": {
            "continuation_state_sha256": "b" * 64,
            "continuation_owner_epoch": 3,
            "canonical_run_state_sha256": "c" * 64,
            "migration_id": "",
            "migration_transaction_sha256": "",
            "migration_phase": "",
            "qualification_evidence_sha256": "",
            "source_head": "e" * 40,
            "runtime_release_digest": "d" * 64,
        },
        "authorization": {
            "risk_envelope_ref": "RISK-1",
            "risk_envelope_digest": "f" * 64,
            "manual_action_authorization_digest": "",
        },
        "envelope_sha256": "",
    }
```

Tests must cover: valid payload, unsupported schema, unknown top-level field, unsafe IDs, invalid sequence, invalid timestamp ordering, actor other than `GPT_OPERATOR`, provider/model field embedded in directive, directive identity mismatch with envelope, malformed digest, state-changing request without expected continuation digest/owner epoch, expired envelope.

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
python -m unittest -v tests.test_remote_operator_envelope
```

Expected: import/module-not-found failure.

- [ ] **Step 4: Implement immutable envelope schema and canonical digest**

Implement `RemoteOperatorEnvelopeV2` as a frozen dataclass or equivalent immutable value object. Use sorted canonical JSON serialization matching repository digest conventions. Reject unknown fields; validate exact nested field sets; call `OperatorDirectiveV1.from_mapping()` for the embedded directive rather than reimplementing operator-stage validation.

Required error classes/messages should map to stable result classes:

```text
SCHEMA_REJECTED
ACTOR_NOT_ALLOWED
DIRECTIVE_EXPIRED
DIGEST_MISMATCH
OPERATOR_DIRECTIVE_BLOCKED
```

- [ ] **Step 5: Add Review Focus test for edited provider/model payloads**

Add a test that injects each of `provider`, `model`, `provider_ref`, `model_ref` into `operator_directive` and asserts validation fails through the existing operator contract.

- [ ] **Step 6: Run focused tests and existing operator regression**

Run:

```bash
python -m unittest -v tests.test_remote_operator_envelope tests.test_operator_control
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add runtime/orchestrator/remote_operator_envelope.py tests/test_remote_operator_envelope.py
git commit -m "feat(ocp): add remote operator envelope v2 contract"
```

---

### Task 2: Add Non-Authoritative Durable Receipt / Replay Ledger

**Files:**
- Create: `runtime/orchestrator/remote_operator_receipt.py`
- Create: `tests/test_remote_operator_receipt.py`

**Interfaces:**
- Consumes: validated `RemoteOperatorEnvelopeV2`.
- Produces: `RemoteOperatorReceiptStore`, `ReceiptStatus`, `record_received()`, `record_terminal_projection()`, `classify_delivery()`.

- [ ] **Step 1: Write failing receipt/replay tests**

Test cases:

```text
new message ID + digest → NEW
same message ID + same digest → IDEMPOTENT_REPLAY
same message ID + different digest → TAMPER_DETECTED
sequence lower than accepted channel sequence → REPLAY_REJECTED
same sequence with different source message identity → REPLAY_REJECTED
symlink receipt root/file → rejected
partial write/crash → old durable receipt remains readable
```

Include an assertion that receipt payload contains no canonical project-state field such as `current_stage`, `migration_phase`, or arbitrary task truth except references/digests copied from canonical evidence.

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m unittest -v tests.test_remote_operator_receipt
```

Expected: module missing.

- [ ] **Step 3: Implement atomic receipt store**

Use repository atomic-write primitives if available; otherwise match `OperatorContinuationStore`'s tempfile + fsync + replace pattern. Store under a dedicated runtime subtree such as:

```text
runtime/operator_control/remote_receipts/<adapter>/<channel>/<message_id>.json
runtime/operator_control/remote_receipts/<adapter>/<channel>/.sequence.json
```

Do not store or derive canonical task state.

- [ ] **Step 4: Add Review Focus replay/tamper tests**

Explicitly test an edited transport message where `source_message_id` is unchanged but content digest changes; expected `TAMPER_DETECTED`, zero mutation callback invocations.

- [ ] **Step 5: Run focused tests**

```bash
python -m unittest -v tests.test_remote_operator_receipt tests.test_remote_operator_envelope
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runtime/orchestrator/remote_operator_receipt.py tests/test_remote_operator_receipt.py
git commit -m "feat(ocp): add durable replay-safe receipt ledger"
```

---

### Task 3: Add Durable Result Outbox With Projection-Only Retry

**Files:**
- Create: `runtime/orchestrator/remote_operator_outbox.py`
- Create: `tests/test_remote_operator_outbox.py`

**Interfaces:**
- Consumes: canonical result/evidence references and `message_id`/`directive_digest`.
- Produces: `RemoteResultProjectionV1`, `RemoteResultOutbox`, `enqueue_projection()`, `mark_published()`.

- [ ] **Step 1: Write failing outbox tests**

Required scenarios:

```text
projection can be queued atomically
queued projection survives process restart
publish failure leaves projection pending
retry invokes only publisher callback, never execution callback
same projection ID/digest is idempotent
same projection ID/different digest is rejected
projection without canonical evidence reference cannot claim CANONICAL_ACTION_COMPLETED
```

- [ ] **Step 2: Verify RED**

```bash
python -m unittest -v tests.test_remote_operator_outbox
```

Expected: module missing.

- [ ] **Step 3: Implement projection model and durable outbox**

Required projection fields:

```text
message_id
directive_digest
project_id
run_id
gate_id
task_id
canonical_state_ref
canonical_state_sha256
effect_evidence_refs
checkpoint_ref
checkpoint_sha256
migration_transaction_sha256
result_class
result_summary
projected_at
```

`CANONICAL_ACTION_COMPLETED` must require a non-empty canonical evidence/reference set validated by the ingress/execution integration layer.

- [ ] **Step 4: Add Review Focus outage test**

Use separate counters for `execute()` and `publish()`; simulate execute success + publisher exception + publish retry. Assert execute count remains exactly 1 while publish count increases.

- [ ] **Step 5: Run tests**

```bash
python -m unittest -v tests.test_remote_operator_outbox
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runtime/orchestrator/remote_operator_outbox.py tests/test_remote_operator_outbox.py
git commit -m "feat(ocp): add durable result projection outbox"
```

---

### Task 4: Implement Ingress Validation and Existing OperatorDirective Bridge

**Files:**
- Create: `runtime/orchestrator/remote_operator_ingress.py`
- Create: `tests/test_remote_operator_ingress.py`
- Modify only if needed: `runtime/orchestrator/operator_control.py`
- Extend regression: `tests/test_operator_control.py`

**Interfaces:**
- Consumes: `RemoteOperatorEnvelopeV2`, `RemoteOperatorReceiptStore`, canonical-state reader callbacks.
- Produces: `ValidatedRemoteDirective`, `IngressDecision`, `prepare_existing_operator_directive()`.

- [ ] **Step 1: Write failing ingress tests**

Tests must prove:

```text
valid envelope returns existing OperatorDirectiveV1 instance
actor/channel/source allowlist enforced
expired envelope rejected before canonical mutation callback
replay/tamper classification enforced before mutation callback
project/run/task/execution/gate mismatch rejected
state-changing request requires expected continuation digest + epoch
risk envelope mismatch returns AUTHORIZATION_SCOPE_MISMATCH
transport metadata never appears in OperatorDirectiveV1 payload
```

- [ ] **Step 2: Verify RED**

```bash
python -m unittest -v tests.test_remote_operator_ingress
```

- [ ] **Step 3: Implement ingress without action logic**

`remote_operator_ingress.py` may validate, normalize, correlate, and call `OperatorDirectiveV1.from_mapping()`. It must not import shell/subprocess/git execution libraries or `ProductionToolTransport` launchers.

- [ ] **Step 4: Add static negative-space assertion**

Add a test that inspects the module source/AST and fails if forbidden direct-execution imports/calls are introduced, including `subprocess`, `os.system`, direct Git command execution, or direct `MigrationStore._save`/JSON mutation.

- [ ] **Step 5: Run ingress + operator regression**

```bash
python -m unittest -v tests.test_remote_operator_ingress tests.test_operator_control
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runtime/orchestrator/remote_operator_ingress.py tests/test_remote_operator_ingress.py runtime/orchestrator/operator_control.py tests/test_operator_control.py
git commit -m "feat(ocp): bridge validated remote directives to existing operator control"
```

Only include `operator_control.py`/its test in the commit if the task actually required a narrow public digest/projection helper; otherwise leave them untouched.

---

### Task 5: Add Canonical CAS Snapshot and Single-Writer Execution Entry

**Files:**
- Modify: `runtime/orchestrator/production_full_plan_runner.py`
- Create: `tests/test_remote_operator_single_writer.py`
- Extend: `tests/test_durable_continuation_locking.py`
- Modify: `runtime/orchestrator/remote_operator_ingress.py`

**Interfaces:**
- Consumes: validated directive + expected continuation/run state digests and expected owner epoch.
- Produces: one public canonical entrypoint such as `execute_remote_operator_directive(...) -> Mapping[str, Any]` that internally uses existing ownership/transaction methods; exact name should follow existing runner naming discovered during implementation, but only one entrypoint should exist.

- [ ] **Step 1: Inspect exact existing continuation APIs before editing**

Locate and document signatures for:

```text
claim_attested_continuation_owner
assert_current_epoch
assert_current_epoch_locked
continuation_transaction
canonical state load/persist methods
```

The implementation plan must bind to these existing APIs rather than inventing replacements.

- [ ] **Step 2: Write failing single-writer tests**

Create tests with two concurrent/ordered request actors:

```text
request A claims epoch N
request B claims epoch N+1
request A attempts mutation → stale epoch failure
request B enters transaction → success
```

Add a systemd/reconcile simulation callback and an OCP callback that both use the same canonical entrypoint/ownership boundary; assert at most one mutation counter increment.

- [ ] **Step 3: Add in-lock double-CAS test**

Test a state change between pre-lock validation and transaction acquisition. Inside-lock re-read must detect digest mismatch and return `STALE_DIRECTIVE` without calling the transition/mutation callback.

- [ ] **Step 4: Verify RED**

```bash
python -m unittest -v tests.test_remote_operator_single_writer tests.test_durable_continuation_locking
```

- [ ] **Step 5: Implement the narrow canonical remote-entry helper**

Requirements:

```text
pre-lock expected-state comparison
→ claim/verify continuation owner
→ enter existing continuation_transaction
→ reload canonical state
→ compare expected digests/epoch again
→ invoke existing canonical transition function
→ return canonical state/evidence refs
```

Do not add a new lock file or OCP-owned lease.

- [ ] **Step 6: Run focused and existing locking regressions**

```bash
python -m unittest -v tests.test_remote_operator_single_writer tests.test_durable_continuation_locking
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add runtime/orchestrator/production_full_plan_runner.py runtime/orchestrator/remote_operator_ingress.py tests/test_remote_operator_single_writer.py tests/test_durable_continuation_locking.py
git commit -m "feat(ocp): converge remote directives on canonical continuation ownership"
```

---

### Task 6: Enforce Execution Gateway / Full MCP Boundary for ACTION Mutation

**Files:**
- Modify narrowly: `runtime/orchestrator/remote_operator_ingress.py`
- Modify narrowly if correlation support is necessary: `runtime/orchestrator/production_execution_gateway.py`
- Add/extend gateway test file discovered in repository.
- Create or extend: `tests/test_remote_operator_ingress.py`

**Interfaces:**
- Consumes: ACTION-stage existing directive after canonical owner/CAS validation.
- Produces: existing gateway request/response/effect evidence references only.

- [ ] **Step 1: Locate current production execution gateway tests**

Run repository search for imports of `build_gateway_request`, `validate_gateway_request`, and gateway execution methods. Record the exact test filename before changes.

- [ ] **Step 2: Write failing boundary test**

Inject a fake canonical execution-gateway callable into the remote entrypoint and assert:

```text
ACTION state-changing directive → gateway callable exactly once
VERIFY/read-only directive → no mutation gateway call unless existing canonical flow requires it
no direct broker/file/shell callback exposed to the transport layer
```

- [ ] **Step 3: Add authorization-projection test**

A state-changing remote request lacking the existing canonical plan/requirement/tool-authorization binding required by Production Execution Gateway must fail closed with `EXECUTION_GATEWAY_BLOCKED`.

- [ ] **Step 4: Verify RED**

Run the focused ingress/gateway tests and confirm expected failure.

- [ ] **Step 5: Implement minimal integration**

Route mutation through the same existing request-builder/validator/execution path used by production workers. Do not add new operation registrations for remote control itself.

- [ ] **Step 6: Run gateway and tool-transport regression**

Run the discovered gateway tests plus production tool-transport tests and the remote ingress tests.

Expected: PASS; existing closed registry and sensitive-scope protections unchanged.

- [ ] **Step 7: Commit**

```bash
git add runtime/orchestrator/remote_operator_ingress.py runtime/orchestrator/production_execution_gateway.py tests/
git commit -m "feat(ocp): preserve production execution gateway action boundary"
```

Stage only files actually changed by this task.

---

### Task 7: Add Migration-v2 CAS Integration and Qualified-Resume Protection

**Files:**
- Modify narrowly: `runtime/orchestrator/runtime_migration_handoff.py` only if a public CAS helper is required.
- Create: `tests/test_remote_operator_migration.py`
- Extend: `tests/test_runtime_migration_handoff.py`
- Modify: `runtime/orchestrator/remote_operator_ingress.py`

**Interfaces:**
- Consumes: migration ID, expected transaction SHA, exact phase, expected qualification digest where applicable.
- Produces: canonical `MigrationStore` transition result and new transaction digest.

- [ ] **Step 1: Write failing migration CAS tests**

Required tests:

```text
wrong transaction digest → STALE_DIRECTIVE, no advance
wrong phase → STALE_DIRECTIVE, no advance
SUCCESSOR_VERIFIED → PREDECESSOR_CLOSED remote request → rejected because ACTIVE_RUNTIME_QUALIFICATION required
ACTIVE_RUNTIME_QUALIFICATION with matching qualification digest → PREDECESSOR_CLOSED allowed through existing API
attempt to replace qualification digest → rejected
attempt to recreate same predecessor migration → rejected
post-close rollback → rejected
```

- [ ] **Step 2: Add Review Focus existing-qualified-resume test**

Build a v2 transaction already at `ACTIVE_RUNTIME_QUALIFICATION` with qualification evidence. Feed the remote close directive and assert:

```text
create_v2 call count = 0
successor registration call count = 0
qualification advance call count = 0
PREDECESSOR_CLOSED advance count = 1
```

- [ ] **Step 3: Verify RED**

```bash
python -m unittest -v tests.test_remote_operator_migration tests.test_runtime_migration_handoff
```

- [ ] **Step 4: Implement CAS wrapper around existing MigrationStore**

Prefer a read/compare/advance sequence inside the same canonical ownership/transaction boundary rather than adding a second migration store. If a public helper is added, it should validate `transaction_sha256` and phase then delegate to existing `advance()`.

- [ ] **Step 5: Run focused migration regression**

```bash
python -m unittest -v tests.test_remote_operator_migration tests.test_runtime_migration_handoff
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runtime/orchestrator/runtime_migration_handoff.py runtime/orchestrator/remote_operator_ingress.py tests/test_remote_operator_migration.py tests/test_runtime_migration_handoff.py
git commit -m "feat(ocp): bind remote migration actions to migration-v2 CAS"
```

Only include `runtime_migration_handoff.py` if a narrow helper was required.

---

### Task 8: Close Crash-After-Mutation Receipt Gap

**Files:**
- Modify: `runtime/orchestrator/remote_operator_receipt.py`
- Modify: `runtime/orchestrator/remote_operator_ingress.py`
- Modify: `runtime/orchestrator/remote_operator_outbox.py`
- Create/extend: `tests/test_remote_operator_ingress.py`, `tests/test_remote_operator_outbox.py`

**Interfaces:**
- Consumes: canonical evidence resolver callback keyed by directive/correlation identity.
- Produces: reconstructed receipt/projection only when canonical evidence proves the action already committed.

- [ ] **Step 1: Write failing crash-recovery test**

Simulate:

```text
canonical mutation callback commits and writes canonical evidence
→ artificial crash before OCP receipt write
→ process restart
→ same remote message arrives
```

Expected:

```text
canonical mutation callback total count remains 1
receipt is reconstructed from canonical evidence
projection is queued/published
```

- [ ] **Step 2: Add ambiguous-evidence test**

If receipt is missing and canonical evidence cannot prove the directive completed, the system must return a blocked/reconciliation-required result rather than automatically replaying mutation.

- [ ] **Step 3: Verify RED**

Run ingress/receipt/outbox tests.

- [ ] **Step 4: Implement evidence-backed reconstruction path**

Do not infer completion from transport metadata, timestamps, or absence of errors. Require exact directive/correlation binding to canonical evidence.

- [ ] **Step 5: Run focused tests**

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runtime/orchestrator/remote_operator_receipt.py runtime/orchestrator/remote_operator_ingress.py runtime/orchestrator/remote_operator_outbox.py tests/test_remote_operator_ingress.py tests/test_remote_operator_outbox.py
git commit -m "fix(ocp): reconcile crash gap from canonical execution evidence"
```

---

### Task 9: Define Transport-Neutral Adapter Contract

**Files:**
- Create: `runtime/orchestrator/remote_operator_transport.py`
- Create: `tests/test_remote_operator_transport.py`

**Interfaces:**
- Produces protocol/classes such as:

```python
class RemoteOperatorTransport(Protocol):
    def receive(self) -> Sequence[RawControlEnvelope]: ...
    def acknowledge_delivery(self, message_id: str) -> None: ...
    def publish_projection(self, projection: Mapping[str, Any]) -> None: ...
```

Exact typing may follow repository conventions, but adapter methods must expose transport only and no canonical mutation callback.

- [ ] **Step 1: Write failing contract tests**

Create a fake adapter and prove ingress can consume it and outbox can publish through it without importing vendor-specific code.

- [ ] **Step 2: Add disable-equivalence test**

Instantiate Harness control without any transport adapter. Existing local/canonical operator functions must remain usable; OCP transport absence may disable remote intake only.

- [ ] **Step 3: Verify RED**

```bash
python -m unittest -v tests.test_remote_operator_transport
```

- [ ] **Step 4: Implement protocol and adapter registry/selection by configuration identity only**

Transport selection must never affect Provider Router/model selection or execution semantics.

- [ ] **Step 5: Run tests**

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runtime/orchestrator/remote_operator_transport.py tests/test_remote_operator_transport.py
git commit -m "feat(ocp): add transport-neutral remote operator adapter contract"
```

---

### Task 10: Implement Bounded GitHub Private-Control Reference Adapter

**Files:**
- Create: `runtime/operator_transport/__init__.py`
- Create: `runtime/operator_transport/github_control_adapter.py`
- Create: `tests/test_github_control_adapter.py`

**Interfaces:**
- Consumes: a small injected GitHub client interface, allowlisted repository/channel identity, allowlisted actor identity.
- Produces: `RawControlEnvelope` objects and bounded result publication.

- [ ] **Step 1: Write fake-client tests first**

No live GitHub call in unit tests. Fake-client tests must cover:

```text
wrong repository/channel identity → SOURCE_NOT_ALLOWED
wrong actor → ACTOR_NOT_ALLOWED
edited same-message content → downstream tamper detection possible because stable source_message_id preserved
private-channel payload parsed but not executed by adapter
result publish emits bounded projection only
adapter never modifies source-code branch/files
```

- [ ] **Step 2: Verify RED**

```bash
python -m unittest -v tests.test_github_control_adapter
```

- [ ] **Step 3: Implement minimal adapter**

The adapter may fetch control messages and publish results/comments through an injected client. It must not import `MigrationStore`, `DurableFullPlanSupervisor`, `ProductionToolTransport`, subprocess, shell helpers, or Git source mutation functions.

- [ ] **Step 4: Add secret-redaction/output-boundary test**

Use a projection containing a synthetic credential-like string; assert publication is rejected/redacted according to the repository's approved secret-scan utility. If no reusable scan utility exists, add a bounded projection validator in the OCP layer rather than a generic new security framework.

- [ ] **Step 5: Run tests**

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runtime/operator_transport/__init__.py runtime/operator_transport/github_control_adapter.py tests/test_github_control_adapter.py
git commit -m "feat(ocp): add bounded GitHub control transport adapter"
```

---

### Task 11: Add Observe-Only Service Loop Without Self-Authorization

**Files:**
- Create: `runtime/orchestrator/remote_operator_service.py`
- Create: `tests/test_remote_operator_service.py`
- Do not create/enable systemd unit in this task.

**Interfaces:**
- Consumes: transport adapter, ingress, receipt store, outbox.
- Produces: one-shot `poll_once(mode=...)` service function supporting `OBSERVE_ONLY` and later explicit modes.

- [ ] **Step 1: Write mode-gating tests**

Required assertions:

```text
DISABLED → receive not called
OBSERVE_ONLY → messages can be validated/projected but no mutation entrypoint called
CONTROL_READ_ONLY → only state_change_required=False directives permitted
CONTROL_MUTATION_CANARY → mutation allowed only for explicit canary scope/ID
ACTIVE → normal approved-scope remote control enabled
unknown mode → fail closed
```

- [ ] **Step 2: Verify RED**

Run service tests.

- [ ] **Step 3: Implement one-shot service loop**

Keep scheduling/daemonization outside core logic. The loop should process bounded batches and persist receipts/outbox between runs.

- [ ] **Step 4: Add bootstrap negative-space test**

Assert importing/running the service module does not create systemd files, install packages, mutate git config, or start background daemons.

- [ ] **Step 5: Run tests**

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runtime/orchestrator/remote_operator_service.py tests/test_remote_operator_service.py
git commit -m "feat(ocp): add authorization-gated one-shot control service"
```

---

### Task 12: Add Harness Operator Console Read/Control Contract Projection

**Files:**
- Create: `runtime/orchestrator/operator_console_projection.py`
- Create: `tests/test_operator_console_projection.py`

**Interfaces:**
- Consumes: authorization-filtered canonical read-model data plus OCP receipt/outbox projections.
- Produces: non-authoritative console projection only.

- [ ] **Step 1: Write failing projection tests**

Projection should expose, when available:

```text
project/run/gate/stage refs
execution readiness
operator authority label
transport state
checkpoint/evidence refs
migration phase/digest refs
blocked/stale/replay/security status
```

Tests must prove projection cannot write canonical state and does not expose secrets/restricted fields.

- [ ] **Step 2: Add Dashboard authority regression test**

A console control request must normalize into the same OCPv2 remote envelope/ingress path; no direct Full Plan or Full MCP call from the console projection module.

- [ ] **Step 3: Verify RED**

Run projection tests.

- [ ] **Step 4: Implement minimal projection**

No UI framework in this task. This is only the backend read/control contract that the later Harness Operator Console consumes.

- [ ] **Step 5: Run tests**

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add runtime/orchestrator/operator_console_projection.py tests/test_operator_console_projection.py
git commit -m "feat(ocp): add non-authoritative operator console projection"
```

---

### Task 13: Full OCPv2 Regression, EDP, and Static Authority Audit

**Files:**
- Create: `docs/harness/OCPV2_R2_IMPLEMENTATION_DIAGNOSIS_20260921.md`
- Create/update only generated evidence under the repository's approved docs/evidence pattern.
- No production activation in this task.

**Interfaces:**
- Consumes: all implemented OCPv2 modules/tests.
- Produces: implementation-level regression and EDP evidence.

- [ ] **Step 1: Run all OCPv2 focused tests**

```bash
python -m unittest -v \
  tests.test_remote_operator_envelope \
  tests.test_remote_operator_receipt \
  tests.test_remote_operator_outbox \
  tests.test_remote_operator_ingress \
  tests.test_remote_operator_single_writer \
  tests.test_remote_operator_migration \
  tests.test_remote_operator_transport \
  tests.test_github_control_adapter \
  tests.test_remote_operator_service \
  tests.test_operator_console_projection
```

Expected: all PASS.

- [ ] **Step 2: Run existing authority/regression suites**

At minimum:

```bash
python -m unittest -v \
  tests.test_operator_control \
  tests.test_durable_continuation_locking \
  tests.test_runtime_migration_handoff
```

Also run the discovered Production Execution Gateway and Production Tool Transport test modules.

- [ ] **Step 3: Run full repository regression**

Use the repository's canonical full-test command. Record total/pass/skip/fail counts and exact HEAD.

Expected: zero failures; any newly skipped test requires explicit disposition.

- [ ] **Step 4: Run static authority search**

Search new OCP files for forbidden direct authority patterns:

```text
subprocess / os.system / shell runner
provider/model selection
MigrationStore private-save/direct JSON mutation
ToolEffectJournal direct write
new run lock/lease implementation
canonical task/gate completion state owned by OCP receipt/outbox
```

Expected: zero unauthorized findings.

- [ ] **Step 5: Run Code Intelligence impact review**

Bind analysis to exact post-implementation HEAD. CI-01/05/06/07/08/09 must be evidenced. If Graphify/CodeGraph tooling is unavailable, document CI-02/03 fallback/N/A strictly according to the approved extension without using absence as fail-open authorization.

- [ ] **Step 6: Perform EDP-1.0 implementation re-diagnosis**

Required final metrics before implementation PASS:

```text
BLOCKER_COUNT                           = 0
UNRESOLVED_MAJOR_COUNT                 = 0
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
```

- [ ] **Step 7: Commit evidence**

```bash
git add docs/harness/OCPV2_R2_IMPLEMENTATION_DIAGNOSIS_20260921.md
git commit -m "docs(ocp): record R2 implementation regression and EDP evidence"
```

---

### Task 14: Prepare Explicit Bootstrap Package — Do Not Activate Yet

**Files:**
- Create: `deploy/operator-control-plane-v2/README.md`
- Create: `deploy/operator-control-plane-v2/ocpv2.example.env`
- Create: `deploy/operator-control-plane-v2/ocpv2.service.example`
- Create: `tests/test_ocpv2_deploy_package.py`

**Interfaces:**
- Consumes: implemented one-shot service and adapter config names.
- Produces: reviewed deployment templates only; no installation or enablement action.

- [ ] **Step 1: Write deployment-package validation tests**

Tests must assert:

```text
example env contains placeholders, never real secrets
default mode is OBSERVE_ONLY or DISABLED
systemd template does not auto-enable itself
service uses explicit working directory/user/env-file references
restart policy cannot bypass application-level mutation mode gates
```

- [ ] **Step 2: Verify RED**

Run deployment package tests.

- [ ] **Step 3: Create deployment templates**

`README.md` must describe the explicit user authorization boundary between preparation and server installation/enablement. It must include rollback/disable commands as documentation, but implementation execution must not run them yet.

- [ ] **Step 4: Run tests**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add deploy/operator-control-plane-v2 tests/test_ocpv2_deploy_package.py
git commit -m "docs(ocp): prepare non-activating deployment package"
```

---

## Post-Plan Execution Gates

### Gate A — Implementation Branch Review

Before any server bootstrap:

```text
all Task 1-14 code/tests committed
full regression PASS
implementation EDP ALL PASS
0 BLOCKER / 0 unresolved MAJOR
source/authority drift check PASS
```

### Gate B — Explicit Bootstrap Authorization

Requires separate user approval because it installs/enables a persistent server-side control component.

After approval only:

```text
install service files/credentials outside repository
→ start OBSERVE_ONLY
```

### Gate C — Observe-Only Live Qualification

Verify on Jarvis:

```text
transport receives bounded message
identity/digest/sequence/expiry checks work
canonical state is read/projected correctly
zero mutation occurs
receipt/outbox survive restart
RDC not required
```

### Gate D — Controlled Mutation Canary

Requires separate approval if outside the already approved implementation-risk envelope. Use one bounded, reversible, non-migration canary first. Verify exactly-once mutation and effect evidence.

### Gate E — Resume Current Runtime Migration

Only after the canary and migration-state re-read succeed:

```text
load existing active migration
verify exact transaction SHA
verify phase = ACTIVE_RUNTIME_QUALIFICATION
verify existing qualification digest
verify existing successor/r2 identity
DO NOT recreate migration/qualification/successor
→ canonical predecessor close
→ C2
→ C3
→ C4
→ ABC-EDP
```

Any mismatch is `STALE_DIRECTIVE`/BLOCKED and returns to GPT/user review rather than guessing or recreating state.

### Gate F — Operator Console v0

After migration work is stable, implement the visual console against `operator_console_projection.py`. It remains a non-authoritative operations client, not the formal Advancement Dashboard.

---

## Self-Review Record

### Spec coverage

All R2 design obligations are mapped to Tasks 1-14 and Post-Plan Gates A-F: authority preservation, transport neutrality, replay/idempotency, CAS, single-writer, gateway/full-MCP boundary, migration-v2 invariants, crash recovery, result outbox, security, bootstrap authorization, dashboard boundary, roadmap order, rollout/rollback, and EDP closure.

### Placeholder scan

No `TODO`, `TBD`, `FIXME`, “implement later”, or unbounded “add tests/error handling” steps are permitted in this plan. Implementation workers must treat any newly discovered material ambiguity as a plan-review stop rather than filling it silently.

### Type/interface consistency

Core flow is consistent throughout:

```text
RemoteOperatorEnvelopeV2
→ validate_remote_envelope
→ RemoteOperatorReceiptStore classification
→ OperatorDirectiveV1
→ canonical Full Plan continuation owner/transaction
→ Production Execution Gateway
→ Full MCP/effect evidence
→ RemoteResultProjectionV1
→ RemoteResultOutbox
→ RemoteOperatorTransport.publish_projection
```

### Review Focus coverage

- crash-after-mutation gap → Task 8;
- concurrent reconcile/OCP writers → Task 5;
- edited/replayed/delayed message → Tasks 1-2/4;
- result-delivery outage → Task 3/8;
- already-qualified migration resume → Task 7 + Gate E.

