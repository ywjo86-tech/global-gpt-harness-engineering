# External Capability Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing capability discovery/evaluation/adoption pipeline with an MCP/Adapter-first operational contract lifecycle that can activate, monitor, drain, replace, quarantine, reassess, and retire external capabilities without absorbing external Agent code into Harness Core or creating a second assignment/effect authority.

**Architecture:** Keep existing inventory/discovery/evaluator and local-skill install/use-authorization as reusable admission components, but make external Agent adoption MCP/Adapter-first. Add a small lifecycle ledger keyed by an authorized capability contract; MCP/Adapter endpoints do not require local code installation, local Skill installation is fallback-only, Full Plan still owns final assignment, and state-changing external capability calls remain proposals that must enter Production Execution Gateway/Full MCP.

**Tech Stack:** Python 3.12 dataclasses, atomic JSON persistence from existing durable IO helpers, unittest.

**Spec:** `docs/superpowers/specs/2026-09-24-ai-office-harness-topdown-edp-reconciled-design.md`

## Global Constraints

- Do not duplicate capability inventory, discovery, candidate evaluation, supply-chain review, installation, or use authorization.
- A lifecycle record may bind an evaluated MCP/Adapter endpoint or an already authorized local Skill fallback.
- External Agent default binding is `MCP_ENDPOINT` or `ADAPTER`; `LOCAL_SKILL` is fallback-only (`ABSORB LAST`).
- Contract exposure is allowlist-based: risky/conflicting/duplicate capabilities can be excluded without importing the external runtime implementation.
- Capability lifecycle code never emits `final_assignee`, provider, or model selection.
- `ACTIVE -> RETIRED` is rejected while active dependencies are nonzero.
- Replacement does not silently rebind running work.
- Running work records `capability_contract_id`, `capability_contract_version`, `endpoint_version`, and `activation_epoch`.
- State-changing external calls require the existing Execution Gateway/Full MCP path by default.
- External lifecycle failure cannot mutate Full Plan Gate state by itself.

## Review Focus

1. Direct retirement with active dependencies fails closed.
2. A replacement capability cannot steal a running task lineage.
3. Lifecycle/binding APIs never return `final_assignee`, provider, or model fields, and MCP/Adapter candidates require no local code copy.
4. Read-only invocation may be allowed through an approved adapter; state-changing invocation returns `GATEWAY_REQUIRED` and no executor.
5. Persisted lifecycle records reject digest/version drift on reload.

---

### Task 1: Define lifecycle and contract-reference schemas

**Files:**
- Create: `runtime/orchestrator/capability_lifecycle.py`
- Test: `tests/test_capability_lifecycle.py`
- Create test helper: `tests/capability_lifecycle_fixtures.py`

**Interfaces:**
- Consumes: evaluated external endpoint evidence for `MCP_ENDPOINT`/`ADAPTER`, or stable asset IDs from existing `SkillUseAuthorizationResult`/`RuntimeSelection` only for `LOCAL_SKILL` fallback.
- Produces: `CapabilityContractRefV1`, `CapabilityLifecycleRecordV1`, `transition_capability_lifecycle(record, target_state, evidence_refs)`.

- [ ] **Step 1: Write failing schema/transition tests**

```python
# tests/capability_lifecycle_fixtures.py
from runtime.orchestrator.capability_lifecycle import CapabilityContractRefV1, CapabilityLifecycleRecordV1

def active_record() -> CapabilityLifecycleRecordV1:
    return CapabilityLifecycleRecordV1.create(
        contract=CapabilityContractRefV1(
            contract_id="cap:ui-design:1",
            contract_version="1.0.0",
            binding_kind="MCP_ENDPOINT",
            endpoint_ref="mcp:ui-design-agent",
            stable_asset_identifier="",
            endpoint_version="rev-001",
            activation_epoch=1,
        ),
        state="ACTIVE", health="HEALTHY", active_dependency_ids=(),
        evidence_refs=("evidence:use-auth",),
    )

# tests/test_capability_lifecycle.py
import dataclasses, pytest
from tests.capability_lifecycle_fixtures import active_record
from runtime.orchestrator.capability_lifecycle import CapabilityLifecycleError, transition_capability_lifecycle

def test_direct_retire_with_active_dependencies_is_rejected():
    record = dataclasses.replace(active_record(), active_dependency_ids=("TASKEXEC-1", "TASKEXEC-2"))
    with pytest.raises(CapabilityLifecycleError, match="active dependencies"):
        transition_capability_lifecycle(record, "RETIRED", ("evidence:retire",))

def test_direct_retire_without_dependencies_requires_evidence():
    with pytest.raises(CapabilityLifecycleError, match="retire evidence"):
        transition_capability_lifecycle(active_record(), "RETIRED", ())
```

- [ ] **Step 2: Run and confirm missing module**

```bash
python -m pytest tests/test_capability_lifecycle.py -q
```

Expected: import failure.

- [ ] **Step 3: Implement closed lifecycle states and transition table**

```python
LIFECYCLE_STATES = frozenset({
    "DISCOVERED", "CANDIDATE", "SANDBOX", "QUALIFIED", "ACTIVE",
    "DEGRADED", "QUARANTINED", "DISABLE_NEW_ASSIGNMENT", "DRAINING",
    "SUPERSEDED", "DEPRECATED", "RETIRED",
})

_ALLOWED = {
    "QUALIFIED": {"ACTIVE", "QUARANTINED"},
    "ACTIVE": {"DEGRADED", "QUARANTINED", "DISABLE_NEW_ASSIGNMENT", "RETIRED"},
    "DEGRADED": {"ACTIVE", "QUARANTINED", "DISABLE_NEW_ASSIGNMENT"},
    "QUARANTINED": {"ACTIVE", "DISABLE_NEW_ASSIGNMENT"},
    "DISABLE_NEW_ASSIGNMENT": {"DRAINING"},
    "DRAINING": {"SUPERSEDED", "DEPRECATED", "RETIRED"},
    "SUPERSEDED": {"RETIRED"},
    "DEPRECATED": {"RETIRED"},
}
```

`CapabilityContractRefV1` stores `binding_kind` (`MCP_ENDPOINT`, `ADAPTER`, `LOCAL_SKILL`), bounded `endpoint_ref`, optional `stable_asset_identifier`, version, activation epoch, allowed capabilities, blocked capabilities, and evidence refs. MCP/Adapter records require an endpoint ref and forbid an installed-skill identifier; LOCAL_SKILL requires the existing authorized stable asset identifier. `CapabilityLifecycleRecordV1` stores `active_dependency_ids: tuple[str, ...]` and exposes `active_dependency_count` as a property. `transition_capability_lifecycle()` requires zero active dependencies plus non-empty retirement evidence for direct `RETIRED`, and seals every record with a canonical digest.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_capability_lifecycle.py -q
```

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/capability_lifecycle.py tests/test_capability_lifecycle.py tests/capability_lifecycle_fixtures.py
git commit -m "feat: add external capability lifecycle contract"
```

### Task 2: Add durable lifecycle registry with digest-bound reload

**Files:**
- Create: `runtime/orchestrator/capability_lifecycle_store.py`
- Test: `tests/test_capability_lifecycle_store.py`

**Interfaces:**
- Consumes: `CapabilityLifecycleRecordV1`.
- Produces: `CapabilityLifecycleStore(root)`, `put(record)`, `get(contract_id)`, `list_records()`.

- [ ] **Step 1: Write failing persistence and drift tests**

```python
import json, pytest
from tests.capability_lifecycle_fixtures import active_record
from runtime.orchestrator.capability_lifecycle_store import CapabilityLifecycleStore, CapabilityLifecycleStoreError

def test_store_round_trip_rejects_tampered_record(tmp_path):
    store = CapabilityLifecycleStore(tmp_path)
    record = active_record()
    store.put(record)
    assert store.get(record.contract.contract_id) == record
    path = tmp_path / "capability-lifecycle" / "cap_ui-design_1.json"
    payload = json.loads(path.read_text())
    payload["state"] = "RETIRED"
    path.write_text(json.dumps(payload))
    with pytest.raises(CapabilityLifecycleStoreError, match="digest"):
        store.get(record.contract.contract_id)
```

- [ ] **Step 2: Run and confirm failure**

```bash
python -m pytest tests/test_capability_lifecycle_store.py -q
```

- [ ] **Step 3: Implement atomic persistence**

```python
def _safe_contract_filename(contract_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in contract_id)
    if not safe or len(safe) > 180:
        raise CapabilityLifecycleStoreError("unsafe contract id")
    return safe + ".json"

class CapabilityLifecycleStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve() / "capability-lifecycle"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, contract_id: str) -> Path:
        return self.root / _safe_contract_filename(contract_id)

    def put(self, record: CapabilityLifecycleRecordV1) -> Path:
        path = self._path(record.contract.contract_id)
        atomic_write_json(path, record.to_dict())
        return path
```

Use the existing durable atomic JSON helper and validate schema/digest on every `get()`.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_capability_lifecycle_store.py -q
```

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/capability_lifecycle_store.py tests/test_capability_lifecycle_store.py
git commit -m "feat: persist capability lifecycle records"
```

### Task 3: Add dependency lease accounting and drain semantics

**Files:**
- Modify: `runtime/orchestrator/capability_lifecycle.py`
- Modify: `runtime/orchestrator/capability_lifecycle_store.py`
- Test: `tests/test_capability_lifecycle_drain.py`

**Interfaces:**
- Consumes: task execution ID + capability contract reference.
- Produces: `acquire_dependency(contract_id, task_execution_id)`, `release_dependency(contract_id, task_execution_id)`, `begin_drain(contract_id, evidence_ref)`.

- [ ] **Step 1: Write failing drain tests**

```python
import pytest
from tests.capability_lifecycle_fixtures import active_record
from runtime.orchestrator.capability_lifecycle_store import CapabilityLifecycleStore, CapabilityLifecycleStoreError

def test_disable_new_assignment_blocks_new_lease_but_preserves_existing(tmp_path):
    store = CapabilityLifecycleStore(tmp_path)
    store.put(active_record())
    store.acquire_dependency("cap:ui-design:1", "TASKEXEC-1")
    drained = store.begin_drain("cap:ui-design:1", evidence_ref="evidence:drain")
    assert drained.state == "DRAINING"
    with pytest.raises(CapabilityLifecycleStoreError, match="new assignment disabled"):
        store.acquire_dependency("cap:ui-design:1", "TASKEXEC-2")
    store.release_dependency("cap:ui-design:1", "TASKEXEC-1")
    assert store.get("cap:ui-design:1").active_dependency_count == 0
```

- [ ] **Step 2: Run and verify failure**

```bash
python -m pytest tests/test_capability_lifecycle_drain.py -q
```

- [ ] **Step 3: Implement dependency lease updates against the record's sealed ID set**

```python
def acquire_dependency(self, contract_id: str, task_execution_id: str) -> CapabilityLifecycleRecordV1:
    record = self.get(contract_id)
    if record.state in {"DISABLE_NEW_ASSIGNMENT", "DRAINING", "SUPERSEDED", "DEPRECATED", "RETIRED"}:
        raise CapabilityLifecycleStoreError("new assignment disabled")
    ids = tuple(sorted(set(record.active_dependency_ids) | {task_execution_id}))
    updated = record.with_dependencies(ids)
    self.put(updated)
    return updated

def release_dependency(self, contract_id: str, task_execution_id: str) -> CapabilityLifecycleRecordV1:
    record = self.get(contract_id)
    ids = tuple(item for item in record.active_dependency_ids if item != task_execution_id)
    updated = record.with_dependencies(ids)
    self.put(updated)
    return updated
```

`begin_drain()` validates `ACTIVE/DEGRADED/QUARANTINED -> DISABLE_NEW_ASSIGNMENT -> DRAINING`, preserves existing dependency IDs, blocks new lease acquisition, and writes one new digest-bound revision.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_capability_lifecycle_drain.py -q
```

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/capability_lifecycle.py runtime/orchestrator/capability_lifecycle_store.py tests/test_capability_lifecycle_drain.py
git commit -m "feat: drain capability dependencies before retirement"
```


### Task 4: Qualify MCP/Adapter endpoint contracts without local code absorption

**Files:**
- Create: `runtime/orchestrator/external_capability_binding.py`
- Test: `tests/test_external_capability_binding.py`

**Interfaces:**
- Consumes: existing discovery/evaluation evidence, requested capability set, risk/permission facts, and an MCP/Adapter endpoint reference.
- Produces: `ExternalCapabilityBindingV1`, `qualify_external_binding(...)`, and a stable `external-capability:sha256:<digest>` identifier eligible for lifecycle registration; no final assignment.

- [ ] **Step 1: Write failing MCP-first and surface-reduction tests**

```python
def test_mcp_binding_does_not_require_install_or_copy(candidate_evaluation):
    binding = qualify_external_binding(
        evaluation=candidate_evaluation,
        binding_kind="MCP_ENDPOINT",
        endpoint_ref="mcp:design-agent",
        requested_capabilities=("ui_design", "filesystem_write"),
        allowed_capabilities=("ui_design",),
        blocked_capabilities=("filesystem_write",),
        effect_policy="GATEWAY_REQUIRED",
    )
    assert binding.binding_kind == "MCP_ENDPOINT"
    assert binding.allowed_capabilities == ("ui_design",)
    assert binding.blocked_capabilities == ("filesystem_write",)
    assert binding.stable_asset_identifier.startswith("external-capability:sha256:")
    assert not hasattr(binding, "install_path")


def test_binding_never_selects_assignee_provider_or_model(candidate_evaluation):
    payload = qualify_external_binding(
        evaluation=candidate_evaluation,
        binding_kind="ADAPTER", endpoint_ref="adapter:design-review",
        requested_capabilities=("ui_design",), allowed_capabilities=("ui_design",),
        blocked_capabilities=(), effect_policy="READ_ONLY",
    ).to_dict()
    assert not {"final_assignee", "provider", "model"}.intersection(payload)
```

- [ ] **Step 2: Run and confirm missing binding module**

```bash
python -m pytest tests/test_external_capability_binding.py -q
```

- [ ] **Step 3: Implement the contract-only endpoint binding**

```python
BINDING_KINDS = frozenset({"MCP_ENDPOINT", "ADAPTER", "LOCAL_SKILL"})
EFFECT_POLICIES = frozenset({"READ_ONLY", "GATEWAY_REQUIRED"})

@dataclass(frozen=True, slots=True)
class ExternalCapabilityBindingV1:
    binding_kind: str
    endpoint_ref: str
    stable_asset_identifier: str
    allowed_capabilities: tuple[str, ...]
    blocked_capabilities: tuple[str, ...]
    permission_scope: tuple[str, ...]
    effect_policy: str
    evaluation_evidence_ref: str
    binding_digest: str
```

For `MCP_ENDPOINT`/`ADAPTER`, `qualify_external_binding()` must never invoke installer code, copy repository content, or import the external Agent runtime. It seals only identity, safe capability surface, permissions, effect policy, and evidence. `LOCAL_SKILL` is accepted only when the existing install/use-authorization evidence is supplied.

- [ ] **Step 4: Run tests and source guard**

```bash
python -m pytest tests/test_external_capability_binding.py -q
python - <<'PY2'
from pathlib import Path
text=Path('runtime/orchestrator/external_capability_binding.py').read_text().lower()
for forbidden in ('skill_installer', 'shutil.copy', 'subprocess', 'final_assignee', 'provider_ref', 'model_ref'):
    assert forbidden not in text
PY2
```

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/external_capability_binding.py tests/test_external_capability_binding.py
git commit -m "feat: bind external capabilities through mcp adapters"
```

### Task 5: Bind capability lineage to runtime selection without changing final assignment

**Files:**
- Modify: `runtime/orchestrator/operational_capability.py`
- Test: `tests/test_operational_capability.py`
- Test: `tests/test_capability_lifecycle_lineage.py`

**Interfaces:**
- Consumes: `CapabilityContractRefV1` selected for an already authorized stable asset.
- Produces: optional lineage fields on `RuntimeSelection`; ledger projection field `capability_contract_lineage`.

- [ ] **Step 1: Write a backward-compatible lineage test**

```python
def test_runtime_selection_can_carry_contract_lineage_without_assignment_authority():
    selection = RuntimeSelection(
        asset_id="installed-skill:sha256:" + "a" * 64,
        skill_id="ui-design",
        installed_target=".agents/skills/ui-design",
        artifact_digest="b" * 64,
        attestation_evidence_reference="sha256:" + "c" * 64,
        use_authorization_evidence_reference="sha256:" + "d" * 64,
        capability_requirement="ui_design",
        project_id="P1",
        gate_id="G1",
        lv_id="LV1",
        canonical_plan_sha256="e" * 64,
        source="project-installed",
        capability_contract_id="cap:ui-design:1",
        capability_contract_version="1.0.0",
        endpoint_version="rev-001",
        activation_epoch=1,
    )
    payload = dataclasses.asdict(selection)
    assert "final_assignee" not in payload
    assert payload["capability_contract_id"] == "cap:ui-design:1"
```

- [ ] **Step 2: Run existing + new tests before implementation**

```bash
python -m pytest tests/test_capability_lifecycle_lineage.py tests/test_operational_capability.py -q
```

Expected: new test fails because lineage parameters are not accepted; existing tests remain green.

- [ ] **Step 3: Append optional fields with defaults to `RuntimeSelection`**

```python
capability_contract_id: str = ""
capability_contract_version: str = ""
endpoint_version: str = ""
activation_epoch: int = 0
```

Extend `OperationalCapabilityResult.ledger_projection()` with a `capability_contract_lineage` object only when `capability_contract_id` is present. Do not add `final_assignee` or provider/model fields.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_capability_lifecycle_lineage.py tests/test_operational_capability.py -q
```

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/operational_capability.py tests/test_operational_capability.py tests/test_capability_lifecycle_lineage.py
git commit -m "feat: bind capability contract lineage to runtime selection"
```

### Task 6: Enforce external invocation effect policy

**Files:**
- Create: `runtime/orchestrator/external_capability_policy.py`
- Test: `tests/test_external_capability_policy.py`

**Interfaces:**
- Consumes: execution authority (`READ_ONLY`/`STATE_CHANGING`), lifecycle state, approved capability scope.
- Produces: `ExternalCapabilityInvocationDecisionV1` with disposition `DIRECT_READ_ALLOWED`, `GATEWAY_REQUIRED`, or `BLOCKED`.

- [ ] **Step 1: Write failing authority tests**

```python
def test_state_change_never_returns_direct_executor():
    decision = decide_external_capability_invocation(
        execution_authority="STATE_CHANGING",
        lifecycle_state="ACTIVE",
        capability_id="publish_content",
        approved_capabilities=("publish_content",),
    )
    assert decision.disposition == "GATEWAY_REQUIRED"
    assert not hasattr(decision, "execute")
    assert "full_mcp" not in decision.to_dict()


def test_read_only_active_capability_is_direct_read_allowed():
    decision = decide_external_capability_invocation(
        execution_authority="READ_ONLY",
        lifecycle_state="ACTIVE",
        capability_id="ui_design_review",
        approved_capabilities=("ui_design_review",),
    )
    assert decision.disposition == "DIRECT_READ_ALLOWED"
```

- [ ] **Step 2: Run and confirm failure**

```bash
python -m pytest tests/test_external_capability_policy.py -q
```

- [ ] **Step 3: Implement policy-only decision object**

```python
@dataclass(frozen=True, slots=True)
class ExternalCapabilityInvocationDecisionV1:
    disposition: str
    capability_id: str
    required_effect_boundary: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)
```

State-changing decisions set `required_effect_boundary="PRODUCTION_EXECUTION_GATEWAY"`; this module contains no transport/executor implementation.

- [ ] **Step 4: Run policy + existing authority tests**

```bash
python -m pytest tests/test_external_capability_policy.py tests/test_ai_office_capability_governance.py tests/test_ai_office_authority_negative_space.py -q
```

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/external_capability_policy.py tests/test_external_capability_policy.py
git commit -m "feat: enforce external capability effect boundary"
```

### Task 7: Add lifecycle operations projection for Dashboard/Advanced consumers

**Files:**
- Modify: `runtime/orchestrator/capability_lifecycle.py`
- Create: `runtime/orchestrator/capability_lifecycle_projection.py`
- Test: `tests/test_capability_lifecycle_projection.py \
  tests/test_external_capability_binding.py \
  tests/test_capability_watch.py`

**Interfaces:**
- Consumes: lifecycle store records.
- Produces: bounded `CapabilityLifecycleProjectionV1` with identity, state, health, dependency count, version, replacement relation, evidence refs.

- [ ] **Step 1: Write failing projection secrecy test**

```python
def test_lifecycle_projection_contains_no_assignment_or_credentials():
    projection = project_capability_lifecycle(active_record())
    payload = projection.to_dict()
    assert payload["state"] == "ACTIVE"
    for field in ("final_assignee", "provider", "model", "credential", "token"):
        assert field not in repr(payload).lower()
```

- [ ] **Step 2: Run and verify failure**

```bash
python -m pytest tests/test_capability_lifecycle_projection.py \
  tests/test_external_capability_binding.py \
  tests/test_capability_watch.py -q
```

- [ ] **Step 3: Implement closed projection**

```python
@dataclass(frozen=True, slots=True)
class CapabilityLifecycleProjectionV1:
    contract_id: str
    contract_version: str
    endpoint_version: str
    activation_epoch: int
    state: str
    health: str
    active_dependency_count: int
    replacement_contract_id: str
    evidence_refs: tuple[str, ...]
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_capability_lifecycle_projection.py \
  tests/test_external_capability_binding.py \
  tests/test_capability_watch.py -q
```

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/capability_lifecycle.py runtime/orchestrator/capability_lifecycle_projection.py tests/test_capability_lifecycle_projection.py \
  tests/test_external_capability_binding.py \
  tests/test_capability_watch.py
git commit -m "feat: expose bounded capability lifecycle projection"
```


### Task 8: Add lightweight capability watch and reassessment recommendations

**Files:**
- Create: `runtime/orchestrator/capability_watch.py`
- Test: `tests/test_capability_watch.py`

**Interfaces:**
- Consumes: lifecycle records, bounded health/usage/version/overlap facts, capability gaps, last scan time, and caller-supplied scan interval.
- Produces: `CapabilityWatchDecisionV1` recommendations only; no install/activate/rebind/retire mutation.

- [ ] **Step 1: Write failing due/not-due and non-mutating recommendation tests**

```python
def test_watch_is_not_a_resident_or_every_call_network_scanner(active_record, now):
    decision = evaluate_capability_watch(
        records=(active_record,), capability_gaps=(), metrics=(),
        last_scan_at=now, now=now, scan_interval_seconds=86400,
    )
    assert decision.scan_due is False
    assert decision.actions == ("NO_ACTION",)


def test_degraded_overlap_only_recommends_replacement_review(active_record, now):
    decision = evaluate_capability_watch(
        records=(active_record,), capability_gaps=(),
        metrics=({"contract_id": active_record.contract.contract_id, "health": "DEGRADED", "overlap_candidate_ref": "candidate:2"},),
        last_scan_at="2026-09-22T00:00:00+00:00", now=now, scan_interval_seconds=86400,
    )
    assert "REPLACEMENT_REVIEW" in decision.actions
    assert active_record.state == "ACTIVE"
```

- [ ] **Step 2: Run and confirm missing watch module**

```bash
python -m pytest tests/test_capability_watch.py -q
```

- [ ] **Step 3: Implement a one-shot policy evaluator**

```python
WATCH_ACTIONS = frozenset({"NO_ACTION", "SEARCH", "REASSESS", "REPLACEMENT_REVIEW", "RETIREMENT_REVIEW"})

@dataclass(frozen=True, slots=True)
class CapabilityWatchDecisionV1:
    scan_due: bool
    actions: tuple[str, ...]
    capability_refs: tuple[str, ...]
    rationale_refs: tuple[str, ...]
    next_eligible_scan_at: str
```

The evaluator has no loop/thread/service of its own. When a configured scheduler invokes it and `scan_due=True`, the caller may run the existing read-only discovery/evaluation pipeline. Results become review candidates only. Any install, activation, replacement, drain, or retirement still uses the lifecycle/governance functions from earlier tasks.

- [ ] **Step 4: Run tests and source guard**

```bash
python -m pytest tests/test_capability_watch.py tests/test_capability_lifecycle_drain.py -q
python - <<'PY2'
from pathlib import Path
text=Path('runtime/orchestrator/capability_watch.py').read_text().lower()
for forbidden in ('while true', 'threading', 'subprocess', 'install(', 'retire('):
    assert forbidden not in text
PY2
```

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/capability_watch.py tests/test_capability_watch.py
git commit -m "feat: add lightweight external capability reassessment watch"
```

### Task 9: Track B qualification

**Files:**
- Create during execution: `docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/CAPABILITY_LIFECYCLE_QUALIFICATION.json`

**Interfaces:**
- Consumes: Tasks 1-8.
- Produces: `CAPABILITY_LIFECYCLE_TRACK=PASS` evidence.

- [ ] **Step 1: Run new lifecycle suites**

```bash
python -m pytest \
  tests/test_capability_lifecycle.py \
  tests/test_capability_lifecycle_store.py \
  tests/test_capability_lifecycle_drain.py \
  tests/test_capability_lifecycle_lineage.py \
  tests/test_external_capability_policy.py \
  tests/test_capability_lifecycle_projection.py \
  tests/test_external_capability_binding.py \
  tests/test_capability_watch.py -q
```

- [ ] **Step 2: Run existing capability pipeline regressions**

```bash
python -m pytest \
  tests/test_capability_inventory.py \
  tests/test_skill_discovery.py \
  tests/test_skill_candidate_evaluator.py \
  tests/test_skill_adoption.py \
  tests/test_skill_installer.py \
  tests/test_skill_use_authorization.py \
  tests/test_operational_capability.py \
  tests/test_ai_office_capability_governance.py \
  tests/test_ai_office_authority_negative_space.py -q
```

- [ ] **Step 3: Record no-authority-drift evidence**

```json
{
  "schema_version": "gch.capability-lifecycle-qualification.v1",
  "track": "B",
  "status": "PASS",
  "final_assignment_authority": "FULL_PLAN",
  "state_change_boundary": "PRODUCTION_EXECUTION_GATEWAY_FULL_MCP",
  "parallel_registry_created": false
}
```

- [ ] **Step 4: Commit qualification evidence**

```bash
git add docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/CAPABILITY_LIFECYCLE_QUALIFICATION.json
git commit -m "test: qualify external capability lifecycle"
```
