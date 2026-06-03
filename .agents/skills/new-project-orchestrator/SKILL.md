---
name: new-project-orchestrator
description: Start a new project from a short idea, requirements, constraints, and desired deliverables by designing the project agent team, skills, orchestration, and delivery pipeline.
---

# New Project Orchestrator

Use this skill when the user starts a new project and provides an idea, requirements, constraints, desired output direction, or business goal.

Trigger phrases include:

- `새 프로젝트 시작`
- `새 프로젝트 진행`
- `프로젝트 아이디어`
- `이 아이디어로 프로젝트를 시작`
- `하네스 방식으로 새 프로젝트 구성`

## Inputs

- Project idea
- Requirements
- Constraints and non-goals
- Desired deliverables
- Target users or business purpose, when provided
- Preferred stack or runtime, when provided
- Existing repository path, when provided

## Default Behavior

When the user provides enough information to infer the project direction, proceed with the standard new-project harness flow without requiring the user to paste a long prompt.

Treat MVP as an intermediate milestone, not the final objective, unless the user explicitly asks for MVP-only planning. The default target is a deployable project path that includes implementation, integration, QA, release readiness, and deployment handoff.

Ask follow-up questions only when a missing fact would create high implementation risk, such as:

- target repository or workspace is unknown and files must be created
- sensitive data, credentials, network access, or external systems are involved
- the requested deliverable conflicts with stated constraints
- success criteria are too vague to choose an architecture

## Agent Team Pattern

Use the smallest architecture that can satisfy the project.

- Pipeline: default for idea -> requirements -> architecture -> MVP milestone -> implementation -> integration -> QA -> release readiness -> deployment handoff.
- Fan-out/Fan-in: use for independent research, UX, security, performance, deployment, or technical-option reviews.
- Expert Pool: use when only a subset of specialists should run for each request.
- Producer-Reviewer: use whenever a generated artifact needs a separate quality gate.
- Supervisor: use when tasks emerge dynamically and need central assignment through implementation, QA, and release readiness.
- Hierarchical Delegation: use when a large project naturally splits into bounded subdomains.

## Standard Team

- Project orchestrator: owns scope, routing, handoffs, and final reporting.
- Intake analyst: clarifies business purpose, users, constraints, and success criteria.
- Requirements analyst: creates functional and non-functional requirements.
- Architecture designer: chooses stack, boundaries, components, and integration points.
- Implementation planner: turns architecture into staged work packages.
- Specialist pool: domain-specific implementers, reviewers, or researchers.
- Integration coordinator: owns cross-component wiring, compatibility, and end-to-end readiness when the project has multiple moving parts.
- QA release reviewer: validates tests, risks, release readiness, and handoff quality.
- Deployment handoff lead: defines deployment prerequisites, runbook, rollback notes, and final operator handoff when deployment is in scope.

Create only the roles that the project actually needs.

## Workflow

1. Capture the project idea and desired outcome.
2. Define business purpose, users, requirements, constraints, non-goals, and acceptance criteria.
3. Define MVP as the first usable milestone and define what remains after MVP.
4. Choose the project team architecture and explain why it fits.
5. Define the agent roles and subagent responsibilities.
6. Define skill files to create under `.agents/skills/`.
7. Define orchestration and handoff docs under `docs/harness/{project}/`.
8. Define `_workspace/` handoff artifacts for large or multi-phase work.
9. Define implementation, integration, QA, release readiness, deployment handoff, and rollback-readiness gates.
10. Present the planned target files before editing.
11. After approval, create the repo-local project harness inside the approved scope.

## Generated Artifacts

Default artifact set:

- `AGENTS.md` only when the project needs durable repo-wide guidance
- `.agents/skills/{project}-orchestrator/SKILL.md`
- `.agents/skills/{specialist}/SKILL.md` for reusable specialist roles
- `docs/harness/{project}/team-spec.md`
- `docs/harness/{project}/workflow.md`
- `docs/harness/{project}/usage-guide.md`
- `docs/harness/{project}/release-handoff.md` when deployment or operator handoff is in scope
- `_workspace/` folders for temporary handoffs, when useful

Do not create `.claude/` paths.

## Output

For planning-only requests, output:

- project summary
- requirements and constraints
- selected team architecture
- role list
- MVP milestone and post-MVP path to deployment
- file plan
- validation plan
- release readiness and deployment handoff plan
- approval needed before edits

For approved implementation, output:

- changed file list
- validation commands
- validation results
- remaining risks
- commit/push suggestion status

## Validation

- Skills have YAML frontmatter with `name` and `description`.
- `AGENTS.md` remains short and pointer-heavy.
- Detailed workflow guidance lives in `docs/harness/`.
- Role handoffs and output artifacts are deterministic.
- MVP is clearly separated from release readiness and deployment handoff.
- Safety, secrets, network, deletion, and git push boundaries are explicit.
- The project can be started from a short `새 프로젝트 시작` request.
