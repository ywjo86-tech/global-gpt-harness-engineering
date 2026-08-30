# Orchestration Runtime Work Items

## Purpose

This document records the current runtime work items for the local orchestration engine and the document classes affected by each item.

## Work Item 1: Summary Standardization

Goal:
- Standardize fan-in, collection, and stage-gate summary markdown so the runtime emits compact, comparable review artifacts.

Document classes:
- runtime source
- runtime templates
- runtime tests
- runtime docs

Change targets:
- `runtime/orchestrator/summary_rendering.py`
- `runtime/orchestrator/result_collector.py`
- `runtime/orchestrator/fanin.py`
- `runtime/orchestrator/stage_gate.py`
- `tests/test_summary_rendering.py`
- `docs/harness/orchestration-runtime-engine.md`

## Work Item 2: Resume Granularity

Goal:
- Keep `run_id` resume behavior from re-running completed threads while rerunning only missing outputs.

Document classes:
- runtime source
- runtime tests
- runtime docs

Change targets:
- `runtime/orchestrator/engine.py`
- `runtime/orchestrator/cli.py`
- `runtime/orchestrator/schemas.py`
- `tests/test_codex_runtime_flow.py`

## Work Item 3: Result Normalization

Goal:
- Normalize worker and Codex outputs into a canonical result schema regardless of synonym-heavy payloads.

Document classes:
- runtime source
- runtime templates
- runtime tests
- runtime docs

Change targets:
- `runtime/orchestrator/result_normalizer.py`
- `runtime/orchestrator/worker_runner.py`
- `runtime/orchestrator/codex_adapter.py`
- `runtime/orchestrator/result_collector.py`
- `runtime/orchestrator/fanin.py`
- `runtime/orchestrator/stage_gate.py`
- `tests/test_result_normalizer.py`
- `tests/test_codex_adapter_manual_mode.py`
- `tests/test_result_collector.py`

## Work Item 4: Jarvis Bridge

Goal:
- Expose orchestration state and command dispatch through a file-based bridge that Jarvis Assistant can consume later.

Document classes:
- runtime source
- runtime bridge package
- runtime tests
- runtime docs

Change targets:
- `runtime/jarvis_bridge/state_reader.py`
- `runtime/jarvis_bridge/command_dispatcher.py`
- `runtime/jarvis_bridge/approval_handler.py`
- `runtime/jarvis_bridge/event_stream.py`
- `runtime/jarvis_bridge/bridge_api.py`
- `runtime/orchestrator/task_queue.py`
- `runtime/orchestrator/worker_pool.py`
- `runtime/orchestrator/retry_policy.py`
- `runtime/orchestrator/failure_recovery.py`
- `runtime/orchestrator/approval_inbox.py`
- `runtime/orchestrator/audit_log.py`
- `tests/test_jarvis_bridge_api.py`
- `tests/test_task_queue.py`
- `tests/test_worker_pool.py`
- `tests/test_retry_policy.py`
- `tests/test_failure_recovery.py`
- `tests/test_approval_inbox.py`
- `tests/test_audit_log.py`
- `docs/harness/orchestration-jarvis-bridge.md`

## Work Item 5: Post-review Remediation Lineage

Goal:
- Seal a generic, immutable remediation lineage when an owned-file validation defect is found after a PASS hard-stop review.
- Preserve the parent run and review while binding the remediation reason, before/after owned-content evidence, canonical plan, approval, Gate, LV, and Git baseline.

Document classes:
- runtime source
- runtime tests
- runtime docs

Change targets:
- `runtime/orchestrator/lv_remediation.py`
- `runtime/orchestrator/cli.py`
- `tests/test_lv_remediation.py`
- `runtime/orchestrator/README.md`

Completion constraints:
- Existing package, preflight, worker, and review artifacts remain immutable.
- Remediation package, preflight, worker result, and independent review use a namespace separate from review attempts.
- Non-owned, staged, branch, HEAD, tree, index, parent-artifact, and content-binding drift fail closed.
- Every review result has `hard_stop=true`; PASS grants neither checkpoint, Gate completion, nor LV transition.

## Work Item 6: Global Gate Orchestrator

Goal:
- Provide one project-Codex entrypoint with one Gate approval, derived LV authorization, `SYSTEM_TRANSITION`, deterministic LV lifecycle, completeness ledger, structured handoff, isolation, and resume-safe execution.

Required requirements:
- R01-R25 from the approved global Gate orchestration stage remain mandatory and are not narrowed by this work item.
- `GATE_BY_GATE` is the default; `FULL_PLAN` requires final project validation plus explicit opt-in; `RESUME` starts only from a sealed checkpoint.
- Canonical plan SHA, Gate/LV order, owned files, completion criteria, tests, evidence, and status are fail-closed bindings.
- Lifecycle order is plan, package, preflight, worker, review, same-LV remediation when needed, checkpoint, Exit, and structured handoff.
- `SYSTEM_TRANSITION` is orchestration state, never a reused approval object. User intervention is limited to the next Gate, scope expansion, dangerous/external work, or a material unresolved choice.
- Project path, approval, state, artifact, run, branch/HEAD, environment, and secret namespaces are isolated.
- Existing global/project Skill, Agent, script, and tool assets are routed before any verified project-local capability-gap creation; global shared Skill/Agent changes remain separately approved.
- Existing projects receive read-only compatibility checks; new projects use declarative onboarding after `dev new` or `dev add`.

Canonical requirements:

R01. 사용자는 각 프로젝트의 `<alias> codex`만 사용자 진입점으로 사용하며 Harness Codex로 이동하지 않는다.

R02. 기본 운영모드 `GATE_BY_GATE`에서는 사용자가 Gate 시작을 한 번 승인한다.

R03. 승인된 Gate 아래의 모든 LV는 Gate 승인에서 파생된 `SYSTEM_TRANSITION` 권한으로 계획 순서에 따라 자동 진행한다.

R04. 다음 Gate는 기존 Gate 승인으로 자동 시작하지 않고 별도 사용자 승인을 기다린다.

R05. Wallet 검증 완료 후 사용자가 명시적으로 선택한 경우에만 `FULL_PLAN`을 활성화하며, 모든 Gate와 하위 LV를 canonical plan 순서로 자동 오케스트레이션한다.

R06. `RESUME` 모드는 영속 checkpoint와 evidence binding을 검증한 후 중단 지점에서 재개한다.

R07. 모든 실행은 프로젝트 canonical plan과 sealed plan SHA를 기준으로 한다.

R08. 계획의 범위 확장·누락·생략·제외·대체·순서변경·테스트 축소·문서화 축소를 금지한다.

R09. canonical plan의 모든 Gate·LV·요구사항을 completeness ledger에 전수 연결한다.

R10. completeness ledger는 각 plan item의 Gate/LV, 순서, owned files, Skill/Agent, tests, evidence SHA, status, checkpoint, Exit, handoff를 기록한다.

R11. 누락·중복·미연결·순서 위반·plan SHA drift가 발견되면 hard stop한다.

R12. 각 LV는 package → preflight → worker → independent review → remediation → checkpoint → Exit → structured handoff 순서로 실행한다.

R13. review와 remediation 결과에 관계없이 hard stop 경계를 유지하며 PASS를 Gate 완료나 다음 Gate 승인으로 자동 전용하지 않는다.

R14. 승인 범위 안의 구현·테스트 실패는 오케스트레이터가 자동 remediation하고 독립 재검증한다.

R15. 범위 확대, 파괴적 작업, 시스템 변경, 외부 작업, credential 작업, 비용·보안에 영향을 주는 중요 선택만 사용자에게 추가 승인을 요청한다.

R16. 기존 global/project Skill·Agent·script·tool·runtime을 먼저 inventory하고 관련 자산을 실제 실행에서 100% 활용한다.

R17. verified capability gap에서만 project-local Skill/Agent를 생성하며 이유, 입력·출력, permission, owned files, 종료조건과 tests를 기록한다.

R18. 전역 공유 Skill/Agent의 신규 생성 또는 변경은 별도 사용자 승인 없이 수행하지 않는다.

R19. 독립 작업만 병렬화하고 동일 파일을 여러 Agent가 동시에 수정하지 않으며 루트 오케스트레이터가 fan-in QA를 수행한다.

R20. Skill/Agent 선택은 substring 추측이 아니라 registry, manifest, capability, permission, owned-file 계약을 사용하고 선택·제외 근거를 ledger와 handoff에 기록한다.

R21. 현재 등록 프로젝트와 `dev new`/`dev add`로 추가될 신규 프로젝트가 동일한 공통 engine을 사용하며 프로젝트 차이는 declarative mapping으로 처리한다.

R22. 프로젝트별 path, state, approval, artifact, run, branch, owned files 및 secret namespace를 격리하고 traversal, symlink, alias collision과 cross-project 재사용을 차단한다.

R23. structured handoff는 project/Gate/LV/run, plan SHA, branch/HEAD, 완료·잔여 항목, owned·changed files, tests/review, artifact SHA, known issues/deferred items, recovery point, 다음 조건, permissions/forbidden actions, Skill/Agent 선택 근거를 포함한다.

R24. 모바일 사용자를 위해 프로젝트별 안정적인 고정 orchestration 명령을 제공하며 최초 명령 승인 후 같은 Gate의 내부 LV 명령 승인을 반복하지 않도록 한다. 고정 runner는 sealed action manifest와 등록 command ID만 사용하고 arbitrary shell, shell=True, command injection을 금지한다.

R25. Git push, destructive Git, AppArmor·시스템 변경, 네트워크·외부 API, 패키지 설치 및 secret 값 출력은 자동 실행하지 않고 별도 명시적 사용자 승인 없이는 금지한다.

Change targets:
- `runtime/orchestrator/gate_orchestrator.py`
- `runtime/orchestrator/cli.py`
- `tests/test_gate_orchestrator.py`
- `runtime/orchestrator/README.md`
- `docs/harness/orchestration-runtime-engine.md`

Acceptance:
- Gate approval once drives multiple ordered derived LV transitions without user renewal.
- Out-of-Gate LV/file access, missing/reordered plan items, incomplete ledger, stale checkpoint, overwrite, concurrent file ownership, and cross-project namespace access fail closed.
- Wallet, a second existing project, and a new-project fixture have explicit dry-run results.

## Validation

- `inspect`, `plan`, `run`, `collect`, `fanin`, `gate`, and `status` must remain functional.
- Summary markdown must stay human-readable and stable across the three runtime summaries.
- Resume behavior must skip completed threads.
- Result normalization must preserve manual fallback and stage-gate status contracts.
- Bridge snapshots must be generated without requiring a separate UI runtime.

## Work Item 7: Production Recovery Lifecycle Batch

Goal:
- Recover a rejected, unbound partial production attempt inside the same run
  without treating the rejected attempt as completion evidence.

Ledger:

| ID | Work item | Status |
| --- | --- | --- |
| R1 | Connect the recovery contract to CLI, controller, and lifecycle | COMPLETE |
| R2 | Execute attempt 2 package, preflight, and worker in the existing run | COMPLETE |
| R3 | Exclude rejected attempts from completion consumers | COMPLETE |
| R4 | Enforce one canonical binding across lifecycle artifacts | COMPLETE |
| R5 | Validate and consume recovery lineage during review | PENDING |
| R6 | Connect checkpoint, LV Exit, Gate Exit, and structured handoff | PENDING |
| R7 | Cover state transitions with fault, restart, and replay tests | PENDING |

Completion constraints:
- All seven rows must be COMPLETE before independent release audit begins.
- Rejected source artifacts are append-only and byte-identical.
- Recovery uses the existing run ID and a strictly increasing attempt number.
- The next Gate remains `USER_APPROVAL_REQUIRED` and cannot auto-run.
