# Global GPT Harness Engineering

## Purpose

This repository acts as the Global Harness Engineering PMO for managing Codex-based agent teams, reusable skills, project templates, QA standards, and release workflows.

## Operating Principles

- Understand the user's business purpose before making changes.
- Before editing files, present the plan and target files.
- Split large work into requirements, design, implementation, test, documentation, and QA.
- Keep AGENTS.md concise. Put detailed standards in docs/harness/.
- Store reusable workflows as skills under .agents/skills/.
- Store Codex-specific agent definitions under .codex/agents/.
- Store project templates under templates/.
- Store temporary handoff artifacts under _workspace/.
- Do not store API keys, tokens, passwords, or secrets in the repository.
- Do not use .claude/ paths in this Codex-based repository.

## Project Lifecycle

1. Project intake
2. Requirements analysis
3. Agent team design
4. Skill design
5. Implementation plan
6. Development
7. Testing
8. Documentation
9. Release review
10. Deployment handoff

## Harness Usage

Use the harness skill when designing a new project team, creating reusable skills, defining QA handoffs, or building a project-specific workflow.

## Global Agent V02 Planning Policy

- For Global Agent feature work, use [docs/global-agent/feature-development/V02/V02_OPERATION_GUIDE.md](docs/global-agent/feature-development/V02/V02_OPERATION_GUIDE.md) as the working guide.
- Use [docs/global-agent/feature-development/V02/PLAN_STATE.md](docs/global-agent/feature-development/V02/PLAN_STATE.md) for the current routing state.
- Use [docs/global-agent/feature-development/V02/STAGE_EXIT_STANDARD.md](docs/global-agent/feature-development/V02/STAGE_EXIT_STANDARD.md) for stage-end policy and handoff review format.
- Keep AGENTS.md concise; detailed V02 routing, status, and exit rules live in the V02 docs.

## New Project Standard

New projects default to `project-workspace/{project-slug}/`.

When the user provides project keywords, purpose, goals, or short trigger phrases such as "프로젝트 진행", "만들어줘", or "생성해줘", use the `new-project-orchestrator` skill to run the standard flow from requirements analysis through team architecture, project subagent and skill creation, orchestration, MVP milestones, QA, release readiness, and deployment handoff.

New projects always use the full harness lifecycle from requirements analysis through final handoff, even when the initial request is short. Do not downshift to a reduced planning mode unless the user explicitly asks to stop before implementation or handoff.

For ordinary new-project work inside `project-workspace/`, the global harness may proceed within the previously approved scope without requiring the user to repeat the full prompt. Caution and dangerous work still follow the Safety Warning Protocol.

When new-project work contains independent requirements, design, research, implementation, documentation, or QA streams, the harness should split them into bounded parallel work and fan the results back into a supervised review and synthesis step.

Every project must include `docs/DEVELOPMENT_PLAN.txt`, `CHANGELOG.txt`, and `logs/app.log`; project code, plans, change history, and test logs must stay consistent.

When a user reports real-use test feedback or requested improvements after a project handoff, QA must review the relevant `docs/DEVELOPMENT_PLAN.txt`, `logs/app.log`, and user feedback, then decide which specialist should perform the fix. Each completed fix must include a dedicated `.txt` fix artifact in the project output.

## Safety Warning Protocol

If the user says "승인", "진행해", "계속 진행", or "OK 진행", continue ordinary work within the previously proposed scope without asking again.

Ordinary work includes new docs, new skills, new project-pattern docs, new project folders under `project-workspace/`, `tree`, `git status`, `git diff`, approved file creation, typo fixes, and `docs/harness` documentation improvements.

Before caution work, show:

```text
[주의 작업]
작업 내용:
영향 범위:
되돌리는 방법:
계속하려면 "승인" 또는 "진행해"라고 입력하세요.
```

Caution work includes `AGENTS.md` changes, `.gitignore` changes, existing skill changes, large existing `docs/harness` rewrites, `git add`, `git commit`, and folder-structure changes.

Before dangerous work, do not proceed on "승인" alone. Show:

```text
[위험 작업]
작업 내용:
왜 위험한가:
영향 범위:
되돌리는 방법:
대안:
계속하려면 "위험 확인 후 승인"이라고 입력하세요.
```

Dangerous work includes `git push`, force push, `git reset`, `git rebase`, `git clean`, file or folder deletion, package installation, external network access, secret-related work, large `.codex/agents/*.toml` changes, `.agents/skills/harness` changes or deletion, `.git` folder work, access or edits outside the current workspace, and whole-repository restructuring.

## Commit/Push Explanation Protocol

When suggesting commit or push, include:

```text
커밋이란?
- 현재까지 작업한 변경사항을 내 PC의 Git 기록에 저장하는 작업입니다.
- 쉽게 말해 “현재 상태를 저장 지점으로 남기는 것”입니다.
- 커밋만 해서는 GitHub에 업로드되지 않습니다.

푸쉬란?
- 내 PC에 저장된 커밋을 GitHub 원격 저장소에 업로드하는 작업입니다.
- 쉽게 말해 “내 PC의 작업 기록을 GitHub에 반영하는 것”입니다.
- push 후에는 GitHub 저장소에 변경사항이 보이게 됩니다.
```

When suggesting both commit and push, ask:

```text
커밋과 푸쉬를 진행하시겠습니까?

진행하려면 다음 중 하나로 답변하세요.
- "커밋만 진행"
- "커밋과 푸쉬 진행"
- "중단"
```
