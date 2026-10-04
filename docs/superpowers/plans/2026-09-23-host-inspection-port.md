# Host Inspection Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bounded RDC-independent read path from OCPv2 to approved JARVIS-SERVER project state without granting OCP shell, mutation, provider, planning, or completion authority.

**Architecture:** OCP keeps GitHub transport/receipt/result-delivery ownership. A new Harness Host Inspection Port resolves only registered project roots, reuses `WorkspacePathPolicy`, `FilesystemService`, and `GitService`, adds narrow service/Harness observers, and publishes typed no-effect results through the existing durable OCP delivery lifecycle. Existing V2 mutation/resume behavior remains unchanged.

**Tech Stack:** Python 3, unittest/pytest, existing OCPv2 transport, Full MCP read services, systemd user `show`, durable JSON/outbox utilities.

**Spec:** `docs/superpowers/specs/2026-09-23-ocp-observation-gateway-design.md`

## Global Constraints

- `OCP_EXECUTION_AUTHORITY=NO`; `NEW_EXECUTION_OWNER=NO`.
- No arbitrary shell, argv, environment overrides, provider/model fields, network target, Git publication, or filesystem mutation.
- Do not call production `FullMCPRuntime.call()` or synthesize `InvocationContext` for inspection.
- Reuse the existing `OnboardingRegistry` for alias/project/root identity; do not create a second root registry.
- Reuse the existing OCP durable result-delivery lifecycle; do not create an unrelated second pending/published state machine.
- Legacy `RemoteOperatorEnvelopeV2` and legacy `READ_ONLY_ACCEPTED` behavior must remain backward-compatible.
- Feature activation is OFF by default and must fail closed.

## Review Focus

1. Registered alias points to a project whose canonical root moved or became a symlink: request must BLOCK before any read.
2. A read request targets a sensitive or out-of-scope path: `WorkspacePathPolicy` must reject it without fallback.
3. A Git diff attempts external diff/textconv/prompt/network behavior: existing `GitService` protections must remain effective.
4. A sealed result is retried after transport failure: result is republished without rerunning inspection.
5. OCP receives malformed/unknown request kinds while ACTIVE: mutation path must remain unchanged and the new request must fail closed.

---

### Task 1: Typed Host Inspection Contract



**Files:**
- Create: `runtime/orchestrator/host_inspection_contract.py`
- Test: `tests/test_host_inspection_contract.py`

**Interfaces:**
- Produces: `HostInspectionRequestV1.from_mapping(payload)`, `HostInspectionResultV1`, `HOST_INSPECTION_OPERATIONS`.
- Consumes: no runtime service; pure validation only.

- [ ] **Step 1: Write failing contract tests**

```python
request = HostInspectionRequestV1.from_mapping({
    "schema_version": "orchestration.host-inspection-request.v1",
    "request_id": "INSP-1", "correlation_id": "CORR-1",
    "project_alias": "global-gpt-harness-engineering",
    "operation": "git.status", "arguments": {},
    "state_change_required": False,
})
self.assertEqual(request.operation, "git.status")
with self.assertRaises(HostInspectionContractError):
    HostInspectionRequestV1.from_mapping({**request.to_dict(), "operation": "shell.execute"})
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_host_inspection_contract -v`
Expected: import/module failure because the contract does not exist.

- [ ] **Step 3: Implement the closed request/result dataclasses**

```python
HOST_INSPECTION_OPERATIONS = frozenset({
    "filesystem.read", "filesystem.search", "filesystem.metadata",
    "git.status", "git.diff", "git.branch",
    "user_service.properties", "harness.attention",
})

@dataclass(frozen=True, slots=True)
class HostInspectionRequestV1:
    schema_version: str
    request_id: str
    correlation_id: str
    project_alias: str
    operation: str
    arguments: Mapping[str, Any]
    state_change_required: bool = False
```

Validation must reject unknown fields/operations, absolute caller roots, executable/argv/env/provider/model keys, and any `state_change_required=True`.

- [ ] **Step 4: Run GREEN and full suite**

Run: `python -m unittest tests.test_host_inspection_contract -v && python -m unittest discover -s tests -p 'test_host_inspection*.py' -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/host_inspection_contract.py tests/test_host_inspection_contract.py
git commit -m "feat(ocpv2): add typed host inspection contract"
```

### Task 2: Registered Project Resolution and Safe Read Services

**Files:**
- Create: `runtime/orchestrator/host_inspection_port.py`
- Test: `tests/test_host_inspection_port.py`
- Reuse unchanged: `runtime/full_mcp/path_policy.py`, `filesystem_service.py`, `git_service.py`
- Reuse unchanged: `runtime/orchestrator/project_onboarding.py`

**Interfaces:**
- Consumes: `OnboardingRegistry.entries()`, `WorkspacePathPolicy`, `FilesystemService`, `GitService`.
- Produces: `HostInspectionPort.inspect(request: HostInspectionRequestV1) -> HostInspectionResultV1`.

- [ ] **Step 1: Write failing tests for alias resolution and read operations**

```python
port = HostInspectionPort(registry_root=registry_root, read_scopes=(".",))
result = port.inspect(request(operation="git.branch"))
self.assertEqual(result.status, "OK")
self.assertEqual(result.data["branch"], "main")

entry = registry_root / "aliases" / "demo.json"
payload = json.loads(entry.read_text()); payload["project_root"] = str(base / "moved")
entry.write_text(json.dumps(payload))
with self.assertRaisesRegex(HostInspectionError, "PROJECT_BINDING_INVALID"):
    port.inspect(request(operation="git.status"))
```

Also test sensitive paths, symlink traversal, max byte bounds, `git.diff`, `filesystem.read/search/metadata`.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_host_inspection_port -v`
Expected: module/class missing.

- [ ] **Step 3: Implement minimal port composition**

```python
class HostInspectionPort:
    def inspect(self, request: HostInspectionRequestV1) -> HostInspectionResultV1:
        root = self._resolve_registered_project(request.project_alias)
        policy = WorkspacePathPolicy(root, read_scopes=self.read_scopes, mutable_scopes=())
        filesystem = FilesystemService(policy)
        git = GitService(root, policy)
        handlers = {
            "filesystem.read": lambda a: filesystem.read(**a),
            "filesystem.search": lambda a: filesystem.search(**a),
            "filesystem.metadata": lambda a: filesystem.metadata(**a),
            "git.status": lambda a: git.status(a.get("paths", ())),
            "git.diff": lambda a: git.diff(**a),
            "git.branch": lambda a: git.branch(),
        }
        return HostInspectionResultV1.ok(request, handlers[request.operation](dict(request.arguments)))
```

Do not import `ProcessService`, `FullMCPRuntime`, mutation/publication services, or subprocess in this module.

- [ ] **Step 4: Run GREEN plus reused Full MCP read tests**

Run: `python -m unittest tests.test_host_inspection_port tests.full_mcp.test_filesystem tests.full_mcp.test_git -v`
These are the existing Full MCP filesystem/Git service suites under `tests/full_mcp/`.
Expected: PASS with no Full MCP read regression.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/host_inspection_port.py tests/test_host_inspection_port.py
git commit -m "feat(ocpv2): reuse safe services for host inspection"
```

### Task 3: Narrow Service and Harness Attention Observers

**Files:**
- Create: `runtime/orchestrator/user_service_observer.py`
- Modify: `runtime/orchestrator/host_inspection_port.py`
- Test: `tests/test_user_service_observer.py`
- Test: `tests/test_host_inspection_port.py`

**Interfaces:**
- Produces: `UserServiceObserver.read(unit_id: str) -> dict[str, str]`.
- Reuses: `production_attention_watch.discover_pending_attention()` for `harness.attention`.

- [ ] **Step 1: Write failing fixed-allowlist tests**

```python
observer = UserServiceObserver(
    allowed_units=frozenset({"ocpv2.service"}),
    runner=fake_systemctl_show,
)
self.assertEqual(observer.read("ocpv2.service")["ActiveState"], "active")
with self.assertRaisesRegex(UserServiceObserverError, "UNIT_NOT_ALLOWED"):
    observer.read("ssh.service")
```

Assert the runner receives exactly `systemctl --user show UNIT --property=ActiveState,SubState,Result,ExecMainStatus` and no caller-controlled argv.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_user_service_observer -v`
Expected: missing module.

- [ ] **Step 3: Implement bounded observer and wire the two operations**

`user_service.properties` uses the observer; `harness.attention` calls existing `discover_pending_attention(search_root, ...)` with server-configured roots only.

- [ ] **Step 4: Run GREEN/regression**

Run: `python -m unittest tests.test_user_service_observer tests.test_host_inspection_port tests.test_production_attention_watch -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/user_service_observer.py runtime/orchestrator/host_inspection_port.py tests/test_user_service_observer.py tests/test_host_inspection_port.py
git commit -m "feat(ocpv2): add bounded service and attention inspection"
```

### Task 4: Additive Remote Host-Inspection Envelope

**Files:**
- Create: `runtime/orchestrator/remote_control_envelope.py`
- Modify: `runtime/orchestrator/ocpv2_runtime_service.py`
- Test: `tests/test_remote_control_envelope.py`
- Test: `tests/test_ocpv2_runtime_service.py`

**Interfaces:**
- Produces: `RemoteControlEnvelopeV1`, `decode_remote_control_payload(raw: Mapping[str, Any])`.
- Compatibility: existing `RemoteOperatorEnvelopeV2` remains valid and unchanged.

- [ ] **Step 1: Write failing host-inspection envelope tests**

```python
value = seal_remote_control_envelope({
    "schema_version": "orchestration.remote-control-envelope.v1",
    "request_kind": "HOST_INSPECTION",
    "message_id": "MSG-I1", "sequence": 2,
    "issued_at": issued, "expires_at": expires, "actor": "GPT_OPERATOR",
    "transport": transport,
    "payload": inspection_request.to_dict(), "payload_digest": "",
    "authorization": {"inspection_policy_ref": "POLICY-1"},
    "envelope_sha256": "",
})
self.assertEqual(validate_remote_control_envelope(value, now=now).request_kind, "HOST_INSPECTION")
```

Reject unknown kind, provider/model fields, payload digest drift, expired messages, and `state_change_required=True`.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_remote_control_envelope -v`
Expected: missing module.

- [ ] **Step 3: Implement additive schema/decoder**

`decode_remote_control_payload()` dispatches by `schema_version`; V2 delegates to `validate_remote_envelope()`, V1 validates the typed request. Do not alter V2 fields/digests.

- [ ] **Step 4: Run GREEN plus V2 regression**

Run: `python -m unittest tests.test_remote_control_envelope tests.test_remote_operator_envelope tests.test_ocpv2_runtime_service -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/remote_control_envelope.py runtime/orchestrator/ocpv2_runtime_service.py tests/test_remote_control_envelope.py tests/test_ocpv2_runtime_service.py
git commit -m "feat(ocpv2): add typed host inspection remote request"
```

### Task 5: Reuse the Existing Durable Result Delivery Lifecycle



**Files:**
- Modify: `runtime/orchestrator/remote_operator_outbox.py`
- Modify: `runtime/operator_transport/github_control_adapter.py`
- Test: `tests/test_remote_operator_outbox.py`
- Test: `tests/test_remote_operator_transport.py`

**Interfaces:**
- Produces: additive `RemoteInspectionProjectionV1` plus `parse_remote_projection(mapping)`.
- Preserves: `RemoteResultProjectionV1` and `RemoteResultOutbox` create-once/pending/published semantics.

- [ ] **Step 1: Write failing retry/replay tests**

```python
projection = RemoteInspectionProjectionV1.from_result(result, message_id="MSG-I1")
outbox.enqueue_projection(projection)
with self.assertRaises(RuntimeError):
    outbox.publish_pending(failing_publisher)
restarted = RemoteResultOutbox(root)
self.assertEqual(restarted.publish_pending(successful_publisher), 1)
self.assertEqual(port.inspect_calls, 1)
```

Also prove legacy `RemoteResultProjectionV1` round-trips unchanged and GitHub result prefix/secret scan/byte limit remain identical.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_remote_operator_outbox tests.test_remote_operator_transport -v`
Expected: inspection projection type unsupported.

- [ ] **Step 3: Generalize parsing without creating a second outbox**

Store either known projection schema under the same pending/published lifecycle. `publish_projection()` stays transport-neutral and receives mappings exactly as today.

- [ ] **Step 4: Run GREEN**

Run: `python -m unittest tests.test_remote_operator_outbox tests.test_remote_operator_transport -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/remote_operator_outbox.py runtime/operator_transport/github_control_adapter.py tests/test_remote_operator_outbox.py tests/test_remote_operator_transport.py
git commit -m "feat(ocpv2): persist host inspection results in existing outbox"
```

### Task 6: Runtime Composition, Mode Gating, and Feature-Off Default



**Files:**
- Modify: `runtime/orchestrator/remote_operator_service.py`
- Modify: `runtime/orchestrator/ocpv2_runtime_service.py`
- Modify: `deploy/operator-control-plane-v2/ocpv2.user.service.in`
- Test: `tests/test_remote_operator_service.py`
- Test: `tests/test_ocpv2_runtime_service.py`

**Interfaces:**
- Consumes: `HostInspectionPort.inspect()` and the additive remote-control decoder.
- Produces: exact mode behavior from the spec; V2 mutation callback remains `execute_authorized_canonical()`.

- [ ] **Step 1: Write failing mode/negative-space tests**

```python
self.assertEqual(service.poll_once(mode="OBSERVE_ONLY").inspected, 1)
self.assertEqual(service.poll_once(mode="CONTROL_READ_ONLY").inspected, 1)
self.assertEqual(active_mutation_result.executed, 1)
self.assertEqual(mutation_executor_calls, [("MSG-M1", "D1")])
```

Add source assertions proving no `FullMCPRuntime`, `ProcessService`, `register_job(`, provider router, or arbitrary shell path enters the host-inspection branch.

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests.test_remote_operator_service tests.test_ocpv2_runtime_service -v`
Expected: inspection callback/config missing.

- [ ] **Step 3: Wire feature flag and callback**

Use a dedicated environment flag such as `OCP_HOST_INSPECTION_ENABLED=0|1`; absent/invalid means disabled. In ACTIVE/CANARY, branch by validated request kind before calling the legacy mutation path. Inspection failure returns a typed inspection error projection; it never falls through to mutation.

- [ ] **Step 4: Run GREEN and OCP focused regression**

Run: `python -m unittest tests.test_remote_operator_service tests.test_ocpv2_runtime_service tests.test_ocpv2_authority_negative_space tests.test_ocpv2_single_execution_owner -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/remote_operator_service.py runtime/orchestrator/ocpv2_runtime_service.py deploy/operator-control-plane-v2/ocpv2.user.service.in tests/test_remote_operator_service.py tests/test_ocpv2_runtime_service.py
git commit -m "feat(ocpv2): wire feature-gated host inspection runtime"
```

### Task 7: Qualification Package and Feature-OFF Successor Runtime



**Files:**
- Create: `tests/test_ocpv2_host_inspection_integration.py`
- Modify: `docs/DEVELOPMENT_PLAN.txt` only if the implementation changes an already-approved operational contract; otherwise add a scoped runbook under `docs/harness/`.
- Create: `docs/harness/ocpv2-host-inspection-runbook.md`

**Interfaces:**
- Produces: focused regression evidence and a live qualification checklist with feature OFF first.
- Depends on: Tasks 1-6.

- [ ] **Step 1: Write the integration test before any live activation**

The test must cover registered-root resolution, real temporary Git status/diff/branch, bounded file read/search/metadata, service observer allowlist, outbox retry, legacy V2 mutation compatibility, and zero mutation from inspection.

- [ ] **Step 2: Run focused and broad tests**

Run:
```bash
python -m unittest tests.test_ocpv2_host_inspection_integration -v
python -m unittest tests.test_remote_operator_service tests.test_remote_operator_envelope tests.test_remote_operator_outbox tests.test_ocpv2_runtime_service tests.test_ocpv2_single_execution_owner -v
python -m unittest discover -s tests -v
```
Expected: all existing and new tests PASS; report any pre-existing failure by exact test name instead of hiding it.

- [ ] **Step 3: Write the runbook with exact OFF→canary→OFF rollback steps**

The first deployed successor runtime must start with `OCP_HOST_INSPECTION_ENABLED=0`. The runbook must specify one bounded `git.branch` smoke request, result digest verification, and immediate feature-OFF rollback.

- [ ] **Step 4: Verify diff and forbidden dependencies**

Run:
```bash
git diff --check
grep -R "FullMCPRuntime\|ProcessService\|shell_execute\|register_job(" runtime/orchestrator/host_inspection* runtime/orchestrator/user_service_observer.py
```
Expected: `git diff --check` clean; forbidden dependency grep has no implementation hit except explanatory comments/tests.

- [ ] **Step 5: Commit**

```bash
git add tests/test_ocpv2_host_inspection_integration.py docs/harness/ocpv2-host-inspection-runbook.md
git commit -m "test(ocpv2): qualify RDC-independent host inspection"
```

## Plan Self-Review Result

- Spec coverage: host inspection contract, existing service reuse, project registry reuse, service/attention observation, typed remote request, shared outbox, mode gating, rollback and qualification are mapped to Tasks 1-7.
- Placeholder scan: no deferred or unspecified implementation steps remain.
- Type consistency: all later tasks consume `HostInspectionRequestV1`, `HostInspectionResultV1`, and `HostInspectionPort.inspect()` defined in Tasks 1-2.
- Review Focus coverage: root drift Task 2; sensitive/symlink Task 2; Git safety Task 2; replay Task 5; malformed request/mutation preservation Tasks 4/6.
- This plan intentionally does not implement new-work activation; that is a separate independently reviewable plan.