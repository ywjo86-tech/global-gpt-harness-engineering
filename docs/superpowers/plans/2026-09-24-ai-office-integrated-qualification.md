# AI Office Harness Integrated Qualification Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that Operations Read Model, External Capability Lifecycle, Reporting & Records, and List Operations Dashboard integrate without authority drift, stale-state misrepresentation, duplicate side effects, or regression of the declared AI Office Harness stable baseline.

**Architecture:** Qualification is evidence-first and non-activating. Each track must already have its own PASS evidence. The suite then exercises cross-track scenarios, old authority-negative-space tests, full regression with an MCP-capable Python interpreter, and a release-candidate closure artifact. Live activation, runtime-current switch, service restart, push, or orphan cleanup are outside this plan.

**Tech Stack:** Python 3.12, unittest/pytest, existing stable test suites, JARVIS FastAPI TestClient, EDP-1.0 evidence metrics.

**Spec:** `docs/superpowers/specs/2026-09-24-ai-office-harness-topdown-edp-reconciled-design.md`

## Global Constraints

- All Track A/B/C qualification evidence must be PASS before cross-track tests.
- List Dashboard qualification must be PASS before UI integration tests.
- 3D renderer qualification may still be a separate gate; `NO_GO` there blocks 3D production integration but must not invalidate List Dashboard or Harness backend qualification.
- Full Plan remains final assignment authority; Provider Router remains provider/model authority; Gateway+Full MCP remain canonical state-change path.
- Report failure cannot change execution success or cause execution retry.
- Historical/stale incident evidence cannot become current issue state.
- Capability retirement cannot invalidate running checkpoint lineage.
- Notion/LLMWiki cannot become Runtime Truth.
- All PASS claims require fresh command output and stored evidence.

## Review Focus

1. Cross-track serialization must not leak forbidden provider/credential/effect payloads into Dashboard or reports.
2. A capability entering `DRAINING` during a report/dashboard read must preserve running task lineage and read continuity.
3. One failed report sink plus a healthy execution must display `WAITING_REPORT`, not `FAILED`, in Dashboard/records.
4. A historical stall followed by recovery must display Recovery history with zero current issue count.
5. Full regression must run under an interpreter that actually imports `mcp`; a missing package is a qualification block, not a source PASS.

---

### Task 1: Verify track evidence and source lineage before integration

**Files:**
- Read: `docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/OPERATIONS_READ_MODEL_QUALIFICATION.json`
- Read: `docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/CAPABILITY_LIFECYCLE_QUALIFICATION.json`
- Read: `docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/REPORTING_RECORDS_QUALIFICATION.json`
- Read JARVIS: `docs/AI_OFFICE_DASHBOARD_QUALIFICATION_20260924.json`
- Create: `docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/INTEGRATION_INPUT_FREEZE.json`

**Interfaces:**
- Consumes: per-track PASS evidence and current Git SHAs.
- Produces: one source/input freeze for integrated tests.

- [ ] **Step 1: Assert all required backend track statuses are PASS**

```python
from pathlib import Path
import json
root=Path('docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION')
required={
    'OPERATIONS_READ_MODEL_QUALIFICATION.json':'A',
    'CAPABILITY_LIFECYCLE_QUALIFICATION.json':'B',
    'REPORTING_RECORDS_QUALIFICATION.json':'C',
}
for name, track in required.items():
    payload=json.loads((root/name).read_text())
    assert payload['status']=='PASS', (track, payload)
```

- [ ] **Step 2: Record Harness and JARVIS source heads**

```bash
HARNESS_HEAD=$(git rev-parse HEAD)
JARVIS_HEAD=$(git -C /home/ywjo/AI-Workspace/worktrees/jarvis-ai-office-dashboard-20260924 rev-parse HEAD)
printf '%s\n%s\n' "$HARNESS_HEAD" "$JARVIS_HEAD"
```

- [ ] **Step 3: Write `INTEGRATION_INPUT_FREEZE.json` with exact evidence digests**

```python
payload = {
    "schema_version": "gch.ai-office-integration-input-freeze.v1",
    "harness_head": harness_head,
    "jarvis_head": jarvis_head,
    "operations_schema": "orchestration.operations-read-model.v1",
    "track_evidence_sha256": evidence_digests,
}
```

- [ ] **Step 4: Validate and commit input freeze**

```bash
python3 -m json.tool docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/INTEGRATION_INPUT_FREEZE.json >/dev/null
git add docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/INTEGRATION_INPUT_FREEZE.json
git commit -m "docs: freeze AI Office integration inputs"
```

### Task 2: Add cross-track integration scenarios in Harness tests

**Files:**
- Create: `tests/test_ai_office_upgrade_integration.py`

**Interfaces:**
- Consumes: Track A/B/C public contracts.
- Produces: end-to-end in-process scenarios without network/live effects.

- [ ] **Step 1: Write scenario for healthy execution + failed report sink**

```python
def test_report_failure_does_not_turn_execution_or_dashboard_failed(tmp_path):
    report = verified_completion_report()
    outcome = coordinator_with_failing_llm_sink(tmp_path).record(report)
    assert outcome.execution_status == "SUCCESS"
    assert outcome.final_completion_status == "WAITING_REPORT"
    projection = build_projection_for_recording_outcome(outcome)
    assert projection.normalized_state != "FAILED"
    assert projection.impact
```

- [ ] **Step 2: Write scenario for recovered historical stall**

```python
def test_recovered_stall_is_history_not_current_issue():
    incidents = project_incidents(
        current_state="RUNNING",
        current_state_ref="run:R1:generation-9",
        evidence_rows=(stale_stall_evidence(),),
        now=NOW,
    )
    assert incidents[0].state == "HISTORICAL"
    assert not any(i.state in {"OPEN", "ACKNOWLEDGED", "RECOVERING"} for i in incidents)
```

- [ ] **Step 3: Write scenario for capability drain preserving lineage**

```python
def test_capability_drain_preserves_running_lineage(tmp_path):
    store = seeded_active_capability_store(tmp_path)
    store.acquire_dependency("cap:research:1", "TASKEXEC-1")
    before = runtime_selection_for_contract("cap:research:1", activation_epoch=4)
    store.begin_drain("cap:research:1", evidence_ref="evidence:drain")
    after = runtime_selection_for_contract("cap:research:1", activation_epoch=4)
    assert before.capability_contract_id == after.capability_contract_id
    assert before.activation_epoch == after.activation_epoch
```

- [ ] **Step 4: Run and then implement only small test adapters needed to compose existing public functions**

```bash
python -m pytest tests/test_ai_office_upgrade_integration.py -q
```

Expected final result: all scenarios pass; adapters must stay under test fixtures/helpers and must not create production authority.

- [ ] **Step 5: Commit integration tests**

```bash
git add tests/test_ai_office_upgrade_integration.py
git commit -m "test: add AI Office upgrade integration scenarios"
```

### Task 3: Run focused authority and continuity regression

**Files:**
- No product files.
- Evidence: `docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/FOCUSED_REGRESSION.json`

**Interfaces:**
- Consumes: integrated source tree.
- Produces: exact test counts and zero-failure evidence.

- [ ] **Step 1: Run the previously verified focused baseline plus new suites**

```bash
python -m unittest \
  tests.test_ai_office_integrated_qualification \
  tests.test_ai_office_baseline_closure \
  tests.test_ai_office_authority_negative_space \
  tests.test_ai_office_reporting \
  tests.test_production_full_plan_boot \
  tests.test_production_full_plan_entry \
  tests.test_production_full_plan_runner \
  tests.test_production_provider_router_integration \
  tests.test_durable_continuation \
  tests.test_durable_continuation_failure_injection \
  tests.test_operator_console_projection \
  tests.test_operations_diagnostic_projection \
  tests.test_external_capability_binding \
  tests.test_capability_watch -v
```

Expected: zero failures/errors.

- [ ] **Step 2: Run all new Harness upgrade suites**

```bash
python -m pytest \
  tests/test_operations_read_model.py \
  tests/test_incident_projection.py \
  tests/test_process_lifecycle_diagnostics.py \
  tests/test_jarvis_bridge_operations_projection.py \
  tests/test_capability_lifecycle*.py \
  tests/test_external_capability_policy.py \
  tests/test_ai_office_work_records.py \
  tests/test_ai_office_report_*.py \
  tests/test_llmwiki_report_sink.py \
  tests/test_notion_report_sink.py \
  tests/test_ai_office_reporting_coordinator.py \
  tests/test_ai_office_upgrade_integration.py -q
```

- [ ] **Step 3: Record exact commands, interpreter, counts, failures, and source HEAD**

```json
{
  "schema_version": "gch.ai-office-focused-regression.v1",
  "status": "PASS",
  "failure_count": 0,
  "error_count": 0
}
```

- [ ] **Step 4: Commit evidence**

```bash
git add docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/FOCUSED_REGRESSION.json
git commit -m "test: record focused AI Office upgrade regression"
```

### Task 4: Run full regression with an MCP-capable interpreter

**Files:**
- Evidence: `docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/FULL_REGRESSION.json`

**Interfaces:**
- Consumes: full test tree and an interpreter that imports `mcp`.
- Produces: full-suite PASS or explicit environment BLOCKED; never extrapolates from focused tests.

- [ ] **Step 1: Resolve and validate the full-regression interpreter**

```bash
FULL_MCP_TEST_PYTHON=${FULL_MCP_TEST_PYTHON:-/home/ywjo/AI-Workspace/worktrees/ocp-observation-gateway-design-20260923/.venv/bin/python}
test -x "$FULL_MCP_TEST_PYTHON"
"$FULL_MCP_TEST_PYTHON" - <<'PY2'
import mcp, sys
print(sys.executable)
print(mcp.__file__)
PY2
```

If either command fails, record `FULL_REGRESSION=BLOCKED_ENVIRONMENT_MCP_UNAVAILABLE` and do not declare integrated ALL PASS.

- [ ] **Step 2: Run full test discovery with that interpreter**

```bash
"$FULL_MCP_TEST_PYTHON" -m unittest discover -s tests -v
```

Expected for PASS: zero failures/errors; skips are recorded separately.

- [ ] **Step 3: Record full regression evidence**

```json
{
  "schema_version": "gch.ai-office-full-regression.v1",
  "status": "PASS",
  "mcp_import_verified": true,
  "failure_count": 0,
  "error_count": 0
}
```

- [ ] **Step 4: Commit evidence only if it reflects the actual command result**

```bash
git add docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/FULL_REGRESSION.json
git commit -m "test: record full AI Office harness regression"
```

### Task 5: Run JARVIS Dashboard cross-repository qualification

**Files:**
- JARVIS tests: `tests/test_ai_office_dashboard_*.py`
- JARVIS qualification: `docs/AI_OFFICE_DASHBOARD_QUALIFICATION_20260924.json`
- Harness mirror evidence: `docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/JARVIS_DASHBOARD_INTEGRATION.json`

**Interfaces:**
- Consumes: frozen Harness read-model contract and JARVIS Dashboard implementation.
- Produces: cross-repository schema binding evidence.

- [ ] **Step 1: Run JARVIS Dashboard and existing WebApp regression**

```bash
J=/home/ywjo/AI-Workspace/worktrees/jarvis-ai-office-dashboard-20260924
cd "$J"
python -m pytest tests/test_ai_office_dashboard_*.py tests/test_webapp_voice_api.py tests/test_webapp_voice_adapters.py -q
```

- [ ] **Step 2: Verify JARVIS qualification binds the frozen Harness schema**

```python
import json
q=json.load(open('docs/AI_OFFICE_DASHBOARD_QUALIFICATION_20260924.json'))
assert q['status']=='PASS'
assert q['read_schema']=='orchestration.operations-read-model.v1'
assert q['direct_execution_authority'] is False
```

- [ ] **Step 3: Mirror only immutable refs/digests into Harness evidence**

```json
{
  "schema_version": "gch.jarvis-dashboard-integration.v1",
  "read_schema": "orchestration.operations-read-model.v1",
  "dashboard_authority": "NON_AUTHORITATIVE",
  "status": "PASS"
}
```

- [ ] **Step 4: Commit Harness mirror evidence**

```bash
cd /home/ywjo/AI-Workspace/project-workspace/.worktrees/AI-OFFICE-HARNESS-TOPDOWN-EDP-20260924
git add docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/JARVIS_DASHBOARD_INTEGRATION.json
git commit -m "test: bind qualified JARVIS dashboard to harness read model"
```

### Task 6: Execute EDP-1.0 final upgrade re-diagnosis

**Files:**
- Authority: `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md`
- Create: `docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/EDP_IMPLEMENTATION_REDIAGNOSIS.json`

**Interfaces:**
- Consumes: final source, track evidence, full regression, cross-repo Dashboard evidence.
- Produces: EDP closure metrics and PASS/FAIL/BLOCKED.

- [ ] **Step 1: Freeze all material obligations from the approved spec**

```text
Map every O-AC, C-AC, R-AC, X-AC and INV-01..INV-15 to implementation files + tests + evidence.
```

- [ ] **Step 2: Run negative-space and cross-document checks**

```text
Search for:
- duplicate assignment/provider/effect authority
- raw runtime bypass from Dashboard
- provider-specific storage in Harness Core
- report re-execution path
- active capability direct-retire path
- unresolved placeholder/open question in release-critical contracts
```

- [ ] **Step 3: Run adversarial second pass and PASS challenge**

```text
Assume the implementation PASS conclusion is wrong and search for counterexamples in authority boundaries, stale-state projection, retries, lifecycle replacement, sink failures, and cross-repo schema drift.
```

- [ ] **Step 4: Require universal closure metrics**

```json
{
  "BLOCKER_COUNT": 0,
  "UNRESOLVED_MAJOR_COUNT": 0,
  "MUST_REQUIREMENT_COVERAGE": "100%",
  "MUST_TRACEABILITY_COVERAGE": "100%",
  "DOMAIN_EVIDENCE_COVERAGE": "100%",
  "NEGATIVE_SPACE_OPEN_MATERIAL_COUNT": 0,
  "CROSS_DOCUMENT_CONFLICT_COUNT": 0,
  "ADVERSARIAL_NEW_BLOCKER_MAJOR": 0,
  "PASS_CHALLENGE_OPEN_COUNT": 0
}
```

- [ ] **Step 5: Write evidence and commit only the observed verdict**

```bash
git add docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/EDP_IMPLEMENTATION_REDIAGNOSIS.json
git commit -m "docs: record AI Office implementation EDP rediagnosis"
```

### Task 7: Create a non-activating release candidate declaration

**Files:**
- Create: `docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/RELEASE_CANDIDATE.json`

**Interfaces:**
- Consumes: EDP PASS + full regression PASS + Dashboard integration PASS.
- Produces: release-candidate identity only.

- [ ] **Step 1: Refuse release candidate creation if EDP or full regression is not PASS**

```python
assert edp['decision'] == 'ALL_PASS'
assert full_regression['status'] == 'PASS'
assert dashboard['status'] == 'PASS'
```

- [ ] **Step 2: Seal candidate identity and non-activation boundary**

```json
{
  "schema_version": "gch.ai-office-harness-upgrade-release-candidate.v1",
  "status": "QUALIFIED_CANDIDATE",
  "live_activated": false,
  "runtime_current_switched": false,
  "services_restarted": false,
  "orphan_cleanup_performed": false
}
```

- [ ] **Step 3: Verify stable runtime has not changed**

```bash
readlink -f /home/ywjo/AI-Workspace/runtime/runtime-current 2>/dev/null || true
systemctl --user is-active production-full-plan-reconcile.timer 2>/dev/null || true
```

Record observations; do not restart or switch anything.

- [ ] **Step 4: Commit release-candidate declaration**

```bash
git add docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/RELEASE_CANDIDATE.json
git commit -m "docs: declare qualified AI Office upgrade candidate"
```
