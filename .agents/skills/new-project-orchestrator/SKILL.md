---
name: new-project-orchestrator
description: Start a new project from a short idea, requirements, constraints, and desired deliverables by designing the project agent team, skills, orchestration, and delivery pipeline.
---

# New Project Orchestrator

Use this skill when the user starts a new project and provides an idea, requirements, constraints, desired output direction, or business goal.

Trigger phrases include:

- `새 프로젝트 시작`
- `새 프로젝트 진행`
- `프로젝트 진행`
- `프로젝트 아이디어`
- `이 아이디어로 프로젝트를 시작`
- `하네스 방식으로 새 프로젝트 구성`
- `만들어줘`
- `생성해줘`
- `만들어줘 프로젝트`
- `생성해줘 프로젝트`

## Inputs

- Project idea
- Requirements
- Constraints and non-goals
- Desired deliverables
- Project keywords, purpose, and target achievement goals
- Target users or business purpose, when provided
- Preferred stack or runtime, when provided
- Existing repository path, when provided

## Default Behavior

When the user provides enough information to infer the project direction, proceed with the standard new-project harness flow without requiring the user to paste a long prompt.

Create each new project under `project-workspace/{project-slug}/` by default. Use a deterministic, repository-friendly slug inferred from the project keyword or name. Ask only when the slug would be ambiguous, unsafe, or likely to collide with existing project work.

Always run the full harness lifecycle for new projects: requirements analysis, team architecture, project subagent definition, skill analysis and creation, orchestration, MVP milestone delivery, implementation, integration, QA, release readiness, and final deployment handoff. Treat MVP as an intermediate milestone, not the final objective, unless the user explicitly asks to stop at MVP. Do not downshift to a reduced planning mode just to save tokens; preserve scope stability by keeping the full lifecycle visible and controlled.

For ordinary project-harness work, the global harness may proceed within the approved scope without asking the user to repeat the full prompt. Ordinary work includes project-folder creation under `project-workspace/`, new project docs, new project-specific skills, project templates, `_workspace/` handoff artifacts, typo fixes, and documentation improvements. Still follow repo safety rules for caution or dangerous work such as editing global guidance, changing existing shared skills, installing packages, deleting files, or performing Git stage/commit/push operations.

Enable bounded parallel work by default whenever tasks can be completed independently and later merged through a deterministic handoff. The supervisor central agent owns the split, assigns independent streams, tracks outputs, resolves conflicts, and performs the fan-in synthesis before QA.

Every project must include `docs/DEVELOPMENT_PLAN.txt`, `CHANGELOG.txt`, and `logs/app.log`. Treat `docs/DEVELOPMENT_PLAN.txt` as the durable project contract for final output, future real-use testing, and error analysis. Keep it synchronized with the actual code structure whenever code, architecture, execution flow, tests, or deployment behavior changes.

Ask follow-up questions only when a missing fact would create high implementation risk, such as:

- target repository or workspace is unknown and files must be created outside `project-workspace/`
- sensitive data, credentials, network access, or external systems are involved
- the requested deliverable conflicts with stated constraints
- success criteria are too vague to choose an architecture

## Agent Team Pattern

Use the full harness lifecycle for every new project, then size the number of active specialists and parallel streams to the actual scope and dependencies.

- Pipeline: default for idea -> requirements -> architecture -> MVP milestone -> implementation -> integration -> QA -> release readiness -> deployment handoff.
- Fan-out/Fan-in: use for independent research, UX, security, performance, deployment, or technical-option reviews.
- Expert Pool: use when only a subset of specialists should run for each request or project situation.
- Producer-Reviewer: use whenever a generated artifact needs a separate quality gate.
- Supervisor: use when tasks emerge dynamically and need central assignment, redistribution, and final synthesis through implementation, QA, and release readiness.
- Hierarchical Delegation: use when a large project naturally splits into bounded subdomains that may require top-down recursive delegation.

Compose these patterns when useful: a central supervisor may run the main pipeline, dispatch bounded fan-out/fan-in work to independent specialists, selectively call an expert pool by situation, and use producer-reviewer loops before fan-in synthesis.

## Parallel Work Activation

Activate parallel work when at least two work streams can proceed without modifying the same artifact or depending on each other's unfinished decisions.

Good parallel streams include:

- intake and requirements clarification drafts
- UX, information architecture, and user journey options
- technical architecture, data model, security, performance, and deployment option reviews
- independent feature specifications or implementation work packages
- documentation, QA checklist, release handoff, and risk review drafts
- multi-surface review such as architecture, security, maintainability, and release readiness

Do not parallelize work that shares a fragile editing surface, requires a single unresolved decision, touches secrets, performs package installation, deletes files, changes Git state, or needs external network access. Route those items through the supervisor as sequential gates and use the Safety Warning Protocol when required.

For every fan-out, create or declare:

- work-stream owner or specialist role
- input artifact and expected output artifact
- independence assumption
- merge point and reviewer
- conflict policy when outputs disagree

For every fan-in, the supervisor central agent must:

- compare outputs against requirements and acceptance criteria
- identify conflicts, gaps, duplicate work, and incompatible assumptions
- select, merge, or request bounded revision from specialists
- preserve intermediate outputs under `_workspace/` when the project is large or multi-phase
- send the synthesized result through QA release review before final handoff

## Required Project Records

Create and maintain these files for every generated project:

- `project-workspace/{project-slug}/docs/DEVELOPMENT_PLAN.txt`
- `project-workspace/{project-slug}/CHANGELOG.txt`
- `project-workspace/{project-slug}/logs/app.log`

`docs/DEVELOPMENT_PLAN.txt` must describe the current, real project state in detail. Include at least:

- project purpose
- feature list
- execution flow
- file structure
- major function or class responsibilities
- exception handling policy
- logging policy
- test scenarios
- build and deployment method
- modification-forbidden areas

Keep `docs/DEVELOPMENT_PLAN.txt` aligned with the actual implementation. When creating or modifying code, update the plan in the same work pass if the file structure, public behavior, major function responsibility, exception handling, logging, tests, build, deployment, or protected areas change.

Record code changes in `CHANGELOG.txt`. Each entry should include the date, changed area, summary, reason, and any validation performed. Do not use the changelog for secrets, credentials, or sensitive runtime data.

Write test execution results to `logs/app.log`. Include the timestamp, command or scenario, pass/fail status, and important error messages. If tests cannot be run, record the reason in the final response and, when working inside a generated project, in `logs/app.log`.

For future error analysis, review `docs/DEVELOPMENT_PLAN.txt` together with `logs/app.log` before changing code. Use the development plan to verify expected structure and behavior, then use the log to identify observed failures.

## Real-Use Feedback and Fix Flow

Use this flow when the user performs final-output real-use testing, reviews the result in ChatGPT, and returns improvement requests, defects, or supplement notes.

Required inputs for a fix cycle:

- user feedback or requested improvement
- current `docs/DEVELOPMENT_PLAN.txt`
- relevant `logs/app.log` excerpts, selected by recency, error keyword, scenario, or timestamp
- current code or artifact context related to the requested fix

The QA release reviewer owns first analysis for fix cycles. QA must:

- compare the user feedback against `docs/DEVELOPMENT_PLAN.txt`
- inspect only the relevant `logs/app.log` sections needed to understand the failure or requested improvement
- classify the item as defect, missing requirement, UX improvement, documentation gap, test gap, deployment issue, or scope change
- identify the likely affected files, functions, risks, and validation needs
- decide which specialist should perform the correction
- provide the supervisor central agent with the fix assignment, rationale, and acceptance criteria

The supervisor central agent then assigns the correction to the selected specialist, tracks dependencies, prevents scope drift, and routes the completed work back through QA.

After every completed fix, include a dedicated `.txt` fix artifact in the project output. Default path:

- `project-workspace/{project-slug}/docs/fixes/{YYYYMMDD}-{fix-slug}.txt`

Each fix artifact must include:

- user feedback summary
- QA classification and analysis
- assigned specialist and assignment reason
- affected files or artifacts
- implementation summary
- `DEVELOPMENT_PLAN.txt` updates made or reason no update was needed
- `CHANGELOG.txt` entry reference
- `logs/app.log` test evidence summary
- remaining risks or follow-up items

## Standard Team

- Project orchestrator: owns scope, routing, handoffs, and final reporting.
- Supervisor central agent: dynamically distributes work, tracks dependencies, delegates from higher-level goals to lower-level subgoals, and owns final synthesis.
- Intake analyst: clarifies business purpose, users, constraints, and success criteria.
- Requirements analyst: creates functional and non-functional requirements.
- Architecture designer: chooses stack, boundaries, components, and integration points.
- Implementation planner: turns architecture into staged work packages.
- Specialist pool: domain-specific implementers, reviewers, or researchers selected only when their expertise fits the current project situation.
- Integration coordinator: owns cross-component wiring, compatibility, and end-to-end readiness when the project has multiple moving parts.
- QA release reviewer: validates tests, risks, release readiness, and handoff quality.
- Fix QA dispatcher: analyzes user real-use feedback against `DEVELOPMENT_PLAN.txt` and `logs/app.log`, classifies the issue, and selects the specialist for correction. This role may be handled by the QA release reviewer when no separate role is needed.
- Deployment handoff lead: defines deployment prerequisites, runbook, rollback notes, and final operator handoff when deployment is in scope.

Create only the roles that the project actually needs.

## Workflow

1. Capture the project idea and desired outcome.
2. Define business purpose, users, requirements, constraints, non-goals, and acceptance criteria.
3. Create or target `project-workspace/{project-slug}/` as the project root.
4. Define MVP as the first usable milestone and define what remains after MVP.
5. Choose the project team architecture and explain why it fits.
6. Define the project subagents, responsibilities, handoff edges, and specialist pool routing rules.
7. Define project-specific skill files to create under `project-workspace/{project-slug}/.agents/skills/` unless a reusable global skill is explicitly needed.
8. Define orchestration and handoff docs under `project-workspace/{project-slug}/docs/harness/`.
9. Define `project-workspace/{project-slug}/_workspace/` handoff artifacts for large or multi-phase work.
10. Activate bounded parallel fan-out for independent streams, synthesize outputs through the supervisor central agent, and route defects back through producer-reviewer loops.
11. Create and keep synchronized `docs/DEVELOPMENT_PLAN.txt`, `CHANGELOG.txt`, and `logs/app.log`.
12. Define implementation, integration, QA, release readiness, deployment handoff, and rollback-readiness gates.
13. Present the planned target files before caution edits or when the requested scope is not already approved.
14. After approval when required, create the project harness and project artifacts inside the approved scope.
15. For post-handoff real-use feedback, run the fix cycle: QA analysis -> specialist assignment -> correction -> QA validation -> dedicated fix `.txt` artifact -> updated final handoff.

## Generated Artifacts

Default artifact set:

- `project-workspace/{project-slug}/AGENTS.md` only when the project needs durable project-wide guidance
- `project-workspace/{project-slug}/.agents/skills/{project}-orchestrator/SKILL.md`
- `project-workspace/{project-slug}/.agents/skills/{specialist}/SKILL.md` for reusable specialist roles
- `project-workspace/{project-slug}/docs/harness/team-spec.md`
- `project-workspace/{project-slug}/docs/harness/workflow.md`
- `project-workspace/{project-slug}/docs/harness/usage-guide.md`
- `project-workspace/{project-slug}/docs/harness/milestones.md`
- `project-workspace/{project-slug}/docs/harness/release-handoff.md` when deployment or operator handoff is in scope
- `project-workspace/{project-slug}/docs/DEVELOPMENT_PLAN.txt`
- `project-workspace/{project-slug}/docs/fixes/{YYYYMMDD}-{fix-slug}.txt` for every completed post-handoff fix
- `project-workspace/{project-slug}/CHANGELOG.txt`
- `project-workspace/{project-slug}/logs/app.log`
- `project-workspace/{project-slug}/_workspace/` folders for temporary handoffs, when useful

Global artifacts may be changed only when the project creates a reusable repository-wide pattern. Prefer project-local artifacts inside `project-workspace/{project-slug}/`.

Do not create `.claude/` paths.

## Output

For planning-only requests, output:

- project summary
- requirements and constraints
- selected team architecture
- role list
- parallel work-stream plan and fan-in merge point
- MVP milestone and post-MVP path to deployment
- file plan
- required record plan for `docs/DEVELOPMENT_PLAN.txt`, `CHANGELOG.txt`, and `logs/app.log`
- validation plan
- release readiness and deployment handoff plan
- project workspace path
- approval needed before edits

For approved implementation, output:

- changed file list
- `CHANGELOG.txt` update summary
- fix artifact path and summary, when handling user real-use feedback
- validation commands
- validation results
- `logs/app.log` test log summary
- parallel work-stream results and fan-in decisions
- remaining risks
- MVP milestone status and final handoff status
- commit/push suggestion status

## Validation

- Skills have YAML frontmatter with `name` and `description`.
- `AGENTS.md` remains short and pointer-heavy.
- Detailed workflow guidance lives in `docs/harness/`.
- Role handoffs and output artifacts are deterministic.
- MVP is clearly separated from release readiness and deployment handoff.
- Safety, secrets, network, deletion, and git push boundaries are explicit.
- Independent work streams are parallelized only with explicit handoff artifacts, merge points, and conflict policy.
- `docs/DEVELOPMENT_PLAN.txt` exists and matches the actual code structure, execution flow, function responsibilities, exception policy, logging policy, test scenarios, build/deploy method, and modification-forbidden areas.
- Code changes are recorded in `CHANGELOG.txt`.
- Test execution results are recorded in `logs/app.log`.
- Post-handoff user feedback is analyzed by QA against `docs/DEVELOPMENT_PLAN.txt`, relevant `logs/app.log` excerpts, and the user-provided improvement details before any code correction.
- Every completed post-handoff fix includes a dedicated `.txt` fix artifact in `docs/fixes/`.
- The project can be started from a short `새 프로젝트 시작`, `프로젝트 진행`, `만들어줘`, or `생성해줘` request.
- New project artifacts default to `project-workspace/{project-slug}/`.
