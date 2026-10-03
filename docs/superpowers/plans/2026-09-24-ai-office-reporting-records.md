# AI Office Reporting & Records Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a verified `REPORT_DATA` work-record service that renders one human report and one AI Markdown report from the same facts, saves them through bounded external sinks, and makes Office final completion wait for required report receipts without ever re-running execution.

**Architecture:** Keep existing `runtime/ai_office/reporting.py` unchanged as operational status/KPI projection. New work-record modules live beside it with separate schemas. Storage is adapter-based: LLMWiki uses its existing safe create path; Notion uses an injected external capability contract rather than turning the existing JARVIS memory bridge into a write path or embedding provider-specific API code in Harness Core.

**Tech Stack:** Python 3.12 dataclasses, FastAPI-compatible HTTP client injection, Markdown renderers, unittest/pytest-compatible tests.

**Spec:** `docs/superpowers/specs/2026-09-24-ai-office-harness-topdown-edp-reconciled-design.md`

## Global Constraints

- `OfficeReportV1` stays an operations projection and is not renamed/reused as `REPORT_DATA`.
- Both reports derive from one immutable `ReportDataV1`.
- Unknown facts are omitted or represented as unknown; renderers cannot invent progress or conclusions.
- Human report purpose is exactly one sentence; summary supports 5–8 short sentences.
- AI report uses the fixed heading order from the approved spec.
- LLMWiki writes remain under `inbox/`, create/append safe-write rules remain intact, and destructive writes are not introduced.
- Existing JARVIS `NotionBridgeAdapter` remains memory dry-run only; do not silently convert it into an auto-write memory bridge.
- Notion report writes use a distinct report-sink capability and do not make Notion Runtime Truth.
- Report retries retry only render/save stages; execution and verification callbacks are never invoked by retry.
- `completion_report` and `decision_or_incident_report` have different completion semantics.

## Review Focus

1. Human and LLM renderers must remain semantically consistent for status, issue, action, and next-step facts.
2. One sink failure must preserve execution/verification success and only leave final completion at `WAITING_REPORT`.
3. Retrying a failed sink must not invoke execution/verification functions.
4. LLMWiki conflict/idempotency handling must not create duplicate report notes.
5. Notion sink absence must be explicit and recoverable; it must not silently mark a required report as saved.

---

### Task 1: Define immutable REPORT_DATA contract and verified builder

**Files:**
- Create: `runtime/ai_office/work_records.py`
- Test: `tests/test_ai_office_work_records.py`

**Interfaces:**
- Consumes: verified result mapping, verification mapping, evidence refs, report type.
- Produces: `ReportDataV1`, `build_report_data(verified_result, verification, report_type, evidence_refs)`.

- [ ] **Step 1: Write failing builder tests**

```python
def test_report_data_requires_verified_result_and_preserves_fact_source():
    report = build_report_data(
        verified_result={
            "target": "AI Commerce Intelligence",
            "date": "2026-09-24",
            "purpose": "AI Commerce Intelligence의 현재 구현 결과와 다음 작업을 확인하기 위한 보고서입니다.",
            "status": "in_progress",
            "progress": 72,
            "progress_source": "gate-count:5/7",
            "summary": ("시장조사 단계가 완료되었습니다.", "상품 후보 평가를 진행하고 있습니다.",
                        "현재 확인된 문제는 없습니다.", "현재 사용자 조치는 필요하지 않습니다.",
                        "다음 단계는 콘텐츠 제작입니다."),
            "completed": ("시장조사",),
            "in_progress": ("상품 후보 평가",),
            "issues": (),
            "impact": "현재 영향 없음",
            "user_action": "현재 사용자 조치 없음",
            "next_actions": ("콘텐츠 제작",),
            "final_state": "정상 진행",
            "technical_references": ("TASK-015",),
        },
        verification={"status": "PASS", "evidence_ref": "verification:015"},
        report_type="implementation_progress",
        evidence_refs=("evidence:015",),
    )
    assert report.verification_status == "PASS"
    assert report.progress == 72
    assert report.progress_source == "gate-count:5/7"
```

- [ ] **Step 2: Run and confirm missing module**

```bash
python -m unittest tests.test_ai_office_work_records -v
```

Expected: import failure.

- [ ] **Step 3: Implement `ReportDataV1` and builder validation**

```python
REPORT_DATA_SCHEMA_V1 = "ai-office.report-data.v1"

@dataclass(frozen=True, slots=True)
class ReportDataV1:
    report_id: str
    schema_version: str
    report_type: str
    target: str
    date: str
    purpose: str
    status: str
    progress: int | None
    progress_source: str
    summary: tuple[str, ...]
    completed: tuple[str, ...]
    in_progress: tuple[str, ...]
    issues: tuple[str, ...]
    impact: str
    user_action: str
    next_actions: tuple[str, ...]
    final_state: str
    technical_references: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    execution_status: str
    verification_status: str
    human_report_status: str = "PENDING"
    llm_report_status: str = "PENDING"
    final_completion_status: str = "WAITING_REPORT"
```

`build_report_data()` rejects verification states other than `PASS` for `completion_report`; `decision_or_incident_report` may be built from a verified incident state even when execution is incomplete.

- [ ] **Step 4: Run tests**

```bash
python -m unittest tests.test_ai_office_work_records -v
```

- [ ] **Step 5: Commit**

```bash
git add runtime/ai_office/work_records.py tests/test_ai_office_work_records.py
git commit -m "feat: add verified AI Office report data contract"
```

### Task 2: Implement deterministic Human and LLM renderers

**Files:**
- Create: `runtime/ai_office/report_renderers.py`
- Test: `tests/test_ai_office_report_renderers.py`

**Interfaces:**
- Consumes: `ReportDataV1`.
- Produces: `render_human_report(report) -> str`, `render_llm_report(report) -> str`.

- [ ] **Step 1: Write failing renderer-format tests**

```python
def test_human_report_has_one_line_purpose_then_summary(sample_report):
    text = render_human_report(sample_report)
    purpose = text.split("■ 보고서 작성 목적\n\n", 1)[1].split("\n\n", 1)[0]
    assert "\n" not in purpose
    assert "■ 보고서 요약" in text
    assert text.index("■ 보고서 작성 목적") < text.index("■ 보고서 요약")


def test_llm_report_uses_fixed_heading_order(sample_report):
    text = render_llm_report(sample_report)
    headings = ["## REPORT_META", "## PURPOSE", "## READ_WHEN", "## SUMMARY",
                "## CURRENT_STATE", "## COMPLETED", "## IN_PROGRESS", "## ISSUES",
                "## USER_ACTION", "## NEXT", "## FINAL_STATE", "## TECHNICAL_REFERENCES"]
    positions = [text.index(value) for value in headings]
    assert positions == sorted(positions)
```

- [ ] **Step 2: Run and confirm failure**

```bash
python -m unittest tests.test_ai_office_report_renderers -v
```

- [ ] **Step 3: Implement pure renderers with no LLM/network dependency**

```python
def render_human_report(report: ReportDataV1) -> str:
    sections = [
        report.target + " 보고서",
        "작성일: " + report.date,
        "■ 보고서 작성 목적\n\n" + report.purpose,
        "■ 보고서 요약\n\n" + "\n".join(report.summary),
    ]
    return "\n\n".join(sections) + "\n"
```

Complete all required human sections and the fixed LLM headings from the spec. `READ_WHEN` is derived deterministically from `report_type` and `target`, not from a new model call.

- [ ] **Step 4: Run tests and source guard**

```bash
python -m unittest tests.test_ai_office_report_renderers -v
python - <<'PY2'
from pathlib import Path
text=Path('runtime/ai_office/report_renderers.py').read_text().lower()
for forbidden in ('openai', 'provider_router', 'requests.post', 'llm_call'):
    assert forbidden not in text
PY2
```

- [ ] **Step 5: Commit**

```bash
git add runtime/ai_office/report_renderers.py tests/test_ai_office_report_renderers.py
git commit -m "feat: render human and LLM reports from one record"
```

### Task 3: Add cross-render fact consistency validation

**Files:**
- Modify: `runtime/ai_office/report_renderers.py`
- Create: `runtime/ai_office/report_consistency.py`
- Test: `tests/test_ai_office_report_consistency.py`

**Interfaces:**
- Consumes: `ReportDataV1`, human text, LLM Markdown.
- Produces: `validate_report_consistency(report, human_text, llm_text) -> ReportConsistencyResultV1`.

- [ ] **Step 1: Write failing mismatch test**

```python
def test_consistency_rejects_user_action_mismatch(sample_report):
    human = render_human_report(sample_report).replace("현재 사용자 조치 없음", "게시 승인 필요")
    llm = render_llm_report(sample_report)
    result = validate_report_consistency(sample_report, human, llm)
    assert result.status == "FAIL"
    assert "user_action" in result.mismatched_fields
```

- [ ] **Step 2: Run and verify failure**

```bash
python -m unittest tests.test_ai_office_report_consistency -v
```

- [ ] **Step 3: Implement deterministic anchor validation**

```python
@dataclass(frozen=True, slots=True)
class ReportConsistencyResultV1:
    status: str
    mismatched_fields: tuple[str, ...]
    report_id: str
```

Validate the rendered presence/meaning of `status`, `impact`, `user_action`, `next_actions`, issue presence, and report ID/meta. Do not perform semantic comparison via a model.

- [ ] **Step 4: Run tests**

```bash
python -m unittest tests.test_ai_office_report_consistency -v
```

- [ ] **Step 5: Commit**

```bash
git add runtime/ai_office/report_renderers.py runtime/ai_office/report_consistency.py tests/test_ai_office_report_consistency.py
git commit -m "feat: validate dual report fact consistency"
```

### Task 4: Define report sink protocol, receipts, and idempotency registry

**Files:**
- Create: `runtime/ai_office/report_sinks.py`
- Create: `runtime/ai_office/report_receipts.py`
- Test: `tests/test_ai_office_report_sinks.py`

**Interfaces:**
- Consumes: `report_id`, `destination_key`, rendered content, injected writer.
- Produces: `ReportSaveReceiptV1`, `save_once(sink, request, receipt_store)`.

- [ ] **Step 1: Write failing idempotency test**

```python
def test_same_report_destination_returns_existing_receipt_without_second_write(tmp_path):
    calls = []
    sink = FakeReportSink(lambda request: calls.append(request) or {"remote_ref": "r1", "digest": "a" * 64})
    store = ReportReceiptStore(tmp_path)
    request = ReportSaveRequest("RPT-1", "LLMWIKI", "inbox/RPT-1.md", "body")
    first = save_once(sink, request, store)
    second = save_once(sink, request, store)
    assert first == second
    assert len(calls) == 1
```

- [ ] **Step 2: Run and confirm failure**

```bash
python -m unittest tests.test_ai_office_report_sinks -v
```

- [ ] **Step 3: Implement sink protocol and sealed receipt**

```python
@dataclass(frozen=True, slots=True)
class ReportSaveRequest:
    report_id: str
    destination: str
    destination_key: str
    content: str

@dataclass(frozen=True, slots=True)
class ReportSaveReceiptV1:
    report_id: str
    destination: str
    destination_key: str
    remote_ref: str
    content_sha256: str
    saved_at: str
    status: str
    receipt_digest: str
```

The receipt store key is the canonical digest of `report_id + destination + destination_key`. Existing matching receipts short-circuit before writer invocation.

- [ ] **Step 4: Run tests**

```bash
python -m unittest tests.test_ai_office_report_sinks -v
```

- [ ] **Step 5: Commit**

```bash
git add runtime/ai_office/report_sinks.py runtime/ai_office/report_receipts.py tests/test_ai_office_report_sinks.py
git commit -m "feat: add idempotent report sink receipts"
```

### Task 5: Implement LLMWiki safe-write report sink adapter

**Files:**
- Create: `runtime/operator_transport/llmwiki_report_sink.py`
- Test: `tests/test_llmwiki_report_sink.py`
- Read-only compatibility target: `/home/ywjo/AI-Workspace/project-workspace/llmwiki-action-api/openapi/llmwiki-action.yaml`

**Interfaces:**
- Consumes: `ReportSaveRequest`, injected HTTP `post_json(path, body) -> Mapping`.
- Produces: sink result for `ReportSaveReceiptV1`.

- [ ] **Step 1: Write failing path and create-only tests**

```python
def test_llmwiki_sink_uses_inbox_create_only():
    calls = []
    sink = LLMWikiReportSink(lambda path, body: calls.append((path, body)) or {
        "path": body["path"], "sha256": "a" * 64, "size": len(body["content"].encode())
    })
    result = sink.save(ReportSaveRequest("RPT-1", "LLMWIKI", "inbox/RPT-1.md", "# report\n"))
    assert calls[0][0] == "/notes/create"
    assert calls[0][1]["path"] == "inbox/RPT-1.md"
    assert result["remote_ref"] == "inbox/RPT-1.md"
```

- [ ] **Step 2: Run and confirm failure**

```bash
python -m unittest tests.test_llmwiki_report_sink -v
```

- [ ] **Step 3: Implement a transport-injected adapter**

```python
class LLMWikiReportSink:
    destination = "LLMWIKI"

    def __init__(self, post_json: Callable[[str, Mapping[str, object]], Mapping[str, object]]) -> None:
        self._post_json = post_json

    def save(self, request: ReportSaveRequest) -> Mapping[str, object]:
        if not request.destination_key.startswith("inbox/") or not request.destination_key.endswith(".md"):
            raise ReportSinkError("LLMWiki report path must be an inbox Markdown note")
        payload = self._post_json("/notes/create", {"path": request.destination_key, "content": request.content})
        return {"remote_ref": str(payload["path"]), "digest": str(payload["sha256"])}
```

No delete/update endpoint is added to LLMWiki.

- [ ] **Step 4: Run adapter tests**

```bash
python -m unittest tests.test_llmwiki_report_sink -v
```

- [ ] **Step 5: Commit**

```bash
git add runtime/operator_transport/llmwiki_report_sink.py tests/test_llmwiki_report_sink.py
git commit -m "feat: add LLMWiki safe report sink adapter"
```

### Task 6: Implement Notion report sink as an external capability adapter, separate from memory bridge

**Files:**
- Create: `runtime/operator_transport/notion_report_sink.py`
- Test: `tests/test_notion_report_sink.py`
- Read-only boundary reference: `/home/ywjo/AI-Workspace/project-workspace/jarvis-assistant/knowledge-agent/memory/adapters/notion_bridge.py`

**Interfaces:**
- Consumes: `ReportSaveRequest`, active report-write capability ref, injected `create_report_page` callable.
- Produces: sink result containing page reference/digest; no memory synchronization.

- [ ] **Step 1: Write failing separation tests**

```python
def test_notion_report_sink_requires_active_report_capability():
    sink = NotionReportSink(capability_state="QUALIFIED", create_report_page=lambda payload: {})
    with pytest.raises(ReportSinkError, match="ACTIVE"):
        sink.save(ReportSaveRequest("RPT-1", "NOTION", "AI-OFFICE/RPT-1", "report"))


def test_notion_report_sink_never_imports_memory_bridge():
    source = Path("runtime/operator_transport/notion_report_sink.py").read_text().lower()
    assert "notion_bridge" not in source
    assert "memorycontract" not in source
```

- [ ] **Step 2: Run and confirm failure**

```bash
python -m pytest tests/test_notion_report_sink.py -q
```

- [ ] **Step 3: Implement injected external write capability**

```python
class NotionReportSink:
    destination = "NOTION"

    def __init__(self, *, capability_state: str, create_report_page: Callable[[Mapping[str, object]], Mapping[str, object]]) -> None:
        self.capability_state = capability_state
        self._create_report_page = create_report_page

    def save(self, request: ReportSaveRequest) -> Mapping[str, object]:
        if self.capability_state != "ACTIVE":
            raise ReportSinkError("Notion report-write capability must be ACTIVE")
        result = self._create_report_page({"report_id": request.report_id, "content": request.content})
        return {"remote_ref": str(result["page_ref"]), "digest": str(result["content_sha256"])}
```

The production binding is supplied by the External Capability Lifecycle; this module does not store tokens or call `api.notion.com` directly.

- [ ] **Step 4: Run tests and source guards**

```bash
python -m pytest tests/test_notion_report_sink.py -q
python - <<'PY2'
from pathlib import Path
text=Path('runtime/operator_transport/notion_report_sink.py').read_text().lower()
for forbidden in ('api.notion.com', 'notion_token', 'notion_bridge', 'memorycontract'):
    assert forbidden not in text
PY2
```

- [ ] **Step 5: Commit**

```bash
git add runtime/operator_transport/notion_report_sink.py tests/test_notion_report_sink.py
git commit -m "feat: add external Notion report sink boundary"
```

### Task 7: Add recording coordinator and completion semantics

**Files:**
- Create: `runtime/ai_office/reporting_coordinator.py`
- Test: `tests/test_ai_office_reporting_coordinator.py`

**Interfaces:**
- Consumes: `ReportDataV1`, two renderers, sink registry, receipt store.
- Produces: `RecordingOutcomeV1`; updates report statuses without mutating execution result.

- [ ] **Step 1: Write failing partial-save and retry tests**

```python
def test_one_sink_failure_preserves_execution_success_and_waits_for_report(coordinator, sample_report):
    outcome = coordinator.record(sample_report, fail_destination="LLMWIKI")
    assert outcome.execution_status == "SUCCESS"
    assert outcome.verification_status == "PASS"
    assert outcome.human_report_status == "SAVED"
    assert outcome.llm_report_status == "PENDING"
    assert outcome.final_completion_status == "WAITING_REPORT"


def test_retry_calls_only_pending_sink(coordinator, sample_report):
    first = coordinator.record(sample_report, fail_destination="LLMWIKI")
    second = coordinator.retry_pending(first.report_id)
    assert second.final_completion_status == "COMPLETE"
    assert coordinator.execution_call_count == 0
```

- [ ] **Step 2: Run and confirm failure**

```bash
python -m unittest tests.test_ai_office_reporting_coordinator -v
```

- [ ] **Step 3: Implement coordinator with no execution callback**

```python
@dataclass(frozen=True, slots=True)
class RecordingOutcomeV1:
    report_id: str
    execution_status: str
    verification_status: str
    human_report_status: str
    llm_report_status: str
    final_completion_status: str
    receipt_refs: tuple[str, ...]
```

`retry_pending(report_id)` reads the persisted report record and receipts, re-renders deterministically, and invokes only missing destinations.

- [ ] **Step 4: Run tests**

```bash
python -m unittest tests.test_ai_office_reporting_coordinator -v
```

- [ ] **Step 5: Commit**

```bash
git add runtime/ai_office/reporting_coordinator.py tests/test_ai_office_reporting_coordinator.py
git commit -m "feat: coordinate dual report completion and retry"
```

### Task 8: Implement LLMWiki selective-read index parsing

**Files:**
- Create: `runtime/ai_office/report_index.py`
- Test: `tests/test_ai_office_report_index.py`

**Interfaces:**
- Consumes: LLM report Markdown.
- Produces: `ReportIndexV1`, `extract_report_index(markdown)`, `is_report_relevant(index, target, intent)`.

- [ ] **Step 1: Write failing selective-read tests**

```python
def test_index_reads_meta_purpose_read_when_summary_without_detail(sample_report):
    markdown = render_llm_report(sample_report)
    index = extract_report_index(markdown)
    assert index.target == sample_report.target
    assert index.purpose == sample_report.purpose
    assert len(index.summary) >= 1
    assert "TECHNICAL_REFERENCES" not in index.raw_sections
```

- [ ] **Step 2: Run and confirm failure**

```bash
python -m unittest tests.test_ai_office_report_index -v
```

- [ ] **Step 3: Implement heading-bounded parser**

```python
@dataclass(frozen=True, slots=True)
class ReportIndexV1:
    report_type: str
    target: str
    date: str
    status: str
    purpose: str
    read_when: tuple[str, ...]
    summary: tuple[str, ...]
    raw_sections: tuple[str, ...] = ("REPORT_META", "PURPOSE", "READ_WHEN", "SUMMARY")
```

Stop parsing for index construction after `SUMMARY`; detailed sections are read only after relevance passes.

- [ ] **Step 4: Run tests**

```bash
python -m unittest tests.test_ai_office_report_index -v
```

- [ ] **Step 5: Commit**

```bash
git add runtime/ai_office/report_index.py tests/test_ai_office_report_index.py
git commit -m "feat: index AI reports for selective reading"
```

### Task 9: Track C qualification

**Files:**
- Create during execution: `docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/REPORTING_RECORDS_QUALIFICATION.json`

**Interfaces:**
- Consumes: Tasks 1-8.
- Produces: `REPORTING_RECORDS_TRACK=PASS` evidence.

- [ ] **Step 1: Run all new reporting suites**

```bash
python -m unittest \
  tests.test_ai_office_work_records \
  tests.test_ai_office_report_renderers \
  tests.test_ai_office_report_consistency \
  tests.test_ai_office_report_sinks \
  tests.test_llmwiki_report_sink \
  tests.test_ai_office_reporting_coordinator \
  tests.test_ai_office_report_index -v
python -m pytest tests/test_notion_report_sink.py -q
```

- [ ] **Step 2: Run existing operational-report regression**

```bash
python -m unittest tests.test_ai_office_reporting tests.test_ai_office_authority_negative_space -v
```

- [ ] **Step 3: Record split-authority evidence**

```json
{
  "schema_version": "gch.reporting-records-qualification.v1",
  "track": "C",
  "status": "PASS",
  "operations_report_schema_preserved": "ai-office.report.v1",
  "work_record_schema": "ai-office.report-data.v1",
  "execution_retry_on_report_failure": false,
  "notion_runtime_truth": false,
  "llmwiki_runtime_truth": false
}
```

- [ ] **Step 4: Commit qualification evidence**

```bash
git add docs/history/upgrades/2026-09-24-AI-OFFICE-HARNESS-IMPLEMENTATION/REPORTING_RECORDS_QUALIFICATION.json
git commit -m "test: qualify AI Office reporting and records"
```
