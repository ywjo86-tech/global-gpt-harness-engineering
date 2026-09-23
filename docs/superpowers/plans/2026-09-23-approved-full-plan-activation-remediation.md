# Approved Full Plan Activation Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an RDC-independent executable activation path for already-approved work that registers one generic `AUTO_RECONCILE` Full Plan job only after existing mapping, TASK-to-LV, Gate approval, requirement, source, runtime and AI Office bindings have been validated.

**Architecture:** Keep `APPROVED_WORK_ACTIVATION` V1 byte/semantic compatible as a tracking/manual-receipt path and add a distinct `APPROVED_FULL_PLAN_ACTIVATION` contract. OCP validates and registers authority only; normal `production_full_plan_boot` / generic `run_job()` executes the new `AUTO_RECONCILE` job through existing `execute_gate()` → Router/MPRF → production worker → Production Gateway → Full MCP. No new execution owner, provider selector, worker, outbox, approval schema, requirement schema, shell path or direct OCP effect path is introduced.

**Tech Stack:** Python 3.12, `unittest`, existing OCPv2 GitHub control transport, AI Office state store/workflow, Full Plan durable supervisor, project onboarding/contract mapping, TASK-to-LV projection, Gate approval v1, production worker/Gateway/Full MCP, systemd --user for existing Full Plan boot/reconcile.

**Spec:** `docs/superpowers/specs/2026-09-23-approved-work-execution-link-remediation-design.md`
**Authority-boundary amendment:** Spec SHA `10d1c94cc391b770d124f68fb8c4af8776ccca30bd119c3c5d863da17b76f8ab`; Gate approval and engine conformance evidence are Harness-sealed namespace artifacts, not project-committed files.

## Global Constraints

- Gate approval evidence MUST resolve only under `namespace_root(harness_state_root, project_id, "approval")`; engine R01-R25 evidence MUST resolve only under `namespace_root(harness_state_root, project_id, "artifact")`; neither authority root is caller-supplied.
- Plan/spec/project requirement contracts remain committed project evidence; activation never creates, relocates, or translates approval/requirement authority.

- OCP SHALL remain transport/control only and SHALL NOT gain shell, filesystem-write, provider/model, planner, worker, Gateway or Full MCP effect authority.
- Existing `APPROVED_WORK_ACTIVATION` V1 SHALL retain its current tracking/manual semantics and durable replay meaning.
- Executable new-work activation SHALL use `APPROVED_FULL_PLAN_ACTIVATION` and `orchestration.approved-full-plan-activation-request.v1`.
- Remote callers SHALL NOT provide provider, model, backend, command, argv, environment, editable scope, owned scope, mapping root or arbitrary absolute host paths.
- Project identity SHALL come from the existing Onboarding alias registry and be cross-checked against the existing executable contract mapping.
- The system-configured authority root SHALL be canonical, non-symlinked and read-only from the remote caller's perspective; aliases are resolved from `AUTHORITY_ROOT/aliases` and executable contract mappings from `AUTHORITY_ROOT/mappings`.
- A TASK/STAGE-GATE plan SHALL execute only with an existing mapping-bound TASK-to-LV authority projection whose digest matches the mapping.
- Gate/LV order, owned scope, completion criteria, validation IDs and capabilities SHALL be derived from canonical Harness contracts only.
- `approval_ref` is provenance only; executable Gate authority SHALL come from the existing Gate approval contract and SHALL NOT be synthesized or translated from production-approval-v2.
- Engine R01-R25 requirement evidence and project/Gate/LV requirement contracts SHALL remain distinct schemas and validation paths.
- The executable job SHALL be generic `orchestration.production-full-plan-job.v1`, SHALL set `execution_owner=AUTO_RECONCILE`, and SHALL omit `executor_kind`.
- `register_job()` remains the sole job-registration and authority-sealing boundary.
- OCP SHALL NOT spawn the Full Plan worker; `production_full_plan_boot` / generic `run_job()` own launch/recovery.
- State-changing work SHALL flow only through existing `execute_gate()` → Router/MPRF → production worker/Gateway → Full MCP.
- Existing OCPV2-owned continuation control remains separate and SHALL reject the new `AUTO_RECONCILE` run.
- Executable activation SHALL reuse the existing `RemoteResultOutbox`; no second outbox/recovery state machine is permitted.
- `OCP_FULL_PLAN_ACTIVATION_ENABLED=0` is the default and uses a dedicated policy ref separate from V1 activation.
- Missing mapping, projection, Gate approval, requirement evidence, source/runtime binding or executable qualification SHALL fail closed with no auto-bootstrap, V1 downgrade, Manual Action, shell or RDC fallback.
- `GPT-ACT-20260923-02` is immutable failure evidence and SHALL NOT be rebound or reused.
- No live executable canary, runtime switch or feature enable occurs before a separate explicit user approval gate.

## Resume State After Authority-Boundary Amendment

- Task 1 is already implemented at `dd4e548`; `ArtifactRefV1` remains intentionally domain-neutral, while Task 3 supplies the field-implied Harness/project authority-domain resolution.
- Task 2 is already implemented at `98a82f2` and remains valid unchanged.
- Task 3 previously stopped before commit when the project-committed Gate approval self-reference was discovered. Resume at Task 3 after this amended plan is approved; do not repeat Tasks 1-2.
- The failed historical canary `GPT-ACT-20260923-02` remains immutable evidence and is never reused.

## File Structure

New focused modules:

- `runtime/orchestrator/approved_full_plan_activation_contract.py` — closed remote executable-activation payload types and canonical digesting only.
- `runtime/orchestrator/approved_full_plan_binding.py` — pure/read-only authority-root resolution, alias↔mapping↔plan cross-check, Gate/approval/requirement validation and immutable executable authority bundle.
- `runtime/ai_office/full_plan_activation.py` — additive AI Office executable-activation context bound to the executable authority bundle; does not change V1 context semantics.
- `runtime/orchestrator/full_plan_activation.py` — generic Full Plan job builder, executable activation result/receipt and create-once registration store; no worker launch.

Existing files changed only at integration boundaries:

- `runtime/orchestrator/gate_orchestrator.py` — add optional explicit `mapping_root` threading to read-only Gate loading/global binding validation so activation validation does not mutate process environment.
- `runtime/orchestrator/remote_control_envelope.py` — add the new typed request kind and dedicated authorization type while preserving V1.
- `runtime/orchestrator/remote_operator_outbox.py` — add one typed executable-activation projection to the existing outbox union.
- `runtime/orchestrator/remote_operator_service.py` — route the new kind through a separate callback/feature/policy path.
- `runtime/orchestrator/ocpv2_runtime_service.py` — compose the validator/context/registration path from system-derived roots and independent feature/policy flags.
- `deploy/operator-control-plane-v2/ocpv2.user.service.in` — declare executable activation OFF by default.

Protected execution owners remain unchanged unless a focused regression proves an integration defect:

- `runtime/orchestrator/production_full_plan_entry.py`
- `runtime/orchestrator/production_full_plan_boot.py`
- Router/MPRF/production worker/Gateway/Full MCP modules

## Review Focus

- **Authority-root / namespace confinement:** aliases may exist without executable mappings, and Gate approval / engine R01-R25 evidence must resolve only below their field-implied system-derived Harness namespaces; missing mappings, traversal, symlink components, wrong-namespace placement, absolute caller paths, project-Git substitutes, and code-owned mapping fallback all fail closed without creating authority state.
- **Approval-domain collision:** `gate-approval.v1`, canonical Gate state and production-approval-v2 are distinct authority domains; executable activation accepts only the existing Full Plan Gate authority and never translates schemas.
- **Registration/publication crash:** a crash after `register_job()` but before projection publication must replay the same receipt/projection without registering a second job or creating a second effect path.
- **Binding-to-execution drift:** branch/HEAD, mapping/projection and runtime release may change after activation validation; existing preflight/runtime checks must block execution rather than allowing the activation bundle to override current canonical checks.
- **Owner/path coexistence:** V1 tracking activation, OCPV2-owned continuation and the new `AUTO_RECONCILE` executable run must remain mutually non-convertible even when they reference the same project.

## Requirement-to-Task Traceability

| Requirement | Owning task(s) | Proof point |
|---|---|---|
| AWEL-MUST-001 | 8, 9, 11 | service/runtime negative-space source tests |
| AWEL-MUST-002 | 1, 4, 6, 7, 8, 9 | V1 contract/context/projection/integration regressions |
| AWEL-MUST-003 | 1, 6 | distinct request schema/kind tests |
| AWEL-MUST-004 | 1, 11 | exact-field rejection and source audit |
| AWEL-MUST-005 | 3 | alias↔mapping↔plan identity tests |
| AWEL-MUST-006 | 3, 9 | system authority-root derivation and remote-field exclusion |
| AWEL-MUST-007 | 2, 3 | explicit mapping-root loading and source SHA cross-check |
| AWEL-MUST-008 | 3, 10 | missing/drifted projection fail-closed tests |
| AWEL-MUST-009 | 3 | canonical `GatePlan`-derived LV order/scope/capability tests |
| AWEL-MUST-010 | 3, 10 | Harness approval-namespace confinement + `validate_global_gate_bindings()` failure matrix |
| AWEL-MUST-011 | 3, 10 | production-approval-v2 rejection and opaque `approval_ref` tests |
| AWEL-MUST-012 | 3, 10 | Harness artifact-domain engine evidence vs committed project requirement schema/LV coverage tests |
| AWEL-MUST-013 | 3, 5, 10 | source/runtime binding and preflight drift tests |
| AWEL-MUST-014 | 3, 5, 10 | sealed `job["mapping_root"]` and boot/preflight tests |
| AWEL-MUST-015 | 5, 10 | generic job shape and `AUTO_RECONCILE` owner tests |
| AWEL-MUST-016 | 5, 10 | create-once store and `register_job()` rebind tests |
| AWEL-MUST-017 | 5, 10 | boot/reconcile launch ownership, no OCP spawn |
| AWEL-MUST-018 | 10, 11, 13 | generic Gate path integration and live bounded effect evidence |
| AWEL-MUST-019 | 10, 11 | OCPV2 continuation owner rejection |
| AWEL-MUST-020 | 4 | executable AI Office context exact bundle binding |
| AWEL-MUST-021 | 5, 7, 10 | receipt/projection identity and shared outbox replay |
| AWEL-MUST-022 | 3, 8, 9, 10 | typed fail-closed matrix with no fallback |
| AWEL-MUST-023 | 13 | explicit exclusion/immutability check for `GPT-ACT-20260923-02` |
| AWEL-MUST-024 | 13, 14 | fresh no-RDC effect/validation/replay/rollback evidence |
| AWEL-MUST-025 | 8, 9, 12, 13 | separate OFF-by-default feature/policy and rollback proof |
| AWEL-AC-001 | 1, 4, 6, 7, 8, 9 | V1 compatibility regression |
| AWEL-AC-002 | 1, 11 | forbidden remote-field rejection |
| AWEL-AC-003 | 3, 10 | aliases-only authority root registers zero jobs |
| AWEL-AC-004 | 3, 10 | TASK plan without projection registers zero jobs |
| AWEL-AC-005 | 3, 10 | mapping/projection/plan/source drift matrix |
| AWEL-AC-006 | 3, 10 | missing/expired/wrong-scope/wrong-namespace Gate approval matrix |
| AWEL-AC-007 | 3, 10 | missing/wrong-profile/wrong-authority-domain requirement matrix |
| AWEL-AC-008 | 5, 10 | exact one generic `AUTO_RECONCILE` job |
| AWEL-AC-009 | 5, 10 | idempotent replay and conflict rejection |
| AWEL-AC-010 | 10 | boot accepts AUTO owner; OCP resume rejects it |
| AWEL-AC-011 | 10, 11 | existing Router/MPRF/worker/Gateway/Full MCP path |
| AWEL-AC-012 | 4 | AI Office bundle binding/no second store |
| AWEL-AC-013 | 7, 10 | shared outbox crash/replay |
| AWEL-AC-014 | 11 | forbidden-path source audit |
| AWEL-AC-015 | 13 | fresh live no-RDC bounded effect/validation/rollback |
| AWEL-AC-016 | 11, 14 | broad regression and EDP runtime closure |

---

### Task 1: Closed Executable Activation Request Contract

**Files:**
- Create: `runtime/orchestrator/approved_full_plan_activation_contract.py`
- Create: `tests/test_approved_full_plan_activation_contract.py`

**Interfaces:**
- Consumes: existing canonical JSON/digest style from `approved_work_binding.py` and OCP remote-control envelope conventions.
- Produces: `ArtifactRefV1`, `LVArtifactRefV1`, `GateBindingRefV1`, `ApprovedFullPlanActivationRequestV1`, and `APPROVED_FULL_PLAN_ACTIVATION_REQUEST_SCHEMA`.

- [ ] **Step 1: Write the failing closed-schema tests**

```python
from runtime.orchestrator.approved_full_plan_activation_contract import (
    ApprovedFullPlanActivationRequestV1,
    ApprovedFullPlanActivationContractError,
)


def executable_request():
    return {
        "schema_version": "orchestration.approved-full-plan-activation-request.v1",
        "activation_request_id": "FP-ACT-1",
        "project_alias": "demo",
        "approved_plan": {"path": "docs/DEVELOPMENT_PLAN.txt", "sha256": "a" * 64},
        "approved_spec": {"path": "docs/spec.md", "sha256": "b" * 64},
        "expected_branch": "main",
        "expected_head": "c" * 40,
        "runtime_release_digest": "d" * 64,
        "approval_ref": "USER-APPROVAL-1",
        "gate_bindings": [{
            "gate_id": "GATE-001",
            "approval_evidence": {"path": "approval-g1.json", "sha256": "e" * 64},
            "engine_requirement_evidence": {"path": "engine-g1.json", "sha256": "f" * 64},
            "project_requirement_evidence_by_lv": [{
                "lv_id": "TASK-001", "path": "docs/req-task-001.json", "sha256": "1" * 64,
            }],
        }],
    }


def test_request_is_closed_and_digest_stable():
    request = ApprovedFullPlanActivationRequestV1.from_mapping(executable_request())
    assert request.to_dict() == executable_request()
    assert len(request.request_digest) == 64


def test_authority_bearing_caller_fields_are_rejected():
    for field in ("provider", "model", "backend", "command", "argv", "environment", "owned_scope", "mapping_root"):
        value = executable_request(); value[field] = "forbidden"
        try:
            ApprovedFullPlanActivationRequestV1.from_mapping(value)
        except ApprovedFullPlanActivationContractError as exc:
            assert "FIELDS_MISMATCH" in str(exc)
        else:
            raise AssertionError(field)
```

- [ ] **Step 2: Run the contract tests and verify RED**

Run:

```bash
python3 -m unittest -v tests.test_approved_full_plan_activation_contract
```

Expected: import failure because the module does not exist.

- [ ] **Step 3: Implement the exact dataclasses and validators**

```python
APPROVED_FULL_PLAN_ACTIVATION_REQUEST_SCHEMA = "orchestration.approved-full-plan-activation-request.v1"

@dataclass(frozen=True, slots=True)
class ArtifactRefV1:
    path: str
    sha256: str

@dataclass(frozen=True, slots=True)
class LVArtifactRefV1:
    lv_id: str
    path: str
    sha256: str

@dataclass(frozen=True, slots=True)
class GateBindingRefV1:
    gate_id: str
    approval_evidence: ArtifactRefV1
    engine_requirement_evidence: ArtifactRefV1 | None
    project_requirement_evidence_by_lv: tuple[LVArtifactRefV1, ...]

@dataclass(frozen=True, slots=True)
class ApprovedFullPlanActivationRequestV1:
    schema_version: str
    activation_request_id: str
    project_alias: str
    approved_plan: ArtifactRefV1
    approved_spec: ArtifactRefV1
    expected_branch: str
    expected_head: str
    runtime_release_digest: str
    approval_ref: str
    gate_bindings: tuple[GateBindingRefV1, ...]
```

Validation rules in this task are exact field sets, safe **relative** artifact references, lowercase SHA-256 digests, attached branch syntax, 40/64-hex HEAD, unique ordered Gate IDs, unique LV refs per Gate, non-empty approval provenance, and canonical `request_digest = sha256(canonical_json(to_dict()))`. The contract stays domain-neutral: `approval_evidence.path` is interpreted by Task 3 under the Harness approval namespace, `engine_requirement_evidence.path` under the Harness artifact namespace, while plan/spec/project-requirement refs are interpreted under the project root. No host root lookup belongs in this module.

- [ ] **Step 4: Run focused contract tests and existing V1 contract tests**

```bash
python3 -m unittest -v \
  tests.test_approved_full_plan_activation_contract \
  tests.test_approved_work_binding \
  tests.test_remote_control_envelope
```

Expected: PASS.

- [ ] **Step 5: Commit the contract**

```bash
git add runtime/orchestrator/approved_full_plan_activation_contract.py tests/test_approved_full_plan_activation_contract.py
git commit -m "feat(ocpv2): add executable activation request contract"
```

---

### Task 2: Explicit Mapping-Root Threading in Canonical Gate Readers

**Files:**
- Modify: `runtime/orchestrator/gate_orchestrator.py`
- Modify: `tests/test_gate_orchestrator.py`
- Modify: `tests/test_task_contract_compat.py`

**Interfaces:**
- Consumes: `contract_adapter.load_project_mapping(project_root, mapping_root=mappings_root)`.
- Produces: `load_gate_plan(project_root, gate_id, *, mapping_root=None)` and the existing `validate_global_gate_bindings()` extended with optional `mapping_root=None` with backward-compatible defaults.

- [ ] **Step 1: Write failing tests proving explicit mapping roots are process-local**

```python
def test_load_gate_plan_uses_explicit_mapping_root_without_environment_patch():
    with patch("runtime.orchestrator.gate_orchestrator.load_project_mapping") as loader:
        loader.return_value = prepared_mapping
        load_gate_plan(project_root, "GATE-001", mapping_root=mapping_root)
    loader.assert_called_once_with(project_root.resolve(), mapping_root=mapping_root)


def test_validate_global_gate_bindings_threads_explicit_mapping_root():
    with patch("runtime.orchestrator.gate_orchestrator.load_gate_plan", return_value=plan) as loader:
        validate_global_gate_bindings(
            project_root, "GATE-001", requirements_sha256="a" * 64,
            approval_evidence=approval_path, branch="main", head=head,
            harness_root=harness_root, mapping_root=mapping_root,
        )
    loader.assert_called_once_with(project_root.resolve(), "GATE-001", mapping_root=mapping_root)
```

- [ ] **Step 2: Run the focused Gate tests and verify RED**

```bash
python3 -m unittest -v tests.test_gate_orchestrator tests.test_task_contract_compat
```

Expected: new keyword-argument tests fail before code changes.

- [ ] **Step 3: Add optional keyword-only mapping-root parameters without changing default behavior**

```python
def load_gate_plan(project_root: str | Path, gate_id: str, *,
                   mapping_root: str | Path | None = None) -> GatePlan:
    root, root_project_id = _safe_project(project_root)
    match = _GATE_ID.fullmatch(gate_id)
    if not match:
        raise GateOrchestrationError("invalid Gate ID")
    mapping = load_project_mapping(root, mapping_root=mapping_root)
    if mapping is None:
        raise GateOrchestrationError("project declarative mapping is required")
    # Continue through the existing GatePlan construction using this mapping object.


def validate_global_gate_bindings(project_root: str | Path, gate_id: str, *,
                                  requirements_sha256: str, approval_evidence: str | Path,
                                  branch: str, head: str, harness_root: str | Path,
                                  mapping_root: str | Path | None = None) -> dict[str, Any]:
    root, root_project_id = _safe_project(project_root)
    plan = load_gate_plan(root, gate_id, mapping_root=mapping_root)
    # Continue through the existing approval/global-binding validation using this plan.
```

Do not change `execute_gate()` ownership or production runtime behavior in this task. Generic `run_job()` continues to bind `HARNESS_CONTRACT_MAPPING_ROOT` from the sealed job at execution time.

- [ ] **Step 4: Run Gate, task-projection and production Full Plan regressions**

```bash
python3 -m unittest -v \
  tests.test_gate_orchestrator \
  tests.test_task_contract_compat \
  tests.test_production_full_plan_entry
```

Expected: PASS.

- [ ] **Step 5: Commit the read-only parameter threading**

```bash
git add runtime/orchestrator/gate_orchestrator.py tests/test_gate_orchestrator.py tests/test_task_contract_compat.py
git commit -m "refactor(harness): thread explicit Gate mapping root"
```

---

### Task 3: Executable Authority Bundle Validator

**Files:**
- Create: `runtime/orchestrator/approved_full_plan_binding.py`
- Modify: `runtime/orchestrator/approved_work_binding.py`
- Create: `tests/test_approved_full_plan_binding.py`
- Modify: `tests/test_approved_work_binding.py`
- Modify: `tests/test_approved_full_plan_activation_contract.py`

**Interfaces:**
- Consumes: `ApprovedFullPlanActivationRequestV1`, `OnboardingRegistry`, `load_project_mapping`, `validate_mapping_sources`, `load_gate_plan(project_root, gate_id, mapping_root=mappings_root)`, the existing `validate_global_gate_bindings()` extended to receive `mapping_root=mappings_root`, `namespace_root`, `load_approval_evidence`, `load_requirement_evidence`, `load_project_requirement_contract`, `resolve_task_project_requirement_contract`, `RuntimeReleaseManifest`.
- Produces: `ValidatedGateAuthorityV1`, `ExecutableAuthorityBundleV1`, `resolve_executable_authority_roots(configured_root)`, and `validate_approved_full_plan_binding(request, authority_root=authority_root, runtime_release=runtime_release, harness_state_root=harness_state_root)`.

- [ ] **Step 1: Expose the existing committed-file helper without changing V1 semantics**

Replace the private helper call sites in `approved_work_binding.py` with a public helper of the same implementation:

```python
def resolve_committed_project_file(root: Path, raw: object, label: str) -> tuple[Path, str]:
    text = str(raw or "")
    relative = Path(text)
    if not text or relative.is_absolute() or ".." in relative.parts or "\\" in text:
        raise ApprovedWorkBindingError(f"COMMITTED_EVIDENCE_REQUIRED: unsafe {label}")
    target = root / relative
    if target.is_symlink() or not target.is_file():
        raise ApprovedWorkBindingError(f"COMMITTED_EVIDENCE_REQUIRED: {label}")
    try:
        resolved = target.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ApprovedWorkBindingError(f"COMMITTED_EVIDENCE_REQUIRED: {label}") from exc
    tracked = _git(root, "ls-files", "--error-unmatch", "--", relative.as_posix(), allow_nonzero=True)
    clean = _git(root, "diff", "--quiet", "HEAD", "--", relative.as_posix(), allow_nonzero=True)
    staged = _git(root, "diff", "--cached", "--quiet", "HEAD", "--", relative.as_posix(), allow_nonzero=True)
    if tracked.returncode != 0 or clean.returncode != 0 or staged.returncode != 0:
        raise ApprovedWorkBindingError(f"COMMITTED_EVIDENCE_REQUIRED: {label}")
    return resolved, relative.as_posix()
```

Update V1 tests to prove the same dirty/untracked/symlink rejection behavior remains unchanged.

- [ ] **Step 2: Write failing authority-root and alias↔mapping tests**

```python
def test_alias_without_mappings_directory_blocks_and_creates_nothing():
    authority_root = base / "authority"; (authority_root / "aliases").mkdir(parents=True)
    before = sorted(path.relative_to(authority_root) for path in authority_root.rglob("*"))
    with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_FULL_PLAN_REQUIRED"):
        validate_approved_full_plan_binding(request, authority_root=authority_root,
                                            runtime_release=release, harness_state_root=state_root)
    after = sorted(path.relative_to(authority_root) for path in authority_root.rglob("*"))
    self.assertEqual(after, before)


def test_alias_mapping_plan_identity_mismatch_blocks():
    mapping["canonical_implementation_source"]["sha256"] = "0" * 64
    write_mapping(mapping_root, mapping)
    with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_MAPPING_MISMATCH"):
        self.validate()
```

- [ ] **Step 3: Write failing projection/Gate approval/requirement tests**

Tests must cover all of these independently:

```python
# Missing projection on a TASK/STAGE-GATE mapping.
with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_FULL_PLAN_REQUIRED"):
    self.validate_without_projection()

# Expired or wrong-scope gate-approval.v1 from the Harness approval namespace.
with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_APPROVAL_REQUIRED"):
    self.validate_with_expired_gate_approval()

# Approval ref traversal / absolute path / symlink / wrong namespace are rejected before schema validation.
for fixture in (self.approval_traversal, self.approval_absolute, self.approval_symlink, self.approval_in_artifact_namespace):
    with self.subTest(fixture=fixture):
        with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_APPROVAL_REQUIRED"):
            fixture()

# A project-committed gate-approval.v1 is not accepted as a substitute for Harness authority state.
with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_APPROVAL_REQUIRED"):
    self.validate_with_project_git_approval_substitute()

# production-approval.v2 presented in the Harness gate-approval slot.
with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_APPROVAL_REQUIRED"):
    self.validate_with_production_approval_v2()

# Engine evidence must come from the Harness artifact namespace, not project Git or approval namespace.
for fixture in (self.engine_evidence_in_project, self.engine_evidence_in_approval_namespace):
    with self.subTest(fixture=fixture):
        with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_REQUIREMENT_BINDING_MISMATCH"):
            fixture()

# Engine evidence supplied where a project requirement contract is required.
with self.assertRaisesRegex(ApprovedFullPlanBindingError, "EXECUTABLE_REQUIREMENT_BINDING_MISMATCH"):
    self.validate_with_wrong_requirement_profile()
```

- [ ] **Step 4: Run the validator tests and verify RED**

```bash
python3 -m unittest -v \
  tests.test_approved_full_plan_binding \
  tests.test_approved_work_binding
```

Expected: new validator module/imports are missing.

- [ ] **Step 5: Implement authority-root resolution as a pure fail-closed read**

```python
def resolve_executable_authority_roots(configured_root: str | Path) -> tuple[Path, Path, Path]:
    root = Path(configured_root).expanduser().absolute()
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise ApprovedFullPlanBindingError("EXECUTABLE_FULL_PLAN_REQUIRED: authority root unsafe")
    aliases = root / "aliases"
    mappings = root / "mappings"
    for path in (aliases, mappings):
        if path.is_symlink() or not path.is_dir() or path.resolve() != path:
            raise ApprovedFullPlanBindingError("EXECUTABLE_FULL_PLAN_REQUIRED: authority registry incomplete")
    return root, aliases, mappings
```

This function never creates directories and never falls back to `runtime/orchestrator/contract_mappings`.

Add one read-only namespace resolver; it reuses `namespace_root()` and never creates authority artifacts:

```python
def resolve_harness_authority_file(*, harness_state_root: str | Path, project_id: str,
                                   kind: str, raw: object, label: str) -> tuple[Path, str]:
    if kind not in {"approval", "artifact"}:
        raise ApprovedFullPlanBindingError(f"{label}: invalid authority namespace")
    text = str(raw or "")
    relative = Path(text)
    if not text or relative.is_absolute() or ".." in relative.parts or "\\" in text:
        raise ApprovedFullPlanBindingError(f"{label}: unsafe namespace-relative path")
    base = namespace_root(harness_state_root, project_id, kind)
    root = Path(harness_state_root).expanduser().absolute()
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise ApprovedFullPlanBindingError(f"{label}: Harness state root unsafe")
    target = base.joinpath(*relative.parts)
    cursor = root
    for part in target.relative_to(root).parts:
        cursor = cursor / part
        if cursor.exists() and cursor.is_symlink():
            raise ApprovedFullPlanBindingError(f"{label}: symlinked authority path")
    if not target.is_file() or target.is_symlink():
        raise ApprovedFullPlanBindingError(f"{label}: authority artifact missing")
    resolved = target.resolve(strict=True)
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ApprovedFullPlanBindingError(f"{label}: authority namespace escape") from exc
    return resolved, relative.as_posix()
```

`approval_evidence.path` is always resolved with `kind="approval"`; `engine_requirement_evidence.path` is always resolved with `kind="artifact"`. A field can never select its own namespace.

- [ ] **Step 6: Implement the immutable bundle types**

```python
@dataclass(frozen=True, slots=True)
class ValidatedGateAuthorityV1:
    gate_id: str
    approval_evidence_path: str
    approval_evidence_sha256: str
    requirements_sha256: str
    engine_requirement_evidence_path: str
    engine_requirement_evidence_sha256: str
    project_requirement_evidence_paths_by_lv: tuple[tuple[str, str, str], ...]
    lv_order: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ExecutableAuthorityBundleV1:
    schema_version: str
    activation_request_id: str
    request_digest: str
    project_alias: str
    project_id: str
    project_root: str
    authority_root: str
    mapping_root: str
    approved_plan_path: str
    approved_plan_sha256: str
    approved_spec_path: str
    approved_spec_sha256: str
    approval_ref: str
    expected_branch: str
    expected_head: str
    runtime_release_digest: str
    runtime_release_source_head: str
    runtime_code_root: str
    gates: tuple[ValidatedGateAuthorityV1, ...]
```

`bundle_digest` is computed from `to_dict()` and is never caller-supplied.

- [ ] **Step 7: Implement exact validation order**

Define the local read-only Git helper used by the validator:

```python
def _git(root: Path, *args: str, allow_nonzero: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
        check=False, timeout=20,
    )
    if result.returncode != 0 and not allow_nonzero:
        raise ApprovedFullPlanBindingError("SOURCE_BINDING_MISMATCH: Git verification failed")
    return result
```

`validate_approved_full_plan_binding()` must perform, in order:

```python
req = request if isinstance(request, ApprovedFullPlanActivationRequestV1) \
    else ApprovedFullPlanActivationRequestV1.from_mapping(request)
authority_root, aliases_root, mappings_root = resolve_executable_authority_roots(authority_root)
registry = OnboardingRegistry(aliases_root)
entry = next((item for item in registry.entries() if item.get("alias") == req.project_alias), None)
if entry is None:
    raise ApprovedFullPlanBindingError("EXECUTABLE_FULL_PLAN_REQUIRED: project alias")
project_root = Path(str(entry["project_root"])).resolve(strict=True)
mapping = load_project_mapping(project_root, mapping_root=mappings_root)
if mapping is None or validate_mapping_sources(mapping):
    raise ApprovedFullPlanBindingError("EXECUTABLE_MAPPING_MISMATCH")
plan_path, plan_relative = resolve_committed_project_file(project_root, req.approved_plan.path, "approved plan")
spec_path, spec_relative = resolve_committed_project_file(project_root, req.approved_spec.path, "approved spec")
plan_sha = sha256_file(plan_path)
spec_sha = sha256_file(spec_path)
if (
    str(entry["project_id"]) != str(mapping.project_id)
    or Path(str(entry["project_root"])).resolve() != project_root
    or str(entry["canonical_plan"]) != plan_relative
    or str(entry["canonical_plan_sha256"]) != plan_sha
    or mapping.canonical_source.resolve() != plan_path.resolve()
    or mapping.canonical_sha256 != plan_sha
    or req.approved_plan.sha256 != plan_sha
    or req.approved_spec.sha256 != spec_sha
):
    raise ApprovedFullPlanBindingError("EXECUTABLE_MAPPING_MISMATCH")
if mapping.task_lv_projection_path is not None:
    projection_relative = mapping.task_lv_projection_path.relative_to(project_root).as_posix()
    projection_path, _ = resolve_committed_project_file(
        project_root, projection_relative, "TASK-to-LV authority projection",
    )
    if sha256_file(projection_path) != mapping.task_lv_projection_sha256:
        raise ApprovedFullPlanBindingError("EXECUTABLE_MAPPING_MISMATCH")
branch = _git(project_root, "branch", "--show-current").stdout.strip()
head = _git(project_root, "rev-parse", "HEAD").stdout.strip()
if (branch, head) != (req.expected_branch, req.expected_head):
    raise ApprovedFullPlanBindingError("SOURCE_BINDING_MISMATCH")
runtime_root = Path(str(runtime_release.release_path or "")).expanduser().absolute()
try:
    runtime_canonical = runtime_root.resolve(strict=True)
except OSError as exc:
    raise ApprovedFullPlanBindingError("RUNTIME_RELEASE_MISMATCH") from exc
if (
    req.runtime_release_digest != str(runtime_release.manifest_sha256 or "")
    or runtime_root.is_symlink() or not runtime_root.is_dir() or runtime_canonical != runtime_root
):
    raise ApprovedFullPlanBindingError("RUNTIME_RELEASE_MISMATCH")
validated_gates = []
project_requirements_required = mapping.task_lv_projection_path is not None
for gate_ref in req.gate_bindings:
    plan = load_gate_plan(project_root, gate_ref.gate_id, mapping_root=mappings_root)
    approval_path, _ = resolve_harness_authority_file(
        harness_state_root=harness_state_root, project_id=str(mapping.project_id),
        kind="approval", raw=gate_ref.approval_evidence.path, label="EXECUTABLE_APPROVAL_REQUIRED",
    )
    approval_sha = sha256_file(approval_path)
    if approval_sha != gate_ref.approval_evidence.sha256:
        raise ApprovedFullPlanBindingError("EXECUTABLE_APPROVAL_REQUIRED")
    try:
        approval = load_approval_evidence(approval_path)
        requirements_sha256 = str(approval["payload"]["requirements_sha256"])
        validate_global_gate_bindings(
            project_root, gate_ref.gate_id, requirements_sha256=requirements_sha256,
            approval_evidence=approval_path, branch=req.expected_branch, head=req.expected_head,
            harness_root=harness_state_root, mapping_root=mappings_root,
        )
    except (GateApprovalError, GateOrchestrationError, OSError, ValueError) as exc:
        raise ApprovedFullPlanBindingError("EXECUTABLE_APPROVAL_REQUIRED") from exc
    validated_gates.append(_validate_gate_requirement_artifacts(
        project_root=project_root, harness_state_root=Path(harness_state_root),
        project_id=str(mapping.project_id), plan=plan, gate_ref=gate_ref,
        approval_path=approval_path, approval_sha256=approval_sha,
        requirements_sha256=requirements_sha256,
        project_requirements_required=project_requirements_required,
    ))
return ExecutableAuthorityBundleV1(
    schema_version="orchestration.executable-authority-bundle.v1",
    activation_request_id=req.activation_request_id, request_digest=req.request_digest,
    project_alias=req.project_alias, project_id=str(mapping.project_id), project_root=str(project_root),
    authority_root=str(authority_root), mapping_root=str(mappings_root),
    approved_plan_path=plan_relative, approved_plan_sha256=req.approved_plan.sha256,
    approved_spec_path=spec_relative, approved_spec_sha256=req.approved_spec.sha256,
    approval_ref=req.approval_ref, expected_branch=branch, expected_head=head,
    runtime_release_digest=req.runtime_release_digest,
    runtime_release_source_head=str(runtime_release.source_head),
    runtime_code_root=str(runtime_release.release_path), gates=tuple(validated_gates),
)
```

For project requirement validation, derive expected IDs with `resolve_task_project_requirement_contract()` from each canonical `GatePlan` LV and call `load_project_requirement_contract()` with those exact IDs. An LV with canonical Related Requirements must have exactly one supplied project requirement artifact; extra LV refs also block.

Define the helper used above in the same module with this exact interface:

```python
def _validate_gate_requirement_artifacts(*, project_root: Path, harness_state_root: Path,
                                         project_id: str, plan: GatePlan,
                                         gate_ref: GateBindingRefV1, approval_path: Path,
                                         approval_sha256: str, requirements_sha256: str,
                                         project_requirements_required: bool) -> ValidatedGateAuthorityV1:
    engine_path = ""
    engine_sha256 = ""
    engine_ref = gate_ref.engine_requirement_evidence
    if engine_ref is not None:
        resolved, _ = resolve_harness_authority_file(
            harness_state_root=harness_state_root, project_id=project_id, kind="artifact",
            raw=engine_ref.path, label="EXECUTABLE_REQUIREMENT_BINDING_MISMATCH",
        )
        engine_sha256 = sha256_file(resolved)
        if engine_sha256 != engine_ref.sha256:
            raise ApprovedFullPlanBindingError("EXECUTABLE_REQUIREMENT_BINDING_MISMATCH")
        try:
            load_requirement_evidence(resolved, requirements_sha256=requirements_sha256)
        except (GateOrchestrationError, OSError, ValueError) as exc:
            raise ApprovedFullPlanBindingError("EXECUTABLE_REQUIREMENT_BINDING_MISMATCH") from exc
        engine_path = str(resolved)

    supplied = {item.lv_id: item for item in gate_ref.project_requirement_evidence_by_lv}
    expected_lvs = [item.lv_id for item in plan.lvs]
    if project_requirements_required and set(supplied) != set(expected_lvs):
        raise ApprovedFullPlanBindingError("EXECUTABLE_REQUIREMENT_BINDING_MISMATCH")
    if not project_requirements_required and supplied:
        raise ApprovedFullPlanBindingError("EXECUTABLE_REQUIREMENT_BINDING_MISMATCH")

    project_rows: list[tuple[str, str, str]] = []
    if project_requirements_required:
        plan_text = (project_root / plan.canonical_plan_path).read_text(encoding="utf-8")
        for lv in plan.lvs:
            expected = resolve_task_project_requirement_contract(
                plan_text, project_id=plan.project_id,
                canonical_plan_sha256=plan.canonical_plan_sha256,
                gate_id=plan.gate_id, task_id=lv.lv_id,
                owned_files=list(lv.owned_files),
            )
            ref = supplied[lv.lv_id]
            resolved, _ = resolve_committed_project_file(
                project_root, ref.path, f"project requirement evidence {lv.lv_id}",
            )
            actual_sha = sha256_file(resolved)
            if actual_sha != ref.sha256:
                raise ApprovedFullPlanBindingError("EXECUTABLE_REQUIREMENT_BINDING_MISMATCH")
            try:
                loaded = load_project_requirement_contract(
                    resolved, project_id=plan.project_id, gate_id=plan.gate_id,
                    lv_id=lv.lv_id, plan_sha256=plan.canonical_plan_sha256,
                    expected_requirement_ids=tuple(expected["requirements"]),
                )
            except (GateOrchestrationError, OSError, ValueError) as exc:
                raise ApprovedFullPlanBindingError("EXECUTABLE_REQUIREMENT_BINDING_MISMATCH") from exc
            if dict(loaded) != dict(expected["requirements"]):
                raise ApprovedFullPlanBindingError("EXECUTABLE_REQUIREMENT_BINDING_MISMATCH")
            project_rows.append((lv.lv_id, str(resolved), actual_sha))

    if not project_rows and not engine_path:
        raise ApprovedFullPlanBindingError("EXECUTABLE_REQUIREMENT_BINDING_MISMATCH")
    return ValidatedGateAuthorityV1(
        gate_id=plan.gate_id,
        approval_evidence_path=str(approval_path),
        approval_evidence_sha256=approval_sha256,
        requirements_sha256=requirements_sha256,
        engine_requirement_evidence_path=engine_path,
        engine_requirement_evidence_sha256=engine_sha256,
        project_requirement_evidence_paths_by_lv=tuple(project_rows),
        lv_order=tuple(item.lv_id for item in plan.lvs),
    )
```

- [ ] **Step 8: Run validator, Gate and V1 regressions**

```bash
python3 -m unittest -v \
  tests.test_approved_full_plan_binding \
  tests.test_approved_work_binding \
  tests.test_gate_approval \
  tests.test_gate_orchestrator \
  tests.test_task_contract_compat
```

Expected: PASS.

- [ ] **Step 9: Commit the pure validator**

```bash
git add runtime/orchestrator/approved_work_binding.py runtime/orchestrator/approved_full_plan_binding.py \
  tests/test_approved_work_binding.py tests/test_approved_full_plan_binding.py
git commit -m "feat(harness): validate executable Full Plan activation authority"
```

---

### Task 4: Additive AI Office Executable Activation Context

**Files:**
- Create: `runtime/ai_office/full_plan_activation.py`
- Create: `tests/test_ai_office_full_plan_activation.py`
- Test: `tests/test_ai_office_activation.py`

**Interfaces:**
- Consumes: `ExecutableAuthorityBundleV1`, `AIOfficeStateStore`, `intake_requirement`, `WorkflowCoordinator`.
- Produces: `AIFullPlanActivationContextV1` and `coordinate_approved_full_plan_activation(bundle, *, office_store)`.

- [ ] **Step 1: Write failing context-binding and V1-isolation tests**

```python
def test_context_binds_executable_bundle_and_gate_order():
    context = coordinate_approved_full_plan_activation(bundle, office_store=store)
    self.assertEqual(context.executable_authority_bundle_digest, bundle.bundle_digest)
    self.assertEqual(context.gate_ids, tuple(g.gate_id for g in bundle.gates))
    self.assertEqual(context.workflow_state, "INTAKE_READY")


def test_existing_v1_context_schema_is_unchanged():
    self.assertEqual(AI_ACTIVATION_CONTEXT_SCHEMA_V1, "ai-office.activation-context.v1")
```

- [ ] **Step 2: Verify RED**

```bash
python3 -m unittest -v tests.test_ai_office_full_plan_activation tests.test_ai_office_activation
```

- [ ] **Step 3: Implement a separate context schema**

```python
AI_FULL_PLAN_ACTIVATION_CONTEXT_SCHEMA_V1 = "ai-office.full-plan-activation-context.v1"

@dataclass(frozen=True, slots=True)
class AIFullPlanActivationContextV1:
    schema_version: str
    activation_request_id: str
    project_id: str
    office_run_id: str
    requirement_id: str
    requirement_envelope_digest: str
    approved_plan_digest: str
    approved_spec_digest: str
    approval_ref: str
    expected_head: str
    executable_authority_bundle_digest: str
    gate_ids: tuple[str, ...]
    workflow_state: str
    workflow_revision: int
    workflow_state_digest: str
```

Use the same request-local `approved_register` technique as V1, but bind its source/constraints to the already-validated bundle digests. Do not add a persistent approved-register database.

- [ ] **Step 4: Run AI Office focused tests**

```bash
python3 -m unittest -v \
  tests.test_ai_office_full_plan_activation \
  tests.test_ai_office_activation \
  tests.test_ai_office_state_store \
  tests.test_ai_office_workflow
```

Expected: PASS.

- [ ] **Step 5: Commit the additive context**

```bash
git add runtime/ai_office/full_plan_activation.py tests/test_ai_office_full_plan_activation.py
git commit -m "feat(ai-office): bind executable activation authority"
```

---

### Task 5: Generic AUTO_RECONCILE Full Plan Builder and Create-Once Receipt

**Files:**
- Create: `runtime/orchestrator/full_plan_activation.py`
- Create: `tests/test_full_plan_activation.py`
- Modify: `runtime/orchestrator/production_full_plan_entry.py`
- Modify: `tests/test_production_full_plan_entry.py`
- Test: `tests/test_ocpv2_single_execution_owner.py`

**Interfaces:**
- Consumes: `ExecutableAuthorityBundleV1`, `AIFullPlanActivationContextV1`, `AUTO_RECONCILE_OWNER`, `executor_runtime_identity`, `preflight_job`, `register_job`, `load_job`, `canonical_job_path`, durable JSON helpers.
- Produces: `build_executable_full_plan_job()`, `activate_approved_full_plan()`, `FullPlanActivationResultV1`, `FullPlanActivationReceiptV1`, `FullPlanActivationStore`.

Use these exact result/receipt contracts:

```python
@dataclass(frozen=True, slots=True)
class FullPlanActivationResultV1:
    schema_version: str
    activation_request_id: str
    project_id: str
    run_id: str
    status: str
    canonical_job_path: str
    authority_digest: str
    executable_authority_bundle_digest: str

@dataclass(frozen=True, slots=True)
class FullPlanActivationReceiptV1:
    schema_version: str
    activation_request_id: str
    bundle_digest: str
    result_status: str
    canonical_job_path: str
    run_id: str
    authority_digest: str
    executable_authority_bundle_digest: str
    activation_digest: str

```

`FullPlanActivationStore.record_or_load(*, request_id: str, bundle: ExecutableAuthorityBundleV1, registrar: Callable[[], FullPlanActivationResultV1]) -> FullPlanActivationReceiptV1` uses the existing durable file-lock/create-once algorithm from `PlanActivationStore`: validate request identity, lock one receipt namespace, load existing receipt, return exact replay for matching `bundle_digest`, raise `ACTIVATION_REPLAY_CONFLICT` for mismatched digest, otherwise call `registrar()` once and durably save the sealed receipt.

- [ ] **Step 1: Write the failing generic-job-shape tests**

```python
def test_builder_emits_generic_auto_reconcile_job_without_executor_kind():
    job = build_executable_full_plan_job(
        bundle, ai_context=context, harness_state_root=state_root,
    )
    self.assertEqual(job["schema_version"], "orchestration.production-full-plan-job.v1")
    self.assertEqual(job["execution_owner"], "AUTO_RECONCILE")
    self.assertNotIn("executor_kind", job)
    self.assertEqual(job["mapping_root"], bundle.mapping_root)
    self.assertEqual(job["runtime_release_digest"], bundle.runtime_release_digest)
    self.assertEqual(job["runtime_release_source_head"], bundle.runtime_release_source_head)
    self.assertEqual(job["expected_branch"], bundle.expected_branch)
    self.assertEqual(job["expected_head"], bundle.expected_head)
    self.assertEqual(job["activation_binding_digest"], bundle.request_digest)
    self.assertEqual(job["executable_authority_bundle_digest"], bundle.bundle_digest)
    self.assertEqual(job["ai_office_context_digest"], context.context_digest)
```

- [ ] **Step 2: Write failing Gate-entry and preflight tests**

```python
def test_builder_uses_only_validated_gate_authority():
    job = build_executable_full_plan_job(bundle, ai_context=context, harness_state_root=state_root)
    gate = job["gates"][0]
    self.assertEqual(gate["gate_id"], bundle.gates[0].gate_id)
    self.assertEqual(gate["approval_evidence"], bundle.gates[0].approval_evidence_path)
    self.assertEqual(gate["requirements_sha256"], bundle.gates[0].requirements_sha256)
    self.assertEqual(gate["approval_evidence_sha256"], bundle.gates[0].approval_evidence_sha256)
    self.assertEqual(gate["requirement_evidence_sha256_by_lv"], expected_project_digests)
    self.assertEqual(gate["requirement_evidence_paths_by_lv"], expected_project_paths)
    self.assertTrue(gate["full_plan_opt_in"])
    self.assertTrue(gate["project_final_validation"])


def test_activation_requires_preflight_pass_before_register_job():
    with patch("runtime.orchestrator.full_plan_activation.preflight_job", return_value={"status": "BLOCK", "reason": "SOURCE"}), \
         patch("runtime.orchestrator.full_plan_activation.register_job") as registrar:
        with self.assertRaisesRegex(FullPlanActivationError, "ACTIVATION_PREFLIGHT_BLOCKED"):
            activate_approved_full_plan(bundle, ai_context=context, harness_state_root=state_root)
    registrar.assert_not_called()


def test_preflight_revalidates_expected_head_and_authority_artifact_digests():
    job = build_executable_full_plan_job(bundle, ai_context=context, harness_state_root=state_root)
    self.assertEqual(preflight_job(job)["status"], "PASS")
    mutate_file(Path(bundle.gates[0].approval_evidence_path))
    result = preflight_job(job)
    self.assertEqual(result["status"], "BLOCK")
    self.assertIn("GATE_AUTHORITY_EVIDENCE_DRIFT", result["reason"])
```

- [ ] **Step 3: Verify RED**

```bash
python3 -m unittest -v tests.test_full_plan_activation
```

- [ ] **Step 4: Implement the generic job builder**

The builder must emit this authority-bearing shape and nothing caller-derived beyond already validated bundle/context fields:

```python
job = {
    "schema_version": "orchestration.production-full-plan-job.v1",
    "execution_owner": AUTO_RECONCILE_OWNER,
    "project_root": bundle.project_root,
    "harness_root": str(harness_state_root),
    "harness_state_root": str(harness_state_root),
    "runtime_code_root": bundle.runtime_code_root,
    "runtime_release_digest": bundle.runtime_release_digest,
    "runtime_release_source_head": bundle.runtime_release_source_head,
    "mapping_root": bundle.mapping_root,
    "project_id": bundle.project_id,
    "run_id": bundle.activation_request_id,
    "git_common_dir": _git_common_dir(Path(bundle.project_root)),
    "expected_branch": bundle.expected_branch,
    "expected_head": bundle.expected_head,
    "approved_plan_path": str(Path(bundle.project_root) / bundle.approved_plan_path),
    "approved_plan_sha256": bundle.approved_plan_sha256,
    "approved_spec_path": str(Path(bundle.project_root) / bundle.approved_spec_path),
    "approved_spec_sha256": bundle.approved_spec_sha256,
    "approval_ref": bundle.approval_ref,
    "activation_binding_digest": bundle.request_digest,
    "executable_authority_bundle_digest": bundle.bundle_digest,
    "ai_office_context_digest": ai_context.context_digest,
    "required_executables": ["git"],
    "executor_runtime_identity": executor_runtime_identity(bundle.runtime_code_root),
    "gates": [
        {
            "gate_id": gate.gate_id,
            "approval_evidence": gate.approval_evidence_path,
            "approval_evidence_sha256": gate.approval_evidence_sha256,
            "requirements_sha256": gate.requirements_sha256,
            "branch": bundle.expected_branch, "head": bundle.expected_head,
            "full_plan_opt_in": True, "project_final_validation": True,
            **({"requirement_evidence_path": gate.engine_requirement_evidence_path,
                "requirement_evidence_sha256": gate.engine_requirement_evidence_sha256}
               if gate.engine_requirement_evidence_path else {}),
            **({"requirement_evidence_paths_by_lv": {lv: path for lv, path, _sha in gate.project_requirement_evidence_paths_by_lv},
                "requirement_evidence_sha256_by_lv": {lv: sha for lv, _path, sha in gate.project_requirement_evidence_paths_by_lv}}
               if gate.project_requirement_evidence_paths_by_lv else {}),
        }
        for gate in bundle.gates
    ],
}
```

Do not add `executor_kind`, provider/model/backend fields, worker commands, manual-action fallback or a second runtime policy. Omitted `policy` uses the existing `DurableFullPlanSupervisor` defaults.

Define these local checks in `full_plan_activation.py`:

```python
def _git_common_dir(root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-common-dir"],
        capture_output=True, text=True, check=False, timeout=10,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise FullPlanActivationError("ACTIVATION_SOURCE_DRIFT")
    common = Path(completed.stdout.strip())
    return str((root / common).resolve() if not common.is_absolute() else common.resolve())

def _validate_context(bundle: ExecutableAuthorityBundleV1, context: AIFullPlanActivationContextV1) -> None:
    if (context.activation_request_id != bundle.activation_request_id
            or context.project_id != bundle.project_id
            or context.office_run_id != bundle.activation_request_id
            or context.approved_plan_digest != bundle.approved_plan_sha256
            or context.approved_spec_digest != bundle.approved_spec_sha256
            or context.approval_ref != bundle.approval_ref
            or context.expected_head != bundle.expected_head
            or context.executable_authority_bundle_digest != bundle.bundle_digest
            or context.gate_ids != tuple(g.gate_id for g in bundle.gates)
            or context.workflow_state != "INTAKE_READY"):
        raise FullPlanActivationError("ACTIVATION_CONTEXT_MISMATCH")
```

Extend `production_full_plan_entry.preflight_job()` additively for jobs that carry the new optional bindings:

```python
expected_head = job.get("expected_head")
if expected_head:
    probe = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"],
                           capture_output=True, text=True, check=False, timeout=10)
    if probe.returncode != 0 or probe.stdout.strip() != expected_head:
        return {"status": "BLOCK", "state": "BLOCKED", "reason": "SOURCE_HEAD_MISMATCH"}
release_digest = str(job.get("runtime_release_digest") or "")
release_head = str(job.get("runtime_release_source_head") or "")
if release_digest or release_head:
    if not (_SHA256.fullmatch(release_digest) and re.fullmatch(r"[0-9a-f]{40,64}", release_head)):
        return {"status": "BLOCK", "state": "BLOCKED", "reason": "RUNTIME_RELEASE_BINDING_INVALID"}
    try:
        release = verify_runtime_release(runtime, release_head)
    except (RuntimeReleaseError, OSError, ValueError):
        return {"status": "BLOCK", "state": "BLOCKED", "reason": "RUNTIME_RELEASE_DRIFT"}
    if release.manifest_sha256 != release_digest:
        return {"status": "BLOCK", "state": "BLOCKED", "reason": "RUNTIME_RELEASE_DRIFT"}
for gate in job.get("gates", []):
    checks = [(gate.get("approval_evidence"), gate.get("approval_evidence_sha256"), "approval")]
    if gate.get("requirement_evidence_path"):
        checks.append((gate["requirement_evidence_path"], gate.get("requirement_evidence_sha256"), "engine_requirement"))
    for lv_id, path in dict(gate.get("requirement_evidence_paths_by_lv") or {}).items():
        expected = dict(gate.get("requirement_evidence_sha256_by_lv") or {}).get(lv_id)
        checks.append((path, expected, f"project_requirement:{lv_id}"))
    for path, expected, label in checks:
        source = Path(str(path or ""))
        if (not expected or not _SHA256.fullmatch(str(expected)) or source.is_symlink() or not source.is_file()):
            return {"status": "BLOCK", "state": "BLOCKED",
                    "reason": f"GATE_AUTHORITY_EVIDENCE_DRIFT:{gate['gate_id']}:{label}"}
        try:
            actual = sha256_file(source)
        except OSError:
            return {"status": "BLOCK", "state": "BLOCKED",
                    "reason": f"GATE_AUTHORITY_EVIDENCE_DRIFT:{gate['gate_id']}:{label}"}
        if actual != expected:
            return {"status": "BLOCK", "state": "BLOCKED",
                    "reason": f"GATE_AUTHORITY_EVIDENCE_DRIFT:{gate['gate_id']}:{label}"}
```

Update the module imports to reuse canonical helpers rather than duplicating them:

```python
from .contract_adapter import MAPPING_ROOT_ENV, sha256_file
from .runtime_release import RuntimeReleaseError, verify_runtime_release
```

`load_job()` must validate `expected_head`, `runtime_release_digest`, and `runtime_release_source_head` when present; the two runtime-release fields must either both be absent or both be present. It must also validate any present evidence-digest fields as lowercase SHA-256 values and require LV key coverage to match `requirement_evidence_paths_by_lv`; legacy jobs without these additive fields remain valid.

- [ ] **Step 5: Implement preflight-then-register activation and create-once receipt storage**

```python
def activate_approved_full_plan(bundle, *, ai_context, harness_state_root) -> FullPlanActivationResultV1:
    _validate_context(bundle, ai_context)
    job = build_executable_full_plan_job(bundle, ai_context=ai_context, harness_state_root=harness_state_root)
    preflight = preflight_job(job)
    if preflight.get("status") != "PASS":
        raise FullPlanActivationError("ACTIVATION_PREFLIGHT_BLOCKED:" + str(preflight.get("reason")))
    existed = canonical_job_path(job).is_file()
    path = register_job(job)
    sealed = load_job(path)
    return FullPlanActivationResultV1(
        schema_version="orchestration.full-plan-activation-result.v1",
        activation_request_id=bundle.activation_request_id,
        project_id=bundle.project_id, run_id=bundle.activation_request_id,
        status="FULL_PLAN_ALREADY_REGISTERED" if existed else "FULL_PLAN_REGISTERED",
        canonical_job_path=str(path),
        authority_digest=str(sealed["authority_core_sha256"]),
        executable_authority_bundle_digest=bundle.bundle_digest,
    )
```

`FullPlanActivationStore.record_or_load()` follows the existing `PlanActivationStore` durable-lock pattern but uses a distinct receipt schema and `bundle_digest`. Same request + same bundle returns the existing receipt; same request + different bundle raises `ACTIVATION_REPLAY_CONFLICT`.

- [ ] **Step 6: Run builder, entry and owner regressions**

```bash
python3 -m unittest -v \
  tests.test_full_plan_activation \
  tests.test_production_full_plan_entry \
  tests.test_production_full_plan_boot \
  tests.test_ocpv2_single_execution_owner
```

Expected: PASS, including generic runner accepting `AUTO_RECONCILE` and OCP canonical resume rejecting non-OCP ownership.

- [ ] **Step 7: Commit the registration boundary**

```bash
git add runtime/orchestrator/full_plan_activation.py runtime/orchestrator/production_full_plan_entry.py \
  tests/test_full_plan_activation.py tests/test_production_full_plan_entry.py
git commit -m "feat(full-plan): register executable approved work"
```

---

### Task 6: Add the New Remote Request Kind Without Changing V1

**Files:**
- Modify: `runtime/orchestrator/remote_control_envelope.py`
- Modify: `tests/test_remote_control_envelope.py`

**Interfaces:**
- Consumes: `ApprovedFullPlanActivationRequestV1`.
- Produces: `APPROVED_FULL_PLAN_ACTIVATION_KIND`, `RemoteFullPlanActivationAuthorization`, and `RemoteControlEnvelopeV1.payload` union support.

- [ ] **Step 1: Write failing envelope tests**

```python
def test_executable_full_plan_activation_has_distinct_kind_and_policy_ref():
    sealed = seal_remote_control_envelope(full_plan_envelope())
    value = validate_remote_control_envelope(sealed, now=NOW)
    self.assertEqual(value.request_kind, "APPROVED_FULL_PLAN_ACTIVATION")
    self.assertIsInstance(value.authorization, RemoteFullPlanActivationAuthorization)
    self.assertEqual(value.authorization.full_plan_activation_policy_ref, "FP-POLICY-1")


def test_v1_activation_bytes_and_authorization_class_remain_unchanged():
    value = validate_remote_control_envelope(seal_remote_control_envelope(v1_envelope()), now=NOW)
    self.assertEqual(value.request_kind, "APPROVED_WORK_ACTIVATION")
    self.assertIsInstance(value.authorization, RemoteWorkActivationAuthorization)
```

- [ ] **Step 2: Verify RED**

```bash
python3 -m unittest -v tests.test_remote_control_envelope
```

- [ ] **Step 3: Extend only the typed union and authorization dispatch**

```python
APPROVED_FULL_PLAN_ACTIVATION_KIND = "APPROVED_FULL_PLAN_ACTIVATION"
_FULL_PLAN_ACTIVATION_AUTH_FIELDS = {"full_plan_activation_policy_ref"}

@dataclass(frozen=True, slots=True)
class RemoteFullPlanActivationAuthorization:
    full_plan_activation_policy_ref: str
```

`_validated_payload()` must dispatch the new kind to `ApprovedFullPlanActivationRequestV1.from_mapping()`. V1 field sets and digest behavior remain unchanged.

- [ ] **Step 4: Run contract/envelope regressions**

```bash
python3 -m unittest -v \
  tests.test_remote_control_envelope \
  tests.test_approved_full_plan_activation_contract \
  tests.test_ocpv2_approved_work_activation_integration
```

- [ ] **Step 5: Commit the typed transport extension**

```bash
git add runtime/orchestrator/remote_control_envelope.py tests/test_remote_control_envelope.py
git commit -m "feat(ocpv2): add executable Full Plan request kind"
```

---

### Task 7: Shared Outbox Executable Activation Projection

**Files:**
- Modify: `runtime/orchestrator/remote_operator_outbox.py`
- Modify: `tests/test_remote_operator_outbox.py`
- Test: `tests/test_full_plan_activation.py`

**Interfaces:**
- Consumes: `FullPlanActivationReceiptV1`.
- Produces: `RemoteFullPlanActivationProjectionV1` with schema `orchestration.remote-full-plan-activation-projection.v1`; extends existing `RemoteProjectionV1` union and parser.

- [ ] **Step 1: Write failing projection and parser tests**

```python
def test_full_plan_projection_carries_profile_and_bundle_digest():
    projection = RemoteFullPlanActivationProjectionV1.from_receipt(receipt, message_id="MSG-FP-1")
    self.assertEqual(projection.activation_profile, "AUTO_RECONCILE_FULL_PLAN")
    self.assertEqual(projection.executable_authority_bundle_digest, receipt.executable_authority_bundle_digest)
    self.assertEqual(parse_remote_projection(projection.to_dict()), projection)


def test_existing_outbox_rejects_conflicting_projection_id():
    outbox.enqueue_projection(projection)
    conflict = replace(projection, authority_digest="0" * 64)
    with self.assertRaisesRegex(RemoteOperatorOutboxError, "conflicting projection ID"):
        outbox.enqueue_projection(conflict)
```

- [ ] **Step 2: Verify RED**

```bash
python3 -m unittest -v tests.test_remote_operator_outbox
```

- [ ] **Step 3: Add one projection type to the existing lifecycle**

Required fields:

```python
@dataclass(frozen=True, slots=True)
class RemoteFullPlanActivationProjectionV1:
    projection_id: str
    message_id: str
    activation_request_id: str
    activation_profile: str
    binding_digest: str
    executable_authority_bundle_digest: str
    result_status: str
    canonical_job_path: str
    run_id: str
    authority_digest: str
    activation_digest: str
    schema_version: str = "orchestration.remote-full-plan-activation-projection.v1"
```

`activation_profile` is exactly `AUTO_RECONCILE_FULL_PLAN`; result status is `FULL_PLAN_REGISTERED` or `FULL_PLAN_ALREADY_REGISTERED`. Reuse `RemoteResultOutbox.enqueue_projection()`, `pending()`, `mark_published()` and `publish_pending()` unchanged.

- [ ] **Step 4: Run outbox, V1 activation and host-inspection regressions**

```bash
python3 -m unittest -v \
  tests.test_remote_operator_outbox \
  tests.test_plan_activation \
  tests.test_ocpv2_host_inspection_integration
```

- [ ] **Step 5: Commit the shared projection**

```bash
git add runtime/orchestrator/remote_operator_outbox.py tests/test_remote_operator_outbox.py
git commit -m "feat(ocpv2): project executable activation through shared outbox"
```

---

### Task 8: Remote Service Mode, Callback and Policy Separation

**Files:**
- Modify: `runtime/orchestrator/remote_operator_service.py`
- Modify: `tests/test_remote_operator_service.py`

**Interfaces:**
- Consumes: `APPROVED_FULL_PLAN_ACTIVATION_KIND`, `RemoteFullPlanActivationAuthorization`.
- Produces: separate `activate_full_plan_authorized` callback, `full_plan_activation_enabled`, `full_plan_activation_policy_ref`, typed status projection and `full_plan_activated` count.

- [ ] **Step 1: Write failing separation tests**

```python
def test_v1_enable_does_not_enable_executable_activation():
    service = make_service(work_activation_enabled=True, full_plan_activation_enabled=False)
    result = service.poll_once(mode=ControlMode.ACTIVE)
    self.assertEqual(result.full_plan_activated, 0)
    self.assertEqual(transport.projections[0]["result_class"], "FULL_PLAN_ACTIVATION_DISABLED")


def test_executable_activation_requires_active_mode_and_exact_dedicated_policy():
    service = make_full_plan_service(policy="EXPECTED")
    blocked = service.poll_once(mode=ControlMode.CONTROL_READ_ONLY)
    self.assertEqual(blocked.blocked, 1)
    # Fresh service/transport for policy mismatch.
    service = make_full_plan_service(policy="OTHER")
    mismatch = service.poll_once(mode=ControlMode.ACTIVE)
    self.assertEqual(mismatch.blocked, 1)
```

- [ ] **Step 2: Verify RED**

```bash
python3 -m unittest -v tests.test_remote_operator_service
```

- [ ] **Step 3: Add a distinct branch for the new kind**

Constructor additions:

```python
activate_full_plan_authorized: Callable[[RemoteControlEnvelopeV1], Mapping[str, Any]] | None = None,
full_plan_activation_enabled: bool = False,
full_plan_activation_policy_ref: str = "",
```

Service behavior:

```python
elif envelope.request_kind == APPROVED_FULL_PLAN_ACTIVATION_KIND:
    if resolved_mode != ControlMode.ACTIVE:
        projection = self._full_plan_activation_status_projection(envelope, "MODE_BLOCKED")
    elif not self.full_plan_activation_enabled or self.activate_full_plan_authorized is None:
        projection = self._full_plan_activation_status_projection(envelope, "FULL_PLAN_ACTIVATION_DISABLED")
    elif not exact_dedicated_policy(envelope.authorization, self.full_plan_activation_policy_ref):
        projection = self._full_plan_activation_status_projection(envelope, "FULL_PLAN_ACTIVATION_AUTHORIZATION_MISMATCH")
    else:
        projection = self.activate_full_plan_authorized(envelope)
        full_plan_activated += 1
```

Do not route this request through `ingress`, `execute_authorized`, V1 `activate_authorized`, or canary `CanaryScope`.

- [ ] **Step 4: Run service and V1 regressions**

```bash
python3 -m unittest -v \
  tests.test_remote_operator_service \
  tests.test_ocpv2_approved_work_activation_integration \
  tests.test_ocpv2_rdc_independent_primary_path
```

- [ ] **Step 5: Commit service separation**

```bash
git add runtime/orchestrator/remote_operator_service.py tests/test_remote_operator_service.py
git commit -m "feat(ocpv2): separate executable activation policy path"
```

---

### Task 9: Runtime Composition and OFF-by-Default Deployment Contract

**Files:**
- Modify: `runtime/orchestrator/ocpv2_runtime_service.py`
- Modify: `deploy/operator-control-plane-v2/ocpv2.user.service.in`
- Modify: `tests/test_ocpv2_runtime_service.py`
- Modify: `tests/test_ocpv2_deploy_package.py`

**Interfaces:**
- Consumes: executable contract/binding/context/activation modules and shared outbox projection.
- Produces: `full_plan_activation_enabled_from_environment()`, `RuntimeConfig.full_plan_activation_enabled`, `RuntimeConfig.full_plan_activation_policy_ref`, and a composed executable activation callback.

- [ ] **Step 1: Write failing config tests for independent exact-1 enablement**

```python
def test_full_plan_activation_flag_is_exact_one_and_independent():
    self.assertFalse(full_plan_activation_enabled_from_environment({}))
    self.assertFalse(full_plan_activation_enabled_from_environment({"OCP_FULL_PLAN_ACTIVATION_ENABLED": "true"}))
    self.assertTrue(full_plan_activation_enabled_from_environment({"OCP_FULL_PLAN_ACTIVATION_ENABLED": "1"}))


def test_v1_activation_flag_does_not_enable_full_plan_activation():
    cfg = load_runtime_config(env_file_with(OCP_WORK_ACTIVATION_ENABLED="1",
                                            OCP_FULL_PLAN_ACTIVATION_ENABLED="0"))
    self.assertTrue(cfg.work_activation_enabled)
    self.assertFalse(cfg.full_plan_activation_enabled)
```

- [ ] **Step 2: Write failing authority-root composition tests**

```python
def test_executable_activation_uses_system_authority_root_and_never_request_mapping_root():
    cfg = config(full_plan_enabled=True, authority_root=authority_root)
    with patch("runtime.orchestrator.ocpv2_runtime_service.validate_approved_full_plan_binding") as validate:
        service = _compose_service(cfg)
        service.activate_full_plan_authorized(envelope)
    self.assertEqual(validate.call_args.kwargs["authority_root"], authority_root)
```

- [ ] **Step 3: Verify RED**

```bash
python3 -m unittest -v tests.test_ocpv2_runtime_service tests.test_ocpv2_deploy_package
```

- [ ] **Step 4: Add independent environment keys and RuntimeConfig fields**

Add to `_OPTIONAL_ENV`:

```text
OCP_FULL_PLAN_ACTIVATION_ENABLED
OCP_FULL_PLAN_ACTIVATION_POLICY_REF
```

Add fields:

```python
full_plan_activation_enabled: bool = False
full_plan_activation_policy_ref: str = ""
```

Validate the dedicated policy ref only when the executable feature is enabled.

- [ ] **Step 5: Compose the executable callback without spawning a worker**

```python
def activate_full_plan(envelope: RemoteControlEnvelopeV1) -> Mapping[str, Any]:
    if full_plan_activation_store is None or activation_release is None:
        raise RuntimeServiceError("FULL_PLAN_ACTIVATION_DISABLED")
    bundle = validate_approved_full_plan_binding(
        envelope.payload,
        authority_root=authority_root,
        runtime_release=activation_release,
        harness_state_root=harness_state_root,
    )
    office = AIOfficeStateStore(harness_state_root, project_id=bundle.project_id,
                                run_id=bundle.activation_request_id)
    context = coordinate_approved_full_plan_activation(bundle, office_store=office)
    receipt = full_plan_activation_store.record_or_load(
        request_id=bundle.activation_request_id,
        bundle=bundle,
        registrar=lambda: activate_approved_full_plan(
            bundle, ai_context=context, harness_state_root=harness_state_root,
        ),
    )
    projection = RemoteFullPlanActivationProjectionV1.from_receipt(receipt, message_id=envelope.message_id)
    outbox.enqueue_projection(projection)
    return projection.to_dict()
```

`finalize_remote_control_projection()` must accept the new projection schema and mark it published through the same outbox.

- [ ] **Step 6: Set deployment defaults explicitly OFF**

`deploy/operator-control-plane-v2/ocpv2.user.service.in` must include:

```ini
Environment=OCP_FULL_PLAN_ACTIVATION_ENABLED=0
```

Do not place a live policy ref in the template.

- [ ] **Step 7: Run runtime/deployment/V1/inspection regressions**

```bash
python3 -m unittest -v \
  tests.test_ocpv2_runtime_service \
  tests.test_ocpv2_deploy_package \
  tests.test_ocpv2_approved_work_activation_integration \
  tests.test_ocpv2_host_inspection_integration
```

- [ ] **Step 8: Commit the runtime composition**

```bash
git add runtime/orchestrator/ocpv2_runtime_service.py deploy/operator-control-plane-v2/ocpv2.user.service.in \
  tests/test_ocpv2_runtime_service.py tests/test_ocpv2_deploy_package.py
git commit -m "feat(ocpv2): compose executable activation feature gate"
```

---

### Task 10: Offline End-to-End Registration, Replay, Boot and Owner Qualification

**Files:**
- Create: `tests/test_ocpv2_approved_full_plan_activation_integration.py`
- Modify: `tests/test_ocpv2_rdc_independent_primary_path.py`
- Test: `tests/test_production_full_plan_boot.py`
- Test: `tests/test_ocpv2_single_execution_owner.py`

**Interfaces:**
- Consumes: the complete executable activation path from typed envelope through registration/outbox.
- Produces: offline evidence that one request registers one discoverable generic job, replay is idempotent, boot owns execution, OCP continuation rejects ownership and no direct product effect occurs during registration.

- [ ] **Step 1: Build a real temporary executable project fixture**

The fixture MUST keep product Git evidence and Harness authority evidence in separate roots. Do not commit `gate-approval.v1` into the product repository because it seals the exact product HEAD.

First create and commit only the product-repository evidence, then freeze its exact HEAD:

```text
project/docs/DEVELOPMENT_PLAN.txt        # TASK/STAGE-GATE plan with one TASK and one Gate
project/docs/spec.md
project/docs/req-task-001.json           # orchestration.project-requirement-contract.v1
project/docs/harness/task-lv-authority-projection.json
```

After that commit exists, create the external authority/runtime fixture roots without changing the product HEAD:

```text
authority/aliases/demo.json
authority/mappings/project.json
harness/_workspace/global-gate/<project_id>/approval/approval-g1.json   # gate-approval.v1 seals the frozen product HEAD
harness/_workspace/global-gate/<project_id>/artifact/engine-g1.json     # orchestration.requirement-evidence.v1 when used
runtime-release/RUNTIME_RELEASE_MANIFEST.json
```

The request uses `approval-g1.json` and `engine-g1.json` as namespace-relative refs. It never carries the `harness/...` absolute/host-relative location.

Use existing helpers `seal_approval_evidence`, `resolve_task_project_requirement_contract`, and `RuntimeReleaseManifest` rather than hand-inventing alternate schemas.

Inside `OCPv2ApprovedFullPlanActivationIntegrationTests`, define these fixture helpers explicitly:

```python
def request(self, **changes) -> dict[str, object]:
    value = self.valid_request_payload.copy()
    value.update(changes)
    return value

def typed_envelope(self, request: dict[str, object], *, message_id: str) -> RemoteControlEnvelopeV1:
    payload = self.remote_envelope_payload(request, message_id=message_id)
    return validate_remote_control_envelope(seal_remote_control_envelope(payload), now=self.now)

def run_remote_full_plan_activation(self, request: dict[str, object], *, message_id: str = "MSG-FP-1"):
    envelope = self.typed_envelope(request, message_id=message_id)
    service = self.compose_test_service(envelope)
    return service.poll_once(mode=ControlMode.ACTIVE), self.transport
```

`self.valid_request_payload`, `remote_envelope_payload()`, and `compose_test_service()` are populated in `setUp()` from the real committed fixture artifacts listed above; they do not synthesize runtime authority beyond those files.

- [ ] **Step 2: Write the failing successful-registration test**

```python
def test_remote_executable_activation_registers_one_auto_reconcile_job():
    result, transport = run_remote_full_plan_activation(valid_request())
    self.assertEqual(result.full_plan_activated, 1)
    jobs = discover_registered_jobs(state_root)
    self.assertEqual(len(jobs), 1)
    job = load_registered_job(jobs[0])
    self.assertEqual(job["execution_owner"], "AUTO_RECONCILE")
    self.assertNotIn("executor_kind", job)
    self.assertEqual(job["mapping_root"], str((authority_root / "mappings").resolve()))
```

- [ ] **Step 3: Write crash/replay and owner-separation tests**

```python
def test_publish_failure_replay_does_not_register_second_job():
    first = run_with_publish_failure(valid_request())
    self.assertEqual(len(discover_registered_jobs(state_root)), 1)
    second = replay_same_request()
    self.assertEqual(len(discover_registered_jobs(state_root)), 1)
    self.assertEqual(second.projection.activation_profile, "AUTO_RECONCILE_FULL_PLAN")


def test_boot_accepts_auto_reconcile_while_ocp_resume_rejects_owner():
    job_path = discover_registered_jobs(state_root)[0]
    with patch("runtime.orchestrator.production_full_plan_boot._unit_active", return_value=False):
        boot = reconcile_job(job_path, launch=False)
    self.assertEqual(boot["action"], "WOULD_RESUME")
    with self.assertRaisesRegex(Exception, "EXECUTION_OWNER_MISMATCH"):
        execute_registered_full_plan_continuation(
            harness_state_root=state_root, project_id=job["project_id"], run_id=job["run_id"],
            gate_id=job["gates"][0]["gate_id"], task_id=job["gates"][0]["gate_id"],
            task_execution_id="OWNER-CHECK", expected_state_sha256="0" * 64,
            expected_owner_epoch=1, expected_source_head=bundle.expected_head,
            expected_runtime_release_digest=bundle.runtime_release_digest,
            remote_message_id="MSG-OWNER-CHECK", remote_directive_digest="a" * 64,
        )
```

For the OCP-resume call, build the exact current state/head/runtime bindings from the registered job and supervisor state so the failure is specifically owner mismatch rather than malformed input.

- [ ] **Step 4: Write fail-closed integration tests**

One test each for:

```text
aliases present / mappings absent
mapping plan SHA drift
projection SHA drift
expired Gate approval
production-approval-v2 in Gate approval slot
missing project requirement LV artifact
runtime release digest drift
same request ID + different bundle
```

Every case must assert zero registered jobs and zero worker/Gateway calls.

- [ ] **Step 5: Run the integration tests and verify RED before final wiring**

```bash
python3 -m unittest -v tests.test_ocpv2_approved_full_plan_activation_integration
```

- [ ] **Step 6: Complete only the minimal wiring required by failing tests**

Changes belong in the modules from Tasks 1-9. Do not add another executor, background service, mapping registry or fallback callback to make integration green.

- [ ] **Step 7: Run owner/boot/primary-path regressions**

```bash
python3 -m unittest -v \
  tests.test_ocpv2_approved_full_plan_activation_integration \
  tests.test_production_full_plan_boot \
  tests.test_ocpv2_single_execution_owner \
  tests.test_ocpv2_rdc_independent_primary_path
```

Expected: PASS.

- [ ] **Step 8: Commit the end-to-end offline qualification**

```bash
git add tests/test_ocpv2_approved_full_plan_activation_integration.py tests/test_ocpv2_rdc_independent_primary_path.py \
  runtime/orchestrator runtime/ai_office
git commit -m "test(ocpv2): qualify executable activation offline"
```

Before committing, inspect `git diff --cached --name-only` and unstage any unrelated runtime files; this commit must contain only changes required by Tasks 1-10.

---

### Task 11: Authority Negative-Space and Full Repository Regression

**Files:**
- Create: `tests/test_ocpv2_full_plan_activation_authority_negative_space.py`
- Modify: `.github/workflows/ocpv2-r2-ci.yml` only if the current workflow enumerates focused test modules rather than using discovery.

**Interfaces:**
- Consumes: complete code path from Tasks 1-10.
- Produces: source-level proof that the new path did not acquire prohibited authority and repository-level regression evidence.

- [ ] **Step 1: Write negative-space source tests**

```python
def test_executable_activation_modules_have_no_effect_runtime_imports():
    sources = read_sources(
        "runtime/orchestrator/approved_full_plan_activation_contract.py",
        "runtime/orchestrator/approved_full_plan_binding.py",
        "runtime/ai_office/full_plan_activation.py",
        "runtime/orchestrator/full_plan_activation.py",
    )
    for forbidden in (
        "FullMCPRuntime", "execute_production_worker", "dispatch_action_through_production_gateway",
        "provider_router", "subprocess.Popen", "os.system", "systemctl", "shell=True",
    ):
        self.assertNotIn(forbidden, sources)


def test_no_new_executor_owner_or_outbox_class_is_created():
    self.assertNotIn("EXECUTION_OWNERS.add", sources)
    self.assertNotIn("class FullPlanActivationOutbox", sources)
```

Also assert the new request contract has no fields named `provider`, `model`, `backend`, `command`, `argv`, `environment`, `owned_scope`, `editable_scope`, or `mapping_root`.
Also assert `approved_full_plan_binding.py` never resolves Gate approval with `resolve_committed_project_file()` and never resolves engine conformance evidence under the project root; those two fields must pass through the fixed `approval` / `artifact` namespace resolver.

- [ ] **Step 2: Run the authority-focused matrix**

```bash
python3 -m unittest -v \
  tests.test_ocpv2_full_plan_activation_authority_negative_space \
  tests.test_ocpv2_approved_full_plan_activation_integration \
  tests.test_ocpv2_approved_work_activation_integration \
  tests.test_ocpv2_single_execution_owner \
  tests.test_production_full_plan_entry \
  tests.test_production_full_plan_boot \
  tests.test_gate_orchestrator \
  tests.test_provider_router \
  tests.test_production_execution_gateway
```

Expected: PASS.

- [ ] **Step 3: Run the whole repository using the established MCP-capable Python environment**

```bash
export PYTHONPATH="$PWD/.venv/lib/python3.12/site-packages"
/usr/bin/python3 -m unittest discover -s tests -v 2>&1 | tee /tmp/awel-full-regression.log
```

Expected: `OK`; compare the skipped count with the branch baseline and investigate any delta before proceeding. Do not treat missing `mcp` under bare `/usr/bin/python3` as a product regression; the established branch test environment explicitly adds the worktree `.venv` site-packages.

- [ ] **Step 4: Record exact regression evidence**

Create `docs/history/upgrades/2026-09-23-OCP-APPROVED-WORK-EXECUTION-LINK/IMPLEMENTATION_REGRESSION.json` from the completed log with this command so the committed artifact contains actual values rather than examples:

```bash
python3 - <<'PY2'
import json, re, subprocess
from pathlib import Path
log = Path('/tmp/awel-full-regression.log').read_text(encoding='utf-8', errors='replace')
match = re.search(r'Ran (\d+) tests', log)
skipped = re.search(r'OK \(skipped=(\d+)\)', log)
if not match or 'FAILED' in log or 'ERROR:' in log:
    raise SystemExit('full regression is not PASS')
payload = {
    'schema_version': 'awel.implementation-regression.v1',
    'tested_head': subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(),
    'focused_status': 'PASS', 'full_status': 'PASS',
    'full_test_count': int(match.group(1)),
    'skipped_count': int(skipped.group(1)) if skipped else 0,
    'feature_enabled': False, 'live_activation_performed': False,
}
Path('docs/history/upgrades/2026-09-23-OCP-APPROVED-WORK-EXECUTION-LINK/IMPLEMENTATION_REGRESSION.json').write_text(
    json.dumps(payload, sort_keys=True, indent=2) + '\n', encoding='utf-8')
PY2
```

- [ ] **Step 5: Commit regression evidence**

```bash
git add tests/test_ocpv2_full_plan_activation_authority_negative_space.py \
  docs/history/upgrades/2026-09-23-OCP-APPROVED-WORK-EXECUTION-LINK/IMPLEMENTATION_REGRESSION.json \
  .github/workflows/ocpv2-r2-ci.yml
git commit -m "test(ocpv2): close executable activation authority regression"
```

If the workflow file did not require a change, omit it from `git add`.

---

### Task 12: Successor Runtime Deployment and Feature-OFF Qualification

**Files:**
- Create before deployment: `docs/history/upgrades/2026-09-23-OCP-APPROVED-WORK-EXECUTION-LINK/SUCCESSOR_FEATURE_OFF_AUTHORIZATION_PACKAGE.md`
- Create after deployment: `docs/history/upgrades/2026-09-23-OCP-APPROVED-WORK-EXECUTION-LINK/SUCCESSOR_FEATURE_OFF_QUALIFICATION.md`
- Modify: `docs/harness/ocpv2-approved-work-activation-runbook.md`
- Modify: `docs/harness/ocpv2-rdc-independent-acceptance-runbook.md`

**Interfaces:**
- Consumes: a clean exact implementation/evidence HEAD from Task 11, `runtime.orchestrator.runtime_release.build_runtime_release()`, the existing reviewed `ocpv2.service`/`ocpv2.env`, and the current OCP user timer/service.
- Produces: one immutable successor release, a separately approved live runtime switch, and evidence that the successor is healthy while `OCP_FULL_PLAN_ACTIVATION_ENABLED=0` and all pre-existing Host Inspection/V1 settings are unchanged.

- [ ] **Step 1: Update runbooks with the corrected three-way activation split and commit the documentation-only preparation**

Document exactly:

```text
APPROVED_WORK_ACTIVATION       = V1 tracking/manual receipt only
APPROVED_FULL_PLAN_ACTIVATION = executable generic AUTO_RECONCILE registration
EXISTING_RUN_CONTROL           = OCPV2-owned continuation only
```

Also document `OCP_FULL_PLAN_ACTIVATION_ENABLED=0` as the required normal post-deploy state and state explicitly that a successor runtime switch is a separate live operational approval.

Run:

```bash
grep -R "OCP_FULL_PLAN_ACTIVATION_ENABLED=0" deploy/operator-control-plane-v2 docs/harness
git diff --check
git add docs/harness/ocpv2-approved-work-activation-runbook.md \
  docs/harness/ocpv2-rdc-independent-acceptance-runbook.md
git commit -m "docs(ocpv2): prepare executable activation successor runbooks"
```

- [ ] **Step 2: Build the exact immutable successor release without switching the live service**

Run from the clean implementation worktree:

```bash
python3 - <<'PY2'
import json
from pathlib import Path
from runtime.orchestrator.runtime_release import build_runtime_release
repo = Path.cwd().resolve()
releases = Path.home() / ".local" / "share" / "global-gpt-harness" / "releases"
manifest = build_runtime_release(repo, releases, "HEAD")
selection_root = Path.home() / ".local/state/global-gpt-harness/awel-successor-review"
selection_root.mkdir(parents=True, exist_ok=True)
(selection_root / "selected-head.txt").write_text(manifest.source_head + "\n", encoding="ascii")
print(json.dumps(manifest.to_dict(), sort_keys=True, indent=2))
PY2
```

Record the printed `source_head`, `release_path`, and `manifest_sha256`. Require `source_head == git rev-parse HEAD` and require the release to contain `runtime/orchestrator/ocpv2_runtime_service.py`, the updated service template, and `RUNTIME_RELEASE_MANIFEST.json`.

- [ ] **Step 3: Prepare reviewed successor unit/env files and predecessor rollback evidence without installing them**

Run:

```bash
SELECTION_ROOT="$HOME/.local/state/global-gpt-harness/awel-successor-review"
SUCCESSOR_HEAD="$(cat "$SELECTION_ROOT/selected-head.txt")"
RELEASE="$HOME/.local/share/global-gpt-harness/releases/$SUCCESSOR_HEAD"
REVIEW="$SELECTION_ROOT/$SUCCESSOR_HEAD"
test ! -e "$REVIEW"
install -d -m 700 "$REVIEW"
RELEASE="$RELEASE" REVIEW="$REVIEW" python3 - <<'PY2'
import os
from pathlib import Path
release = Path(os.environ["RELEASE"]).resolve()
review = Path(os.environ["REVIEW"]).resolve()
service = (release / "deploy/operator-control-plane-v2/ocpv2.user.service.in").read_text(encoding="utf-8")
service = service.replace("@REPO_ROOT@", str(release))
if "@REPO_ROOT@" in service:
    raise SystemExit("unresolved repo root")
(review / "ocpv2.service").write_text(service, encoding="utf-8")
current_env = Path.home() / ".config/gch/ocpv2.env"
rows = {}
for raw in current_env.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    key, value = line.split("=", 1)
    rows[key] = value
rows["OCP_FULL_PLAN_ACTIVATION_ENABLED"] = "0"
rows.pop("OCP_FULL_PLAN_ACTIVATION_POLICY_REF", None)
(review / "ocpv2.env").write_text("".join(f"{k}={v}\n" for k, v in rows.items()), encoding="utf-8")
os.chmod(review / "ocpv2.env", 0o600)
PY2
sha256sum ~/.config/systemd/user/ocpv2.service ~/.config/gch/ocpv2.env \
  "$REVIEW/ocpv2.service" "$REVIEW/ocpv2.env" > "$REVIEW/sha256.txt"
grep '^Environment=OCP_FULL_PLAN_ACTIVATION_ENABLED=0$' "$REVIEW/ocpv2.service"
grep '^OCP_FULL_PLAN_ACTIVATION_ENABLED=0$' "$REVIEW/ocpv2.env"
! grep -q '^OCP_FULL_PLAN_ACTIVATION_POLICY_REF=' "$REVIEW/ocpv2.env"
```

The reviewed env file remains local evidence and is never committed because it contains deployment bindings. The authorization package records only safe digests/paths and the non-secret setting names/expected values; it never copies credential paths or values into Git.

- [ ] **Step 4: Write `SUCCESSOR_FEATURE_OFF_AUTHORIZATION_PACKAGE.md` and stop at a HUMAN APPROVAL GATE**

The package must bind:

```text
successor source HEAD
runtime release path + manifest digest
current service/env SHA-256 digests
reviewed service/env SHA-256 digests
expected WorkingDirectory = exact successor release
OCP_FULL_PLAN_ACTIVATION_ENABLED = 0
OCP_FULL_PLAN_ACTIVATION_POLICY_REF = absent
Host Inspection setting = preserve predecessor value
V1 activation setting/policy = preserve predecessor value
rollback source = exact predecessor service/env files backed up before install
```

Commit this package before any live switch:

```bash
git add docs/history/upgrades/2026-09-23-OCP-APPROVED-WORK-EXECUTION-LINK/SUCCESSOR_FEATURE_OFF_AUTHORIZATION_PACKAGE.md
git commit -m "docs(ocpv2): bind executable activation successor deployment"
```

This documentation commit intentionally advances the worktree HEAD after the immutable release was built. The live deployment identity remains the exact value in local `awel-successor-review/selected-head.txt` and in the authorization package; Steps 5-8 must never substitute the newer documentation HEAD for that selected release.

**STOP.** Request explicit user approval for this exact successor runtime switch. Building the immutable release and review package does not authorize `install`, `systemctl --user daemon-reload`, service start/restart, or any live control request.

- [ ] **Step 5: After explicit successor-deployment approval, back up predecessor files and install only the reviewed feature-OFF unit/env**

Run:

```bash
SELECTION_ROOT="$HOME/.local/state/global-gpt-harness/awel-successor-review"
SUCCESSOR_HEAD="$(cat "$SELECTION_ROOT/selected-head.txt")"
REVIEW="$SELECTION_ROOT/$SUCCESSOR_HEAD"
BACKUP="$HOME/.local/state/global-gpt-harness/awel-deploy-backup/$SUCCESSOR_HEAD"
test -d "$REVIEW"
test ! -e "$BACKUP"
install -d -m 700 "$BACKUP"
cp --preserve=mode,timestamps ~/.config/systemd/user/ocpv2.service "$BACKUP/ocpv2.service"
cp --preserve=mode,timestamps ~/.config/gch/ocpv2.env "$BACKUP/ocpv2.env"
install -m 0644 "$REVIEW/ocpv2.service" ~/.config/systemd/user/ocpv2.service
install -m 0600 "$REVIEW/ocpv2.env" ~/.config/gch/ocpv2.env
systemctl --user daemon-reload
systemctl --user start ocpv2.service
```

Do not stop/restart the timer unless the health check proves it is not active. The one-shot service start is the successor smoke; executable activation remains OFF.

- [ ] **Step 6: Prove successor identity, feature-OFF state, and preserved pre-existing settings**

Run:

```bash
SELECTION_ROOT="$HOME/.local/state/global-gpt-harness/awel-successor-review"
SUCCESSOR_HEAD="$(cat "$SELECTION_ROOT/selected-head.txt")"
RELEASE="$HOME/.local/share/global-gpt-harness/releases/$SUCCESSOR_HEAD"
grep '^OCP_FULL_PLAN_ACTIVATION_ENABLED=0$' ~/.config/gch/ocpv2.env
! grep -q '^OCP_FULL_PLAN_ACTIVATION_POLICY_REF=' ~/.config/gch/ocpv2.env
systemctl --user show ocpv2.service \
  --property=WorkingDirectory --property=Result --property=ExecMainStatus --no-pager
systemctl --user is-active ocpv2.timer
python3 - <<'PY2'
from pathlib import Path
from runtime.orchestrator.runtime_release import verify_runtime_release
selection = Path.home() / '.local/state/global-gpt-harness/awel-successor-review/selected-head.txt'
head = selection.read_text(encoding='ascii').strip()
release = Path.home() / '.local/share/global-gpt-harness/releases' / head
manifest = verify_runtime_release(release, head)
print(manifest.manifest_sha256)
PY2
```

Required evidence:

```text
WorkingDirectory = exact successor release
Result = success
ExecMainStatus = 0
ocpv2.timer = active
successor release manifest verifies against exact HEAD
OCP_FULL_PLAN_ACTIVATION_ENABLED = 0
no executable activation policy ref configured
Host Inspection value equals predecessor review snapshot
V1 activation flag/policy equals predecessor review snapshot
```

Then submit one typed `APPROVED_FULL_PLAN_ACTIVATION` request through the existing GitHub private control channel while the feature is OFF. Require `FULL_PLAN_ACTIVATION_DISABLED`, `full_plan_activated=0`, and zero new registered jobs for that activation ID. This blocked request is feature-OFF qualification only; it grants no canary authority.

- [ ] **Step 7: Fail closed to the exact predecessor on any successor qualification failure**

If Step 5 or 6 fails, run immediately:

```bash
SELECTION_ROOT="$HOME/.local/state/global-gpt-harness/awel-successor-review"
SUCCESSOR_HEAD="$(cat "$SELECTION_ROOT/selected-head.txt")"
BACKUP="$HOME/.local/state/global-gpt-harness/awel-deploy-backup/$SUCCESSOR_HEAD"
install -m 0644 "$BACKUP/ocpv2.service" ~/.config/systemd/user/ocpv2.service
install -m 0600 "$BACKUP/ocpv2.env" ~/.config/gch/ocpv2.env
systemctl --user daemon-reload
systemctl --user start ocpv2.service
systemctl --user is-active ocpv2.timer
systemctl --user show ocpv2.service --property=WorkingDirectory --property=Result --property=ExecMainStatus --no-pager
```

Preserve successor release/review evidence and failure logs. Do not delete registered Harness state, change execution owners, or enable the executable feature to “test through” a failed OFF qualification.

- [ ] **Step 8: Write and commit `SUCCESSOR_FEATURE_OFF_QUALIFICATION.md` only after Step 6 PASS**

Record exact successor/predecessor unit digests, release manifest digest, WorkingDirectory, service/timer results, preserved pre-existing flag comparison, blocked executable request digest/result, zero-job proof, rollback backup path and `live_executable_feature_enabled=false`.

Run `git diff --check`, then commit:

```bash
git add docs/history/upgrades/2026-09-23-OCP-APPROVED-WORK-EXECUTION-LINK/SUCCESSOR_FEATURE_OFF_QUALIFICATION.md
git commit -m "docs(ocpv2): record executable activation successor feature-off qualification"
```

Task 13 may begin only from a deployed successor with this qualification PASS. It still requires its own separate live-canary approval before enabling executable activation.

---

### Task 13: Fresh No-RDC Executable Canary Qualification

**Files:**
- Create: `docs/history/upgrades/2026-09-23-OCP-APPROVED-WORK-EXECUTION-LINK/LIVE_CANARY_AUTHORIZATION_PACKAGE.md`
- Create after execution: `docs/history/upgrades/2026-09-23-OCP-APPROVED-WORK-EXECUTION-LINK/LIVE_CANARY_EVIDENCE.json`

**Interfaces:**
- Consumes: a deployed successor that passed Task 12, a fresh disposable project with pre-existing alias + executable mapping + projection + Gate approval + requirement evidence, and a fresh activation/run identity.
- Produces: one bounded canonical product effect, one validation result, replay/idempotency proof, rollback-to-OFF proof and explicit no-RDC path evidence.

- [ ] **Step 1: Prepare a canary authorization package without enabling anything**

The package names the exact disposable project, expected one-file effect, validation command/evidence, activation request ID, Gate ID, source HEAD, runtime release digest, executable policy ref, rollback command and expected post-rollback state. It must explicitly state that `GPT-ACT-20260923-02` is excluded and immutable.

- [ ] **Step 2: Verify the disposable project is fully qualified before feature enable**

Qualification must resolve Gate approval/engine evidence from the deployed Harness namespace roots; the remote request carries only safe namespace-relative refs plus digests, never absolute host paths.

Read-only checks must prove:

```text
alias entry exists and matches project root/plan SHA
mappings/project.json exists and validates
TASK-to-LV projection exists and matches its configured SHA
Gate approval exists only in the system-derived Harness approval namespace and is active, unexpired and exact-scope
engine conformance evidence, when required, exists only in the system-derived Harness artifact namespace
project requirement contracts remain committed project-relative evidence and validate
project worktree is on expected branch/HEAD and clean
runtime release manifest matches deployed successor
no prior job/receipt exists for the fresh activation ID
```

If any check fails, record the reason and stop; do not bootstrap or repair it inside the canary task.

- [ ] **Step 3: HUMAN APPROVAL GATE — stop and request explicit live-canary authorization**

No command that changes the deployed executable feature flag, policy, service state, disposable project, registered Full Plan state or source tree may run until the user explicitly approves this exact package.

- [ ] **Step 4: After explicit authorization, enable only the executable canary feature/policy**

Do not change Host Inspection, V1 activation, OCP mode semantics, Router configuration or execution owner rules.

- [ ] **Step 5: Submit exactly one fresh `APPROVED_FULL_PLAN_ACTIVATION` request without RDC**

Require the returned projection to contain:

```text
activation_profile=AUTO_RECONCILE_FULL_PLAN
result_status=FULL_PLAN_REGISTERED
fresh activation_request_id/run_id
executable_authority_bundle_digest
sealed job authority digest
```

- [ ] **Step 6: Observe canonical Full Plan execution without RDC**

Use OCP/Host Inspection/Harness canonical status only. Require one bounded expected source effect, canonical validation/review/checkpoint/handoff evidence, and no OCP direct worker/Gateway call.

- [ ] **Step 7: Replay the identical request and prove idempotency**

Require the same registration result/projection identity semantics, one registered job total, and no duplicate source effect.

- [ ] **Step 8: Disable executable activation and verify rollback-to-OFF**

Require `OCP_FULL_PLAN_ACTIVATION_ENABLED=0`, normal OCP timer/service health, successful Host Inspection/V1 regression smoke checks, and preservation of registered/evidence artifacts.

- [ ] **Step 9: Write immutable live evidence**

`LIVE_CANARY_EVIDENCE.json` records exact request/bundle/job/effect/validation/replay/rollback digests and includes:

```text
rdc_used_in_tested_path=false
feature_final_state=OFF
old_canary_mutated=false
```

- [ ] **Step 10: Commit only the evidence after rollback is verified**

```bash
git add docs/history/upgrades/2026-09-23-OCP-APPROVED-WORK-EXECUTION-LINK/LIVE_CANARY_AUTHORIZATION_PACKAGE.md \
  docs/history/upgrades/2026-09-23-OCP-APPROVED-WORK-EXECUTION-LINK/LIVE_CANARY_EVIDENCE.json
git commit -m "docs(ocpv2): record executable activation live canary"
```

---

### Task 14: Runtime EDP Closure and RDC-Independent Acceptance Update

**Files:**
- Create: `docs/history/upgrades/2026-09-23-OCP-APPROVED-WORK-EXECUTION-LINK/EDP_RUNTIME_ALL_PASS.md`
- Modify: `docs/harness/ocpv2-rdc-independent-acceptance-runbook.md`

**Interfaces:**
- Consumes: implementation commits, Task 11 regression evidence, Task 12 successor feature-OFF qualification, Task 13 live canary evidence and the canonical EDP-1.0 protocol.
- Produces: scoped runtime EDP decision; only a genuine complete acceptance may advance the RDC-independent gate status.

- [ ] **Step 1: Re-run focused tests on the final evidence commit**

```bash
python3 -m unittest -v \
  tests.test_approved_full_plan_activation_contract \
  tests.test_approved_full_plan_binding \
  tests.test_ai_office_full_plan_activation \
  tests.test_full_plan_activation \
  tests.test_remote_control_envelope \
  tests.test_remote_operator_outbox \
  tests.test_remote_operator_service \
  tests.test_ocpv2_runtime_service \
  tests.test_ocpv2_approved_full_plan_activation_integration \
  tests.test_ocpv2_full_plan_activation_authority_negative_space
```

- [ ] **Step 2: Re-run the whole repository on the final evidence commit**

```bash
export PYTHONPATH="$PWD/.venv/lib/python3.12/site-packages"
/usr/bin/python3 -m unittest discover -s tests -v 2>&1 | tee /tmp/awel-final-full-regression.log
```

Require `OK` and explain any intentional skipped tests by existing baseline identity.

- [ ] **Step 3: Execute the EDP mandatory sequence**

The runtime closure document must include:

```text
Canonical Source Resolution
Obligation Extraction & Freeze for AWEL-MUST-001..025 and AWEL-AC-001..016
Primary Domain Audit
Mandatory Evidence Matrix
Mandatory RTM
Negative-Space Audit
Cross-Document Audit
Adversarial Second Pass
PASS Challenge
Regression Re-Diagnosis
Closure Metrics
Exhaustion Statement
Final Decision
```

- [ ] **Step 4: Permit `AWEL_RUNTIME_EDP_ALL_PASS` only when every closure metric is satisfied**

Required minimum metrics:

```text
BLOCKER_COUNT=0
UNRESOLVED_MAJOR_COUNT=0
MUST_REQUIREMENT_COVERAGE=100%
MUST_TRACEABILITY_COVERAGE=100%
DOMAIN_EVIDENCE_COVERAGE=100%
NEGATIVE_SPACE_OPEN_MATERIAL_COUNT=0
CROSS_DOCUMENT_CONFLICT_COUNT=0
BROKEN_REFERENCE_COUNT=0
ADVERSARIAL_NEW_BLOCKER_MAJOR=0
PASS_CHALLENGE_OPEN_COUNT=0
REGRESSION_REDIAGNOSIS_STATUS=PASS
MATERIAL_DEFECT_SEARCH=EXHAUSTED_FOR_AVAILABLE_EVIDENCE
```

- [ ] **Step 5: Update RDC-independent acceptance only from actual evidence**

If all pre-existing RDC-independent gates plus the repaired executable-activation gates are now proven, update `docs/harness/ocpv2-rdc-independent-acceptance-runbook.md` with the actual completed/total acceptance count and allow the operating documentation to state `RDC=OPTIONAL_RECOVERY`. If another acceptance gate remains open, record the exact remaining gate in that same runbook and keep `RDC=NORMAL_DEPENDENCY` for that unproven scope.

- [ ] **Step 6: Commit the runtime closure**

```bash
git add docs/history/upgrades/2026-09-23-OCP-APPROVED-WORK-EXECUTION-LINK/EDP_RUNTIME_ALL_PASS.md \
  docs/harness/ocpv2-rdc-independent-acceptance-runbook.md
git commit -m "docs(ocpv2): close executable activation runtime EDP"
```

---

## Self-Review Checklist

- **Spec coverage:** Tasks 1-14 cover AWEL-MUST-001..025 and AWEL-AC-001..016. Contract, authority validation, AI Office binding, generic job registration, replay, outbox, service policy, runtime composition, owner separation, negative space, full regression, successor OFF qualification, fresh no-RDC live canary and runtime EDP closure all have explicit owners.
- **No duplicate authority:** no task creates a new project registry, mapping semantics, TASK-to-LV semantics, approval schema, requirement schema, execution owner, provider router, worker, Gateway, Full MCP runtime or result outbox.
- **V1 compatibility:** V1 contract/context/receipt/projection remain separate and have explicit regression tests in Tasks 1, 4, 6, 7, 8 and 9.
- **Type consistency:** `ApprovedFullPlanActivationRequestV1` → `ExecutableAuthorityBundleV1` → `AIFullPlanActivationContextV1` → `FullPlanActivationReceiptV1` → `RemoteFullPlanActivationProjectionV1` is the only new-work executable type chain.
- **Mapping-root consistency:** remote payload contains no mapping root; runtime resolves one system authority root, validator derives `AUTHORITY_ROOT/aliases` and `AUTHORITY_ROOT/mappings`, and the sealed job persists only the exact validated mappings directory in `job["mapping_root"]`.
- **Execution-owner consistency:** the new job sets `AUTO_RECONCILE`; generic boot/run executes it; OCPV2 resume rejects it; no rebind occurs.
- **Review Focus coverage:** authority-root absence is tested in Tasks 3/10; approval-domain and Harness namespace confinement in Tasks 3/10/11; registration/publication crash in Tasks 7/10; binding-to-execution drift in Tasks 5/10/11; V1/OCPV2/AUTO_RECONCILE coexistence in Tasks 6/8/10/11.
- **Live safety:** Tasks 1-12 contain no live feature enable or runtime switch. Task 13 has an explicit human approval hard stop before any live state change.

## Execution Handoff

Implementation must resume from Task 3 of this plan and the approved amended AWEL spec together. Tasks 1-2 are already implemented at `dd4e548` and `98a82f2` and are not to be repeated. The stopped V1 implementation history remains evidence and compatibility surface; it is not to be merged wholesale or reinterpreted as executable authority.
