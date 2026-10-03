# AI Office 3D Renderer Qualification Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Select and qualify one production 3D visualization renderer for the AI Office spatial view without treating the existing Canvas pseudo-3D spike or an external design agent as production authority.

**Architecture:** Renderer selection is a bounded qualification activity. External UI/3D/design capabilities may produce isolated prototypes through the existing capability discovery/evaluation path, but production receives only reviewed artifacts and a renderer contract. Every candidate must consume the same `orchestration.operations-read-model.v1` fixture and own no orchestration/control state.

**Tech Stack:** Browser WebGL/GPU rendering, isolated prototype assets, browser performance instrumentation, existing external capability discovery/evaluation contracts.

**Spec:** `docs/superpowers/specs/2026-09-24-ai-office-harness-topdown-edp-reconciled-design.md`

## Global Constraints

- External 3D design Agents/Skills are MCP/Adapter-first capability contracts; their runtime code is not copied into Harness/JARVIS.
- Renderer libraries are evaluated separately as frontend dependencies with license and supply-chain evidence.

- The old Canvas/Fibonacci-sphere visual spike is a quality reference only, not renderer selection evidence.
- Candidate discovery follows `SEARCH → EVALUATE → CONTRACT → SANDBOX → QUALIFY`; external agent code is not absorbed into Harness Core.
- Candidate agents receive no stable runtime modification, deploy, service restart, Full Plan, Router, or Full MCP authority.
- Prototypes run in an isolated directory/worktree and use synthetic operations-read-model fixtures only.
- The selected renderer consumes `orchestration.operations-read-model.v1` and is visualization-only.
- List Operations remains primary; 3D may fail independently without affecting Harness execution or List view.
- Renderer selection requires measured browser performance and mobile/tablet fallback behavior.

## Review Focus

1. A visually strong candidate that requires direct Harness state access is rejected.
2. A candidate that cannot degrade to a static/list fallback on low GPU capability is rejected.
3. External design agent output with shell/deploy/global-install requirements is quarantined or adapted before prototype use.
4. Renderer maintains stable office/agent identity across provider changes.
5. The selected candidate cannot submit control actions directly from the rendering engine.

---

### Task 1: Freeze the renderer input contract and synthetic fixture

**Files:**
- Create in JARVIS Dashboard worktree: `tests/fixtures/ai_office_operations_read_model_v1.json`
- Create: `docs/AI_OFFICE_3D_RENDERER_INPUT_CONTRACT_20260924.json`

**Interfaces:**
- Consumes: Track A frozen public schema.
- Produces: one deterministic fixture used by every renderer candidate.

- [ ] **Step 1: Create the synthetic fixture from public fields only**

```json
{
  "schema_version": "orchestration.operations-read-model.v1",
  "project_id": "AI-OFFICE-3D-FIXTURE",
  "run_id": "RUN-001",
  "normalized_state": "RUNNING",
  "human_state": "작업 중",
  "progress": 60,
  "progress_source": "fixture:3/5-phases",
  "outcome": "운영 상태를 공간적으로 이해",
  "impact": "현재 영향 없음",
  "next_step": "상품평가",
  "approval_required": false,
  "incidents": [],
  "sources": [{"source_component":"HARNESS","source_version":"fixture-v1","source_head":"fixture","source_timestamp":"2026-09-24T00:00:00+00:00"}]
}
```

- [ ] **Step 2: Record forbidden renderer dependencies**

```json
{
  "schema_version": "jarvis.ai-office-3d-renderer-input-contract.v1",
  "read_schema": "orchestration.operations-read-model.v1",
  "authority": "VISUALIZATION_ONLY",
  "forbidden_inputs": ["credentials", "raw_authorization", "raw_effect_payload", "provider_selection", "final_assignee"],
  "required_fallback": "LIST_OPERATIONS"
}
```

- [ ] **Step 3: Verify fixture contains no forbidden fields**

```bash
python - <<'PY2'
import json
p=json.load(open('tests/fixtures/ai_office_operations_read_model_v1.json'))
raw=json.dumps(p).lower()
for token in ('credential','token','raw_effect_payload','final_assignee'):
    assert token not in raw
PY2
```

- [ ] **Step 4: Commit fixture and contract**

```bash
git add tests/fixtures/ai_office_operations_read_model_v1.json docs/AI_OFFICE_3D_RENDERER_INPUT_CONTRACT_20260924.json
git commit -m "test: freeze AI Office 3D renderer input contract"
```

### Task 2: Search and evaluate external design/3D capabilities through the existing capability pipeline

**Files:**
- Create evidence only: `docs/AI_OFFICE_3D_EXTERNAL_CAPABILITY_EVALUATION_20260924.json`
- Reuse Harness modules: `runtime/orchestrator/capability_inventory.py`, `skill_discovery.py`, `skill_candidate_evaluator.py`, `skill_adoption.py`.

**Interfaces:**
- Consumes capability requirements `operations_dashboard_design`, `web_3d_visualization`, `motion_design`, `browser_performance`.
- Produces evaluated candidate evidence; no candidate activation or installation without existing approval contracts.

- [ ] **Step 1: Inventory existing project/global capability assets**

```text
Capability requirements:
- operations_dashboard_design
- web_3d_visualization
- motion_design
- browser_performance
Required authority: READ_ONLY for discovery/evaluation.
```

Use the existing capability inventory API so exact duplicates are identified before discovery.

- [ ] **Step 2: Run approved read-only discovery only for verified gaps**

```text
Discovery output must bind project ID, Gate/LV, canonical plan SHA, immutable candidate revision, provenance, license, permissions, and risk metadata.
```

- [ ] **Step 3: Evaluate candidate risk before prototype use**

```text
Reject or escalate candidates requiring secrets, destructive action, production deployment, global install/change, or uncontrolled shell/network writes.
Project-local sandbox/package use requires the existing adoption/approval path.
```

- [ ] **Step 4: Record candidate disposition**

```json
{
  "schema_version": "jarvis.ai-office-3d-external-capability-evaluation.v1",
  "required_capabilities": ["operations_dashboard_design", "web_3d_visualization", "motion_design", "browser_performance"],
  "disposition_values": ["USE_AS_IS", "ADAPT", "WRAP", "WATCH", "REJECT"],
  "production_runtime_dependency_allowed": false
}
```

The actual candidate IDs and evidence refs are populated from verified discovery results; absence of a safe candidate is a valid `NO_SAFE_EXTERNAL_CANDIDATE` result and does not authorize automatic Build/Absorb.

- [ ] **Step 5: Commit evaluation evidence**

```bash
git add docs/AI_OFFICE_3D_EXTERNAL_CAPABILITY_EVALUATION_20260924.json
git commit -m "docs: evaluate external 3D design capabilities"
```

### Task 3: Build isolated renderer prototypes against the same fixture

**Files:**
- Create throwaway sandbox root outside production WebApp modules: `poc/ai_office_3d_renderer/`
- Create: `poc/ai_office_3d_renderer/README.md`
- Create one subdirectory per qualified renderer candidate using its immutable candidate ID.

**Interfaces:**
- Consumes: Task 1 fixture and Task 2 qualified candidates.
- Produces: throwaway visual/performance prototype artifacts; no production import path.

- [ ] **Step 1: Create the sandbox manifest**

```text
poc/ai_office_3d_renderer/
  README.md
  fixtures/operations-read-model.v1.json
  candidates/<immutable-candidate-id>/
```

The README states `THROWAWAY QUALIFICATION ONLY`, the frozen input schema, and the prohibition on Harness control imports.

- [ ] **Step 2: Bind each prototype to the exact same fixture**

```javascript
const state = await fetch('../fixtures/operations-read-model.v1.json').then(r => r.json());
if (state.schema_version !== 'orchestration.operations-read-model.v1') throw new Error('schema mismatch');
```

- [ ] **Step 3: Reject any prototype that accesses control/runtime paths**

```bash
grep -RniE 'full_mcp|provider_router|OrchestrationEngine|/api/.+approve|subprocess|service restart' poc/ai_office_3d_renderer/candidates && exit 1 || true
```

- [ ] **Step 4: Keep prototypes out of production imports**

```bash
grep -Rni 'poc.ai_office_3d_renderer\|poc/ai_office_3d_renderer' webapp runtime && exit 1 || true
```

- [ ] **Step 5: Commit only qualification prototype assets**

```bash
git add poc/ai_office_3d_renderer
git commit -m "test: add isolated AI Office 3D renderer prototypes"
```

### Task 4: Measure visual parity, browser performance, and fallback behavior

**Files:**
- Create: `docs/AI_OFFICE_3D_RENDERER_BENCHMARK_20260924.json`
- Reference visual baseline: approved JARVIS visual spike and Dashboard requirements; do not promote spike code.

**Interfaces:**
- Consumes: candidate prototypes.
- Produces: comparable benchmark rows and PASS/FAIL per candidate.

- [ ] **Step 1: Measure each candidate at desktop and mobile viewport classes**

```text
Required measurements per candidate:
- initial_render_ms
- steady_state_frame_ms_p50
- steady_state_frame_ms_p95
- memory_mb_peak
- interaction_latency_ms_p95
- WebGL/context-loss recovery result
- low-GPU/static fallback result
```

- [ ] **Step 2: Score non-performance requirements as gates, not weighted cosmetics**

```text
Hard gates:
- same operations read model
- visualization-only authority
- no invented operational data
- text status remains accessible
- List fallback available
- office/agent identity stable
- current issue/freshness semantics preserved
```

- [ ] **Step 3: Record benchmark evidence**

```json
{
  "schema_version": "jarvis.ai-office-3d-renderer-benchmark.v1",
  "read_schema": "orchestration.operations-read-model.v1",
  "hard_gate_failures_allowed": 0,
  "selection_requires_measured_performance": true,
  "visual_baseline_is_selection_authority": false
}
```

- [ ] **Step 4: Do not select a candidate with any hard-gate failure**

```python
assert all(candidate["hard_gate_failures"] == 0 for candidate in eligible_candidates)
```

- [ ] **Step 5: Commit benchmark evidence**

```bash
git add docs/AI_OFFICE_3D_RENDERER_BENCHMARK_20260924.json
git commit -m "test: benchmark AI Office 3D renderer candidates"
```

### Task 5: Seal renderer selection contract

**Files:**
- Create: `docs/AI_OFFICE_3D_RENDERER_SELECTION_20260924.json`

**Interfaces:**
- Consumes: candidate evaluation and benchmark evidence.
- Produces: one selected renderer contract or explicit `NO_GO`.

- [ ] **Step 1: Select only among candidates with complete evidence and zero hard-gate failures**

```text
Tie-break order:
1. lower steady_state_frame_ms_p95
2. lower memory_mb_peak
3. lower interaction_latency_ms_p95
4. lower external/runtime dependency footprint
```

- [ ] **Step 2: Seal required selection fields**

```json
{
  "schema_version": "jarvis.ai-office-3d-renderer-selection.v1",
  "decision": "GO_OR_NO_GO",
  "selected_candidate_id": "POPULATED_FROM_QUALIFIED_EVIDENCE",
  "read_schema": "orchestration.operations-read-model.v1",
  "authority": "VISUALIZATION_ONLY",
  "list_view_remains_primary": true,
  "production_integration_allowed": false
}
```

At execution time `decision` is replaced with literal `GO` or `NO_GO`; `selected_candidate_id` is empty for `NO_GO` and an immutable qualified ID for `GO`. These are evidence fields, not implementation placeholders.

- [ ] **Step 3: Verify selection references existing evidence digests**

```python
assert selection["evaluation_evidence_sha256"] == sha256(evaluation_file)
assert selection["benchmark_evidence_sha256"] == sha256(benchmark_file)
```

- [ ] **Step 4: Set `production_integration_allowed=true` only for a `GO` selection with valid evidence bindings**

```python
if selection["decision"] == "GO":
    assert selection["selected_candidate_id"]
    selection["production_integration_allowed"] = True
```

- [ ] **Step 5: Commit selection evidence**

```bash
git add docs/AI_OFFICE_3D_RENDERER_SELECTION_20260924.json
git commit -m "docs: select AI Office 3D renderer candidate"
```

### Task 6: Qualification closure

**Files:**
- Create: `docs/AI_OFFICE_3D_RENDERER_QUALIFICATION_20260924.json`

**Interfaces:**
- Consumes: Tasks 1-5.
- Produces: `3D_RENDERER_QUALIFICATION=PASS` when one `GO` renderer is sealed, otherwise an explicit `NO_GO` that blocks 3D production only and leaves List Dashboard unaffected.

- [ ] **Step 1: Verify the List Dashboard remains independent of prototype assets**

```bash
grep -Rni 'poc/ai_office_3d_renderer' webapp && exit 1 || true
```

- [ ] **Step 2: Verify candidate selection authority is visual-only**

```python
assert selection["authority"] == "VISUALIZATION_ONLY"
assert selection["read_schema"] == "orchestration.operations-read-model.v1"
```

- [ ] **Step 3: Record qualification result**

```json
{
  "schema_version": "jarvis.ai-office-3d-renderer-qualification.v1",
  "list_dashboard_dependency": false,
  "authority_change": false,
  "production_3d_allowed_only_after_go": true
}
```

- [ ] **Step 4: Commit qualification evidence**

```bash
git add docs/AI_OFFICE_3D_RENDERER_QUALIFICATION_20260924.json
git commit -m "test: close AI Office 3D renderer qualification"
```
