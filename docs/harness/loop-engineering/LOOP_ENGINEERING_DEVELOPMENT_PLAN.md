# Loop Engineering 개발 계획

## 목표

저장소 수준의 Loop Engineering 스캐폴드를 구축해 아래 항목을 표준화한다.

- 정책 소유권
- 프로젝트 상속
- 서브에이전트 경계
- 평가 기준
- QA 검사
- 루프 기록
- 재시도 방지
- Best Known Loop 추적

## 산출물

- `AGENTS.md`
- `LOOP_ENGINEERING_POLICY.md`
- `.codex-loop/criteria/evaluation-criteria.md`
- `.codex-loop/logs/failed-loop-log.md`
- `.codex-loop/logs/success-loop-log.md`
- `.codex-loop/logs/updated-success-loop-log.md`
- `.codex-loop/qa/qa-checklist.md`
- `.codex-loop/memory/forbidden-retry-patterns.md`
- `.codex-loop/memory/best-known-loops.md`
- `.codex-loop/subagents/*.md`
- `.codex-loop/templates/*.md`

## 구현 단계

1. 루트 정책 파일을 만든다.
2. `.codex-loop` 구조를 추가한다.
3. 평가 및 QA 기준을 정의한다.
4. 서브에이전트 역할 경계를 정의한다.
5. 루프 및 기록 템플릿을 추가한다.
6. 트리를 확인하고 루프 기반 작업이 가능한지 검증한다.

## 성공 기준

- 저장소에 필요한 정책과 템플릿 파일이 존재한다.
- 루프 절차가 끝까지 문서화되어 있다.
- 이후 작업에 바로 쓸 수 있을 만큼 규칙이 명확하다.
- 로그, 기준, QA, 재시도 금지 영역이 분리되어 있다.
