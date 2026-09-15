# Global GPT Harness Engineering — Execution Backend Contract Finalization — Implementation Design Revision Candidate

## Candidate Control

PROJECT_ID: GCH-EXEC-BACKEND  
PROJECT_KEY: GCH-EXEC-BACKEND  
UPGRADE_SEQUENCE: UPGRADE-002  
DOCUMENT_TYPE: IMPLEMENTATION_DESIGN_REVISION_CANDIDATE  
REVISION_FORM: BOUNDED_DELTA_AGAINST_APPROVED_DESIGN  
DESIGN_VERSION: ID-EXEC-BACKEND-1.2-CANDIDATE  
DESIGN_STATUS: CANDIDATE  
APPROVAL_STATUS: NOT_APPROVED  
CREATED_DATE: 2026-09-15  
USER_DESIGN_REAPPROVAL: PENDING

BASE_APPROVED_DESIGN_VERSION: ID-EXEC-BACKEND-1.1  
BASE_APPROVED_DESIGN_SHA256: 4240943a98221bce7547789e1e5d738a4abf0e2c42260223d27d9f984f1bd0a1  
APPROVED_PLAN_VERSION: DP-EXEC-BACKEND-1.1  
APPROVED_PLAN_SHA256: ca47305dfae5638ec7f518318163937bb29118b7b977afd16dd79136262a1fa7  
ACTIVE_EXECUTION_CONTRACT_SHA256_AT_DIAGNOSIS_START: 2e1ca0a9c33f580a23e246aa9ea26bb229b4223e2010969d9f98ef1cf71d28f4

REVISION_CLASS: TECHNICAL_HOW_ONLY_PROJECTION_CORRECTION  
PLAN_REVISION_REQUIRED: NO  
WHAT_CHANGE: NONE  
RUNTIME_IMPLEMENTATION_AUTHORIZATION: NOT_GRANTED

## Correction Diagnosis Basis

The approved Development Plan already defines the exact final ten questions in `DP-10 / Final 10-Question Plan Coverage Check`. The approved `ID-EXEC-BACKEND-1.1` Implementation Design preserved the `10/10 YES` rule but did not losslessly project the exact question texts into TASK-014 / TEST-017 / EVD-015 / GATE-005. The active Execution Contract inherited that omission, causing TASK-014 to fail closed with `MISSING_APPROVED_QUESTION_DEFINITIONS`.

This candidate corrects only that projection loss. It does not create, rewrite, or reinterpret any approved question.

QUESTION_TEXT_IDENTITY_REQUIRED: YES  
QUESTION_REPHRASING: PROHIBITED  
QUESTION_ORDER: Q01_THROUGH_Q10  
MISSING_OR_UNKNOWN_QUESTION: FAIL_CLOSED  
CONDITIONAL_GO: PROHIBITED

## Exact Approved Final Q01~Q10

| ID | Exact approved question |
|---|---|
| Q01 | 현재 설치된 Codex CLI를 실제 기준으로 검증하는가? |
| Q02 | Full Plan launcher와 CLI 호환성을 실제 Worker 실행으로 검증하는가? |
| Q03 | 동일 오류가 다음 프로젝트 시작 시 Gate에서 사전 차단되는가? |
| Q04 | Codex CLI 변경이 상위 Orchestration 계층 변경으로 전파되지 않는가? |
| Q05 | Provider Router authority가 유지되는가? |
| Q06 | NVIDIA→Codex automatic fallback 금지가 유지되는가? |
| Q07 | Codex→manual fallback semantics가 유지되는가? |
| Q08 | Full Plan Core 변경이 필요하면 Controlled Change 절차로 분리되는가? |
| Q09 | Backend 수정 후 기존 Full Plan 및 Graphify regression을 수행하는가? |
| Q10 | 위 조건이 모두 PASS해야 PHASE 3 본 실행으로 진입하는가? |

## Required Projection Binding

| Question | Runtime design binding |
|---|---|
| Q01 | TASK-015/TASK-014 → TEST-019/017/018 → EVD-001/014/015/016 → GATE-001/005 |
| Q02 | TASK-007/008/014 → TEST-008/009/017 → EVD-004/005/015/016 → GATE-003/005 |
| Q03 | TASK-005/006/014 → TEST-002/003/017/020 → EVD-002/014/015/016 → GATE-002/005 |
| Q04 | TASK-004/010/013/014 → TEST-007/012/015/017 → EVD-008/009/012/015/016 → GATE-004/005 |
| Q05 | TASK-003/009/013/014 → TEST-006/011/015/017 → EVD-007/009/012/015/016 → GATE-003/004/005 |
| Q06 | TASK-009/013/014 → TEST-011/015/017 → EVD-007/012/015/016 → GATE-003/004/005 |
| Q07 | TASK-002/008/014 → TEST-005/010/017 → EVD-006/015/016 → GATE-003/005 |
| Q08 | TASK-010/013/014 → TEST-015/017 → EVD-009/012/015/016 → GATE-004/005 |
| Q09 | TASK-011/014 → TEST-013/014/017 → EVD-010/011/015/016 → GATE-004/005 |
| Q10 | TASK-014 → TEST-017/018 → EVD-014/015/016 → GATE-005 |

### TASK-014 projection correction

`final_validation_questions.json` MUST contain exactly Q01~Q10 above, in order, with exact text identity, answer (`YES`/`NO`/`UNKNOWN`), and per-question evidence references. Any missing or rephrased question is fail-closed.

### TEST-017 projection correction

TEST-017 MUST verify exact Q01~Q10 text identity before evaluating answers. Only all mandatory Entry Gate predicates PASS plus exact Q01~Q10 = `10/10 YES` yields GO. Any missing/rephrased/NO/UNKNOWN item yields NO_GO.

### EVD-015 projection correction

EVD-015 MUST contain the exact Q01~Q10 text set, per-question evidence references, and the final 10/10 answer record. It may not synthesize replacement questions.

### GATE-005 projection correction

GATE-005 MUST evaluate the existing mandatory conjunction and the exact approved Q01~Q10 set above. `GO` is permitted only when every mandatory predicate is PASS, every evidence reference resolves, and Q01~Q10 are exactly `10/10 YES`. `CONDITIONAL_GO` remains unavailable.

## Explicitly Unchanged Authority

The following remain byte/semantic authority of the approved `ID-EXEC-BACKEND-1.1` design except for the exact-question projection binding above:
- REQ-901~REQ-910, NFR-901~NFR-904, SEC-901~SEC-902, OPS-901~OPS-909
- IN SCOPE / OUT OF SCOPE / deferred / future-candidate boundaries
- SC-BACKEND-001~SC-BACKEND-008 and DEL-001~DEL-007
- Project Identity, root, lifecycle, version semantics, and UPGRADE_SEQUENCE
- `EXECUTION_MODE=HYBRID`
- Provider Router selection authority and Planner provider-neutrality
- state-changing capability precedence and NVIDIA state-changing prohibition
- NVIDIA→Codex automatic fallback prohibition
- existing Codex→manual fallback semantics
- Worker Result normalization, Collector/Fan-in, Stage Gate, Completion/Worker Authority meanings
- Controlled Change vs Planning revision boundary
- security, permission, evidence, gate, recovery, and ownership semantics other than exact Q01~Q10 binding

UNAUTHORIZED_REQUIREMENT_CHANGE: NONE  
UNAUTHORIZED_SCOPE_CHANGE: NONE  
UNAUTHORIZED_CONSTRAINT_CHANGE: NONE  
UNAUTHORIZED_SUCCESS_CRITERIA_CHANGE: NONE  
UNAUTHORIZED_DELIVERABLE_CHANGE: NONE  
UNAUTHORIZED_PROJECT_IDENTITY_CHANGE: NONE  
UNAUTHORIZED_HYBRID_POLICY_CHANGE: NONE  
UNAUTHORIZED_CORE_AUTHORITY_CHANGE: NONE

## Candidate Approval Boundary

This candidate is non-authoritative until independent diagnosis PASS and explicit user Design re-approval. The currently approved Implementation Design remains `ID-EXEC-BACKEND-1.1`; the active execution Contract remains unchanged. Approval of this candidate does not itself authorize runtime/source/test mutation, deployment, merge, push, or Gate override.

NEXT_ACTION: independent diagnosis → explicit user Design re-approval → only then project execution-approval/Contract projection correction → TASK-014/GATE-005 re-evaluation.
