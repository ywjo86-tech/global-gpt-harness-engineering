# Agent TOML Schema

Codex custom agent definitions live under `.codex/agents/` and use `.toml` files.

## Required Fields

```toml
name = "agent-name"
description = "Short description of the agent role."
```

## Recommended Sections

```toml
[instructions]
purpose = "Why this agent exists."
scope = [
  "What this agent should handle."
]
outputs = [
  "Expected output artifact or decision."
]

[boundaries]
do_not_create = [".claude/"]
avoid_committing = ["_workspace/", "secrets"]
```

## Naming

- Use lowercase kebab-case file names.
- Match the `name` field to the file name without `.toml`.
- Keep descriptions role-focused, not task-specific.

## Role Examples

### PMO Orchestrator

Use for lifecycle coordination across intake, requirements, harness design, QA, and release handoff.

```toml
name = "pmo-orchestrator"
description = "Coordinates the Global Harness Engineering PMO workflow."

[instructions]
purpose = "Keep Codex project work aligned with the PMO lifecycle."
scope = [
  "Clarify business purpose.",
  "Route work through the project lifecycle.",
  "Choose the smallest useful agent team."
]
outputs = [
  "Lifecycle plan",
  "Target file plan",
  "QA and release checklist"
]

[boundaries]
do_not_create = [".claude/"]
avoid_committing = ["_workspace/", "secrets"]
```

### Requirements Analyst

Use before design or implementation when project requirements are not yet stable.

```toml
name = "requirements-analyst"
description = "Analyzes project purpose, requirements, constraints, risks, and open questions."

[instructions]
purpose = "Turn ambiguous project requests into clear requirements."
scope = [
  "Capture business goals.",
  "Separate functional and non-functional requirements.",
  "Identify assumptions and risks."
]
outputs = [
  "Requirements summary",
  "Acceptance criteria",
  "Open questions"
]
```

### QA Release Reviewer

Use before commit, release, or deployment handoff.

```toml
name = "qa-release-reviewer"
description = "Reviews harness changes for structure, security, documentation, and release readiness."

[instructions]
purpose = "Keep PMO artifacts shippable and safe to reuse."
scope = [
  "Verify path conventions.",
  "Check secrets and sensitive data.",
  "Confirm tests and documentation."
]
outputs = [
  "QA findings",
  "Verification summary",
  "Release readiness notes"
]
```

## Review Rules

- Do not place secrets in agent files.
- Do not create `.claude/` paths.
- Keep agent roles stable and reusable.
- Prefer docs or skills over new agents for narrow one-off work.
