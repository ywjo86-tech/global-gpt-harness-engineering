# New Project Orchestration Pattern

## Purpose

Use this pattern to convert a short project-start request into a full project-local agent team, role architecture, skill set, orchestration workflow, validation plan, and usage guide.

The goal is to remove the need for the user to paste a long prompt every time a new project begins. The user should be able to provide only:

- project start signal
- idea
- requirements
- constraints
- desired deliverables or direction

MVP is a milestone in this pattern, not the default endpoint. Unless the user asks for MVP-only planning, the project flow continues through implementation, integration, QA, release readiness, and deployment handoff.

## Trigger

Use this pattern when the request includes phrases such as:

- `새 프로젝트 시작`
- `새 프로젝트 진행`
- `프로젝트 아이디어`
- `이 아이디어로 프로젝트를 시작`
- `하네스 방식으로 프로젝트 구성`

The trigger does not grant permission for dangerous work. It only selects the new-project orchestration flow.

## Inputs

- Project idea
- Business purpose
- Target users
- Requirements
- Constraints
- Non-goals
- Desired deliverables
- Preferred stack or platform
- Existing repository path or desired project location

If some inputs are missing, infer safe defaults and continue unless the missing information affects file creation, sensitive data, external systems, or implementation safety.

## Architecture Selection

Choose the smallest architecture that preserves quality.

| Pattern | Use When | Output |
| --- | --- | --- |
| Pipeline | Work has a natural order from idea to deployment handoff | ordered workflow and phase handoffs |
| Fan-out/Fan-in | Independent specialists can review the same input | branch outputs and synthesis |
| Expert Pool | Only selected specialists should run per request | routing table and specialist list |
| Producer-Reviewer | Quality review is required after artifact generation | producer skill, reviewer skill, review loop |
| Supervisor | Work units appear dynamically during execution | backlog, assignment, escalation policy |
| Hierarchical Delegation | The project splits into large subdomains | top-level and subdomain handoff contracts |

Default to Pipeline plus Producer-Reviewer through release readiness. Add Fan-out/Fan-in for independent domain reviews, Expert Pool for selective specialist routing, Supervisor for dynamic work assignment, and Hierarchical Delegation for large subdomains only when the project needs them.

## Standard Agent Team

| Role | Responsibility | Typical Skill |
| --- | --- | --- |
| Project Orchestrator | Scope, routing, sequencing, handoffs, final reporting | `{project}-orchestrator` |
| Intake Analyst | Business purpose, users, constraints, success criteria | `{project}-intake-analyst` |
| Requirements Analyst | Functional and non-functional requirements | `{project}-requirements-analyst` |
| Architecture Designer | Stack, system boundaries, components, integrations | `{project}-architecture-designer` |
| Implementation Planner | Work packages, sequencing, validation plan | `{project}-implementation-planner` |
| Specialist Pool | Domain-specific implementation or review | project-specific names |
| Integration Coordinator | Cross-component wiring, compatibility, and end-to-end readiness | `{project}-integration-coordinator` |
| QA Release Reviewer | Testing, risks, release readiness, handoff quality | `{project}-qa-release-reviewer` |
| Deployment Handoff Lead | Deployment prerequisites, runbook, rollback notes, operator handoff | `{project}-deployment-handoff-lead` |

Do not create every role automatically. Create only roles that are durable enough to reuse.

## Workflow

### Phase 1: Project Intake

Actions:

- Capture the project idea and desired outcome.
- Identify users, business purpose, constraints, non-goals, and success criteria.
- Classify missing information as blocker or safe assumption.

Outputs:

- project summary
- assumption list
- open questions, if any

### Phase 2: Requirements Definition

Actions:

- Convert the idea into functional requirements.
- Define non-functional requirements.
- Define acceptance criteria.

Outputs:

- requirements summary
- acceptance criteria
- risk list

### Phase 3: Team Architecture Design

Actions:

- Choose Pipeline, Fan-out/Fan-in, Expert Pool, Producer-Reviewer, Supervisor, Hierarchical Delegation, or a small combination.
- Define why each selected pattern is necessary.
- Define handoff artifacts.
- Define MVP as the first usable milestone and define the post-MVP path to release readiness.

Outputs:

- selected architecture
- role topology
- routing rules
- MVP boundary and post-MVP delivery plan

### Phase 4: Agent and Skill Definition

Actions:

- Define orchestrator skill.
- Define specialist skills.
- Move detailed role instructions to `docs/harness/{project}/` when needed.
- Keep skill entrypoints short and discoverable.

Outputs:

- `.agents/skills/{project}-orchestrator/SKILL.md`
- `.agents/skills/{specialist}/SKILL.md`
- optional references under specialist folders

### Phase 5: MVP Implementation Pipeline

Actions:

- Define the MVP feature set.
- Define implementation work packages.
- Route work to the specialist pool.
- Use Producer-Reviewer loops for generated code, UI, documentation, or workflow artifacts.
- Use Supervisor routing when work items change during implementation.

Outputs:

- MVP implementation plan
- work package list
- review gates

### Phase 6: Integration and Orchestration

Actions:

- Define phase order.
- Define ownership and handoff files.
- Define worker delegation rules.
- Define failure and escalation policy.
- Define how MVP outputs become integrated release-candidate outputs.

Outputs:

- `docs/harness/{project}/team-spec.md`
- `docs/harness/{project}/workflow.md`

### Phase 7: Fan-out/Fan-in Quality Review

Actions:

- Run independent reviews where useful: functionality, UX, security, performance, maintainability, data handling, deployment, and documentation.
- Keep branch outputs separate.
- Synthesize disagreements into a single fix list.

Outputs:

- specialist review artifacts
- synthesis report
- release-blocker list

### Phase 8: QA and Release Readiness

Actions:

- Define validation commands.
- Define review criteria.
- Define release handoff format.
- Define manual verification requirements.
- Define release candidate acceptance criteria.

Outputs:

- QA checklist
- release handoff contract
- `docs/harness/{project}/usage-guide.md`

### Phase 9: Deployment Handoff

Actions:

- Define deployment prerequisites.
- Define environment assumptions.
- Define runbook, rollback notes, and operator handoff.
- Separate local/internal deployment from public/cloud deployment unless explicitly approved.
- Stop before actual deployment when credentials, network access, package installation, git push, or external systems require approval.

Outputs:

- deployment handoff
- runbook
- rollback notes
- remaining operational risks

## Default File Layout

```text
PROJECT_ROOT/
  AGENTS.md
  .agents/
    skills/
      {project}-orchestrator/
        SKILL.md
      {specialist}/
        SKILL.md
  docs/
    harness/
      {project}/
        team-spec.md
        workflow.md
        usage-guide.md
        release-handoff.md
  _workspace/
    00_input/
    01_requirements/
    02_architecture/
    03_implementation/
    04_review/
    05_release/
    final/
```

## Standard Short User Prompt

The user should only need:

```text
새 프로젝트 시작

아이디어:
- ...

요구사항:
- ...

제약사항:
- ...

원하는 산출물:
- ...
```

The orchestrator then expands this into intake, requirements, architecture, MVP milestone planning, agent team design, skill creation, implementation orchestration, fan-out/fan-in review, QA, release readiness, deployment handoff, and usage documentation.

## Approval Rules

Before editing files, present:

- target repository or project path
- file creation and modification plan
- selected team architecture
- validation plan

Proceed only after the appropriate approval for the work type.

If the project target is outside the current workspace, external network is needed, dependencies must be installed, files must be deleted, secrets are involved, or git push is requested, follow the dangerous-work approval protocol.

## Validation Criteria

- The user can trigger the flow with `새 프로젝트 시작`.
- The selected architecture is no larger than necessary.
- MVP is treated as a milestone, not the final default endpoint.
- The post-MVP path to release readiness and deployment handoff is explicit.
- Specialist roles have clear ownership and do not overlap heavily.
- Every phase has an output artifact or clear completion criterion.
- `AGENTS.md` remains concise.
- Detailed project-team behavior lives under `docs/harness/{project}/`.
- No `.claude/` paths are created.
- Sensitive data, secrets, network access, deletion, dependency installation, and git push boundaries are explicit.
