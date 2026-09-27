# OCP Lifecycle V2 P3 Canary Crash/Recovery Design

- 문서 상태: **DESIGN LOCKED / IMPLEMENTATION PENDING**
- 작성일: 2026-09-27
- 대상 저장소: `ywjo86-tech/global-gpt-harness-engineering`
- 대상 브랜치: `impl/ocp-rdc-independent-primary-path-20260923`
- 기준 HEAD: `f16579b8e2f4a9bdb63daf02fe8b25605f99600d`
- 적용 범위: Lifecycle V2 **P3 Promotion Admission → bounded Canary Activation → crash/replay recovery**
- 비적용 범위: runtime-current 전환, predecessor quiesce/stop, 기존 Run migration, generic mutation authority 확대, 신규 execution backend 도입

---

## 1. 문서 목적

P3 Canary Activation에서 canonical Full Plan 등록 성공 후 outer P3 결과가 durable하게 완료되기 전에 프로세스가 종료되는 crash window를 제거하고, 동일 candidate의 재요청을 **중복 mutation 없이 안전하게 복구**할 수 있는 최소 설계를 확정한다.

---

## 2. 배경과 현재 구조

Lifecycle V2 P3는 다음 두 단계로 분리되어 있다.

1. **P3 Promotion Admission**
   - successor가 승인된 branch/HEAD/profile과 일치하는지 검증한다.
   - predecessor가 계속 serving 중인지 확인한다.
   - runtime-current가 predecessor를 계속 가리키는지 확인한다.
   - candidate Run이 아직 등록되지 않았는지 확인한다.
   - 승인된 policy ref/digest를 검증한다.
   - 성공 시 `WAITING_FOR_AUTHORIZED_ACTIVATION` handoff를 seal한다.

2. **P3 Canary Activation**
   - 승인된 P3 Admission을 재검증한다.
   - P3 Canary authorization을 평가한다.
   - 내부 `_P3FullPlanDelegation`을 통해 기존 canonical Full Plan activation callback을 호출한다.
   - canonical Full Plan은 기존 Full Plan activation store와 canonical job registration을 사용한다.

현재 P3 Canary는 별도 generic mutation executor를 만들지 않고 기존 Full Plan activation 경로를 재사용한다. 이 원칙은 유지한다.

---

## 3. 확인된 문제

### 3.1 Crash window

현재 실행 순서는 개념적으로 다음과 같다.

```text
P3 Canary request
    ↓
P3 Admission evidence 재수집
    ↓
evaluate_p3_promotion_admission()
    ↓
evaluate_p3_canary_activation()
    ↓
canonical_full_plan(..., enqueue_projection=False)
    ↓
Full Plan durable receipt/job 등록 성공
    ↓
P3 outer result 생성
    ↓
remote projection / ack
```

문제는 아래 지점이다.

```text
canonical Full Plan registration SUCCESS
                │
                │  ← crash / process exit 가능
                ▼
P3 outer result persistence / projection
```

Full Plan job은 이미 등록되었지만 P3 outer completion evidence가 남지 않은 상태에서 동일 요청이 다시 처리되면, P3 Admission evidence 수집 단계에서 candidate 상태가 `REGISTERED`로 관측된다.

기존 P3 Admission은 신규 promotion의 안전 조건으로 `candidate_run_registration_state == ABSENT`를 요구하므로, 정상적으로 등록된 동일 candidate조차 replay 시 Admission 단계에서 거부될 수 있다.

### 3.2 문제의 본질

이 문제는 Full Plan activation의 idempotency 부족이 아니다.

기존 Full Plan activation은 이미 다음 특성을 가진다.

- `FullPlanActivationStore.record_or_load()`로 동일 activation request receipt 재사용
- canonical job이 이미 존재할 경우 동일 authority core이면 기존 job 사용
- 동일 Run ID에 다른 authority를 결합하려 하면 `RUN_ID_REBIND_FORBIDDEN`
- 기존 durable Full Plan state를 재사용할 수 있음

따라서 필요한 것은 새 mutation capability가 아니라 **P3 외곽 계층의 recovery semantics 보강**이다.

---

## 4. 설계 원칙

### 4.1 권한을 넓히지 않는다

이번 변경은 다음 권한을 추가하지 않는다.

- arbitrary shell
- arbitrary Git mutation
- generic Full MCP mutation
- runtime-current switching
- predecessor service stop/disable
- 기존 Run migration
- 신규 execution backend

### 4.2 기존 canonical Full Plan을 단일 실행 권한으로 유지한다

P3 Canary는 계속 기존 `activate_full_plan_authorized` callback을 사용한다.

P3는 Full Plan의 실행 권한을 복제하지 않는다.

### 4.3 Replay는 재실행이 아니라 복구여야 한다

이미 동일 candidate의 canonical Full Plan receipt/job이 durable하게 존재한다면 replay는 다음만 수행한다.

- binding 재검증
- authority 일치 확인
- durable receipt/job 확인
- P3 terminal result 재구성

새 mutation을 다시 발생시키지 않는다.

### 4.4 Fail-closed

등록된 candidate가 존재하더라도 다음 중 하나라도 증명되지 않으면 recovery로 인정하지 않는다.

- 동일 candidate_run_id
- 동일 approved Full Plan binding
- 동일 bundle/authority digest
- 동일 canonical job identity
- 유효한 durable Full Plan receipt
- 기존 P3 waiting handoff와 일치

불일치 시 신규 activation으로 진행하지 않고 BLOCK한다.

---

## 5. 목표 상태 모델

```text
P3_PROMOTION_ADMISSION_READY
        │
        ▼
WAITING_FOR_AUTHORIZED_ACTIVATION
        │
        ▼
P3_CANARY_ACTIVATION_REQUESTED
        │
        ├──────────────────────────────────┐
        │                                  │
        ▼                                  ▼
 candidate ABSENT                   candidate REGISTERED
        │                                  │
        │ 신규 canonical Full Plan         │ recovery path
        │ activation                       │
        ▼                                  ▼
FULL_PLAN_REGISTERED              verify existing Full Plan
        │                                  │
        └────────────────┬─────────────────┘
                         ▼
                 P3_CANARY_ACTIVATED
                         │
                         ▼
               terminal evidence sealed
```

### 상태 의미

- `WAITING_FOR_AUTHORIZED_ACTIVATION`
  - P3 Admission은 성공했다.
  - 아직 Canary activation 완료 증거는 없다.
  - 추가 mutation 권한을 의미하지 않는다.

- `P3_CANARY_ACTIVATED`
  - 동일 candidate가 canonical Full Plan에 안전하게 등록되었음이 증명되었다.
  - 신규 실행이든 crash recovery든 동일 terminal 의미를 가진다.

---

## 6. Recovery 결정 규칙

P3 Canary 처리 시 candidate 상태에 따라 분기한다.

### 6.1 candidate = ABSENT

기존 신규 activation 경로를 유지한다.

```text
Admission revalidation
→ Canary authorization
→ canonical Full Plan activation
→ Full Plan receipt/job durable commit
→ P3 terminal evidence
→ projection
```

### 6.2 candidate = REGISTERED

무조건 거부하거나 신규 activation을 시도하지 않는다.

먼저 recovery candidate로 분류하고 아래 조건을 모두 검증한다.

1. 해당 candidate_run_id에 대한 P3 waiting handoff가 존재한다.
2. handoff의 project_alias와 candidate_run_id가 요청과 일치한다.
3. admission request/evidence/admission digest가 요청의 lineage와 일치한다.
4. 요청에 포함된 approved Full Plan activation binding이 기존 durable activation receipt와 일치한다.
5. Full Plan activation receipt의 `activation_request_id`와 `run_id`가 candidate_run_id와 일치한다.
6. receipt의 executable authority/bundle digest가 요청 binding과 일치한다.
7. canonical Full Plan job이 존재한다.
8. canonical job의 sealed authority core가 유효하다.
9. 기존 job이 다른 authority로 rebound되지 않았다.

모든 조건이 PASS일 때만 기존 등록을 성공한 activation으로 인정한다.

### 6.3 recovery 성공 시 금지되는 동작

recovery 경로에서는 다음을 다시 수행하지 않는다.

- 새 Run ID 생성
- 새 canonical job 생성 시도
- 별도 worker 실행
- runtime-current 변경
- predecessor mutation
- successor service 활성화 범위 확대
- generic Full MCP mutation 호출

---

## 7. Handoff lifecycle 보강

### 7.1 기존 waiting evidence

P3 Promotion Admission 성공 시 다음 의미의 handoff가 seal된다.

```json
{
  "schema_version": "orchestration.lifecycle-v2-p3-handoff.v1",
  "state": "WAITING_FOR_AUTHORIZED_ACTIVATION",
  "last_completed_step": "P3_PROMOTION_ADMISSION",
  "next_required_request_kind": "LIFECYCLE_V2_P3_CANARY_ACTIVATION",
  "authorization_required": true
}
```

이 waiting handoff는 유지한다.

### 7.2 terminal evidence 추가

P3 Canary activation이 신규 경로 또는 recovery 경로로 성공하면 별도의 immutable terminal evidence를 seal한다.

권장 schema:

```json
{
  "schema_version": "orchestration.lifecycle-v2-p3-handoff-terminal.v1",
  "state": "P3_CANARY_ACTIVATED",
  "project_alias": "...",
  "candidate_run_id": "...",
  "admission_digest": "...",
  "canary_request_digest": "...",
  "full_plan_activation_digest": "...",
  "full_plan_result_status": "FULL_PLAN_REGISTERED|FULL_PLAN_ALREADY_REGISTERED",
  "completion_mode": "NEW_ACTIVATION|RECOVERED_EXISTING_ACTIVATION"
}
```

### 7.3 terminal evidence 특성

- immutable
- create-once
- canonical JSON
- fsync 포함 durable write
- symlink 거부
- 기존 terminal 파일과 내용이 다르면 conflict로 BLOCK
- 동일 내용 replay는 idempotent success 허용

waiting evidence를 덮어쓰지 않는다. waiting과 terminal을 모두 유지해 lineage를 보존한다.

---

## 8. P3 Canary mode 의미

`LIFECYCLE_V2_P3_CANARY`는 독립적인 전체 제어-plane 운영 모드가 아니다.

정확한 의미는 다음과 같다.

> `CONTROL_MUTATION_CANARY` 권한 범위 안에서 Lifecycle V2의 P3 Canary 요청만 제한적으로 수신·처리하기 위한 bounded sub-mode/profile.

따라서 다음 의미를 가져서는 안 된다.

- 모든 mutation 요청 허용
- 기존 mutation canary를 대체하는 범용 모드
- runtime-current 자동 전환
- P4 Active Runtime 진입
- predecessor quiesce

전송 계층에서도 P3 Canary request kind만 poll-limit 이전에 필터링하는 현재 원칙을 유지한다.

---

## 9. 구현 변경 범위

### 9.1 `runtime/orchestrator/ocpv2_successor_stage_runtime.py`

필요한 최소 변경:

1. P3 waiting handoff loader/validator 추가
2. P3 terminal handoff seal 함수 추가
3. candidate `REGISTERED` 시 recovery 검사 경로 추가
4. 신규 activation과 recovery activation 결과를 동일 projection schema로 정규화
5. recovery 성공 시 `completion_mode` 또는 동등한 내부 증거 기록
6. mismatch는 fail-closed

### 9.2 기존 Full Plan 코드

원칙적으로 기능 변경하지 않는다.

재사용 대상:

- `FullPlanActivationStore.record_or_load()`
- canonical Full Plan receipt
- registered Full Plan job
- authority core validation
- Run ID rebind protection

필요할 경우 read-only recovery helper만 추가할 수 있으나, 새 mutation entrypoint는 만들지 않는다.

### 9.3 Remote Operator Service

기존 projection/outbox/ack 흐름을 유지한다.

P3 recovery 때문에 generic remote execution binding이나 canonical worker execution semantics를 변경하지 않는다.

---

## 10. RED 테스트 요구사항

구현 전에 다음 실패 테스트를 추가한다.

### RED-1: Full Plan 등록 직후 crash

조건:

1. P3 Admission 성공
2. P3 Canary authorization 성공
3. canonical Full Plan 등록 성공
4. P3 outer result 생성 전 강제 예외/종료
5. 동일 P3 Canary 요청 replay

현재 코드의 기대 실패:

- candidate가 `REGISTERED`로 관측됨
- P3 Admission 재평가가 신규 candidate 조건에서 차단됨

수정 후 기대:

- 기존 durable Full Plan receipt/job을 검증
- mutation 재실행 없음
- P3 terminal result 복구

### RED-2: Registered candidate지만 binding mismatch

기존 job/receipt가 존재하더라도 bundle/authority digest가 요청과 다르면 BLOCK.

### RED-3: Registered candidate지만 waiting handoff 없음

P3 lineage를 증명할 수 없으므로 BLOCK.

### RED-4: Registered candidate + malformed receipt

receipt digest/schema 불일치 시 BLOCK.

### RED-5: Registered candidate + canonical job authority mismatch

`RUN_ID_REBIND_FORBIDDEN`에 해당하는 충돌을 recovery 성공으로 취급하지 않는다.

### RED-6: terminal evidence replay

동일 terminal evidence 재생성은 idempotent success여야 한다.

### RED-7: terminal evidence conflict

동일 key에 다른 내용이 존재하면 BLOCK.

### RED-8: recovery 중 mutation callback 재호출 금지

이미 등록된 동일 candidate 복구 시 실제 registrar 또는 mutation callback 호출 횟수는 증가하지 않아야 한다.

---

## 11. GREEN 최소 구현 기준

GREEN은 RED 테스트를 통과시키는 최소 변경만 허용한다.

허용:

- read-only durable evidence load
- strict binding comparison
- immutable terminal evidence write
- recovery result reconstruction

금지:

- unrelated refactor
- 새로운 generalized recovery framework
- 새로운 mutation abstraction
- P4 기능 선구현
- runtime-current 전환 코드 추가
- predecessor lifecycle 변경

---

## 12. 회귀 테스트 범위

최소 focused regression:

- `test_lifecycle_v2_p3_canary_activation.py`
- `test_lifecycle_v2_p3_promotion_admission.py`
- `test_lifecycle_v2_p3_promotion_admission_boundaries.py`
- `test_ocpv2_successor_stage_runtime_p3_canary_wiring.py`
- `test_ocpv2_p3_canary_transport_filter.py`
- `test_full_plan_activation.py`
- `test_production_full_plan_entry.py`
- `test_ocpv2_approved_full_plan_activation_integration.py`
- 신규 P3 crash/recovery failure-injection test

그 다음 전체 regression을 수행한다.

---

## 13. 안전 불변조건

구현 후에도 아래 조건은 반드시 유지되어야 한다.

1. predecessor는 계속 serving 중이다.
2. runtime-current는 P3에서 변경하지 않는다.
3. successor profile은 bounded P3 범위를 벗어나 활성화되지 않는다.
4. 기존 Run을 migration하지 않는다.
5. P3 candidate는 하나의 approved Full Plan binding에만 결합된다.
6. 동일 Run ID를 다른 authority로 재결합하지 못한다.
7. replay가 중복 mutation을 발생시키지 않는다.
8. terminal evidence가 없는 성공 상태는 다음 replay에서 재구성 가능하다.
9. 증거가 불충분하면 자동 추론하지 않고 BLOCK한다.
10. P4 Active Runtime authority는 P3에 유입되지 않는다.

---

## 14. Acceptance Criteria

P3 crash/recovery hardening은 아래가 모두 만족될 때 완료로 본다.

- [ ] crash-after-Full-Plan-registration failure injection이 재현된다.
- [ ] 수정 전 RED가 확인된다.
- [ ] 동일 candidate replay가 기존 Full Plan receipt/job으로 복구된다.
- [ ] 복구 시 mutation callback이 재실행되지 않는다.
- [ ] authority/bundle mismatch가 fail-closed 된다.
- [ ] waiting handoff lineage가 필수로 검증된다.
- [ ] terminal evidence가 durable하게 seal된다.
- [ ] terminal replay가 idempotent하다.
- [ ] terminal conflict가 차단된다.
- [ ] focused regression PASS.
- [ ] full regression PASS.
- [ ] runtime-current 미변경 증거 확인.
- [ ] predecessor serving 유지 증거 확인.
- [ ] 기존/in-progress Run migration 없음 확인.
- [ ] P3 FINAL QUALIFICATION 기록 갱신.

---

## 15. 구현 순서

```text
1. RED failure-injection test
   ↓
2. registered candidate recovery evidence loader
   ↓
3. strict Full Plan receipt/job binding validation
   ↓
4. recovery result reconstruction
   ↓
5. immutable terminal handoff seal
   ↓
6. focused regression
   ↓
7. full regression
   ↓
8. PR / CI
   ↓
9. deployed OCP bootstrap verification
   ↓
10. bounded P3 Canary 재검증
   ↓
11. P3 FINAL QUALIFICATION
```

---

## 16. P3와 P4 경계

이번 설계 완료는 P4 진입 승인을 의미하지 않는다.

P3 완료 후 별도 승인/qualification을 거쳐야 하는 항목:

```text
P4 Active Runtime
├─ active-runtime qualification
├─ runtime-current 전환
├─ predecessor transition/quiesce
└─ final qualification
```

P3 recovery hardening은 오직 **P3 Canary activation의 durable correctness**를 닫는 작업이다.

---

## 17. 최종 설계 결정

**결정:** P3 Canary crash/recovery는 기존 canonical Full Plan idempotency를 재사용하는 bounded recovery로 구현한다.

새 실행 권한, 새 mutation executor, 새 Full MCP mutation 경로를 만들지 않는다.

candidate가 이미 등록된 경우 이를 곧바로 실패 또는 신규 activation으로 처리하지 않고, 기존 P3 handoff + Full Plan durable receipt + canonical job authority를 함께 검증하여 동일 activation임이 증명될 때만 P3 성공 결과를 복구한다.

이 설계는 다음 두 목표를 동시에 만족한다.

1. crash 이후 정상 성공을 잃지 않는다.
2. replay를 이용한 duplicate mutation 또는 authority rebinding을 허용하지 않는다.

---

## 18. 현재 작업 상태

```text
P3 Canary Recovery Hardening
├─ RCA / crash window 확인                 ✅
├─ 기존 Full Plan idempotency 확인         ✅
├─ canonical job replay protection 확인    ✅
├─ recovery architecture 확정              ✅
├─ terminal handoff 설계                   ✅
├─ bounded sub-mode 의미 확정              ✅
│
├─ RED failure-injection test              ⏳
├─ GREEN 최소 구현                         ⏳
├─ focused regression                      ⏳
├─ full regression                         ⏳
├─ PR / CI                                 ⏳
└─ P3 FINAL QUALIFICATION                  ⏳
```

문서 상태는 구현 완료 문서가 아니라 **승인된 구현 기준 설계문서**이다. 실제 완료 상태는 RED/GREEN/CI/qualification 증거가 추가된 이후 별도 completion record에서 확정한다.
