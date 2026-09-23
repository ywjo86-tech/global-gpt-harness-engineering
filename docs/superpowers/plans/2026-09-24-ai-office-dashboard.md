# AI Office Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-first AI Office Dashboard that lets a non-developer understand Company → Office → Team → Agent → Work status, timeline, approvals, issues, recovery, and technical detail from the canonical operations read model.

**Architecture:** The Dashboard is the separate `Harness Dashboard` branch of `User -> JARVIS / Harness Dashboard`. It may be hosted by the existing JARVIS FastAPI WebApp at `/ai-office` to avoid a second UI server, but its state comes only from the frozen `orchestration.operations-read-model.v1` projection. New UI modules are separate from the 4,000+ line legacy shell; List Operations is primary, Advanced shows technical refs, and 3D is gated behind a separate renderer qualification plan before production integration.

**Tech Stack:** JARVIS FastAPI WebApp, Python HTML renderer modules, browser JavaScript/CSS, existing Harness operations projection JSON, pytest/unittest.

**Spec:** `docs/superpowers/specs/2026-09-24-ai-office-harness-topdown-edp-reconciled-design.md`

## Global Constraints

- Before implementation, revalidate and classify current JARVIS dirty state; never reset/clean/overwrite local changes.
- Dashboard route is `/ai-office`; JARVIS root `/` remains the current JARVIS interaction surface.
- Dashboard reads schema `orchestration.operations-read-model.v1` only through a bounded adapter.
- No Dashboard view reads raw Harness directories, credentials, provider/model routing internals, or raw effect payloads directly.
- Dashboard read path performs no LLM call.
- List Operations is the primary operational view.
- 3D Office uses the same projection state and remains secondary visualization.
- UI Persona has no execution authority; provider changes do not change Agent Persona identity.
- Actions are explicit and fail closed when an existing authorized control binding is not configured.
- Dashboard action code cannot directly import `OrchestrationEngine`, provider routers, Full MCP effect services, or direct shell/git/process mutation APIs.
- Production 3D renderer is not selected by the old Canvas spike; it requires the separate renderer qualification plan.
- Before List Operations visual implementation, external UX/design Agent/Skill candidates are evaluated through the Track B MCP/Adapter-first capability contract; design artifacts may be used, external runtime code is not absorbed.
- If no external design candidate qualifies, use `BUILD` and continue from approved visual requirements without blocking Dashboard implementation.

## Review Focus

1. A stale operations snapshot renders `상태 확인 필요`/`STALE`, never a green healthy state.
2. Historical incidents appear in history but not in the current issue count.
3. Missing control binding disables approve/reject action rather than falling back to direct engine calls.
4. Provider swaps preserve Agent Persona identity and current work.
5. Mobile/tablet layout remains readable without hiding Outcome/Status/Impact/Action/Next.

---

### Task 1: Revalidate JARVIS source and create an isolated Dashboard worktree

**Files:**
- Read: `/home/ywjo/AI-Workspace/project-workspace/jarvis-assistant/webapp/app.py`
- Read: `/home/ywjo/AI-Workspace/project-workspace/jarvis-assistant/webapp/shell.py`
- Read: `/home/ywjo/AI-Workspace/project-workspace/jarvis-assistant/webapp/schemas.py`
- Create during execution in Harness evidence: `docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/JARVIS_DASHBOARD_SOURCE_CLASSIFICATION.md`

**Interfaces:**
- Consumes: current JARVIS branch/HEAD/status plus Track A read-model contract evidence.
- Produces: a classified source snapshot and a new isolated JARVIS worktree rooted at the exact current source lineage.

- [ ] **Step 1: Capture JARVIS branch, HEAD, origin divergence, status, diff-stat, and diff-check**

```bash
J=/home/ywjo/AI-Workspace/project-workspace/jarvis-assistant
git -C "$J" status --short --branch
git -C "$J" rev-parse HEAD
git -C "$J" rev-list --left-right --count HEAD...origin/$(git -C "$J" branch --show-current)
git -C "$J" diff --stat
git -C "$J" diff --check
```

Expected: observation only; no reset, clean, stash, checkout, or modification.

- [ ] **Step 2: Classify overlapping WebApp changes**

```text
webapp/app.py       -> MERGE or KEEP
webapp/schemas.py   -> MERGE or KEEP
webapp/shell.py     -> KEEP; Dashboard gets a separate renderer module
webapp/voice_*      -> KEEP; outside Dashboard scope
memory/Notion code  -> KEEP; reporting sink is not memory sync
```

Record each changed/untracked file touching WebApp/authority as `KEEP / ABSORB / MERGE / SPLIT / MOVE / DEPRECATE / REWORK` with one-line rationale in `JARVIS_DASHBOARD_SOURCE_CLASSIFICATION.md`.

- [ ] **Step 3: Create a worktree from the current JARVIS HEAD, preserving the original dirty tree**

```bash
J=/home/ywjo/AI-Workspace/project-workspace/jarvis-assistant
WT=/home/ywjo/AI-Workspace/worktrees/jarvis-ai-office-dashboard-20260924
git -C "$J" worktree add "$WT" -b feature/ai-office-dashboard-20260924 "$(git -C "$J" rev-parse HEAD)"
```

Expected: original working tree remains unchanged. If `app.py`/`schemas.py` local modifications are classified `MERGE`, copy only the reviewed diff into the Dashboard worktree as a separate prerequisite commit before Dashboard product changes.

- [ ] **Step 4: Run existing JARVIS WebApp tests in the isolated worktree**

```bash
cd /home/ywjo/AI-Workspace/worktrees/jarvis-ai-office-dashboard-20260924
python -m pytest tests/test_webapp_voice_api.py tests/test_webapp_voice_adapters.py tests/test_webapp_voice_transcript.py -q
```

Expected: zero failures/errors before Dashboard changes.

- [ ] **Step 5: Commit only any explicitly classified prerequisite merge, if required**

```bash
git status --short
git diff --check
```

If no prerequisite merge is needed, make no commit in this step.


### Task 2: Qualify external List Operations UX/design capability without code absorption

**Files:**
- Create during execution: `docs/history/upgrades/2026-09-24-JARVIS-AI-OFFICE-DASHBOARD/DASHBOARD_DESIGN_CAPABILITY_EVALUATION.json`
- Read: Harness Track B external capability contract/lifecycle evidence.

**Interfaces:**
- Consumes: approved Dashboard information hierarchy, visual baseline, accessibility requirements, and Track B MCP/Adapter-first external capability lifecycle.
- Produces: one disposition `ADOPT_MCP`, `ADOPT_ADAPTER`, or `BUILD`, plus evidence/design-artifact refs; no execution authority.

- [ ] **Step 1: Define the bounded design requirement before searching**

```json
{
  "required_capabilities": ["operations_dashboard_ux", "information_architecture", "accessible_ui_design"],
  "allowed_outputs": ["layout_proposal", "design_tokens", "component_spec", "motion_guidance", "prototype_artifact"],
  "forbidden_outputs": ["shell_execution", "deployment", "credential_access", "provider_selection", "final_assignment"],
  "binding_preference": ["MCP_ENDPOINT", "ADAPTER", "BUILD"]
}
```

- [ ] **Step 2: Run existing discovery/evaluation against approved external sources**

```text
Use the existing capability inventory/discovery/evaluation pipeline. Do not copy an external Agent repository into Harness/JARVIS merely to evaluate it. Capture provenance, license, maintenance, capability overlap, permissions, and design-output evidence.
```

- [ ] **Step 3: Seal the disposition**

```python
assert evaluation["disposition"] in {"ADOPT_MCP", "ADOPT_ADAPTER", "BUILD"}
assert evaluation["runtime_authority"] == "NONE"
assert evaluation["code_absorbed"] is False
```

`ADOPT_*` requires an ACTIVE Track B contract exposing only the allowed design surface. `BUILD` is valid when no candidate clears governance/quality gates.

- [ ] **Step 4: Review design artifacts against the approved Dashboard requirements**

```text
Mandatory checks: Company→Office→Team→Agent→Work hierarchy, five user-priority facts, List-first operation, technical-detail separation, text+icon status, mobile/tablet responsiveness, no invented runtime values.
```

- [ ] **Step 5: Commit evaluation evidence only**

```bash
git add docs/history/upgrades/2026-09-24-JARVIS-AI-OFFICE-DASHBOARD/DASHBOARD_DESIGN_CAPABILITY_EVALUATION.json
git commit -m "docs: qualify dashboard external design capability"
```

### Task 3: Add a bounded operations projection client and Dashboard API models

**Files:**
- Create in JARVIS worktree: `webapp/ai_office_client.py`
- Create: `webapp/ai_office_models.py`
- Test: `tests/test_ai_office_dashboard_client.py`

**Interfaces:**
- Consumes: JSON projection from Track A schema `orchestration.operations-read-model.v1` via injected `read_projection() -> Mapping[str, object]`.
- Produces: `AIOfficeDashboardState`, `load_ai_office_dashboard_state(read_projection)`.

- [ ] **Step 1: Write failing schema/freshness tests**

```python
def test_client_rejects_wrong_projection_schema():
    with pytest.raises(AIOfficeDashboardError, match="schema"):
        load_ai_office_dashboard_state(lambda: {"schema_version": "wrong.v1"})


def test_client_maps_stale_projection_to_visible_stale_state():
    state = load_ai_office_dashboard_state(lambda: sample_projection(freshness="STALE"))
    assert state.freshness == "STALE"
    assert state.system_status_label == "상태 확인 필요"
```

- [ ] **Step 2: Run tests and confirm missing modules**

```bash
python -m pytest tests/test_ai_office_dashboard_client.py -q
```

- [ ] **Step 3: Implement strict pydantic models and a transport-injected client**

```python
class AIOfficeDashboardState(BaseModel):
    schema_version: Literal["orchestration.operations-read-model.v1"]
    project_id: str
    run_id: str
    normalized_state: str
    human_state: str
    freshness: str
    progress: int | None = None
    progress_source: str = ""
    outcome: str = ""
    impact: str = ""
    next_step: str = ""
    approval_required: bool = False
    incidents: list[dict[str, object]] = Field(default_factory=list)
    sources: list[dict[str, object]] = Field(default_factory=list)
```

`ai_office_client.py` accepts an injected reader; it does not open raw Harness state files itself. Production wiring reads only the frozen operations projection snapshot or API binding configured for Track A.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_ai_office_dashboard_client.py -q
```

- [ ] **Step 5: Commit**

```bash
git add webapp/ai_office_client.py webapp/ai_office_models.py tests/test_ai_office_dashboard_client.py
git commit -m "feat: add bounded AI Office dashboard client"
```

### Task 4: Add Company/Home and List Operations renderer as a separate module

**Files:**
- Create: `webapp/ai_office_dashboard.py`
- Test: `tests/test_ai_office_dashboard_html.py`

**Interfaces:**
- Consumes: `AIOfficeDashboardState` plus optional office/team/agent/work projection lists from the same public read model extension.
- Produces: `build_ai_office_dashboard_html(state) -> str`.

- [ ] **Step 1: Write failing human-first HTML tests**

```python
def test_home_prioritizes_human_operations_information(sample_dashboard_state):
    html = build_ai_office_dashboard_html(sample_dashboard_state)
    for text in ("AI OFFICE", "전체 상태", "현재 업무", "승인", "문제", "다음 단계"):
        assert text in html
    for raw_id in ("TASK-015", "GATE-C", "CP-018"):
        assert raw_id not in html.split('data-view="advanced"', 1)[0]


def test_status_uses_text_not_color_only(sample_dashboard_state):
    html = build_ai_office_dashboard_html(sample_dashboard_state)
    assert "작업 중" in html
    assert "aria-label" in html
```

- [ ] **Step 2: Run and confirm failure**

```bash
python -m pytest tests/test_ai_office_dashboard_html.py -q
```

- [ ] **Step 3: Implement Home/List view with Outcome/Status/Impact/Action/Next**

```python
def build_ai_office_dashboard_html(state: AIOfficeDashboardState) -> str:
    seed = _safe_json(state.model_dump())
    return DASHBOARD_TEMPLATE.replace("__AI_OFFICE_STATE__", seed)
```

`DASHBOARD_TEMPLATE` contains semantic sections for Company overview, Office cards, current work, approval count, issue count, and navigation. Use text labels alongside status icons. Do not copy the 4,000-line JARVIS shell into this module.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_ai_office_dashboard_html.py -q
```

- [ ] **Step 5: Commit**

```bash
git add webapp/ai_office_dashboard.py tests/test_ai_office_dashboard_html.py
git commit -m "feat: add AI Office list operations dashboard"
```

### Task 5: Expose `/ai-office` and read-only operations API endpoints

**Files:**
- Modify: `webapp/app.py`
- Modify: `webapp/schemas.py`
- Test: `tests/test_ai_office_dashboard_api.py`

**Interfaces:**
- Consumes: `load_ai_office_dashboard_state`, `build_ai_office_dashboard_html`.
- Produces: `GET /ai-office`, `GET /api/ai-office/state`, `GET /api/ai-office/incidents`.

- [ ] **Step 1: Write failing FastAPI route tests**

```python
def test_dashboard_route_is_separate_from_jarvis_root(client):
    root = client.get("/")
    dash = client.get("/ai-office")
    assert root.status_code == 200
    assert dash.status_code == 200
    assert "JARVIS WebApp" in root.text
    assert "AI OFFICE" in dash.text


def test_state_endpoint_is_read_only_projection(client):
    response = client.get("/api/ai-office/state")
    assert response.status_code == 200
    assert response.json()["schema_version"] == "orchestration.operations-read-model.v1"
```

- [ ] **Step 2: Run and confirm 404s**

```bash
python -m pytest tests/test_ai_office_dashboard_api.py -q
```

- [ ] **Step 3: Add routes without changing existing `/` behavior**

```python
@app.get("/ai-office", response_class=HTMLResponse)
def ai_office_dashboard() -> HTMLResponse:
    state = load_ai_office_dashboard_state(_read_configured_operations_projection)
    return HTMLResponse(build_ai_office_dashboard_html(state))

@app.get("/api/ai-office/state")
def ai_office_state() -> dict[str, object]:
    return load_ai_office_dashboard_state(_read_configured_operations_projection).model_dump()
```

`_read_configured_operations_projection` reads only the configured Track A projection artifact/API response and validates it with the client; it must not traverse Harness runtime directories.

- [ ] **Step 4: Run new and existing WebApp routes**

```bash
python -m pytest tests/test_ai_office_dashboard_api.py tests/test_webapp_voice_api.py -q
```

- [ ] **Step 5: Commit**

```bash
git add webapp/app.py webapp/schemas.py tests/test_ai_office_dashboard_api.py
git commit -m "feat: expose AI Office dashboard routes"
```

### Task 6: Add Timeline, Workflow/Handoff, Agent Persona, and Office Manager projections

**Files:**
- Modify: `webapp/ai_office_models.py`
- Modify: `webapp/ai_office_dashboard.py`
- Test: `tests/test_ai_office_dashboard_workflow.py`

**Interfaces:**
- Consumes: normalized event/handoff evidence already present in the operations read model payload.
- Produces: timeline rows, workflow nodes, stable Agent Persona cards, projection-only Office Manager summary.

- [ ] **Step 1: Write failing evidence-only projection tests**

```python
def test_agent_persona_survives_provider_change():
    before = persona_from_projection(sample_projection(provider_ref="provider:a"))
    after = persona_from_projection(sample_projection(provider_ref="provider:b"))
    assert before.agent_id == after.agent_id
    assert before.display_name == after.display_name


def test_office_manager_has_no_execution_controls(sample_dashboard_state):
    html = build_ai_office_dashboard_html(sample_dashboard_state)
    manager_section = html.split('data-role="office-manager"', 1)[1].split('</section>', 1)[0]
    assert "execute" not in manager_section.lower()
    assert "provider" not in manager_section.lower()
```

- [ ] **Step 2: Run and confirm failure**

```bash
python -m pytest tests/test_ai_office_dashboard_workflow.py -q
```

- [ ] **Step 3: Add stable persona and timeline models**

```python
class AgentPersona(BaseModel):
    agent_id: str
    display_name: str
    team: str
    role: str
    status: str
    current_work: str
    current_action: str = ""
    last_result: str = ""
    next_handoff: str = ""
```

Timeline labels are deterministic translations of normalized runtime events. Office Manager text is composed from current phase/status/next-step facts; it does not call an LLM and has no execution callback.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_ai_office_dashboard_workflow.py -q
```

- [ ] **Step 5: Commit**

```bash
git add webapp/ai_office_models.py webapp/ai_office_dashboard.py tests/test_ai_office_dashboard_workflow.py
git commit -m "feat: visualize AI Office workflow and agent personas"
```

### Task 7: Add Issues & Recovery and Advanced technical detail views

**Files:**
- Modify: `webapp/ai_office_dashboard.py`
- Test: `tests/test_ai_office_dashboard_recovery.py`

**Interfaces:**
- Consumes: incident lifecycle, recovery state/evidence refs, source identity, technical refs from Track A.
- Produces: current issue cards, recovery timeline, historical incident section, Advanced detail drawer.

- [ ] **Step 1: Write failing current-vs-history tests**

```python
def test_historical_incident_not_counted_as_current_issue(sample_dashboard_state):
    state = sample_dashboard_state.model_copy(update={"incidents": [
        {"incident_id": "I1", "state": "HISTORICAL", "kind": "STALL_CONFIRMED", "impact": "none"}
    ]})
    html = build_ai_office_dashboard_html(state)
    assert "현재 문제 0" in html
    assert "STALL_CONFIRMED" in html.split('data-view="incident-history"', 1)[1]


def test_recovery_view_answers_impact_and_user_action(sample_dashboard_state):
    html = build_ai_office_dashboard_html(sample_dashboard_state)
    assert "업무 영향" in html
    assert "사용자 조치" in html
    assert "자동 복구" in html
```

- [ ] **Step 2: Run and verify failure**

```bash
python -m pytest tests/test_ai_office_dashboard_recovery.py -q
```

- [ ] **Step 3: Render current incident and history from lifecycle state, not file presence**

```python
current_incidents = [row for row in state.incidents if row.get("state") in {"OPEN", "ACKNOWLEDGED", "RECOVERING"}]
historical_incidents = [row for row in state.incidents if row.get("state") in {"RESOLVED", "SUPERSEDED", "HISTORICAL"}]
```

Advanced shows Task/Gate/Checkpoint/evidence/source release refs only after user opens it. It never displays credentials or raw authorization/effect payloads.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_ai_office_dashboard_recovery.py -q
```

- [ ] **Step 5: Commit**

```bash
git add webapp/ai_office_dashboard.py tests/test_ai_office_dashboard_recovery.py
git commit -m "feat: add AI Office issues recovery and advanced views"
```

### Task 8: Add explicit Approval actions with fail-closed existing-control binding

**Files:**
- Create: `webapp/ai_office_control.py`
- Modify: `webapp/app.py`
- Modify: `webapp/schemas.py`
- Test: `tests/test_ai_office_dashboard_control.py`

**Interfaces:**
- Consumes: `DashboardControlRequest`, injected existing-control submitter that accepts a canonical OCP remote envelope payload.
- Produces: `POST /api/ai-office/approvals/respond`; no direct OrchestrationEngine execution.

- [ ] **Step 1: Write failing no-binding and forbidden-import tests**

```python
def test_missing_control_binding_fails_closed(client):
    response = client.post("/api/ai-office/approvals/respond", json={
        "approval_ref": "approval:R1", "decision": "approve"
    })
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "CONTROL_UNAVAILABLE"


def test_control_module_has_no_direct_engine_or_effect_imports():
    text = Path("webapp/ai_office_control.py").read_text().lower()
    for forbidden in ("orchestrationengine", "full_mcp", "provider_router", "subprocess", "os.system"):
        assert forbidden not in text
```

- [ ] **Step 2: Run and confirm failure**

```bash
python -m pytest tests/test_ai_office_dashboard_control.py -q
```

- [ ] **Step 3: Implement a control-submitter protocol only**

```python
class DashboardControlRequest(BaseModel):
    approval_ref: str = Field(min_length=1)
    decision: Literal["approve", "deny"]

class AIOfficeControlBridge:
    def __init__(self, submit_existing_control: Callable[[Mapping[str, object]], Mapping[str, object]] | None) -> None:
        self._submit_existing_control = submit_existing_control

    def submit(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        if self._submit_existing_control is None:
            raise ControlUnavailableError("existing control path is not configured")
        return self._submit_existing_control(payload)
```

The production binding must build/submit an existing `RemoteOperatorEnvelopeV2` through the authorized OCP transport service; this module does not interpret approval authority itself.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_ai_office_dashboard_control.py tests/test_ai_office_dashboard_api.py -q
```

- [ ] **Step 5: Commit**

```bash
git add webapp/ai_office_control.py webapp/app.py webapp/schemas.py tests/test_ai_office_dashboard_control.py
git commit -m "feat: add fail-closed dashboard approval bridge"
```

### Task 9: Responsive and accessibility qualification for List Operations

**Files:**
- Modify: `webapp/ai_office_dashboard.py`
- Test: `tests/test_ai_office_dashboard_accessibility.py`

**Interfaces:**
- Consumes: existing Dashboard HTML/CSS.
- Produces: responsive list UI that keeps the five user-priority facts visible.

- [ ] **Step 1: Write structural accessibility tests**

```python
def test_dashboard_has_landmarks_text_status_and_keyboard_controls(sample_dashboard_state):
    html = build_ai_office_dashboard_html(sample_dashboard_state)
    assert '<main' in html
    assert '<nav' in html
    assert 'aria-live="polite"' in html
    assert 'type="button"' in html
    for label in ("결과", "상태", "영향", "사용자 조치", "다음 단계"):
        assert label in html
```

- [ ] **Step 2: Run and confirm any missing structure**

```bash
python -m pytest tests/test_ai_office_dashboard_accessibility.py -q
```

- [ ] **Step 3: Add responsive CSS using existing WebApp design tokens where compatible**

```css
.ai-office-grid { display:grid; grid-template-columns:repeat(12,minmax(0,1fr)); gap:16px; }
@media (max-width: 900px) { .ai-office-grid { grid-template-columns:1fr; } }
.status-label { display:inline-flex; align-items:center; gap:.45rem; }
```

Do not encode state using color alone. Preserve visible text labels at all breakpoints.

- [ ] **Step 4: Run Dashboard and existing WebApp tests**

```bash
python -m pytest \
  tests/test_ai_office_dashboard_client.py \
  tests/test_ai_office_dashboard_html.py \
  tests/test_ai_office_dashboard_api.py \
  tests/test_ai_office_dashboard_workflow.py \
  tests/test_ai_office_dashboard_recovery.py \
  tests/test_ai_office_dashboard_control.py \
  tests/test_ai_office_dashboard_accessibility.py \
  tests/test_webapp_voice_api.py -q
```

- [ ] **Step 5: Commit**

```bash
git add webapp/ai_office_dashboard.py tests/test_ai_office_dashboard_accessibility.py
git commit -m "feat: harden AI Office dashboard accessibility"
```

### Task 10: Stop at the 3D renderer qualification gate

**Files:**
- Plan: `docs/superpowers/plans/2026-09-24-ai-office-3d-renderer-qualification.md`
- No production 3D file is created in this task.

**Interfaces:**
- Consumes: frozen operations read-model schema and approved Dashboard visual requirements.
- Produces: renderer qualification evidence required before 3D production integration.

- [ ] **Step 1: Run the renderer qualification plan**

```text
Required output: 3D_RENDERER_QUALIFICATION=PASS with one selected production renderer contract.
```

- [ ] **Step 2: Verify the selection evidence binds the same read model**

```text
Required schema: orchestration.operations-read-model.v1
Required authority: VISUALIZATION_ONLY
```

- [ ] **Step 3: Do not add production 3D code before renderer selection**

```bash
git diff --name-only | grep -E 'three|webgl|3d|spatial' && exit 1 || true
```

Expected: no production 3D file in this plan before the separate qualification gate.

### Task 11: Dashboard Track qualification

**Files:**
- Create during execution in JARVIS worktree: `docs/AI_OFFICE_DASHBOARD_QUALIFICATION_20260924.json`
- Evidence mirror in Harness implementation history after fan-in.

**Interfaces:**
- Consumes: Tasks 1-9.
- Produces: `DASHBOARD_TRACK=PASS` for List/Workflow/Recovery/Advanced; 3D integration remains gated by selected renderer plan.

- [ ] **Step 1: Run all Dashboard tests**

```bash
python -m pytest tests/test_ai_office_dashboard_*.py -q
```

- [ ] **Step 2: Run existing WebApp regression**

```bash
python -m pytest tests/test_webapp_voice_api.py tests/test_webapp_voice_adapters.py tests/test_webapp_voice_transcript.py -q
```

- [ ] **Step 3: Verify no direct authority imports in Dashboard modules**

```bash
python - <<'PY2'
from pathlib import Path
for path in Path('webapp').glob('ai_office_*.py'):
    text=path.read_text().lower()
    for forbidden in ('orchestrationengine', 'provider_router', 'full_mcp', 'subprocess.run', 'os.system'):
        assert forbidden not in text, (path, forbidden)
PY2
```

- [ ] **Step 4: Record qualification evidence**

```json
{
  "schema_version": "jarvis.ai-office-dashboard-qualification.v1",
  "status": "PASS",
  "primary_view": "LIST_OPERATIONS",
  "read_schema": "orchestration.operations-read-model.v1",
  "direct_execution_authority": false,
  "three_d_state": "GATED_BY_RENDERER_QUALIFICATION"
}
```

- [ ] **Step 5: Commit**

```bash
git add docs/AI_OFFICE_DASHBOARD_QUALIFICATION_20260924.json
git commit -m "test: qualify AI Office list operations dashboard"
```
