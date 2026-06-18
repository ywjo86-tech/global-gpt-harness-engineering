# Orchestration Approval Rules

## Purpose

These rules define how the orchestrator classifies work by risk, when repeated approval is allowed, and when user approval is still required even after a stage gate passes.

## Risk Classification

- Classify a task by the highest-risk item included in the task.
- If general work and caution work are mixed, classify the task as caution work.
- If general work or caution work includes any dangerous work, classify the task as dangerous work.
- If the classification is ambiguous, choose the higher-risk class.

## Execution Boundary Safety

- The planner/executor split is an execution detail, not a permission bypass.
- Planning artifacts may be created automatically for general work.
- Execution materialization may be automatic only when the materialized slices remain general work.
- Any slice that touches caution or dangerous work must remain pending until the matching approval is provided.
- If a planning artifact contains mixed-risk slices, the highest-risk slice determines the approval state for that slice.

## General Work

General work may proceed within the already approved scope without repeated approval.
When the orchestrator is operating within an already approved scope, general work is executed automatically without asking again.

General work includes:

- new file creation
- new project folder creation under `project-workspace/`
- `_workspace/` temporary handoff artifact creation
- analysis
- documentation
- document summaries and compression
- test execution
- log review
- flow review
- code analysis
- execution log analysis
- `git status`
- `git diff`
- `tree`
- typo fixes
- project-local planning artifacts
- development plan creation or drafting
- changelog creation or drafting
- app log creation or test-log recording
- docs/harness project-document creation
- fan-out and fan-in planning
- role definition
- stage-gate review documentation

General work does not directly threaten repository structure, Git history, external systems, or sensitive data.

## Caution Work

Caution work may affect shared rules, repository structure, or reversible project scaffolding.

Before caution work starts, the orchestrator must show:

```text
[주의 작업]
작업 내용:
영향 범위:
되돌리는 방법:
계속하려면 "승인" 또는 "진행해"라고 입력하세요.
```

The user may proceed with:

- `승인`
- `진행해`
- `계속 진행`
- `OK 진행`

Caution work includes:

- `AGENTS.md` edits
- `.gitignore` edits
- existing skill edits
- large existing `docs/harness` rewrites
- existing common-template edits
- existing project-common structural edits
- shared rule-document edits
- `git add`
- `git commit`
- shared rule stabilization that does not cross into dangerous work

## Dangerous Work

Dangerous work affects storage, Git history, external systems, security-sensitive material, or files outside the current workspace.

Before dangerous work starts, the orchestrator must show:

```text
[위험 작업]
작업 내용:
왜 위험한가:
영향 범위:
되돌리는 방법:
대안:
계속하려면 "위험 확인 후 승인"이라고 입력하세요.
```

The only valid user response for dangerous work is:

- `위험 확인 후 승인`

Dangerous work includes:

- `git push`
- force push
- `git reset`
- `git rebase`
- `git clean`
- file deletion
- folder deletion
- package installation
- external network access
- API key, token, password, or secret handling
- secret file access or editing
- `.git` folder manipulation
- workspace-outside file changes
- whole-repository restructuring
- large `.codex/agents/*.toml` changes
- `.agents/skills/harness` deletion or large rewrite

## Delegated Documentation Stabilization

When the user explicitly asks for repository or project stabilization, the orchestrator may continue within the previously approved scope for documentation-only cleanup.

That delegated approval may cover:

- document cleanup
- document summarization
- document compression
- internal link cleanup
- duplicate wording removal
- stale-description cleanup
- wording changes that preserve meaning
- document structure cleanup
- consistency updates among `docs/DEVELOPMENT_PLAN.txt`, `CHANGELOG.txt`, and `logs/app.log`

That delegated approval does not cover:

- `git add`
- `git commit`
- `git push`
- file deletion
- folder deletion
- package installation
- external network access
- API key, token, password, or secret handling
- secret file access or editing
- `.git` folder manipulation
- workspace-outside file changes
- whole-repository restructuring
- large `.codex/agents/*.toml` changes
- `.agents/skills/harness` deletion or large rewrite
- weakening approval, security, or dangerous-work rules

The first delegated approval only covers file modification rights inside the approved scope.

## Stage Gate Boundary

- `GO` and `CONDITIONAL GO` are phase-transition judgments only.
- They do not replace the Safety Warning Protocol.
- If the next step is caution work, the orchestrator still needs a user `승인`, `진행해`, `계속 진행`, or `OK 진행`.
- If the next step is dangerous work, the orchestrator still needs `위험 확인 후 승인`.

## Required Approval Record

When a caution or dangerous step is requested, record:

- purpose
- allowed work
- allowed path
- allowed file types
- forbidden work
- effective duration or stage
- log location

## Orchestrator Judgment Flow

1. Classify the task by highest risk item.
2. If the task is general work inside the approved scope, proceed automatically.
3. If the task includes caution work, request a caution approval prompt.
4. If the task includes dangerous work, request a dangerous approval prompt.
5. Treat stage-gate approval and safety approval as separate decisions.

## Notes

- This policy applies to new projects and current project thread work.
- This policy does not authorize runtime code changes by itself.
- This policy does not authorize work outside the approved workspace.
