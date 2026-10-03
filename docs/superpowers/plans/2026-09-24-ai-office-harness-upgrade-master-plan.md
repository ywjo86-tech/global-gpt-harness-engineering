# AI Office Harness Upgrade Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved AI Office Harness enhancements without duplicating existing authorities: canonical operations read model, external capability lifecycle, standardized dual reports, and the human operations Dashboard.

**Architecture:** Preserve `origin/main@c591b01e8a1d9d9bb2dc438ca85f6c2ffcc79a03` authorities and add thin, separately testable layers. Human entry is `User -> JARVIS / Harness Dashboard`; both surfaces converge on existing governed control boundaries. Backend tracks land before the Dashboard consumes them, external Agents are MCP/Adapter-first (`ABSORB LAST`), and final integration qualification proves no assignment/provider/effect authority drift.

**Tech Stack:** Python 3.12, unittest/pytest-compatible tests, FastAPI, existing Full Plan/OCPv2/MPRF/Full MCP contracts, Jarvis FastAPI WebApp, Markdown/HTTP adapters.

**Spec:** `docs/superpowers/specs/2026-09-24-ai-office-harness-topdown-edp-reconciled-design.md`

## Global Constraints

- Preserve Full Plan as final task-to-agent assignment authority.
- Preserve Multi-Provider Router/MPRF as provider/model selection authority.
- Preserve Production Execution Gateway + Full MCP as canonical state-changing effect authority.
- Do not create a second generic capability inventory/discovery/evaluator/authorization path.
- Dashboard is non-authoritative and read-first; controls reuse the existing remote envelope/Governance path.
- `OfficeReportV1` remains operational projection; long-term work records use a separate `REPORT_DATA` contract.
- Notion and LLMWiki never become Runtime Truth.
- External capability retirement must drain active dependencies before `RETIRED`.
- OCP and Harness release identities may differ; source identity is explicit in projections.
- Suspected orphan processes are diagnosed only; cleanup requires separate authorization/evidence.
- JARVIS local uncommitted work must not be reset, cleaned, or overwritten.
- External Agent runtime code is not absorbed into Harness Core by default; MCP/Adapter contract binding is preferred.
- Continuous external capability improvement uses a lightweight periodic/on-demand watch, not a resident autonomous Agent.
- Existing diagnostics/attention/recovery facts are reused for Self-Diagnosis projection; no second diagnostic framework is created.
- List UI and 3D design capability candidates are evaluated through the same external capability lifecycle; accepting design artifacts does not grant runtime authority.

## Review Focus

1. A new read model accidentally exposing provider credentials, raw authorization material, or effect payloads must fail closed in Track A tests.
2. External capability lifecycle transitions that bypass Full Plan assignment or retire an in-use capability must fail closed in Track B tests.
3. Report retry must never re-run execution and dual sinks must never diverge from one `REPORT_DATA`; Track C tests pin both conditions.
4. Dashboard stale/historical evidence must never render as a current incident; Track D API/UI tests cover freshness and incident state.
5. Cross-track integration must leave existing AI Office/Full Plan/Router/Continuity/Operator Console regressions green; Track E runs the focused baseline plus new suites.

---

## Execution Topology

```text
Gate 0  Source/Baseline Revalidation
  |
  +--> Track A  Operations Read Model
  |
  +--> Track B  External Capability Lifecycle + Capability Watch
  |
  +--> Track C  Reporting & Records
  |
  `--> Track D  Harness Dashboard (depends on Track A read contract + Track B external capability contract)
          |
          +--> Track D3  3D Renderer Qualification (production 3D remains gated)
          |
          v
      Track E  Integrated Qualification / Release Candidate
```

Track A, B, and C may execute in parallel after Gate 0. Track D starts only after Track A freezes its public read contract. Track D3 qualifies a renderer but does not silently add renderer-specific production code. Track E starts only after A-D are individually green; a D3 `NO_GO` blocks production 3D only and is recorded explicitly.

## Plan Set

- `docs/superpowers/plans/2026-09-24-ai-office-operations-read-model.md`
- `docs/superpowers/plans/2026-09-24-external-capability-lifecycle.md`
- `docs/superpowers/plans/2026-09-24-ai-office-reporting-records.md`
- `docs/superpowers/plans/2026-09-24-ai-office-dashboard.md`
- `docs/superpowers/plans/2026-09-24-ai-office-3d-renderer-qualification.md`
- `docs/superpowers/plans/2026-09-24-ai-office-integrated-qualification.md`

### Task 1: Freeze execution authorities and branch inputs

**Files:**
- Read: `docs/DEVELOPMENT_PLAN.txt`
- Read: `docs/harness/CURRENT_OPERATIONAL_STATE.json`
- Read: `docs/superpowers/specs/2026-09-24-ai-office-harness-topdown-edp-reconciled-design.md`
- Create during execution: `docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/IMPLEMENTATION_SOURCE_FREEZE.json`

**Interfaces:**
- Consumes: Git HEAD, remote main SHA, stable operational state projection.
- Produces: immutable source-freeze evidence used by every track review.

- [ ] **Step 1: Verify the implementation branch starts from the approved source lineage**

```bash
git fetch origin main
git merge-base --is-ancestor c591b01e8a1d9d9bb2dc438ca85f6c2ffcc79a03 HEAD
git status --short --branch
```

Expected: ancestor check exit `0`; no unrelated product-code changes before task work.

- [ ] **Step 2: Record source-freeze evidence**

```bash
mkdir -p docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION
python3 - <<'PY2'
import json, subprocess
from pathlib import Path
head=subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip()
payload={
    "schema_version":"gch.ai-office-upgrade-source-freeze.v1",
    "approved_baseline":"c591b01e8a1d9d9bb2dc438ca85f6c2ffcc79a03",
    "implementation_head":head,
    "spec_path":"docs/superpowers/specs/2026-09-24-ai-office-harness-topdown-edp-reconciled-design.md",
    "authority_invariants":["FULL_PLAN_ASSIGNMENT","PROVIDER_ROUTER_SELECTION","FULL_MCP_EFFECT"],
}
Path('docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/IMPLEMENTATION_SOURCE_FREEZE.json').write_text(json.dumps(payload, indent=2)+"\n")
PY2
```

- [ ] **Step 3: Validate the evidence is parseable and binds the actual HEAD**

```bash
python3 -m json.tool docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/IMPLEMENTATION_SOURCE_FREEZE.json >/dev/null
python3 - <<'PY2'
import json, subprocess
p=json.load(open('docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/IMPLEMENTATION_SOURCE_FREEZE.json'))
assert p['implementation_head']==subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip()
PY2
```

- [ ] **Step 4: Commit source-freeze evidence**

```bash
git add docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/IMPLEMENTATION_SOURCE_FREEZE.json
git commit -m "docs: freeze AI Office upgrade implementation source"
```

### Task 2: Execute Track A/B/C under separate review gates

**Files:**
- Plan: `docs/superpowers/plans/2026-09-24-ai-office-operations-read-model.md`
- Plan: `docs/superpowers/plans/2026-09-24-external-capability-lifecycle.md`
- Plan: `docs/superpowers/plans/2026-09-24-ai-office-reporting-records.md`

**Interfaces:**
- Consumes: Task 1 source-freeze evidence.
- Produces: three independently green backend feature branches/commits with public interfaces documented in their plan acceptance sections.

- [ ] **Step 1: Run Track A plan task-by-task with fresh reviewer gates**

```text
Required output: OPERATIONS_READ_MODEL_TRACK=PASS
```

- [ ] **Step 2: Run Track B plan task-by-task with fresh reviewer gates**

```text
Required output: CAPABILITY_LIFECYCLE_TRACK=PASS
```

- [ ] **Step 3: Run Track C plan task-by-task with fresh reviewer gates**

```text
Required output: REPORTING_RECORDS_TRACK=PASS
```

- [ ] **Step 4: Reject merge if any track changes final assignment, provider selection, or canonical effect authority**

```bash
python -m unittest tests.test_ai_office_authority_negative_space tests.test_operator_console_projection -v
```

Expected: all tests pass.

### Task 3: Freeze Track A public operations contract before Dashboard work

**Files:**
- Test: `tests/test_operations_read_model.py`
- Read: `runtime/orchestrator/operations_read_model.py`
- Create during execution: `docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/OPERATIONS_READ_MODEL_CONTRACT.json`

**Interfaces:**
- Consumes: Track A public dataclasses/functions.
- Produces: schema/version/digest consumed by Track D.

- [ ] **Step 1: Export a representative projection**

```bash
python3 - <<'PY2'
from dataclasses import fields
from runtime.orchestrator.operations_read_model import OPERATIONS_READ_MODEL_SCHEMA_V1, OperationsReadModelV1
assert OPERATIONS_READ_MODEL_SCHEMA_V1 == "orchestration.operations-read-model.v1"
print([field.name for field in fields(OperationsReadModelV1)])
PY2
```

- [ ] **Step 2: Seal the public field set and schema version**

```bash
python3 - <<'PY2'
import json
from dataclasses import fields
from pathlib import Path
from runtime.orchestrator.operations_read_model import OPERATIONS_READ_MODEL_SCHEMA_V1, OperationsReadModelV1
contract={
    "schema_version":OPERATIONS_READ_MODEL_SCHEMA_V1,
    "public_fields":[field.name for field in fields(OperationsReadModelV1)],
    "forbidden_fields":["credential","token","raw_effect_payload","final_assignee"],
}
path=Path('docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/OPERATIONS_READ_MODEL_CONTRACT.json')
path.write_text(json.dumps(contract, indent=2)+"\n")
PY2
```

- [ ] **Step 3: Validate Track D references this exact contract before UI implementation**

```bash
grep -F "orchestration.operations-read-model.v1" docs/superpowers/plans/2026-09-24-ai-office-dashboard.md
```

- [ ] **Step 4: Commit the contract evidence**

```bash
git add docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/OPERATIONS_READ_MODEL_CONTRACT.json
git commit -m "docs: freeze operations read model contract"
```

### Task 4: Execute Dashboard track only after JARVIS source revalidation

**Files:**
- Plan: `docs/superpowers/plans/2026-09-24-ai-office-dashboard.md`
- External repository: `/home/ywjo/AI-Workspace/project-workspace/jarvis-assistant`

**Interfaces:**
- Consumes: Track A read-model contract; current JARVIS source and local-change classification.
- Produces: Dashboard UI/API implementation with no Harness authority changes.

- [ ] **Step 1: Revalidate JARVIS source without cleaning or resetting**

```bash
git -C /home/ywjo/AI-Workspace/project-workspace/jarvis-assistant status --short --branch
git -C /home/ywjo/AI-Workspace/project-workspace/jarvis-assistant diff --check
git -C /home/ywjo/AI-Workspace/project-workspace/jarvis-assistant rev-parse HEAD
```

Expected: capture the dirty state exactly; do not alter it.

- [ ] **Step 2: Classify every overlapping WebApp change before creating the Dashboard worktree**

```text
Required classifications: KEEP / ABSORB / MERGE / SPLIT / MOVE / DEPRECATE / REWORK
```

- [ ] **Step 3: Execute the Dashboard plan in an isolated JARVIS worktree**

```text
Required output: DASHBOARD_TRACK=PASS
```

- [ ] **Step 4: Verify Dashboard actions still use existing control paths**

```text
No UI route may directly call Full Plan mutation, provider selection, or Full MCP effect functions.
```

### Task 5: Run integrated qualification and create release candidate only

**Files:**
- Plan: `docs/superpowers/plans/2026-09-24-ai-office-integrated-qualification.md`

**Interfaces:**
- Consumes: green Track A-D deliverables.
- Produces: qualification evidence and release-candidate recommendation; no live activation unless separately authorized.

- [ ] **Step 1: Execute the integrated qualification plan**

```text
Required output: INTEGRATED_QUALIFICATION=PASS
```

- [ ] **Step 2: Run the pre-existing focused regression set**

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
  tests.test_operator_console_projection -v
```

Expected: zero failures/errors.

- [ ] **Step 3: Keep release activation separate**

```text
Qualification PASS authorizes a release candidate only. Merge, push, runtime-current switch, service restart, or live cleanup require the normal release/approval path.
```

- [ ] **Step 4: Commit qualification evidence**

```bash
git add docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/
git commit -m "test: qualify AI Office harness enhancement candidate"
```
