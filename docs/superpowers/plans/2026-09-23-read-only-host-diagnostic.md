# READ_ONLY_HOST_DIAGNOSTIC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a typed, bounded, replay-safe read-only host diagnostic capability to OCPv2 so GPT/JARVIS can inspect approved JARVIS-SERVER project and user-service state without arbitrary shell access or any new execution authority.

**Architecture:** Preserve the current `c591b01` mutation path unchanged. Add an additive remote-envelope V3 diagnostic extension and a typed read-only executor that is callable only from the existing OCP `CONTROL_READ_ONLY`/`ACTIVE` observation branch when `state_change_required=false`; keep V2 behavior byte-for-byte compatible. Seal diagnostic results into a dedicated durable diagnostic outbox before transport publication so crash/replay recovery can republish evidence without re-running mutations or claiming Full Plan completion.

**Tech Stack:** Python 3.12 stdlib, `unittest`, existing OCPv2 GitHub transport, systemd user service, Git CLI with fixed argv and sanitized environment, existing durable JSON helpers.

**Spec:** `docs/superpowers/specs/2026-09-23-read-only-host-diagnostic-design.md`

## Global Constraints

- Base source/runtime SHA is exactly `c591b01e8a1d9d9bb2dc438ca85f6c2ffcc79a03` until the implementation branch creates its own successor SHA.
- `FA6_STABLE_BASELINE=PASS` remains protected; no task edits the retained `e74c1ce` rollback runtime.
- OCPv2 remains transport/observation only; it receives no arbitrary shell, provider, model, Full Plan assignment, or state-changing authority.
- Existing `orchestration.remote-operator-envelope.v2` behavior remains backward-compatible.
- The diagnostic feature is OFF by default and fail-closed when its config is missing or unsafe.
- No caller-supplied command, argv fragment, Git flag, systemd property, absolute root, provider, or model is accepted.
- All subprocess execution uses fixed code-owned argv with `shell=False`, bounded timeout, and bounded output.
- Diagnostic results are observational evidence, never canonical Full Plan completion evidence.
- `DIAG_CONTENT` is bounded and secret-redacted before durable storage or transport projection.
- Implementation tasks use TDD and end in focused commits; live activation is not part of implementation and requires a separate explicit activation decision.

## Review Focus

1. **Path races and symlink escapes:** every file/metadata test must prove `../`, absolute paths, intermediate symlinks, final symlinks and special files are blocked without opening outside the registered root.
2. **Git helper escape:** the Git tests must configure malicious diff/textconv/credential helpers and prove `repo.snapshot` does not execute them.
3. **Crash after diagnostic completion but before projection:** the outbox/service integration test must prove a sealed result is republished after restart without re-running the diagnostic.
4. **Sensitive or oversized results:** content tests must prove secrets are redacted, binary/sensitive paths are blocked, payloads are capped, and `PARTIAL/STALE` is not represented as complete.
5. **Regression when feature is OFF or message is V2:** existing OCP V2 `READ_ONLY_ACCEPTED` and canonical mutation tests must remain unchanged and pass.

---

## File Structure

### New files

- `runtime/orchestrator/read_only_host_diagnostic_contract.py` — typed request/config/result contracts, canonical hashing, status/data-class validation and feature/config loading.
- `runtime/orchestrator/read_only_host_diagnostic.py` — safe root/file/Git/systemd operations plus the typed dispatcher; owns no transport or provider logic.
- `runtime/orchestrator/remote_diagnostic_outbox.py` — durable read-only result records and crash-safe pending/published lifecycle.
- `tests/test_read_only_host_diagnostic_contract.py` — strict schema/config/result tests.
- `tests/test_read_only_host_diagnostic.py` — filesystem, Git, systemd, redaction, bounds and no-mutation tests.
- `tests/test_remote_diagnostic_outbox.py` — durability/idempotency/conflict/recovery tests.
- `deploy/operator-control-plane-v2/read-only-host-diagnostic.example.json` — safe example policy with placeholder roots only.
- `docs/operations/read-only-host-diagnostic-rollout.md` — qualification, activation and rollback procedure; activation commands are documentation only.

### Modified files

- `runtime/orchestrator/remote_operator_envelope.py` — preserve V2; add typed V3 diagnostic envelope validation/sealing and a union alias.
- `runtime/orchestrator/remote_operator_ingress.py` — accept the V2/V3 union while preserving existing directive/replay/auth semantics.
- `runtime/orchestrator/remote_operator_receipt.py` — type the receipt store against the V2/V3 union; behavior stays envelope-hash/sequence based.
- `runtime/orchestrator/remote_operator_service.py` — add optional read-only diagnostic callback and a `diagnosed` counter; V2 non-diagnostic read-only behavior remains `READ_ONLY_ACCEPTED`.
- `runtime/orchestrator/ocpv2_runtime_service.py` — feature/config wiring, diagnostic executor composition, diagnostic outbox recovery/publish, exact result projection.
- `deploy/operator-control-plane-v2/bootstrap.py` — future rendered env includes diagnostic keys with feature OFF; existing env without keys remains accepted by runtime.
- `deploy/operator-control-plane-v2/ocpv2.example.env` — show OFF-by-default keys.
- `deploy/operator-control-plane-v2/README.md` — document read-only diagnostic boundary and explicit activation gate.
- `tests/test_remote_operator_envelope.py` — V2 regression plus V3 diagnostic contract tests.
- `tests/test_remote_operator_service.py` — callback/mode/feature behavior and V2 regression.
- `tests/test_ocpv2_runtime_service.py` — composition, feature flag, recovery and authority tests.

---

### Task 1: Typed Diagnostic Contract and Fail-Closed Policy Loader

**Files:**
- Create: `runtime/orchestrator/read_only_host_diagnostic_contract.py`
- Create: `tests/test_read_only_host_diagnostic_contract.py`

**Interfaces:**
- Consumes: stdlib only.
- Produces:
  - `ReadOnlyDiagnosticRequestV1.from_mapping(value: Mapping[str, Any]) -> ReadOnlyDiagnosticRequestV1`
  - `ReadOnlyDiagnosticResultV1.build(...) -> ReadOnlyDiagnosticResultV1`
  - `DiagnosticPolicy.load(path: str | Path) -> DiagnosticPolicy`
  - `diagnostic_feature_enabled(environment: Mapping[str, str]) -> bool`
  - `READ_ONLY_DIAGNOSTIC_CAPABILITY = "read_only_host_diagnostic"`

- [ ] **Step 1: Write strict request/config/result tests**

Create tests that pin the exact contracts:

```python
from pathlib import Path
import json
import tempfile
import unittest

from runtime.orchestrator.read_only_host_diagnostic_contract import (
    DiagnosticContractError,
    DiagnosticPolicy,
    ReadOnlyDiagnosticRequestV1,
    diagnostic_feature_enabled,
)


class DiagnosticContractTests(unittest.TestCase):
    def test_repo_snapshot_request_rejects_unused_fields(self):
        request = ReadOnlyDiagnosticRequestV1.from_mapping({
            "schema_version": "orchestration.read-only-host-diagnostic-request.v1",
            "request_id": "REQ-1",
            "operation": "repo.snapshot",
            "root_id": "jarvis-assistant",
            "relative_path": "",
            "start_line": 0,
            "line_count": 0,
            "service_id": "",
        })
        self.assertEqual(request.operation, "repo.snapshot")
        with self.assertRaisesRegex(DiagnosticContractError, "unused request field"):
            ReadOnlyDiagnosticRequestV1.from_mapping({**request.to_dict(), "relative_path": "README.md"})

    def test_feature_flag_accepts_only_explicit_true(self):
        self.assertFalse(diagnostic_feature_enabled({}))
        self.assertFalse(diagnostic_feature_enabled({"GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED": "false"}))
        self.assertTrue(diagnostic_feature_enabled({"GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED": "true"}))
        with self.assertRaises(DiagnosticContractError):
            diagnostic_feature_enabled({"GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED": "yes"})
```

Add config tests with a temporary regular file containing exactly:

```json
{
  "schema_version": "orchestration.read-only-host-diagnostic-config.v1",
  "roots": {"jarvis-assistant": "/absolute/existing/test/root"},
  "user_services": ["ocpv2.service"],
  "limits": {"max_bytes": 32768, "max_lines": 400, "timeout_seconds": 10}
}
```

Assert duplicate/unsafe root IDs, relative roots, symlink config files, non-existent roots, duplicate/non-user-safe service IDs, `max_bytes > 32768`, `max_lines > 400`, or `timeout_seconds > 15` fail closed.

- [ ] **Step 2: Run the contract tests and verify RED**

Run:

```bash
python3 -m unittest -v tests.test_read_only_host_diagnostic_contract
```

Expected: import failure because `read_only_host_diagnostic_contract.py` does not exist.

- [ ] **Step 3: Implement the minimal contract module**

Use these exact public constants and shapes:

```python
REQUEST_SCHEMA = "orchestration.read-only-host-diagnostic-request.v1"
RESULT_SCHEMA = "orchestration.read-only-host-diagnostic-result.v1"
CONFIG_SCHEMA = "orchestration.read-only-host-diagnostic-config.v1"
READ_ONLY_DIAGNOSTIC_CAPABILITY = "read_only_host_diagnostic"
OPERATIONS = frozenset({"repo.snapshot", "project.file_range", "path.metadata", "user_service.properties"})
STATUSES = frozenset({"OK", "PARTIAL", "STALE", "UNAVAILABLE", "BLOCKED", "ERROR"})
DATA_CLASSES = frozenset({"DIAG_SUMMARY", "DIAG_CONTENT"})
MAX_POLICY_BYTES = 32768
MAX_POLICY_LINES = 400
MAX_POLICY_TIMEOUT_SECONDS = 15
```

`ReadOnlyDiagnosticRequestV1` always serializes the seven request fields shown in Step 1 and enforces operation-specific empty/non-empty fields. `ReadOnlyDiagnosticResultV1.build()` computes `payload_hash` from canonical JSON of the already-sanitized payload. `DiagnosticPolicy.load()` requires an absolute regular non-symlink config file owned by the current uid and not group/world writable; each registered root must already exist, be a directory, and resolve without the root itself being a symlink.

- [ ] **Step 4: Run the contract tests and verify GREEN**

Run the same unittest command. Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/read_only_host_diagnostic_contract.py tests/test_read_only_host_diagnostic_contract.py
git commit -m "feat: add typed read-only diagnostic contract"
```

---

### Task 2: Safe Registered-Root File and Metadata Reads

**Files:**
- Create: `runtime/orchestrator/read_only_host_diagnostic.py`
- Create: `tests/test_read_only_host_diagnostic.py`

**Interfaces:**
- Consumes: `DiagnosticPolicy`, `ReadOnlyDiagnosticRequestV1`, `ReadOnlyDiagnosticResultV1` from Task 1.
- Produces:
  - `read_project_file_range(request, policy) -> dict[str, Any]`
  - `read_path_metadata(request, policy) -> dict[str, Any]`
  - internal `_open_regular_beneath(root: Path, relative: str) -> int`
  - internal `_redact_text(text: str) -> tuple[str, bool]`

- [ ] **Step 1: Write path/symlink/special-file/redaction tests**

Tests must construct a temporary registered root and prove:

```python
def test_file_range_blocks_intermediate_symlink_escape(self):
    outside = self.base / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("password=do-not-return\n", encoding="utf-8")
    (self.root / "jump").symlink_to(outside, target_is_directory=True)
    request = self.file_request("jump/secret.txt", start_line=1, line_count=10)
    with self.assertRaisesRegex(DiagnosticSecurityError, "symlink"):
        read_project_file_range(request, self.policy)
```

Also test absolute paths, `../`, final symlinks, FIFO/special files on POSIX, binary files containing `\x00`, `.env`, `id_rsa`, `*.pem`, oversized line requests, and secret-like text such as `token=abc123`. The returned text must contain `[REDACTED]` and never `abc123`.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
python3 -m unittest -v tests.test_read_only_host_diagnostic
```

Expected: import failure for the new module/functions.

- [ ] **Step 3: Implement descriptor-walk containment**

Implement `_open_regular_beneath()` by splitting a `PurePosixPath`, rejecting absolute paths/`..`/backslashes, opening the registered root directory fd, then walking each intermediate directory with `os.open(component, O_RDONLY|O_DIRECTORY|O_NOFOLLOW, dir_fd=current_fd)` and the final component with `O_RDONLY|O_NOFOLLOW`. Validate the final `fstat()` is a regular file before reading. Close every fd in `finally` blocks.

Use exact default sensitive-name rules:

```python
_SENSITIVE_EXACT = frozenset({".env", ".npmrc", ".pypirc", "id_rsa", "id_ed25519", "credentials.json"})
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
_SECRET_VALUE = re.compile(r"(?i)(api[_-]?key|authorization|bearer|password|token|credential|secret)\s*[:=]\s*([^\s,;}]+)")
```

Do not open a sensitive path and then redact it; reject the path before open. Redaction is a second boundary for otherwise allowed source text.

- [ ] **Step 4: Implement bounded line reads and metadata**

`project.file_range` reads at most `min(request.line_count, policy.max_lines)` and never emits more than `policy.max_bytes` encoded UTF-8 bytes. If the requested range is longer, return a caller-visible `truncated=True` marker in the operation payload. `path.metadata` uses the same open-beneath/containment policy and returns only `exists`, `type`, `size`, `mtime_ns`, `mode_class`, and `canonical_relative_path`.

- [ ] **Step 5: Run tests and verify GREEN**

```bash
python3 -m unittest -v tests.test_read_only_host_diagnostic
```

Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add runtime/orchestrator/read_only_host_diagnostic.py tests/test_read_only_host_diagnostic.py
git commit -m "feat: add safe bounded project diagnostics"
```

---

### Task 3: Hardened `repo.snapshot` Without Git Helper Execution

**Files:**
- Modify: `runtime/orchestrator/read_only_host_diagnostic.py`
- Modify: `tests/test_read_only_host_diagnostic.py`

**Interfaces:**
- Produces:
  - `collect_repo_snapshot(request, policy, *, runner=subprocess.run) -> dict[str, Any]`
  - internal `_run_git(root, args, timeout_seconds, runner) -> CompletedProcess[str]`

- [ ] **Step 1: Add fixed-argv and malicious-helper tests**

Add a runner-spy test asserting every Git call has `shell=False` and the environment contains:

```text
GIT_OPTIONAL_LOCKS=0
GIT_TERMINAL_PROMPT=0
GIT_CONFIG_NOSYSTEM=1
GIT_CONFIG_GLOBAL=/dev/null
GIT_PAGER=cat
PAGER=cat
```

Add an integration test that initializes a temporary repository, writes an executable marker script, configures `diff.evil.command` to that script, adds `.gitattributes` with `*.txt diff=evil`, modifies a tracked text file, runs `repo.snapshot`, and asserts the marker file was not created.

- [ ] **Step 2: Run the two new tests and verify RED**

Run their exact unittest names. Expected: missing `collect_repo_snapshot` or failed fixed-argv assertions.

- [ ] **Step 3: Implement only code-owned Git commands**

`_run_git` prepends fixed config controls and never accepts command text from a request. The snapshot operation may call only these forms:

```text
git -C <root> status --porcelain=v2 --branch --untracked-files=all
git -C <root> rev-parse --verify HEAD
git -C <root> rev-parse --git-dir
git -C <root> rev-parse --git-common-dir
git -C <root> diff --no-ext-diff --no-textconv --stat --
git -C <root> diff --no-ext-diff --no-textconv --name-status --
git -C <root> diff --cached --no-ext-diff --no-textconv --name-status --
git -C <root> diff --check --
git -C <root> ls-files --stage
```

Every call uses `capture_output=True`, `text=True`, `check=False`, `shell=False`, the policy timeout, and an output cap enforced before parsing. `ls-files --stage` is used only to detect submodule mode `160000`; no submodule network command is run.

- [ ] **Step 4: Detect concurrent drift instead of claiming freshness**

Capture `status --porcelain=v2 --branch` before and after the remaining snapshot commands. If the normalized status differs, return an operation marker that the dispatcher will convert to `status="STALE"`; do not silently present a mixed snapshot as `OK`.

- [ ] **Step 5: Run diagnostic tests and verify GREEN**

```bash
python3 -m unittest -v tests.test_read_only_host_diagnostic
```

Expected: `OK`, including the malicious helper test.

- [ ] **Step 6: Commit**

```bash
git add runtime/orchestrator/read_only_host_diagnostic.py tests/test_read_only_host_diagnostic.py
git commit -m "feat: add hardened repository snapshot"
```

---

### Task 4: Allowlisted Structured User-Service Reads

**Files:**
- Modify: `runtime/orchestrator/read_only_host_diagnostic.py`
- Modify: `tests/test_read_only_host_diagnostic.py`

**Interfaces:**
- Produces `read_user_service_properties(request, policy, *, runner=subprocess.run) -> dict[str, Any]`.

- [ ] **Step 1: Add allowlist and argv tests**

Test that a non-allowlisted unit raises `DiagnosticSecurityError`. For an allowed `ocpv2.service`, assert the runner receives exactly:

```python
[
    "systemctl", "--user", "show", "ocpv2.service", "--no-pager",
    "--property=ActiveState", "--property=SubState", "--property=Result",
    "--property=ExecMainStatus", "--property=InvocationID",
]
```

and `shell=False`, `capture_output=True`, `text=True`, `check=False`.

Also assert no public function accepts a systemctl verb or property list from the request.

- [ ] **Step 2: Run new tests and verify RED**

Expected: missing function.

- [ ] **Step 3: Implement the fixed property read**

Parse only the five exact `key=value` properties. Unknown output keys are ignored; duplicate keys or malformed lines produce `ERROR`/raise a closed diagnostic error. A non-zero return code yields `UNAVAILABLE` at the dispatcher boundary and includes no unbounded stderr.

- [ ] **Step 4: Run diagnostic tests and verify GREEN**

```bash
python3 -m unittest -v tests.test_read_only_host_diagnostic
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/read_only_host_diagnostic.py tests/test_read_only_host_diagnostic.py
git commit -m "feat: add allowlisted user service diagnostics"
```

---

### Task 5: Result Dispatcher, Classification, Freshness and Bounds

**Files:**
- Modify: `runtime/orchestrator/read_only_host_diagnostic.py`
- Modify: `tests/test_read_only_host_diagnostic.py`

**Interfaces:**
- Produces:

```python
def execute_read_only_host_diagnostic(
    request: ReadOnlyDiagnosticRequestV1,
    policy: DiagnosticPolicy,
    *,
    project_id: str,
    correlation_id: str,
    source_sha: str,
    runtime_sha: str,
    authorization_decision: str = "ALLOW",
    now: Callable[[], datetime] = utc_now,
) -> ReadOnlyDiagnosticResultV1:
    ...
```

- [ ] **Step 1: Add status/data-class/provenance tests**

Pin these cases:

- `repo.snapshot` → `DIAG_SUMMARY`, `OK` when stable.
- `project.file_range` → `DIAG_CONTENT`.
- concurrent Git drift → `STALE`, never `OK`.
- service command failure → `UNAVAILABLE`.
- sensitive/binary/traversal policy denial → `BLOCKED` with no secret-bearing payload.
- operation output over policy cap → `PARTIAL`, `truncated=True`.
- every result has non-empty `captured_at`, `payload_hash`, request/correlation IDs, `source_sha`, `runtime_sha`, and `execution_owner="NONE"`.

- [ ] **Step 2: Run those tests and verify RED**

Expected: dispatcher missing.

- [ ] **Step 3: Implement a closed operation dispatch table**

Use only this code-owned mapping:

```python
_OPERATION_HANDLERS = {
    "repo.snapshot": collect_repo_snapshot,
    "project.file_range": read_project_file_range,
    "path.metadata": read_path_metadata,
    "user_service.properties": read_user_service_properties,
}
```

Catch only known diagnostic/security/timeouts and map them to the explicit statuses. Unexpected exceptions become `ERROR` with a bounded class/reason string; never serialize a traceback into the result payload.

- [ ] **Step 4: Run Task 1–5 tests and verify GREEN**

```bash
python3 -m unittest -v \
  tests.test_read_only_host_diagnostic_contract \
  tests.test_read_only_host_diagnostic
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/read_only_host_diagnostic.py tests/test_read_only_host_diagnostic.py
git commit -m "feat: seal diagnostic result semantics"
```

---

### Task 6: Additive Remote Envelope V3 for Typed Diagnostics

**Files:**
- Modify: `runtime/orchestrator/remote_operator_envelope.py`
- Modify: `runtime/orchestrator/remote_operator_ingress.py`
- Modify: `runtime/orchestrator/remote_operator_receipt.py`
- Modify: `tests/test_remote_operator_envelope.py`

**Interfaces:**
- Consumes: `ReadOnlyDiagnosticRequestV1` and its canonical digest.
- Produces:
  - `REMOTE_OPERATOR_DIAGNOSTIC_ENVELOPE_SCHEMA = "orchestration.remote-operator-envelope.v3"`
  - `RemoteOperatorEnvelopeV3`
  - `RemoteControlEnvelope = RemoteOperatorEnvelopeV2 | RemoteOperatorEnvelopeV3`
  - `validate_remote_control_envelope(payload, *, now=None) -> RemoteControlEnvelope`
  - `seal_remote_control_envelope(payload) -> dict[str, Any]`
- Existing `validate_remote_envelope()` and `seal_remote_envelope()` remain V2-compatible for existing callers/tests.

- [ ] **Step 1: Add V2 regression and V3 schema tests**

V3 adds exactly:

```text
read_only_request
read_only_request_digest
```

to the V2 top-level field set. A valid V3 diagnostic envelope must have:

```text
state_change_required=false
required_capabilities includes exactly read_only_host_diagnostic for this diagnostic extension
read_only_request validates as V1
read_only_request_digest matches canonical request digest
```

Test that V3 is rejected when a provider/model field appears, request digest drifts, state change is true, capability is absent, or the request contains an absolute host root.

Retain an unchanged V2 round-trip test and assert `validate_remote_envelope()` still returns `RemoteOperatorEnvelopeV2`.

- [ ] **Step 2: Run envelope tests and verify RED**

```bash
python3 -m unittest -v tests.test_remote_operator_envelope
```

Expected: V3 symbols missing.

- [ ] **Step 3: Implement V3 as an additive validator, not a mutation of V2 semantics**

Share common validation helpers, but do not relax V2 exact-field checks. `seal_remote_control_envelope()` branches on `schema_version`; V2 delegates to the current sealer, V3 seals both request digest and envelope digest. `validate_remote_control_envelope()` similarly dispatches V2/V3.

Update ingress/receipt type hints and common-field use to the `RemoteControlEnvelope` union. Do not add any diagnostic execution to ingress or receipt modules.

- [ ] **Step 4: Run envelope + ingress/receipt tests and verify GREEN**

```bash
python3 -m unittest -v \
  tests.test_remote_operator_envelope \
  tests.test_remote_operator_ingress \
  tests.test_remote_operator_receipt
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/remote_operator_envelope.py \
        runtime/orchestrator/remote_operator_ingress.py \
        runtime/orchestrator/remote_operator_receipt.py \
        tests/test_remote_operator_envelope.py
git commit -m "feat: add typed remote diagnostic envelope"
```

---

### Task 7: Durable Diagnostic Result Outbox

**Files:**
- Create: `runtime/orchestrator/remote_diagnostic_outbox.py`
- Create: `tests/test_remote_diagnostic_outbox.py`

**Interfaces:**
- Produces:
  - `RemoteDiagnosticProjectionV1`
  - `RemoteDiagnosticOutbox.enqueue(record)`
  - `RemoteDiagnosticOutbox.pending() -> tuple[RemoteDiagnosticProjectionV1, ...]`
  - `RemoteDiagnosticOutbox.mark_published(projection_id, projection_sha256)`
  - `RemoteDiagnosticOutbox.publish_pending(publisher) -> int`

- [ ] **Step 1: Write durability/idempotency/conflict tests**

Model this after `RemoteResultOutbox`, but use schema `orchestration.remote-diagnostic-projection.v1` and fields:

```text
projection_id
message_id
directive_digest
project_id
run_id
gate_id
task_id
request_digest
diagnostic_result
projected_at
schema_version
```

Test exact re-enqueue is idempotent, same projection ID with different payload is rejected, symlink roots are rejected, pending survives a new outbox instance, and publish moves a record to `published` only after the supplied publisher returns successfully.

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m unittest -v tests.test_remote_diagnostic_outbox
```

Expected: import failure.

- [ ] **Step 3: Implement using existing durable JSON helpers**

Use `durable_json_save`, `durable_json_load`, `canonical_json_bytes`, and `sha256_bytes`. Store only already-sanitized `ReadOnlyDiagnosticResultV1.to_dict()` output; reject a result whose `payload_hash` does not revalidate.

- [ ] **Step 4: Run and verify GREEN**

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/remote_diagnostic_outbox.py tests/test_remote_diagnostic_outbox.py
git commit -m "feat: add durable diagnostic result outbox"
```

---

### Task 8: Execute Diagnostics Only in Existing Read-Only OCP Modes

**Files:**
- Modify: `runtime/orchestrator/remote_operator_service.py`
- Modify: `tests/test_remote_operator_service.py`

**Interfaces:**
- Consumes: V3 envelope request.
- Produces an optional constructor callback:

```python
execute_read_only: Callable[
    [RemoteControlEnvelope, OperatorDirectiveV1, ReadOnlyDiagnosticRequestV1],
    Mapping[str, Any],
] | None = None
```

and `ServicePollResult.diagnosed: int = 0`.

- [ ] **Step 1: Add mode matrix tests**

Pin all rows:

| Mode | V2 read-only | V3 diagnostic | state-changing |
|---|---|---|---|
| DISABLED | no receive | no receive | no receive |
| OBSERVE_ONLY | OBSERVED | OBSERVED, callback not called | OBSERVED |
| CONTROL_READ_ONLY | READ_ONLY_ACCEPTED | diagnostic callback called once | MODE_BLOCKED |
| CONTROL_MUTATION_CANARY | READ_ONLY_ACCEPTED | diagnostic callback called once | existing exact canary only |
| ACTIVE | READ_ONLY_ACCEPTED | diagnostic callback called once | existing canonical mutation |

If a V3 diagnostic arrives but `execute_read_only is None`, project `READ_ONLY_DIAGNOSTIC_UNAVAILABLE`, increment `blocked`, do not call `execute_authorized`.

- [ ] **Step 2: Run service tests and verify RED**

```bash
python3 -m unittest -v tests.test_remote_operator_service
```

Expected: constructor/counter behavior missing.

- [ ] **Step 3: Implement the smallest branch change**

Do not import `subprocess`, `systemctl`, Git, provider code, or diagnostic operation implementations into `remote_operator_service.py`. The service only detects a typed diagnostic request and invokes the supplied callback. Existing mutation callback and canary logic remain unchanged.

- [ ] **Step 4: Re-run service tests and authority negative-space test**

Keep the existing test that source contains no direct shell authority and extend its forbidden strings with `"read_project_file_range("`, `"collect_repo_snapshot("`, and `"systemctl --user"`.

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/remote_operator_service.py tests/test_remote_operator_service.py
git commit -m "feat: route typed read-only diagnostics"
```

---

### Task 9: OCP Runtime Composition, Feature Gate and Crash Recovery

**Files:**
- Modify: `runtime/orchestrator/ocpv2_runtime_service.py`
- Modify: `tests/test_ocpv2_runtime_service.py`

**Interfaces:**
- Consumes Tasks 1–8.
- Produces no new execution authority. The runtime composes the typed diagnostic callback only when `GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED=true` and config validation succeeds.

- [ ] **Step 1: Add OFF/default/fail-closed tests**

Tests must prove:

- existing env with neither diagnostic optional key still loads and feature is OFF;
- feature `true` without config path fails closed before service composition;
- relative/symlink/unsafe config fails closed;
- feature OFF never instantiates a diagnostic executor/outbox;
- mutation `execute_authorized_canonical()` test remains unchanged.

- [ ] **Step 2: Add crash-recovery integration test**

Use a fake transport and diagnostic executor counter:

1. accept a V3 diagnostic;
2. execute once and enqueue sealed diagnostic result;
3. simulate failure before remote publish;
4. construct a new service/outbox instance;
5. run pending projection recovery;
6. assert the transport publishes the same sealed result and the executor counter is still `1`.

- [ ] **Step 3: Run runtime tests and verify RED**

```bash
python3 -m unittest -v tests.test_ocpv2_runtime_service
```

Expected: feature/config/recovery assertions fail.

- [ ] **Step 4: Wire optional env keys and typed executor**

Accept these optional keys:

```text
GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED
GCH_READ_ONLY_HOST_DIAGNOSTIC_CONFIG
```

When enabled, load `DiagnosticPolicy`, create `RemoteDiagnosticOutbox(config.state_root / "diagnostic-outbox")`, publish pending sealed diagnostics before polling new messages, and supply `execute_read_only` to `RemoteOperatorService`.

The callback must:

1. require V3 + typed request;
2. call `execute_read_only_host_diagnostic()` with envelope IDs and current source/runtime SHA provenance;
3. seal/enqueue the diagnostic projection **before** returning it to the service;
4. return only the already-sanitized result mapping.

After successful transport projection, mark the corresponding diagnostic projection published. Existing mutation binding-store behavior remains unchanged.

- [ ] **Step 5: Switch runtime decoder to additive control-envelope validation**

Use `validate_remote_control_envelope()` instead of V2-only validation. V2 behavior must still pass the current tests unchanged.

- [ ] **Step 6: Run runtime + remote service tests and verify GREEN**

```bash
python3 -m unittest -v \
  tests.test_ocpv2_runtime_service \
  tests.test_remote_operator_service \
  tests.test_remote_operator_envelope \
  tests.test_remote_operator_ingress \
  tests.test_remote_operator_receipt \
  tests.test_remote_diagnostic_outbox
```

Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add runtime/orchestrator/ocpv2_runtime_service.py \
        tests/test_ocpv2_runtime_service.py
git commit -m "feat: compose gated host diagnostics in OCPv2"
```

---

### Task 10: Deployment Defaults and Operator Documentation

**Files:**
- Create: `deploy/operator-control-plane-v2/read-only-host-diagnostic.example.json`
- Create: `docs/operations/read-only-host-diagnostic-rollout.md`
- Modify: `deploy/operator-control-plane-v2/bootstrap.py`
- Modify: `deploy/operator-control-plane-v2/ocpv2.example.env`
- Modify: `deploy/operator-control-plane-v2/README.md`
- Test: use the existing OCP bootstrap test module plus `tests/test_ocpv2_runtime_service.py`; if the repository bootstrap tests are split across multiple modules, run every test file containing `operator-control-plane-v2` or `bootstrap` discovered by `python3 -m unittest discover` in Task 11.

**Interfaces:**
- Future rendered env gains two explicit OFF-by-default lines; current env files without them remain runtime-compatible.

- [ ] **Step 1: Add bootstrap rendering assertions**

The rendered env must include exactly:

```text
GCH_READ_ONLY_HOST_DIAGNOSTIC_ENABLED=false
GCH_READ_ONLY_HOST_DIAGNOSTIC_CONFIG=
```

Do not add a CLI flag that can enable the feature during `install-user-service`; activation remains a separate operational decision.

- [ ] **Step 2: Run bootstrap/runtime tests and verify RED**

Expected: rendered env lacks the two lines.

- [ ] **Step 3: Update bootstrap/env example**

Add the two default lines to `_env_text()` and `ocpv2.example.env`. Keep runtime parsing backward-compatible with old env files.

- [ ] **Step 4: Add a safe example policy**

Commit only placeholders:

```json
{
  "schema_version": "orchestration.read-only-host-diagnostic-config.v1",
  "roots": {
    "example-project": "/absolute/path/to/approved/project"
  },
  "user_services": [
    "ocpv2.service",
    "ocpv2.timer",
    "global-gpt-harness-full-plan-reconcile.service",
    "global-gpt-harness-full-plan-reconcile.timer"
  ],
  "limits": {
    "max_bytes": 32768,
    "max_lines": 400,
    "timeout_seconds": 10
  }
}
```

Do not commit JARVIS-SERVER local paths or tokens.

- [ ] **Step 5: Write rollout/rollback documentation**

The document must state that implementation merge/deploy leaves the feature OFF. It must give separate reviewable steps for successor-runtime qualification, config creation with mode `0600`, feature activation, one `repo.snapshot` smoke request, one `project.file_range` smoke request, FA6 invariant recheck, and immediate feature-OFF rollback. It must explicitly forbid deleting `ocpv2-r2-e74c1ce` or the current stable runtime during rollout.

- [ ] **Step 6: Run tests and commit**

```bash
git add deploy/operator-control-plane-v2/bootstrap.py \
        deploy/operator-control-plane-v2/ocpv2.example.env \
        deploy/operator-control-plane-v2/read-only-host-diagnostic.example.json \
        deploy/operator-control-plane-v2/README.md \
        docs/operations/read-only-host-diagnostic-rollout.md
git commit -m "docs: add gated diagnostic deployment contract"
```

---

### Task 11: Adversarial Qualification and Full Regression

**Files:**
- Modify tests only if a missing spec requirement is discovered; no production redesign is permitted in this task without returning to the owning task.

**Interfaces:**
- Consumes the complete feature branch.
- Produces qualification evidence only.

- [ ] **Step 1: Run syntax and whitespace integrity**

```bash
git diff --check c591b01e8a1d9d9bb2dc438ca85f6c2ffcc79a03...HEAD
python3 -m compileall -q runtime tests deploy/operator-control-plane-v2
```

Expected: zero output from `git diff --check`; compileall exits `0`.

- [ ] **Step 2: Run all focused diagnostic/OCP tests**

```bash
python3 -m unittest -v \
  tests.test_read_only_host_diagnostic_contract \
  tests.test_read_only_host_diagnostic \
  tests.test_remote_diagnostic_outbox \
  tests.test_remote_operator_envelope \
  tests.test_remote_operator_ingress \
  tests.test_remote_operator_receipt \
  tests.test_remote_operator_service \
  tests.test_ocpv2_runtime_service
```

Expected: `OK`, zero failures/errors.

- [ ] **Step 3: Run the complete repository regression**

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected: final `OK`, zero failures/errors. Do not hardcode a test count; this feature adds tests.

- [ ] **Step 4: Run the security/adversarial checklist explicitly**

Re-run named tests proving:

```text
absolute path blocked
../ traversal blocked
intermediate symlink blocked
final symlink blocked
special file blocked
binary file blocked
sensitive path blocked
secret value redacted
oversized content PARTIAL+truncated
malicious Git diff helper not executed
caller Git flags unavailable
non-allowlisted systemd unit blocked
systemd lifecycle verb unavailable
V3 state-changing diagnostic rejected
feature OFF blocks diagnostic execution
V2 READ_ONLY_ACCEPTED unchanged
crash recovery republishes without re-execution
```

Expected: every case PASS.

- [ ] **Step 5: Recheck FA6 authority invariants in source tests**

At minimum, preserve assertions that OCP runtime has no job registration, direct `Popen`/`os.system`, or provider selection; mutation still delegates only to registered Full Plan continuation; service source has no direct diagnostic/Git/systemd operation implementation.

- [ ] **Step 6: Record branch qualification evidence and commit documentation-only evidence**

Create `docs/history/upgrades/2026-09-23-read-only-host-diagnostic-qualification.md` containing the implementation SHA, base SHA `c591b01...`, exact commands run, exit codes, test totals reported by unittest, `git diff --check` result, and a statement:

```text
FEATURE_DEFAULT=OFF
LIVE_ACTIVATION_PERFORMED=NO
FA6_STABLE_RUNTIME_MUTATED=NO
```

Then commit:

```bash
git add docs/history/upgrades/2026-09-23-read-only-host-diagnostic-qualification.md
git commit -m "docs: record read-only diagnostic qualification"
```

---

### Task 12: Review Gate and Activation Package — No Live Activation Yet

**Files:**
- Review all branch changes.
- No live runtime files are modified in this task.

**Interfaces:**
- Produces the implementation review decision and a ready-but-disabled activation package.

- [ ] **Step 1: Request code review against the approved spec**

Reviewer focus:

```text
no new execution owner
no mutation bypass
no provider/model binding
V2 compatibility
V3 typed-only input
path containment/TOCTOU
Git helper suppression
service allowlist
secret/redaction bounds
crash/replay durability
feature OFF default
FA6 regression protection
```

- [ ] **Step 2: Apply only evidence-backed review fixes**

For each accepted review issue, return to the task owning that file, add a failing regression test first, make the minimal fix, and rerun that task's focused tests.

- [ ] **Step 3: Re-run Task 11 after all review fixes**

Expected: full `OK` and no diff-check/compile failures.

- [ ] **Step 4: Stop at the activation boundary**

The branch is implementation-complete only when tests/review are green, but JARVIS-SERVER activation remains explicitly pending. Do **not** edit live `ocpv2.env`, switch runtime-current, restart services, or enable the feature in this task.

Required final state before a later activation approval:

```text
IMPLEMENTATION_COMPLETE=YES
IMPLEMENTATION_QUALIFIED=YES
FEATURE_DEFAULT=OFF
LIVE_ACTIVATION=NO
FA6_BASELINE_PRESERVED=YES
NEXT_GATE=EXPLICIT_LIVE_ACTIVATION_APPROVAL
```

---

## Self-Review

### Spec coverage

- Typed repo/file/path/service operations: Tasks 2–5.
- Arbitrary shell/argv prohibition: Tasks 2–5 and Task 11.
- Provider/model/Full MCP authority separation: Tasks 8–12 plus preserved existing mutation tests.
- Canonical containment, symlink/special/binary/TOCTOU controls: Task 2.
- Hardened Git with helper/textconv/prompt/network suppression: Task 3.
- Structured systemd property reads only: Task 4.
- Result status/freshness/provenance/classification: Task 5.
- Additive typed remote contract and V2 compatibility: Task 6.
- Crash-safe replay/result durability: Tasks 7 and 9.
- Feature OFF, config safety, rollout/rollback: Tasks 9–10.
- Adversarial and FA6 regression qualification: Tasks 11–12.

No design requirement is left without an owning task.

### Placeholder scan

The plan contains no `TBD`, `TODO`, generic “add error handling”, or unspecified “write tests” steps. Each code task defines exact interfaces, representative test content, commands and expected results.

### Type consistency

- `ReadOnlyDiagnosticRequestV1` is defined in Task 1 and consumed by Tasks 2–9.
- `ReadOnlyDiagnosticResultV1` is defined in Task 1 and produced by Task 5, persisted by Task 7 and projected by Task 9.
- `RemoteControlEnvelope` is defined in Task 6 and consumed by ingress/receipt/service/runtime thereafter.
- Diagnostic execution remains a callback into `RemoteOperatorService`; the service itself never imports host-operation implementation.

### Review Focus coverage

- Path races/symlink escape → Task 2 tests.
- Malicious Git helper/textconv → Task 3 tests.
- Crash before projection → Tasks 7/9 tests.
- Sensitive/oversized result → Tasks 2/5 tests.
- Feature-OFF/V2 regression → Tasks 6/8/9/11 tests.

---

## Execution Boundary

This plan deliberately separates **implementation** from **live activation**. Completion of Tasks 1–12 yields tested code and a disabled activation package. A later explicit activation gate is required before changing JARVIS-SERVER's live OCP environment/runtime.

The preserved operating mode remains:

```text
Operator=GPT
Execution=HYBRID
Provider/model selection=Multi-Provider Router
```

No task in this plan binds implementation work to Codex, NVIDIA, or any single provider.
