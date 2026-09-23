# AI Office Operations Read Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one bounded, non-authoritative operations read model that normalizes existing Operator Console, AI Office, recovery, self-diagnosis, and source-identity facts for List/3D/Advanced consumers without exposing secrets or creating control authority.

**Architecture:** Reuse `OperatorConsoleProjectionV1`, `OfficeReportV1`, public observability references, and current recovery evidence. New code only normalizes closed projections, resolves incident freshness, and emits diagnostic projections; it never reads credentials, assigns agents, selects providers, or performs effects.

**Tech Stack:** Python 3.12 dataclasses, existing canonical digest helpers, unittest.

**Spec:** `docs/superpowers/specs/2026-09-24-ai-office-harness-topdown-edp-reconciled-design.md`

## Global Constraints

- Schema name is `orchestration.operations-read-model.v1`.
- Only bounded existing projections/canonical evidence refs are inputs.
- Unknown lower-layer fields are ignored, not copied through.
- No `provider`, `model`, credential, token, authorization payload, or raw effect payload appears in the public contract.
- `GPT_OPERATOR` remains the only canonical operator authority label.
- OCP/Harness source SHAs may differ without being classified as an incident by SHA alone.
- Stale/historical evidence cannot create a current incident.
- Orphan-process diagnosis is read-only and cannot kill or clean processes.
- Existing `runtime/diagnostics/*`, attention, stall, recovery, and runtime-health evidence are reused; do not create a second diagnosis engine.
- Self-Diagnosis projection is read-only and cannot restart services, mutate Gate state, or perform recovery effects.

## Review Focus

1. Unexpected secret/provider fields in an input mapping are absent from serialized output.
2. Historical `STALL_CONFIRMED` evidence with a newer healthy canonical state resolves to `HISTORICAL`, not `OPEN`.
3. Different Harness/OCP source heads remain valid when both sources are fresh and contract-compatible.
4. Missing/old source timestamps produce `STALE`/`UNKNOWN` instead of carrying forward a healthy state.
5. Orphan diagnostics can recommend cleanup but expose no callable mutation method.

---

### Task 1: Define source identity and closed operations read-model contracts

**Files:**
- Create: `runtime/orchestrator/operations_read_model.py`
- Test: `tests/test_operations_read_model.py`

**Interfaces:**
- Consumes: `OperatorConsoleProjectionV1`, `OfficeReportV1`, source identity mappings.
- Produces: `SourceIdentityV1`, `OperationsReadModelV1`, `build_operations_read_model(console, office_report, source_identities, now)`, `build_operations_read_model_from_console_snapshot(console, snapshot, source_identities=())`.

- [ ] **Step 1: Write failing contract tests**

```python
from datetime import datetime, timezone
from runtime.ai_office.reporting import (
    OFFICE_KPI_SCHEMA_V1, OFFICE_REPORT_SCHEMA_V1, OFFICE_STATUS_SCHEMA_V1,
    OfficeKPIProjectionV1, OfficeReportV1, OfficeStatusProjectionV1,
)
from runtime.orchestrator.operator_console_projection import OperatorConsoleProjectionV1
from runtime.orchestrator.operations_read_model import (
    OPERATIONS_READ_MODEL_SCHEMA_V1, SourceIdentityV1, build_operations_read_model,
)


def make_console() -> OperatorConsoleProjectionV1:
    return OperatorConsoleProjectionV1(
        project_id="P1", run_id="R1", task_id="T1", gate_id="G1", stage="RUNNING",
        execution_readiness="READY", operator_authority_label="GPT_OPERATOR",
        transport_state="OBSERVE_ONLY", checkpoint_refs=("checkpoint:R1",),
        evidence_refs=("evidence:E1",), migration_phase="", migration_transaction_sha256="",
        status_flags=(),
    )


def make_office_report() -> OfficeReportV1:
    status = OfficeStatusProjectionV1(OFFICE_STATUS_SCHEMA_V1, "P1", "R1", "RUNNING", 3, "", "")
    kpi = OfficeKPIProjectionV1(OFFICE_KPI_SCHEMA_V1, 1, 0, False, False)
    return OfficeReportV1(OFFICE_REPORT_SCHEMA_V1, status, kpi, "", "", "", ("observation:E1",), ())


def test_operations_read_model_is_closed_and_source_tagged():
    model = build_operations_read_model(
        make_console(), make_office_report(),
        source_identities=(
            SourceIdentityV1("HARNESS", "c591b01", "c591b01", "2026-09-24T00:00:00+00:00"),
            SourceIdentityV1("OCP", "996a8d1", "996a8d1", "2026-09-24T00:00:01+00:00"),
        ),
        now=datetime(2026, 9, 24, 0, 0, 5, tzinfo=timezone.utc),
    )
    payload = model.to_dict()
    assert payload["schema_version"] == OPERATIONS_READ_MODEL_SCHEMA_V1
    assert {row["source_component"] for row in payload["sources"]} == {"HARNESS", "OCP"}
    serialized = repr(payload).lower()
    for forbidden in ("credential", "token", "raw_effect_payload", "final_assignee"):
        assert forbidden not in serialized
```

- [ ] **Step 2: Run the test and confirm the module is absent**

```bash
python -m unittest tests.test_operations_read_model -v
```

Expected: import failure for `runtime.orchestrator.operations_read_model`.

- [ ] **Step 3: Implement the minimal immutable contracts**

```python
OPERATIONS_READ_MODEL_SCHEMA_V1 = "orchestration.operations-read-model.v1"

@dataclass(frozen=True, slots=True)
class SourceIdentityV1:
    source_component: str
    source_version: str
    source_head: str
    source_timestamp: str

@dataclass(frozen=True, slots=True)
class OperationsReadModelV1:
    schema_version: str
    project_id: str
    run_id: str
    task_id: str
    gate_id: str
    raw_state: str
    normalized_state: str
    human_state: str
    progress: int | None
    progress_source: str
    current_work: str
    outcome: str
    impact: str
    next_step: str
    approval_required: bool
    approval_refs: tuple[str, ...]
    checkpoint_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    sources: tuple[SourceIdentityV1, ...]
    freshness: str

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["approval_refs"] = list(self.approval_refs)
        value["checkpoint_refs"] = list(self.checkpoint_refs)
        value["evidence_refs"] = list(self.evidence_refs)
        value["sources"] = [asdict(item) for item in self.sources]
        return value
```

`build_operations_read_model()` must copy only explicitly named fields from the two bounded projections; never merge arbitrary mappings. Add a second bounded adapter for the legacy bridge snapshot shape:

```python
def build_operations_read_model_from_console_snapshot(
    console: OperatorConsoleProjectionV1,
    snapshot: Mapping[str, Any],
    *,
    source_identities: tuple[SourceIdentityV1, ...] = (),
) -> OperationsReadModelV1:
    sources = source_identities or (SourceIdentityV1(
        "PROJECT_ORCHESTRATOR", "UNKNOWN", "UNKNOWN", str(snapshot.get("last_updated") or "UNKNOWN")
    ),)
    normalized, human = normalize_operations_state(str(snapshot.get("current_phase") or console.stage))
    return OperationsReadModelV1(
        schema_version=OPERATIONS_READ_MODEL_SCHEMA_V1, project_id=console.project_id, run_id=console.run_id,
        task_id=console.task_id, gate_id=console.gate_id, raw_state=str(snapshot.get("current_phase") or console.stage),
        normalized_state=normalized, human_state=human, progress=None, progress_source="",
        current_work=str(snapshot.get("next_step") or ""), outcome="", impact="",
        next_step=str(snapshot.get("next_step") or ""), approval_required=bool(snapshot.get("approval_required")),
        approval_refs=tuple(), checkpoint_refs=console.checkpoint_refs, evidence_refs=console.evidence_refs,
        sources=sources, freshness="UNKNOWN",
    )
```

Task 2 replaces the provisional `freshness="UNKNOWN"` with `resolve_freshness()` and the closed state map; no percentage is inferred from legacy data.

- [ ] **Step 4: Run the contract test**

```bash
python -m unittest tests.test_operations_read_model -v
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/operations_read_model.py tests/test_operations_read_model.py
git commit -m "feat: add canonical operations read model"
```

### Task 2: Add deterministic state, progress, and freshness normalization

**Files:**
- Modify: `runtime/orchestrator/operations_read_model.py`
- Test: `tests/test_operations_read_model.py`

**Interfaces:**
- Consumes: bounded workflow/stage/readiness values and source timestamps.
- Produces: `normalize_operations_state(raw_state) -> tuple[str, str]`, `resolve_freshness(sources, now, stale_after_seconds=300) -> str`.

- [ ] **Step 1: Add failing normalization tests**

```python
def test_state_normalization_and_progress_do_not_invent_percent():
    normalized, human = normalize_operations_state("WAITING_APPROVAL")
    assert normalized == "WAITING_APPROVAL"
    assert human == "사용자 승인 대기"
    assert normalize_progress(None, "") == (None, "")


def test_old_source_is_stale():
    source = SourceIdentityV1("HARNESS", "v1", "a" * 40, "2026-09-23T23:00:00+00:00")
    assert resolve_freshness((source,), datetime(2026, 9, 24, 0, 0, tzinfo=timezone.utc), 300) == "STALE"
```

- [ ] **Step 2: Run tests and observe the missing functions**

```bash
python -m unittest tests.test_operations_read_model -v
```

Expected: failure naming `normalize_operations_state`, `normalize_progress`, or `resolve_freshness`.

- [ ] **Step 3: Implement a closed translation table and explicit progress sources**

```python
_STATE_MAP = {
    "QUEUED": ("QUEUED", "대기"),
    "PLANNING": ("PLANNING", "계획 작성 중"),
    "RUNNING": ("RUNNING", "작업 중"),
    "WAITING_DEPENDENCY": ("WAITING_DEPENDENCY", "다른 업무 결과 대기"),
    "WAITING_APPROVAL": ("WAITING_APPROVAL", "사용자 승인 대기"),
    "PAUSED": ("PAUSED", "일시 중지"),
    "STALLED": ("STALLED", "진행 정지"),
    "RECOVERING": ("RECOVERING", "자동 복구 중"),
    "FAILED": ("FAILED", "문제 발생"),
    "COMPLETED": ("COMPLETED", "완료"),
}

def normalize_operations_state(raw_state: str) -> tuple[str, str]:
    return _STATE_MAP.get(raw_state.upper(), ("UNKNOWN", "상태 확인 필요"))

def normalize_progress(value: int | None, source: str) -> tuple[int | None, str]:
    if value is None:
        return None, ""
    if not 0 <= value <= 100 or not source:
        raise OperationsReadModelError("progress requires bounded value and evidence source")
    return value, source
```

Implement `resolve_freshness` using parsed timezone-aware timestamps; invalid/missing timestamps resolve to `UNKNOWN`, not healthy.

- [ ] **Step 4: Run tests**

```bash
python -m unittest tests.test_operations_read_model -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/operations_read_model.py tests/test_operations_read_model.py
git commit -m "feat: normalize operations state and freshness"
```

### Task 3: Add incident lifecycle projection that separates current from historical evidence

**Files:**
- Create: `runtime/orchestrator/incident_projection.py`
- Test: `tests/test_incident_projection.py`

**Interfaces:**
- Consumes: current normalized state, current-state reference, timestamped incident evidence rows.
- Produces: `IncidentProjectionV1`, `project_incidents(current_state, current_state_ref, evidence_rows, now)`.

- [ ] **Step 1: Write failing current-vs-historical tests**

```python
def test_resolved_old_stall_is_historical():
    rows = ({
        "incident_id": "STALL-R1",
        "kind": "STALL_CONFIRMED",
        "opened_at": "2026-09-23T10:00:00+00:00",
        "last_observed_at": "2026-09-23T10:05:00+00:00",
        "evidence_ref": "evidence:stall-r1",
    },)
    incidents = project_incidents(
        current_state="RUNNING",
        current_state_ref="run:R1:healthy-generation-9",
        evidence_rows=rows,
        now=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )
    assert incidents[0].state == "HISTORICAL"
    assert incidents[0].user_action_required is False
```

- [ ] **Step 2: Run and verify failure**

```bash
python -m unittest tests.test_incident_projection -v
```

Expected: import failure for `incident_projection`.

- [ ] **Step 3: Implement closed lifecycle values**

```python
INCIDENT_STATES = frozenset({
    "OPEN", "ACKNOWLEDGED", "RECOVERING", "RESOLVED", "SUPERSEDED", "HISTORICAL"
})

@dataclass(frozen=True, slots=True)
class IncidentProjectionV1:
    incident_id: str
    kind: str
    opened_at: str
    last_observed_at: str
    resolved_at: str
    state: str
    current_state_ref: str
    superseded_by: str
    impact: str
    user_action_required: bool
    evidence_refs: tuple[str, ...]
```

Rule: old incident evidence cannot remain `OPEN` unless current canonical state still indicates `STALLED`, `FAILED`, or an explicit unresolved incident reference.

- [ ] **Step 4: Run tests**

```bash
python -m unittest tests.test_incident_projection -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/incident_projection.py tests/test_incident_projection.py
git commit -m "feat: project incident lifecycle and history"
```

### Task 4: Add read-only orphan-process diagnostic projection

**Files:**
- Create: `runtime/diagnostics/process_lifecycle.py`
- Test: `tests/test_process_lifecycle_diagnostics.py`

**Interfaces:**
- Consumes: process metadata, owner reference, state/lock existence, last semantic progress.
- Produces: `ProcessLifecycleDiagnosticV1`, `diagnose_process_lifecycle(facts, now)`; no mutation API.

- [ ] **Step 1: Write failing diagnostic-only tests**

```python
def test_missing_owner_state_marks_orphan_suspected_without_cleanup_method():
    diagnostic = diagnose_process_lifecycle({
        "pid": 550360,
        "owner_ref": "run:DCC_LIVE_AUTO_CANARY",
        "owner_state_exists": False,
        "lock_exists": False,
        "expected_lifecycle_state": "PAUSED_TEST",
        "last_semantic_progress": "2026-09-23T00:00:00+00:00",
    }, now=datetime(2026, 9, 24, tzinfo=timezone.utc))
    assert diagnostic.status == "ORPHAN_SUSPECTED"
    assert diagnostic.cleanup_authorization_required is True
    assert not hasattr(diagnostic, "kill")
```

- [ ] **Step 2: Run and confirm failure**

```bash
python -m unittest tests.test_process_lifecycle_diagnostics -v
```

- [ ] **Step 3: Implement the immutable diagnostic object**

```python
@dataclass(frozen=True, slots=True)
class ProcessLifecycleDiagnosticV1:
    pid: int
    owner_ref: str
    owner_state_exists: bool
    lock_exists: bool
    expected_lifecycle_state: str
    last_semantic_progress: str
    status: str
    orphan_suspicion_reason: str
    recommended_action: str
    cleanup_authorization_required: bool
```

No function in this module may import `os.kill`, `signal`, process-service mutation helpers, or Full MCP effect functions.

- [ ] **Step 4: Run tests and source guard**

```bash
python -m unittest tests.test_process_lifecycle_diagnostics -v
python - <<'PY2'
from pathlib import Path
text=Path('runtime/diagnostics/process_lifecycle.py').read_text().lower()
for forbidden in ('os.kill', 'terminate(', 'kill_process', 'full_mcp'):
    assert forbidden not in text
PY2
```

- [ ] **Step 5: Commit**

```bash
git add runtime/diagnostics/process_lifecycle.py tests/test_process_lifecycle_diagnostics.py
git commit -m "feat: diagnose orphan process lifecycle safely"
```


### Task 5: Project existing Self-Diagnosis evidence into the operations model

**Files:**
- Create: `runtime/orchestrator/operations_diagnostic_projection.py`
- Modify: `runtime/orchestrator/operations_read_model.py`
- Test: `tests/test_operations_diagnostic_projection.py`

**Interfaces:**
- Consumes: bounded results/evidence from existing `runtime/diagnostics/*`, attention/stall state, recovery refs, and current canonical state.
- Produces: `DiagnosticHealthProjectionV1`, `build_diagnostic_health_projection(...)`; optional `diagnostic_health` field on `OperationsReadModelV1`.

- [ ] **Step 1: Write failing read-only health projection tests**

```python
def test_historical_attention_does_not_become_current_self_diagnosis_issue():
    result = build_diagnostic_health_projection(
        current_state={"normalized_state": "RUNNING", "freshness": "FRESH"},
        diagnostic_findings=(),
        attention_events=({"kind": "STALL_CONFIRMED", "state": "HISTORICAL", "evidence_ref": "attention:old"},),
        recovery_refs=(),
    )
    assert result.overall_state == "HEALTHY"
    assert result.current_issue_count == 0
    assert result.user_action_required is False


def test_self_diagnosis_contract_has_no_mutation_methods():
    result = build_diagnostic_health_projection(
        current_state={"normalized_state": "FAILED", "freshness": "FRESH"},
        diagnostic_findings=({"domain": "runtime_binding", "state": "BLOCKED", "evidence_ref": "diag:1"},),
        attention_events=(), recovery_refs=(),
    )
    assert result.overall_state == "BLOCKED"
    for name in ("restart", "kill", "recover", "complete_gate"):
        assert not hasattr(result, name)
```

- [ ] **Step 2: Run and confirm the projection module is missing**

```bash
python -m unittest tests.test_operations_diagnostic_projection -v
```

Expected: import failure.

- [ ] **Step 3: Implement a closed summary contract over existing evidence**

```python
@dataclass(frozen=True, slots=True)
class DiagnosticHealthProjectionV1:
    overall_state: str
    current_issue_count: int
    recovering: bool
    user_action_required: bool
    domain_states: tuple[tuple[str, str], ...]
    evidence_refs: tuple[str, ...]
    freshness: str
```

`build_diagnostic_health_projection()` accepts only named bounded fields from existing diagnostics/attention/recovery records. Allowed states are `HEALTHY`, `WARN`, `DEGRADED`, `BLOCKED`, `RECOVERING`, `UNKNOWN`, `STALE`. Historical/resolved attention evidence cannot raise the current issue count without a matching current-state finding.

Add `diagnostic_health: DiagnosticHealthProjectionV1 | None = None` as the last field of `OperationsReadModelV1`, and serialize it as a nested read-only object.

- [ ] **Step 4: Run tests and source guard**

```bash
python -m unittest tests.test_operations_diagnostic_projection tests.test_operations_read_model -v
python - <<'PY2'
from pathlib import Path
text=Path('runtime/orchestrator/operations_diagnostic_projection.py').read_text().lower()
for forbidden in ('subprocess', 'os.kill', 'systemctl', 'full_mcp', 'complete_gate'):
    assert forbidden not in text
PY2
```

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/operations_diagnostic_projection.py runtime/orchestrator/operations_read_model.py tests/test_operations_diagnostic_projection.py
git commit -m "feat: project existing self diagnosis for operations UI"
```

### Task 6: Add a projection-only JARVIS bridge read path and operations snapshot

**Files:**
- Modify: `runtime/jarvis_bridge/state_reader.py`
- Modify: `runtime/jarvis_bridge/bridge_api.py`
- Modify: `runtime/jarvis_bridge/__init__.py`
- Test: `tests/test_jarvis_bridge_operations_projection.py`

**Interfaces:**
- Consumes: existing orchestration files through the same derivation logic as `read_dashboard_state`, but without persistence/audit writes.
- Produces: `read_dashboard_state_projection_only(project_root, run_id=None)`, `refresh_operations_projection(project_root, run_id=None)`.

- [ ] **Step 1: Write failing no-write bridge tests**

```python
from pathlib import Path
from runtime.jarvis_bridge.bridge_api import refresh_operations_projection
from runtime.jarvis_bridge.state_reader import read_dashboard_state_projection_only


def test_projection_only_reader_does_not_create_bridge_or_queue_files(tmp_path):
    project = build_minimal_orchestrator_fixture(tmp_path)
    before = {p.relative_to(project).as_posix() for p in project.rglob('*') if p.is_file()}
    snapshot = read_dashboard_state_projection_only(project)
    after = {p.relative_to(project).as_posix() for p in project.rglob('*') if p.is_file()}
    assert snapshot["project_root"] == str(project.resolve())
    assert after == before


def test_bridge_exports_closed_operations_projection(tmp_path):
    project = build_minimal_orchestrator_fixture(tmp_path)
    payload = refresh_operations_projection(project)
    assert payload["schema_version"] == "orchestration.operations-read-model.v1"
    serialized = repr(payload).lower()
    for forbidden in ("credential", "token", "raw_effect_payload", "final_assignee"):
        assert forbidden not in serialized
```

At the top of the test file define `build_minimal_orchestrator_fixture(tmp_path)` by using the same `StateStore` fixture construction pattern already used in `tests/test_jarvis_bridge.py` or the nearest existing state-store test; the helper must create only the minimum state/run manifest files and must not mock `read_dashboard_state_projection_only` itself.

- [ ] **Step 2: Run and confirm the projection-only API is missing**

```bash
python -m unittest tests.test_jarvis_bridge_operations_projection -v
```

- [ ] **Step 3: Refactor state assembly so existing behavior stays compatible and new reads stay side-effect free**

```python
def _assemble_dashboard_state(project_root: Path, run_id: str | None = None) -> tuple[dict[str, Any], Path, list[Any], list[Any]]:
    state_store = StateStore(project_root)
    state = state_store.state
    run_root = _latest_run_root(project_root, state_store, run_id)
    run_manifest = _read_json(run_root / "run_manifest.json") or {}
    fanout_plan = _read_json(run_root / "fanout_plan.json") or []
    tasks = [item for item in state.active_threads] or list(fanout_plan)
    queue = []
    if tasks:
        task_slices = [TaskSlice(**item) if isinstance(item, dict) else item for item in tasks]
        queue = build_task_queue(state, task_slices, project_root=str(project_root))
    approval_inbox = build_approval_inbox(state, queue)
    snapshot = _build_snapshot_mapping(project_root, run_root, run_manifest, fanout_plan, state, queue, approval_inbox)
    return snapshot, run_root, queue, approval_inbox


def read_dashboard_state_projection_only(project_root: str | Path, run_id: str | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    snapshot, _, _, _ = _assemble_dashboard_state(root, run_id)
    return snapshot
```

Move the existing mapping construction into `_build_snapshot_mapping(...)`. Keep `read_dashboard_state(...)` behavior by calling `_assemble_dashboard_state(...)` and then performing the existing `write_approval_inbox`, `write_task_queue`, dashboard snapshot writes, and audit appends. The new projection-only reader performs none of those writes.

- [ ] **Step 4: Build the new operations projection only from explicitly selected snapshot fields**

```python
def refresh_operations_projection(project_root: str | Path, run_id: str | None = None) -> dict[str, object]:
    snapshot = read_dashboard_state_projection_only(project_root, run_id=run_id)
    console = build_operator_console_projection(
        {
            "project_id": str(snapshot.get("project_name") or "UNKNOWN_PROJECT"),
            "run_id": str(snapshot.get("run_id") or "UNKNOWN_RUN"),
            "task_id": "",
            "gate_id": str((snapshot.get("stage_gate_result") or {}).get("gate_id") or "UNKNOWN_GATE"),
            "stage": str(snapshot.get("current_phase") or "UNKNOWN"),
            "execution_readiness": "READY" if not snapshot.get("approval_required") else "WAITING_APPROVAL",
            "operator_authority_label": "GPT_OPERATOR",
            "checkpoint_refs": tuple(),
            "evidence_refs": tuple(),
        },
        transport_state="OBSERVE_ONLY",
        status_flags=tuple(),
    )
    return build_operations_read_model_from_console_snapshot(console, snapshot).to_dict()
```

`build_operations_read_model_from_console_snapshot()` is defined in `operations_read_model.py` in Task 1 as the bounded adapter for this source shape; it reads only named human-status/progress/source fields and ignores all other snapshot keys.

- [ ] **Step 5: Run bridge + compatibility + authority regressions, then commit**

```bash
python -m unittest \
  tests.test_jarvis_bridge_operations_projection \
  tests.test_operator_console_projection \
  tests.test_ai_office_authority_negative_space -v
git add runtime/jarvis_bridge/state_reader.py runtime/jarvis_bridge/bridge_api.py runtime/jarvis_bridge/__init__.py runtime/orchestrator/operations_read_model.py tests/test_jarvis_bridge_operations_projection.py
git commit -m "feat: expose side-effect-free operations projection"
```

### Task 7: Track A qualification

**Files:**
- Create during execution: `docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/OPERATIONS_READ_MODEL_QUALIFICATION.json`
- Test: all Track A tests plus existing authority regressions.

**Interfaces:**
- Consumes: Tasks 1-6.
- Produces: `OPERATIONS_READ_MODEL_TRACK=PASS` evidence.

- [ ] **Step 1: Run Track A suite**

```bash
python -m unittest \
  tests.test_operations_read_model \
  tests.test_incident_projection \
  tests.test_process_lifecycle_diagnostics \
  tests.test_jarvis_bridge_operations_projection \
  tests.test_operator_console_projection \
  tests.test_ai_office_reporting \
  tests.test_ai_office_authority_negative_space -v
```

- [ ] **Step 2: Require zero failures/errors before qualification**

```bash
python -m unittest \
  tests.test_operations_read_model \
  tests.test_incident_projection \
  tests.test_process_lifecycle_diagnostics \
  tests.test_jarvis_bridge_operations_projection -q
test $? -eq 0
```

- [ ] **Step 3: Record schema and test evidence**

```json
{
  "schema_version": "gch.operations-read-model-qualification.v1",
  "track": "A",
  "status": "PASS",
  "public_schema": "orchestration.operations-read-model.v1",
  "authority_change": false
}
```

- [ ] **Step 4: Commit qualification evidence**

```bash
git add docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/OPERATIONS_READ_MODEL_QUALIFICATION.json
git commit -m "test: qualify operations read model"
```
