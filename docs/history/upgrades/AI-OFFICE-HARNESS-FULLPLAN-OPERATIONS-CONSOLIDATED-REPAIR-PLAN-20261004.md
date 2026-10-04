# AI Office + Harness + Full Plan Hybrid 종합 운영 정밀진단 및 보수계획 — 2026-10-04

## 0. 문서 목적

이 문서는 2026-10-04에 확인한 AI Office 운영결함과 Full Plan Hybrid/Harness 전체 운영결함을 하나의 원인 모델로 재진단하고, 기존 권한경계와 완료된 실행 증거를 훼손하지 않는 최소 보수 순서를 정의한다.

기준 진단 문서:
- `docs/history/upgrades/AI-OFFICE-FULLPLAN-HYBRID-OPERATIONS-DEEP-DIAGNOSIS-20261004.md`

이번 단계에서 수행한 것은 read-only 진단, 회귀검증, Git 계보 확인, 보수계획 문서화뿐이다.
프로세스 종료, 파일/소켓 삭제, 서비스 재시작, runtime 전환, commit, push는 수행하지 않았다.

---

## 1. 최종 종합 판정

```text
FULL_PLAN_HYBRID_EXECUTION_CORE = HEALTHY
OCP_CONTROL_PATH               = HEALTHY
FULL_PLAN_RECONCILE_CORE       = HEALTHY
AI_OFFICE_EXECUTION_EVIDENCE   = HEALTHY

OPERATIONS_WIRING              = DEGRADED
PROCESS_LIFECYCLE              = DEGRADED
MONITORING_COVERAGE            = BLOCKED
RELEASE_REPRODUCIBILITY        = DEGRADED
OPERATIONAL_ACCEPTANCE         = BLOCKED
```

핵심 해석:
- 승인 → Full Plan → Router/MPRF → 실행 → Gate/Checkpoint/Recovery의 실행 코어를 다시 설계할 필요는 없다.
- 현재 결함은 실행 코어 바깥의 운영 wiring, 감시, 프로세스 수명주기, 보조상태 retirement, release lineage에 집중되어 있다.
- 현재 상태에서 전체 GREEN을 선언하면 False-Green 위험이 있다.

---

## 2. 2026-10-04 재검증된 실시간 사실

### 2.1 OCP / Reconcile
- `ocpv2.timer`: active/waiting, 최근 trigger 정상.
- `ocpv2.service`: latest result success, ExecMainStatus=0.
- `ocpv2-host-runner.service`: active/running.
- `global-gpt-harness-full-plan-reconcile.timer`: active/waiting.
- reconcile service latest result: success, ExecMainStatus=0.
- failed user systemd units: 0.

### 2.2 Post-Change Gate
Live gate 재실행 결과:
- OCP timer/service: PASS.
- OCP host runner: PASS.
- Full Plan reconcile timer/service: PASS.
- diagnostic unit coverage: PASS.
- Reconcile Timer Watch: enabled.
- Attention Watch: disabled.
- 최종 status: `BLOCKED`.
- 직접 차단 이유: `ATTENTION_WATCH_DISABLED`.

### 2.3 Full Plan Registry
- registered jobs: 94
- COMPLETED: 14
- BLOCKED: 60
- CANCELLED: 20
- missing state: 0
- nonterminal canonical jobs: 0

Canonical Registry 관점에서는 현재 진행 중인 Full Plan이 없다.

### 2.4 실제 OS 프로세스
Registry 밖에서 다음 장기 프로세스가 계속 생존 중이다.
- DCC live canary Full Plan: PID 550360, 3521156, 1079401.
- proof HOST_GATEWAY: PID 38602, 1336197.
- AI Office dashboard smoke/uvicorn 계열 프로세스 다수.
- smoke listeners: 8014, 8017, 8018.
- HOST_GATEWAY live UDS listener: 2개.
- /tmp harness-host-gateway socket residue는 live listener 수보다 훨씬 많다.

### 2.5 Auxiliary durable state
- provider-wait `active.json`: 8개.
- 해당 run은 모두 이미 BLOCKED 또는 CANCELLED terminal.
- Full Plan activation receipts: 64개.
- 그중 canonical_job_path dangling: 2개.
- 두 job은 유실되지 않았고 별도 superseded job 보존본 및 terminal state가 존재한다.
- GitHub transport durable ACK: 508 entries.
- delivery pending: 8 entries.
- pending 8건과 durable ACK의 exact overlap: 0.

### 2.6 Attention
Manual attention discovery:
- pending total: 33.
- 지정된 2026-09-19 cutoff 이후: 2.
- 둘 다 2026-09-19 historical terminal MVP incidents.
- 2026-10-03~04 현재 active-run 신규 attention: 0.

### 2.7 Host resource
- disk: 약 50% 사용.
- memory available: 약 4.1 GiB.
- swap: 약 3.0 GiB / 4.0 GiB 사용.
- load average: 낮음.
현재 resource gate blocker는 확인되지 않았다.

---

## 3. Full Plan Hybrid 코어 재검증

정확한 HEAD `478dc312f4c0f6808eab0b21775362c6ff0541bb` Git worktree에서 운영/Hybrid 핵심 회귀를 재실행했다.

대상:
- operational post-change gate
- failure reproduction
- process lifecycle diagnostics
- operations diagnostic projection
- operations read model
- production attention watch
- Hybrid runtime flow
- Full Plan operator resume
- durable continuation failure injection
- production execution gateway

결과:
- 74 tests PASS
- 1 skipped
- 0 failures

확인된 핵심 불변조건:
- Router가 provider/model 선택권을 유지한다.
- MPRF는 eligibility/runtime fact를 제공하되 provider 선택권을 얻지 않는다.
- Manual Action은 WAITING_PROVIDER exact binding에서만 허용된다.
- stale HEAD / 잘못된 LV / replay conflict는 fail-closed 한다.
- duplicate effect는 checkpoint/CAS/epoch fencing으로 차단된다.
- continuation fork/orphan/tamper는 fail-closed 한다.
- Post-Change Gate 자체 로직은 false-green을 차단한다.

결론:
`FULL_PLAN_HYBRID_CORE_REWRITE_REQUIRED = NO`

---

## 4. 종합 원인 모델

### ROOT-1 — 운영 안전기능은 구현됐지만 production wiring이 완성되지 않았다
확인된 예:
- `operational_post_change_gate.py`: 구현 + 테스트 존재, production completion caller 없음.
- `process_lifecycle.py`: 구현 + 테스트 존재, production caller 없음.
- `operations_diagnostic_projection.py`: 구현 + 테스트 존재, production caller 없음.
- `OperationsReadModelV1.diagnostic_health`: 필드 존재, production build path에서 채워지지 않음.
- Jarvis bridge operations projection: legacy snapshot adapter 사용.

결과:
실행 완료는 보이지만 운영 건강상태/고아 프로세스/감시 결함이 같은 완료판정에 묶이지 않는다.

### ROOT-2 — Execution completion과 Operational acceptance가 같은 의미처럼 보인다
Full Plan은 `ALL_GATES_COMPLETED`에서 정상적으로 `COMPLETED`가 된다.
AI Office workflow도 Full Plan completion binding 후 `COMPLETE`가 된다.
그러나 Post-Change operational gate는 별도이며 completion path에 결속되지 않는다.

따라서 다음 조합이 현재 가능하다.
```text
Execution = COMPLETED
AI Office workflow = COMPLETE
Operational Post-Change = BLOCKED
```

이 조합 자체는 의미상 허용 가능하지만, UI/read-model/운영승인 레코드가 이를 구분하지 못하면 False-Green이 된다.

### ROOT-3 — 프로세스 수명주기의 durable ownership/reaping 경계가 약하다
- Registry는 active=0인데 OS에는 Full Plan canary가 살아 있다.
- canary process의 /tmp job root와 lock은 이미 사라졌다.
- process lifecycle 진단기는 이를 ORPHAN_SUSPECTED로 분류할 수 있으나 운영 감시에 연결되지 않았다.
- `UnixSocketHostRunner.serve_once(timeout=1800)`의 timeout은 client 연결 이후 execution에 적용된다.
- `server.accept()`에는 timeout이 없어 client가 오지 않으면 무기한 LISTEN 가능하다.
- live canary의 intentional pause도 parent cleanup에 의존하는 무한 wait 구조가 존재한다.

### ROOT-4 — 보조 durable state의 terminal/supersession retirement 규칙이 불완전하다
- provider-wait active pointer는 terminal run 후에도 남는다.
- activation receipt는 immutable하지만 canonical job이 별도 위치로 이동되면 path가 dangling 된다.
- GitHub delivery pending은 durable recovery에는 강하지만 obsolete/stale classification lifecycle이 약하다.

### ROOT-5 — 현재 runtime role lineage가 3갈래로 나뉘어 있다
현재 실제 역할별 runtime:
- OCP control service WorkingDirectory: `478dc312...`
- Full Plan periodic reconcile `runtime-current`: `d331701...`
- 완료된 AI Office PR33 successor run runtime: `b986450...`

역할별 runtime 차이는 설계상 허용될 수 있으나, 현재 세 계보의 기능집합이 동일하지 않다.

Git ancestry:
- `d331701 -> 478dc312`: YES.
- `478dc312 -> b986450`: NO.
- `b986450 -> 478dc312`: NO.

478-only material patches:
- `b0304c9` False-Green 차단 + Post-Change Gate.
- `f36c044` OCP successor operational health 보존.
- `478dc31` stale reconcile timer fail-closed.

b986-side unique PR33 hardening에는 reporting/incident/capability lineage/registry isolation/validation 보강이 존재한다.

중요:
- GitHub API에서 exact commit `478dc312` 조회는 실패했다.
- `d331701` 및 `b986450`은 GitHub에서 조회 가능했다.

따라서 host loss 시 현재 OCP control runtime을 exact remote source만으로 재구성할 수 없다.

---

## 5. 결함 통합 분류

| ID | 결함 | 심각도 | 현재 실행 중복 위험 | False-Green 위험 | DR/추적성 위험 |
|---|---|---:|---:|---:|---:|
| D-01 | Operational Post-Change production wiring 없음 | MAJOR | 낮음 | 높음 | 중간 |
| D-02 | Diagnostic health / process lifecycle UI·감시 미결속 | MAJOR | 낮음 | 높음 | 중간 |
| D-03 | Attention Watch disabled | MAJOR 운영차단 | 낮음 | 높음 | 낮음 |
| D-04 | HOST_GATEWAY pre-connect timeout 없음 | MAJOR | 낮음 | 중간 | 중간 |
| D-05 | Canary/process ownership reaping 불완전 | MAJOR | 낮음 | 중간 | 중간 |
| D-06 | Runtime role lineage 분산 + 478 remote 부재 | MAJOR | 낮음 | 중간 | 높음 |
| D-07 | provider-wait stale active pointers | MODERATE | 현재 낮음 | 중간 | 중간 |
| D-08 | activation receipt dangling canonical path | MODERATE | 낮음 | 낮음 | 높음 |
| D-09 | transport pending 8건 lifecycle 불명확 | MODERATE | 낮음 | 낮음 | 중간 |
| D-10 | dashboard smoke/process/socket residue | MODERATE | 낮음 | 중간 | 중간 |
| D-11 | 승인계약 NOT_STARTED 문구와 실제 완료 증거의 상태차 | LOW/MODERATE | 없음 | 중간 | 중간 |

---

## 6. 보수 설계 원칙

### 6.1 절대 유지
```text
GPT_OPERATOR              = Operator
Full Plan                 = plan / decomposition / Gate / fan-in
Multi-Provider Router     = provider/model selection
MPRF                      = provider runtime / eligibility
Full MCP                  = state-changing effect authority
OCP / AI Office           = control / governance / activation / observation
Attention / diagnostics   = read-only observation
```

보수 과정에서 위 권한을 이동하지 않는다.

### 6.2 Execution state를 다시 쓰지 않는다
기존 `COMPLETED`를 `BLOCKED`로 되돌리는 방식은 금지한다.

대신 독립된 운영판정을 둔다.
```text
execution_state          = COMPLETED
operational_acceptance   = PENDING | BLOCKED | ACCEPTED
```

### 6.3 기존 immutable evidence를 고치지 않는다
- 기존 approval
- activation receipt
- Full Plan terminal state
- historical attention
- completed run evidence

를 rewrite하지 않는다.
필요한 경우 resolution/acceptance/retirement record를 추가한다.

### 6.4 cleanup보다 detection을 먼저 고친다
현재 orphan process와 stale socket을 먼저 지우지 않는다.
새 detection이 같은 결함을 정확히 잡는 것을 증명한 뒤 evidence를 보존하고 cleanup한다.

### 6.5 runtime lineage를 먼저 통합한 뒤 코드수정한다
현재 dirty main checkout이나 임의 과거 branch에서 보수하지 않는다.
새 recovery worktree를 exact approved baseline에서 만든 뒤 478 operational fixes와 b986 PR33 hardening의 semantic fan-in을 완료한다.

---

# 7. 최종 보수 실행 Blueprint

## GATE-R0 — Evidence Freeze / Baseline Snapshot

목표:
현재 결함을 재현 가능한 before-state로 고정한다.

수집:
- systemd unit status/timestamps.
- OCP unit WorkingDirectory + env release refs.
- runtime-current target.
- Full Plan registry 94건 state distribution.
- OS process list / start time / cwd / cmdline.
- UDS/TCP listeners.
- provider-wait pointers.
- activation receipts + dangling paths.
- delivery ACK/pending.
- Attention Watch / Reconcile Watch state.
- Git refs, commit parents, remote availability.
- current worktree dirtiness.

산출물:
`OPERATIONS-REPAIR-BASELINE-20261004.json/md`

Gate:
- snapshot hash sealed.
- 모든 후속 보수는 이 baseline을 evidence ref로 사용.
- mutation 0.

## GATE-R1 — Canonical Operational Baseline Reconciliation

목표:
분기된 runtime lineage를 하나의 보수 기준으로 통합한다.

권장 기준:
- `d331701`의 안전한 Full Plan Hybrid core를 조상으로 유지.
- `478dc312`의 3개 operational safety patch를 반드시 보존.
- `b986450` 쪽 PR33 hardening을 semantic diff 기준으로 누락 없이 fan-in.
- 기존 completed run runtime은 immutable하게 유지.

금지:
- b986를 단순 checkout하여 478 operational patch를 잃는 것.
- 478만 기준으로 삼아 b986 PR33 hardening을 무시하는 것.
- dirty main checkout에서 직접 구현하는 것.

검증:
- left/right semantic patch inventory 100%.
- operational safety tests PASS.
- b986 PR33 regression tests PASS.
- no authority-boundary diff.
- new candidate commit is GitHub-reconstructable before production rollout.

Gate:
`CANONICAL_OPERATIONS_BASELINE = SEALED`

## GATE-R2 — Monitoring Foundation / Attention Health

목표:
Post-Change Gate가 caller-supplied boolean만 믿지 않고 실제 monitor health evidence를 소비하도록 한다.

설계:
1. `production_attention_watch`의 read-only discovery를 유지.
2. 별도 server-side attention scan timer/service 또는 동등한 독립 health producer를 둔다.
3. scan은 run을 수정하지 않고 monitor-owned health receipt만 기록한다.
4. receipt 최소 항목:
   - scan timestamp
   - runtime source identity
   - search root
   - registered job count
   - pending current-event count
   - scan result
   - receipt digest
5. Post-Change Gate는 fresh receipt를 검증한다.
6. ChatGPT Harness Attention Watch는 사용자 notification layer로 다시 활성화한다.
7. Reconcile Timer Watch는 독립 외부 감시로 유지한다.

중요:
현재 `--attention-watch-enabled` / `--timer-watch-enabled` 같은 caller boolean만으로 PASS시키는 경로는 operational acceptance의 최종 증거로 사용하지 않는다.

실패 시:
- monitor receipt stale/missing -> acceptance BLOCKED.
- attention automation disabled -> notification coverage DEGRADED/BLOCKED 정책 명시.
- run execution 자체는 역으로 취소하지 않는다.

Gate:
`MONITOR_HEALTH_EVIDENCE = PASS`

## GATE-R3 — Operational Acceptance + AI Office Read Model Wiring

목표:
Execution completion과 Operations acceptance를 기계적으로 분리·결속한다.

신규 durable record 권장:
`OperationalAcceptanceRecordV1`

최소 binding:
- project_id
- run_id
- authority_core_sha256
- Full Plan terminal state_sha256
- terminal_reason
- post-change gate evidence digest
- monitor health receipt refs
- process lifecycle diagnostic refs
- runtime release identity refs
- status: PENDING/BLOCKED/ACCEPTED
- failures
- record_sha256

실행 위치:
- Full Plan runner의 Gate semantics 안에 넣지 않는다.
- terminal COMPLETED를 관찰하는 operations/reconcile layer에서 생성한다.
- Full Plan `COMPLETED` state는 변경하지 않는다.

AI Office:
- `operations_diagnostic_projection`을 실제 production builder에 결속.
- `OperationsReadModelV1.diagnostic_health`를 실제 값으로 채움.
- Jarvis bridge legacy snapshot projection에도 bounded diagnostic/acceptance projection을 연결.
- UI는 최소 두 상태를 분리 표시:
  - 실행 상태: 완료
  - 운영 상태: 승인대기/차단/정상

False-Green 규칙:
```text
execution COMPLETED + operational BLOCKED
=> 화면: "실행 완료 / 운영 승인 차단"
=> 전체 상태: GREEN 금지
```

Gate:
- Attention disabled fixture -> execution stays COMPLETED, acceptance BLOCKED.
- Reconcile stale fixture -> acceptance BLOCKED.
- Healthy fixture -> acceptance ACCEPTED.
- diagnostic finding BLOCKED -> dashboard에 반영.
- authority mutation 0.

## GATE-R4 — Process Lifecycle / HOST_GATEWAY Hardening

목표:
Harness가 만든 프로세스가 owner 소실 후 무기한 생존하지 않도록 한다.

### R4-A HOST_GATEWAY
`UnixSocketHostRunner.serve_once`:
- pre-connect accept timeout을 실제 socket에 적용.
- timeout error를 typed failure로 기록.
- finally에서 socket cleanup 유지.
- execution timeout과 accept timeout 의미를 명확히 분리하거나, 최소한 현재 timeout이 accept에도 상한으로 적용되도록 함.

필수 테스트:
- no client -> bounded exit.
- socket removed after timeout.
- duplicate/adoption behavior 유지.
- valid client -> 기존 동작 유지.

### R4-B Live Canary
현재 intentional pause의 unbounded loop 제거.
- parent가 죽어도 canary 자체 TTL/lease 상한으로 종료.
- test purpose는 유지.
- external effect는 계속 NONE.

### R4-C Process ownership discovery
기존 `diagnose_process_lifecycle()`에 실제 fact collector를 연결한다.

향후 managed process에는 가능하면:
- PID
- process start identity
- owner_ref
- owner state path
- lock/lease ref
- expected lifetime/deadline
- command digest
를 durable ownership evidence로 남긴다.

진단 상태:
- OWNED
- OWNERSHIP_DEGRADED
- ORPHAN_SUSPECTED

중요:
진단기가 process를 자동 kill하지 않는다.

Gate:
- 현재 known orphan canary를 ORPHAN_SUSPECTED로 탐지.
- proof host runner idle case 탐지.
- 정상 OCP/reconcile process는 false positive 0.
- Post-Change/diagnostic projection에 finding 전달.

## GATE-R5 — Auxiliary Durable State Lifecycle

### R5-A provider-wait
목표:
terminal/superseded run에 `active.json`이 남지 않도록 한다.

원칙:
- 원 evidence는 보존.
- active pointer만 durable retirement receipt와 함께 비활성화.
- terminal Full Plan state가 source of truth.

검증:
- WAITING_PROVIDER -> active pointer 존재.
- resume/terminal -> active pointer retirement.
- restart 후 terminal run 자동재개 없음.
- 기존 8건은 migration/cleanup 전 dry-run classification.

### R5-B Activation Receipt Resolution
목표:
immutable receipt의 canonical_job_path가 사라져도 evidence chain이 끊기지 않도록 한다.

원칙:
- 기존 receipt rewrite 금지.
- canonical job file 보존을 기본 invariant로 강화.
- supersession이 필요하면 RunSupersessionStore 기반 resolver를 제공.
- legacy 2건은 archived/superseded job과 exact authority binding을 검증해 resolution record 추가.

검증:
- canonical path exists -> direct resolution.
- path missing + valid supersession -> archived resolution.
- ambiguous/mismatched authority -> fail-closed.

### R5-C GitHub delivery pending
목표:
8개 pending을 무조건 삭제하지 않고 의미를 분류한다.

필요:
- pending schema/lifecycle에 queued/last-attempt/result classification 도입 또는 별도 diagnostic record.
- durable ACK 존재 여부.
- source control 존재 여부.
- linked canonical execution/result 존재 여부.
- obsolete 판단은 explicit retirement evidence로만 수행.

금지:
- age만으로 자동 삭제.
- pending을 ACK로 위조.
- historical execution result 재실행.

Gate:
- 모든 pending = ACKED / CURRENT_PENDING / OBSOLETE_WITH_EVIDENCE 중 하나로 분류.
- UNKNOWN 0이 될 때만 정리 승인 단계로 이동.

## GATE-R6 — Integrated Regression + Fault Injection

필수 regression 그룹:
1. Full Plan Hybrid routing/authority.
2. MPRF/Router separation.
3. Full Plan durable continuation.
4. operator resume/manual action.
5. OCP control/activation.
6. Post-Change operational gate.
7. Attention discovery/health receipt.
8. operations read model/diagnostic projection/Jarvis bridge.
9. HOST_GATEWAY.
10. process lifecycle.
11. provider-wait retirement.
12. activation receipt resolver.
13. GitHub delivery ACK/pending recovery.
14. PR33 reporting/incident/capability lineage regression.

필수 장애재현:
- Attention watch OFF.
- reconcile timer stale.
- reconcile service last run fail.
- host runner no client.
- parent loss during canary pause.
- owner state + lock missing.
- terminal run with stale provider-wait pointer.
- superseded activation receipt canonical path missing.
- delivery pending with/without durable ACK.
- runtime source not remotely reconstructable.

Gate:
- focused regression PASS.
- full regression PASS.
- no new skipped test used to hide defect.
- no expectation weakening.
- fault injection shows fail-closed.
- source tree clean.

## GATE-R7 — Remote-backed Runtime Release / Controlled Rollout

목표:
OCP control과 periodic reconcile이 동일한 repaired operational generation을 사용하도록 정리한다.

현재:
- OCP = 478.
- reconcile runtime-current = d331.

권장 rollout:
1. R1~R6 PASS commit에서 immutable runtime release 생성.
2. remote commit availability 확인.
3. release manifest/digest seal.
4. OCP candidate preflight.
5. reconcile candidate preflight.
6. rollback target 고정.
7. OCP WorkingDirectory 전환.
8. runtime-current를 같은 operational generation으로 전환.
9. 기존 completed job의 historical runtime binding은 변경하지 않음.

PR33 completed run `b986450` evidence는 migration하지 않는다.

Rollback:
- OCP -> 기존 478 runtime.
- runtime-current -> 기존 d331.
- existing Full Plan jobs/state untouched.

Gate:
`CONTROL_RUNTIME_IDENTITY = REPRODUCIBLE_AND_ALIGNED`

## GATE-R8 — Evidence-led Residue Cleanup

이 단계는 구현/검증 완료 후 별도 위험 승인 하에서만 수행한다.

대상 후보:
- orphan canary PIDs.
- orphan proof host-runner PIDs.
- AI Office smoke processes.
- 8014/8017/8018 smoke listeners.
- stale UDS files.
- legacy provider-wait active pointers.
- 필요 시 superseded legacy registry artifacts.

순서:
1. 새 diagnostic이 대상 각각을 orphan/stale로 재확인.
2. PID start identity 재확인(PID reuse 방지).
3. owner/run terminal 상태 확인.
4. evidence snapshot/hash 저장.
5. cleanup.
6. process/listener/socket 재조회.
7. 정상 OCP/Full Plan 영향 없음 확인.

금지:
- 이름만 보고 일괄 kill.
- `rm /tmp/harness-host-gateway-*` 식 blind delete.
- canonical run evidence 삭제.

Gate:
- confirmed orphan process = 0.
- unowned live listener = 0.
- stale socket classified/retired.
- canonical Full Plan state unchanged.

## GATE-R9 — Live Operational Acceptance

최종 live 확인:
- OCP poll healthy.
- reconcile timer healthy.
- attention health fresh.
- external user attention watch enabled.
- current attention event 0 또는 명시적으로 처리됨.
- process lifecycle material finding 0.
- auxiliary state consistency PASS.
- runtime remote reconstruction PASS.
- AI Office read model에 execution/operational 상태 동시 표시.
- Post-Change Gate PASS.
- OperationalAcceptanceRecord = ACCEPTED.

최종 선언:
```text
FULL_PLAN_HYBRID_CORE = HEALTHY
AI_OFFICE_EXECUTION = HEALTHY
HARNESS_OPERATIONS = HEALTHY
OPERATIONAL_ACCEPTANCE = ACCEPTED
FALSE_GREEN_GUARD = PASS
```

---

## 8. 단계별 변경 예상 범위

### 기존 파일 수정 후보
- `runtime/orchestrator/operational_post_change_gate.py`
- `runtime/orchestrator/production_attention_watch.py`
- `runtime/orchestrator/operations_diagnostic_projection.py`
- `runtime/orchestrator/operations_read_model.py`
- `runtime/orchestrator/process_lifecycle.py`
- `runtime/orchestrator/production_execution_gateway.py`
- `runtime/orchestrator/host_runner_entry.py`
- `runtime/orchestrator/live_auto_canary.py`
- `runtime/orchestrator/production_full_plan_boot.py`
- `runtime/orchestrator/wait_recovery.py`
- `runtime/orchestrator/full_plan_activation.py` 또는 별도 resolver
- `runtime/operator_transport/github_control_adapter.py`
- `runtime/jarvis_bridge/bridge_api.py`

### 신규 파일 후보
- operational acceptance record/store
- attention monitor health receipt/store
- process ownership/discovery collector
- activation receipt/supersession resolver

정확한 파일 수는 GATE-R1 canonical baseline fan-in 후 다시 고정한다.
현재 단계에서 임의 확장하지 않는다.

---

## 9. 우선순위

### P0 — 운영 False-Green 차단
- R0 baseline
- R1 canonical baseline
- R2 monitoring evidence
- R3 operational acceptance/read-model wiring

### P1 — 무기한 프로세스/ownership 누수 차단
- R4 HOST_GATEWAY + canary + process ownership

### P2 — durable residue/traceability 정리
- R5 provider-wait / activation receipt / delivery pending

### P3 — 통합 배포 및 실제 잔존물 정리
- R6 regression
- R7 rollout
- R8 cleanup
- R9 live acceptance

---

## 10. 위험과 복구 전략

### 위험 1 — runtime 합치는 과정에서 안전장치 재탈락
대응:
- 478-only/b986-only patch inventory를 Gate-R1 evidence로 고정.
- 두 계보 regression을 모두 통과하기 전 release 생성 금지.

### 위험 2 — Operational acceptance가 Full Plan authority를 침범
대응:
- Full Plan COMPLETED를 변경하지 않음.
- acceptance는 별도 observation record.
- provider/model/effect authority 0.

### 위험 3 — cleanup 중 정상 프로세스 종료
대응:
- PID + start identity + owner state + lock/lease + terminal state를 모두 확인.
- cleanup은 진단과 분리.
- 별도 위험 승인.

### 위험 4 — stale pointer 정리로 복구 evidence 유실
대응:
- 원 evidence 보존.
- retirement receipt 생성.
- active pointer만 lifecycle 처리.

### 위험 5 — release 전환 실패
대응:
- OCP 478 / reconcile d331 rollback target 고정.
- existing run migration 금지.
- symlink/unit rollback 가능한 상태에서만 cutover.

---

## 11. 승인 지점

현재 사용자 요청은 진단 및 보수계획 수립이다.
아직 runtime 구현/cleanup/deploy 권한으로 확장하지 않는다.

다음 실행 승인 시 권장 시작 범위:
```text
R0 Evidence Freeze
→ R1 Canonical Operational Baseline Reconciliation
→ R2 Monitoring Foundation
→ R3 Operational Acceptance Wiring
```

R4 이후는 R3 결과를 본 뒤 진행한다.

실제 process kill / socket delete / stale artifact delete가 포함되는 R8은 별도 위험작업으로 분리한다.

---

## 12. 역검증 — 이 계획으로 최종 목표에 도달하는가?

목표:
`승인된 업무가 안전하게 실행되고, 중단 시 정확히 복구되며, 완료 후 OS/monitor/read-model/release까지 일관된 상태인지 증명한 뒤에만 전체 GREEN을 선언한다.`

역산:
1. 실행 코어의 승인/authority/recovery는 이미 건강하다.
2. operational acceptance를 분리하면 execution 완료와 운영완료 오판을 막을 수 있다.
3. monitoring evidence를 실제 health receipt에 결속하면 caller boolean false-green을 막을 수 있다.
4. process lifecycle과 host gateway timeout을 보수하면 Registry↔OS drift의 재발을 차단할 수 있다.
5. auxiliary state retirement를 보수하면 active/dangling/pending 잔존상태가 canonical truth와 일치한다.
6. runtime lineage를 remote-backed generation으로 통합하면 host loss 후 재구성이 가능하다.
7. 마지막 cleanup을 detection 이후에 수행하면 원인 증거를 잃지 않는다.
8. live Post-Change PASS + OperationalAcceptance ACCEPTED가 최종 GREEN의 단일 승인 근거가 된다.

결론:
`PLAN_REACHES_FINAL_GOAL = YES`

단, R1 canonical baseline fan-in과 R3 operational acceptance wiring을 생략하면 최종 목표에 도달하지 못한다.
