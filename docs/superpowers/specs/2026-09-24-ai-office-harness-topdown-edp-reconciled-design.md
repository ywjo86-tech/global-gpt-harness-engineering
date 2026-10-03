# AI Office Harness Top-Down EDP Reconciled Design

- Date: 2026-09-24
- Status: WRITTEN SPEC FOR USER REVIEW
- Source baseline: `origin/main@c591b01e8a1d9d9bb2dc438ca85f6c2ffcc79a03`
- Target: AI Office Harness 고도화 + Operations Dashboard + External Capability Lifecycle + Reporting & Records
- Design mode: additive extension of the declared stable operational baseline
- Core rule: existing canonical authorities are preserved; new layers consume or extend them and must not create parallel execution authority.

## 1. Purpose

AI Office Harness는 이미 `AI_OFFICE_HARNESS_FINAL_OPERATIONAL_BASELINE`이 선언된 운영 기준선이다. 이번 고도화는 미완성 Core를 다시 만드는 작업이 아니라 현재 기준선의 기능을 재사용하여 사람 중심 운영 화면, 외부 Capability 계약 수명주기, 이중 보고서 기록 체계를 얇게 추가하는 작업이다.

성공 기준은 다음 네 가지다.

1. 기존 Full Plan / Provider Router / Execution Gateway / Full MCP / Continuity 권한과 Runtime Truth를 보존한다.
2. 현재 존재하는 Capability inventory/discovery/evaluation 및 Operator Console/Jarvis Bridge/AI Office reporting을 중복 구현하지 않는다.
3. Dashboard는 canonical runtime facts를 사람이 이해할 수 있는 운영 모델로 투영하되 새로운 authority가 되지 않는다.
4. 주요 완료 결과는 하나의 verified `REPORT_DATA`에서 Human Report와 LLM Report를 파생하고 각각 Notion과 LLMWiki에 기록한다.

## 2. Authority and Source Baseline

현재 설계의 authority stack은 다음 순서로 고정한다.

1. Current explicit user decisions
2. `docs/DEVELOPMENT_PLAN.txt`의 current operational state projection
3. `docs/harness/CURRENT_OPERATIONAL_STATE.json`
4. `origin/main@c591b01...`의 verified runtime source
5. 기존 승인·종료 evidence와 regression tests
6. 이전 2026-09-23 design의 사용자 확정 요구사항

이전 design branch는 current remote main보다 302 commits 뒤처져 있으므로 요구사항 source로만 사용하고 구현 현실의 authority로 사용하지 않는다.

## 3. Existing Stable Authorities — KEEP

다음 권한은 변경하지 않는다.

- `Full Plan`: task decomposition, dependency, final task-to-agent assignment, fan-in
- `Multi-Provider Router`: provider/model selection
- `MPRF`: provider runtime, provider health/checkpoint/observability
- `Production Execution Gateway`: execution entry and state-changing execution admission
- `Full MCP`: canonical side-effect authorization/effect/reconciliation/evidence
- `AI Office`: office workflow/governance/state/context/report projection/recovery coordination
- `OCPv2`: remote operator transport/inspection/authorized activation path
- `GPT_OPERATOR`: canonical logical operator authority
- `JARVIS`: interaction/context/briefing/approval UX; not canonical execution authority

`Logical Operator`는 UI/architecture상의 추상 역할명으로만 사용하며 새로운 runtime principal을 만들지 않는다. 실제 authority label은 기존 `GPT_OPERATOR`를 유지한다.

## 4. Top-Down Domain Classification

| Domain | Current implementation | Decision | New work |
|---|---|---|---|
| Governance & Policy | strong | KEEP / EXTEND | reporting/capability lifecycle policy only |
| Contract & Schema | strong | KEEP / EXTEND | read-model/report/lifecycle schemas |
| Planning & Task Control | mature Full Plan | KEEP | none |
| Scheduling & Dispatch | queue/retry/timeout/backpressure | KEEP | projection only |
| Multi-Provider Routing | Router/MPRF/PH7 | KEEP | dashboard projection only |
| Execution & Effect | Gateway + Full MCP | KEEP | external capability effect bridge rules |
| Continuity & Recovery | checkpoint/resume/reconcile | KEEP / EXTEND | external contract lineage/drain refs |
| Observability & Diagnosis | source adapters/attention/diagnostic intelligence | KEEP / MERGE | incident lifecycle normalization |
| Operations & Dashboard | operator console + jarvis bridge exist | MERGE / EXTEND | canonical operations read model + human views |
| Security & Runtime Integrity | strong | KEEP | no weakening |
| Quality & Release | existing qualification/release | KEEP | add new feature qualification |
| External Capability Ecosystem | inventory/discovery/evaluator/adoption exist | MERGE / EXTEND | operational lifecycle registry |
| Reporting & Records | Office runtime report exists | SPLIT / EXTEND | records/report contract and sinks |

## 5. Reuse Map — No Duplicate Core

### 5.1 Existing capability path

Reuse:

- `runtime/ai_office/capability_governance.py`
- `runtime/orchestrator/capability_inventory.py`
- `runtime/orchestrator/skill_discovery.py`
- `runtime/orchestrator/candidate_content_resolver.py`
- `runtime/orchestrator/skill_candidate_evaluator.py`
- `runtime/orchestrator/skill_adoption.py`
- `runtime/orchestrator/skill_use_authorization.py`
- `runtime/orchestrator/operational_capability.py`

Do not create a second generic Capability Registry/Gateway that repeats inventory, discovery, candidate risk evaluation, or authorization.

### 5.2 Existing operations projection path

Reuse:

- `runtime/orchestrator/operator_console_projection.py`
- `runtime/jarvis_bridge/*`
- `runtime/ai_office/reporting.py`
- existing public observability/recovery contracts

Do not create a second raw-runtime interpreter. New Dashboard read models must derive from bounded existing projections and canonical state/evidence sources.

### 5.3 Existing reporting semantics

`OfficeReportV1` remains an operational status/KPI projection. New long-term work records use a separate contract; the two concepts are not merged under one ambiguous schema.

## 6. New Architecture — Thin Additive Layers

```text
Canonical Runtime Truth
  Full Plan / AI Office / OCP / Router / MPRF / Gateway / Full MCP
                |
                +--> Existing bounded projections
                |      Operator Console / Jarvis Bridge / Office Status
                |
                +--> Existing capability governance
                       Inventory / Discovery / Evaluation / Adoption

Existing bounded projections
        ↓
Canonical Operations Read Model          [ADD]
        ↓
Human Operations Projection              [ADD]
   ├─ List Operations View
   ├─ 3D Office View
   └─ Advanced Technical View

Existing capability governance
        ↓
External Capability Lifecycle Contract   [ADD]
        ↓
Activation / Health / Drain / Replace / Retire

Verified Result + Evidence
        ↓
REPORT_DATA Record                       [ADD]
   ├─ Human Renderer → Notion adapter
   └─ LLM Renderer   → LLMWiki adapter
```

## 7. Canonical Operations Read Model

A single normalized read model sits between current bounded projections and all human UI views. It is non-authoritative and read-first.

Minimum fields:

- `schema_version`
- `source_component`
- `source_version`
- `source_head`
- `source_timestamp`
- `project_id`, `run_id`, `task_id`, `gate_id`
- `raw_state`, `normalized_state`, `human_state`
- `progress`, `progress_source`
- `current_work`, `outcome`, `impact`, `next_step`
- `approval_required`, `approval_refs`
- `incident_state`, `recovery_state`
- `checkpoint_refs`, `evidence_refs`
- `last_updated`, `freshness`

Unknown fields from lower layers are not automatically exposed. Secrets, provider credentials, raw authorization payloads, and direct effect payloads stay excluded.

## 8. Multi-Runtime Source Separation

Harness stable runtime과 OCP successor runtime은 서로 다른 release SHA를 사용할 수 있다. Dashboard와 read model은 동일 SHA를 가정하지 않는다.

모든 runtime-derived projection은 최소 다음을 포함한다.

- `source_component`
- `source_version/release`
- `source_head` when available
- `source_timestamp`
- `freshness`

UI는 component-specific release mismatch를 자동 장애로 판정하지 않는다. 실제 contract incompatibility 또는 stale/failed source가 있을 때만 issue로 승격한다.

## 9. Human Operations Model

정보 계층은 다음과 같다.

```text
AI OFFICE
├ Company
├ Office
├ Team
├ Agent Persona
├ Work / Task
└ Technical Detail
```

Projection identity와 execution identity를 분리한다.

- Project → Office
- Phase/Task Group → Team
- Logical Role → Agent Persona
- Current Task → Work
- Runtime Event → Activity/Timeline

Agent Persona는 Worker, Provider, Model 그 자체가 아니다. Provider 변경을 Agent 교체처럼 표시하지 않는다.

## 10. Status and Progress Integrity

상태는 `raw_state → normalized_state → human_state`로 변환한다.

대표 normalized state:

- `QUEUED`
- `PLANNING`
- `RUNNING`
- `WAITING_DEPENDENCY`
- `WAITING_APPROVAL`
- `PAUSED`
- `STALLED`
- `RECOVERING`
- `FAILED`
- `COMPLETED`
- `UNKNOWN`
- `STALE`

숫자 진행률은 explicit progress, milestone, known task count, Gate count 등 검증 가능한 근거가 있을 때만 사용한다. 근거가 없으면 단계/상태 텍스트를 사용한다.

## 11. Incident Lifecycle and Freshness

Historical attention/dead-letter evidence를 현재 장애처럼 표시하지 않도록 incident lifecycle을 first-class read-model로 둔다.

```text
OPEN
 → ACKNOWLEDGED
 → RECOVERING
 → RESOLVED
 → HISTORICAL
```

대체된 사건은 `SUPERSEDED`를 사용할 수 있다.

Incident projection 최소 필드:

- `incident_id`
- `kind`
- `opened_at`
- `last_observed_at`
- `resolved_at`
- `state`
- `current_state_ref`
- `superseded_by`
- `impact`
- `user_action_required`
- `evidence_refs`

Dashboard는 단순 pending-file 존재만으로 현재 장애를 판정하지 않는다. canonical current state와 freshness를 교차 확인한다.

## 12. Dashboard Definition

Harness Dashboard는 새로운 Orchestrator가 아니다.

> `Read-first Human Operations Projection + Existing-policy-based Explicit Action Surface`

List/3D/Advanced는 동일 Canonical Operations Read Model을 사용한다. Dashboard 조회는 기본적으로 LLM 호출을 발생시키지 않는다.

Action은 기존 OCP/remote envelope/Governance/Approval/Execution Gateway 경로로만 전달한다. UI-specific execution shortcut을 만들지 않는다.

## 13. External Capability Operating Principle

정책은 `ABSORB LAST`다.

```text
SEARCH → EVALUATE → CONTRACT → ADAPT → SANDBOX → QUALIFY
       → ACTIVATE → MONITOR → REPLACE/RETIRE
```

Harness가 소유하는 것은 외부 구현 코드가 아니라 capability contract다.

- capability identity/version
- input/output contract
- permission/risk class
- side-effect policy
- timeout/retry/health policy
- evidence requirements
- compatibility
- lifecycle state

## 14. Assignment vs Capability Resolution Authority

외부 Agent를 `Agent`로 등록해 Task를 수행시키는 경우 최종 assignment는 Full Plan만 결정한다.

Capability layer는 다음만 수행한다.

- requirement에 맞는 capability 후보 열거
- contract eligibility 검증
- health/risk/version facts 제공
- 선택 가능한 endpoint/tool 후보 제공

Capability layer는 `final_assignee`를 생성하지 않는다.

외부 시스템을 Tool/Capability Endpoint로 소비하는 경우에도 호출 권한은 active task의 approved capability/effect scope 안에서만 유효하다.

## 15. External Capability Lifecycle

Discovery/evaluation 이후 운영 수명주기를 별도 계약으로 추가한다.

```text
DISCOVERED → CANDIDATE → SANDBOX → QUALIFIED → ACTIVE
                                                |
                             DEGRADED / QUARANTINED
                                                |
                              DISABLE_NEW_ASSIGNMENT
                                                |
                                         DRAINING
                                                |
                       SUPERSEDED / DEPRECATED → RETIRED
```

`ACTIVE → RETIRED` 직접 전환은 active dependency가 없는 경우에만 허용한다.

Lifecycle facts:

- quality/success rate
- reliability/latency
- usage
- cost/quota
- security posture
- version freshness
- maintenance activity
- overlap/replacement relationship
- active dependency count

## 16. Continuity Binding for External Capability

Running task/checkpoint는 외부 capability lifecycle 변경으로 깨지면 안 된다.

Checkpoint/resume evidence에 필요한 경우 다음 lineage를 기록한다.

- `capability_contract_id`
- `capability_contract_version`
- `endpoint_version`
- `activation_epoch`

Retirement sequence:

```text
DISABLE_NEW_ASSIGNMENT
 → DRAINING
 → ACTIVE_DEPENDENCY_COUNT=0
 → RETIRED
```

이미 실행 중인 작업의 lineage를 삭제하거나 암묵적으로 새 endpoint로 바꾸지 않는다. 교체는 명시적 compatibility/rebind 정책을 통과해야 한다.

## 17. External Side-Effect Boundary

External capability의 read/analysis와 state change를 분리한다.

```text
READ / ANALYSIS
  → approved adapter/MCP read path

STATE CHANGE
  → proposal / intent
  → Production Execution Gateway
  → Full MCP canonical effect path
```

외부 endpoint가 shell/git/delete/deploy/restart 등의 기능을 제공하더라도 active task scope와 Full MCP effect authority를 우회할 수 없다.

직접 side effect 예외가 필요한 경우 기존 approved contract에 명시적 exception이 있어야 하며 default는 deny다.

## 18. Reporting & Records — Semantic Split

두 종류의 reporting을 분리한다.

1. `Operations Projection Reporting`: existing `OfficeStatusProjectionV1`, `OfficeKPIProjectionV1`, `OfficeReportV1`
2. `Work Record Reporting`: new `REPORT_DATA` + human/LLM renderers + storage receipts

Operations Projection은 현재 상태 조회용이고 Work Record는 의미 있는 완료/판단의 장기 기록이다.

## 19. REPORT_DATA Contract

`REPORT_DATA`는 Notion/LLMWiki 두 렌더러의 유일한 공통 사실 기준이다.

최소 필드:

- `report_id`, `schema_version`
- `report_type`, `target`, `date`, `purpose`
- `status`, `progress`, `summary`
- `completed`, `in_progress`
- `issues`, `impact`, `user_action`
- `next_actions`, `final_state`
- `technical_references`, `evidence_refs`
- `execution_status`, `verification_status`
- `human_report_status`, `llm_report_status`
- `final_completion_status`

확인되지 않은 사실은 생성하지 않는다. Report는 canonical logs/tests/evidence를 대체하지 않는다.

## 20. Human Report → Notion

고정 사용자 보고서 구조:

```text
보고서 제목
작성일

■ 보고서 작성 목적
[한 줄 목적문]

■ 보고서 요약
[5~8개의 짧은 핵심 문장]

■ 1. 현재 상태
■ 2. 완료된 작업
■ 3. 현재 진행 또는 결과
■ 4. 문제 및 영향
■ 5. 사용자 확인 사항
■ 6. 다음 작업
■ 7. 최종 상태
■ 8. 기술 참고 정보  # 필요한 경우에만
```

목적은 반드시 한 문장이고 요약 바로 위에 위치한다. 기본 언어는 쉬운 한국어이며 기술 용어는 필요한 경우 쉬운 설명을 병기한다.

Notion은 사용자 공식 보고서 저장소이지만 Harness Runtime Truth 또는 canonical AI memory source가 아니다.

## 21. LLM Report → LLMWiki

고정 heading:

```text
# REPORT TITLE
## REPORT_META
## PURPOSE
## READ_WHEN
## SUMMARY
## CURRENT_STATE
## COMPLETED
## IN_PROGRESS
## ISSUES
## USER_ACTION
## NEXT
## FINAL_STATE
## TECHNICAL_REFERENCES
```

`REPORT_META`는 최소 `report_type`, `target`, `date`, `status`, `issue_detected`, `user_action_required`를 포함한다.

AI selective read order:

`REPORT_META → PURPOSE → READ_WHEN → relevance decision → SUMMARY → necessary detail`

문서 선택 우선순위:

`target → PURPOSE → READ_WHEN → report_type → date → SUMMARY`

LLMWiki는 AI 검색/복구용 공식 보고서 archive다. Runtime Truth가 아니며 기존 safe-write scope와 destructive-operation 금지를 유지한다.

## 22. Memory Authority Separation

장기 컨텍스트와 보고서 저장 목적을 분리한다.

```text
Runtime Truth
  → canonical Harness state/evidence

Project Continuity / durable project context
  → Obsidian-compatible memory / PCM policy

Human Report Archive
  → Notion

AI Report Knowledge Archive
  → LLMWiki
```

Notion/LLMWiki 저장 성공이 runtime source-of-truth를 변경하지 않는다. PCM/Obsidian과 report archive의 역할을 합치지 않는다.

## 23. Completion Semantics

Execution completion과 Office final completion을 분리한다.

```text
execution_status
  ↓
verification_status
  ↓
recording_status
  ├─ human_report_status
  └─ llm_report_status
  ↓
final_completion_status
```

`completion_report` 대상의 `final_completion_status=COMPLETE`는 원칙적으로 다음이 모두 성립할 때만 가능하다.

- execution success
- verification success
- REPORT_DATA confirmed
- Notion save verified
- LLMWiki save verified

보고서 저장 실패는 execution success를 failure로 바꾸지 않는다. 실패한 report/save 단계만 idempotent retry한다.

`decision_or_incident_report`는 사용자 승인 필요/장애/복구 실패를 기록하며 report 생성 자체가 execution completion을 의미하지 않는다.

긴급 장애는 안전 확보/복구가 보고서 생성보다 우선한다.

## 24. Report Storage Adapter Policy

새로운 MCP 또는 Agent를 전제로 하지 않는다.

구현 시 순서:

1. existing Notion connection/write capability 확인
2. existing LLMWiki safe-write API/adapter 확인
3. 요구 contract를 만족하면 재사용
4. 부족한 경우 External Capability Contract 방식으로 adapter를 추가
5. Harness Core 내부에 provider-specific storage implementation을 흡수하지 않음

모든 저장은 `report_id + destination_key` idempotency를 사용하고 각 destination의 receipt/evidence를 독립 보존한다.

## 25. Report Trigger Policy

보고서는 의미 있는 완료/판단 단위에만 생성한다.

- 사용자 요청 작업 완료
- 중요 구현/프로젝트 단계 완료
- 중요 검증 완료
- 설계 검토 완료
- 장애 진단/복구 완료 또는 실패
- 중요 운영 점검/설정 변경 완료
- 사용자 승인/판단이 필요한 중요 상태

세부 Task마다 자동 생성하지 않는다.

## 26. OCP Boundary

OCP는 현재 remote operator/inspection/activation path의 일부다. Dashboard/Reporting/Capability lifecycle을 이유로 OCP protocol을 임의 변경하지 않는다.

OCP successor runtime과 Harness stable runtime은 독립 release identity를 가질 수 있으며 read model이 source identity를 명시적으로 표현한다.

## 27. Orphaned Process / Self-Diagnosis Requirement

현재 진단에서 테스트용 paused canary가 parent/temporary state ownership을 잃은 채 sleeping process로 남을 수 있음을 확인했다.

이번 고도화는 production process를 무조건 kill하는 기능을 만드는 것이 아니라 다음 read/diagnostic contract를 추가해야 한다.

- process owner reference
- state/lock existence
- expected lifecycle state
- last semantic progress
- orphan suspicion reason
- recommended action
- cleanup authorization requirement

자동 cleanup은 별도 권한과 false-positive 방지 evidence 없이 수행하지 않는다.

## 28. Dashboard Views

1. Home — 전체 상태, active work, approvals, issues
2. Offices — Office list/detail, 3D Office
3. Work — active/workflow/timeline/completed
4. Agents — role/team/current work/workload
5. Approvals
6. Issues & Recovery
7. Advanced — Harness/Full Plan/Provider/Gate/Checkpoint/MCP/Evidence/Logs/Capability Lifecycle

List Operations View를 먼저 구현하고 동일 read model을 3D에 연결한다.

## 29. Implementation Order

### Track A — Operations Read Model

A0 current source/evidence audit
A1 canonical operations read-model schema
A2 source adapters/normalization
A3 incident lifecycle/freshness
A4 projection store/API
A5 list operations UI
A6 approvals/issues/recovery
A7 3D binding
A8 advanced view

### Track B — External Capability Lifecycle

B0 current capability pipeline audit
B1 lifecycle contract/schema
B2 activation/health state
B3 continuity lineage binding
B4 disable-new-assignment/drain/retire
B5 replacement/supersession
B6 qualification/dashboard projection

### Track C — Reporting & Records

C0 current report/evidence/storage capability audit
C1 REPORT_DATA schema
C2 verified builder
C3 Human renderer
C4 Notion adapter integration
C5 LLM renderer
C6 LLMWiki safe-write integration
C7 cross-render consistency
C8 receipts/idempotent retry
C9 Office final-completion integration
C10 selective-read policy

Tracks may be implemented independently after their shared contract boundaries are frozen. No track may create a parallel assignment/provider/effect authority.

## 30. Acceptance Criteria

### Operations

- O-AC01: Home에서 사용자가 전체 상태, active work, issue, approval need를 빠르게 이해할 수 있다.
- O-AC02: List/3D/Advanced는 동일 read model을 사용한다.
- O-AC03: stale/historical evidence를 current incident로 표시하지 않는다.
- O-AC04: Dashboard read does not require an LLM call.
- O-AC05: Dashboard action reuses existing authorized control path.
- O-AC06: source component/release/freshness가 projection에서 추적 가능하다.
- O-AC07: Dashboard failure cannot stop Harness execution.
- O-AC08: UI Persona creates no runtime authority.

### External Capability

- C-AC01: existing inventory/discovery/evaluator/adoption path is reused.
- C-AC02: external Agent final assignment remains Full Plan authority.
- C-AC03: state-changing external capability cannot bypass Execution Gateway/Full MCP by default.
- C-AC04: lifecycle supports activate/degrade/quarantine/drain/replace/retire.
- C-AC05: active checkpoint/resume lineage survives capability retirement or replacement.
- C-AC06: direct retire is blocked while active dependencies remain.
- C-AC07: lifecycle failure does not become Harness Core authority failure.

### Reporting

- R-AC01: REPORT_DATA is built from verified result/evidence.
- R-AC02: Human and LLM reports derive from the same REPORT_DATA.
- R-AC03: Human report has one-line purpose followed by 5–8 summary sentences.
- R-AC04: Human report uses easy Korean and saves to Notion when configured.
- R-AC05: LLM report uses fixed headings and saves through LLMWiki safe-write when configured.
- R-AC06: each save result has an independent receipt/evidence.
- R-AC07: save failure never rewrites execution success into execution failure.
- R-AC08: retry does not re-run canonical execution.
- R-AC09: completion_report final completion waits for both required report saves.
- R-AC10: decision_or_incident_report is not mistaken for execution completion.
- R-AC11: Notion/LLMWiki are not promoted to Runtime Truth.
- R-AC12: LLM selective read can reject irrelevant reports before full body read.

### Regression / Authority

- X-AC01: existing AI Office/Full Plan/Router/Continuity/Operator Console regression remains green.
- X-AC02: no new provider/model selection authority is introduced.
- X-AC03: no new final task assignment authority is introduced.
- X-AC04: no new direct canonical effect authority is introduced.
- X-AC05: no feature requires weakening existing authorization, source binding, evidence, or recovery contracts.

## 31. Cross-System Invariants

- INV-01: Full Plan remains the final task-to-agent assignment authority.
- INV-02: Provider Router remains provider/model selection authority.
- INV-03: Execution Gateway + Full MCP remain canonical state-changing effect authority path.
- INV-04: Dashboard is non-authoritative and read-first.
- INV-05: List/3D/Advanced derive from one operations read model.
- INV-06: external capability discovery/evaluation is not final assignment.
- INV-07: external capability lifecycle is drainable and replaceable.
- INV-08: running-task continuity lineage is preserved across capability lifecycle changes.
- INV-09: Office runtime report and long-term work record are separate contracts.
- INV-10: Human Report and LLM Report facts come from one REPORT_DATA.
- INV-11: report save retry never re-runs execution.
- INV-12: Notion, LLMWiki, JARVIS, and Dashboard do not become Runtime Truth authorities.
- INV-13: historical incidents are not projected as current without current-state evidence.
- INV-14: OCP and stable Harness release identities may differ and must be source-tagged.
- INV-15: orphan process cleanup requires explicit safe evidence/authorization; diagnosis alone does not mutate processes.

## 32. Explicit Non-Goals

This design does not authorize or require:

- replacing Full Plan
- replacing Provider Router/MPRF
- replacing Execution Gateway/Full MCP
- direct Dashboard execution shortcut
- new autonomous Office Manager agent
- automatic external Agent code absorption
- automatic external side-effect bypass
- provider-specific storage implementation inside Harness Core
- Notion/LLMWiki promotion to canonical runtime state
- automatic deletion/kill of suspected orphan processes
- OCP protocol redesign solely for Dashboard/Reporting

## 33. Design Closure Boundary

This spec is the reconciled architectural design only. It does not authorize product-code implementation, deployment, runtime activation, service restart, merge, push, or production cleanup.

Next permitted step after user review/approval of this written spec is a separate implementation plan using the established Full Plan / Harness workflow.


## 34. Resume Reconciliation Clarifications

This section restores requirements already established in the approved Top-down discussion; it is not a new authority layer.

### 34.1 Dual human entry surfaces

The human entry model is explicitly:

```text
User
 ├─ JARVIS
 └─ Harness Dashboard
        ↓
Shared governed request/control boundary
        ↓
Existing Harness authorities
```

JARVIS and Harness Dashboard may share a hosting process or WebApp server for operational simplicity, but they remain separate logical entry surfaces. Neither surface becomes a new operator, planner, provider router, or effect authority.

### 34.2 External Agent binding is MCP/Adapter-first

`ABSORB LAST` is normative. External Agents/Skills are not copied into Harness Core by default. The preferred binding order is:

`MCP endpoint → bounded Adapter → project-local Skill only when no qualified contract endpoint exists`.

The contract may expose only the safe subset of an external system. Conflicting, duplicate, privileged, destructive, deployment, credential, or unrelated capabilities are excluded from the active contract or routed through existing approval/effect authority. Local code installation remains a fallback path governed by the existing supply-chain/install/use-authorization pipeline.

### 34.3 Continuous capability watch without a resident Agent

External capability improvement is implemented as a lightweight periodic/on-demand watch workflow, not a new autonomous resident Agent. It reuses existing inventory/discovery/evaluation evidence and lifecycle records to identify gaps, degraded capabilities, overlap, stale versions, replacement candidates, and retirement candidates.

The watch may produce `SEARCH`, `REASSESS`, `REPLACEMENT_REVIEW`, `RETIREMENT_REVIEW`, or `NO_ACTION` recommendations. It cannot auto-install, auto-activate, silently rebind running work, or retire an active dependency. Scheduling cadence is configuration, not a planner/provider hardcode.

### 34.4 External design capability intake

List Operations UI, 3D Office, and later JARVIS visual/HCI upgrade work use the same External Capability policy. Design Agents/Skills may be researched and qualified through MCP/Adapter contracts, and their design artifacts may be absorbed. Their runtime implementation code is not absorbed into Harness Core merely because the design was accepted.

A qualified external design capability is optional: if no candidate passes governance/quality gates, the disposition may be `BUILD` using the approved visual requirements and existing WebApp assets.

### 34.5 Existing self-diagnosis is projected, not rebuilt

The enhancement reuses the existing `runtime/diagnostics/*`, attention/stall evidence, recovery evidence, source-binding facts, and runtime health facts. A bounded read-only Self-Diagnosis projection summarizes current health for Dashboard consumers. It does not add a second RCA/diagnostic framework and cannot kill processes, restart services, mutate Gate state, or perform recovery effects.

Additional acceptance criteria:

- O-AC09: `User -> JARVIS / Harness Dashboard` is preserved as two governed human entry surfaces.
- O-AC10: Self-Diagnosis view reuses existing diagnostic evidence and remains read-only.
- C-AC08: External Agent default binding is MCP/Adapter; local code absorption is fallback-only.
- C-AC09: Capability watch is lightweight and recommendation-only until existing governance authorizes lifecycle changes.
- C-AC10: List/3D design capability intake follows the same external lifecycle and effect boundaries.
- X-AC06: Failure or removal of an external capability cannot become a new Harness Core authority failure.

Additional invariants:

- INV-16: External capability implementation ownership stays outside Harness Core by default; Harness owns contracts and evidence.
- INV-17: Capability watch does not create a hidden autonomous Agent or parallel scheduler authority.
- INV-18: Design assistance may influence UI artifacts but never gains execution/control authority.
