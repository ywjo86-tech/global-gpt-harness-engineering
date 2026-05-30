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

## Safety Warning Protocol

If the user says "승인", "진행해", "계속 진행", or "OK 진행", continue ordinary work within the previously proposed scope without asking again.

Ordinary work includes new docs, new skills, new project-pattern docs, `tree`, `git status`, `git diff`, approved file creation, typo fixes, and `docs/harness` documentation improvements.

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
