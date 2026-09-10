---
name: request-intent-definition-harness
description: Preserve and normalize a user's request into an intent contract that separates explicit statements, bounded inferences, constraints, exclusions, unknowns, and conflicts without creating requirements or choosing a solution.
status: PROVISIONAL
---

# Request Intent Definition Harness

Use this skill at the very front of a project or change request when the request is broad, ambiguous, high-impact, easily over-interpreted, or likely to lose important user constraints during downstream planning.

This skill exists before `project-intake` and `requirements-analysis`. It does not replace either one.

- Intent definition preserves what the user actually asked and what remains unknown.
- `project-intake` turns that intent into project purpose, scope, stakeholders, and success context.
- `requirements-analysis` converts approved intake context into functional/non-functional requirements and testable acceptance criteria.

## Purpose

Create a loss-minimized Intent Contract that prevents downstream agents from silently converting assumptions into requirements or prematurely selecting a solution.

## Trigger

Use when one or more of the following are true:

- The user's surface request can reasonably map to multiple technical or business interpretations.
- Existing project work must preserve explicit exclusions or modification-forbidden areas.
- A request mixes observed symptoms with a presumed cause or solution.
- The user provides a short command whose intended outcome depends on prior context.
- Misinterpreting the request would create meaningful scope, cost, security, architecture, or rework risk.

Do not trigger merely to restate every simple request. Do not use this skill to produce requirements, architecture, implementation plans, or release decisions.

## Required Inputs

- Raw user request
- Relevant user-provided or approved context
- Existing project constraints or protected areas, when applicable
- Prior approved intent or plan references when the request modifies existing work

## Intent Classification

Every material statement should be classified as one of:

- `EXPLICIT`: directly stated by the user or an authoritative approved artifact.
- `INFERRED`: a bounded interpretation supported by context but not directly stated.
- `UNKNOWN`: information not known and not safely inferable.
- `CONFLICT`: two authoritative statements or constraints that cannot both be satisfied as written.

Never promote `INFERRED` to `EXPLICIT` without new evidence.

## Agent Team Pattern

Create only the roles needed for the ambiguity level.

- Intent lead: preserves the raw request and produces the normalized intent statement.
- Explicit/inferred classifier: separates direct instructions from bounded interpretation.
- Constraint/exclusion analyst: extracts must-keep, must-not-change, and non-goal statements without inventing new constraints.
- Ambiguity/conflict reviewer: identifies unknowns, contradictions, and decision-blocking ambiguity.
- Preservation reviewer: verifies that the normalized contract has not added a solution, requirement, or scope not present in the source request/context.

Do not create a requirements analyst or solution designer inside this skill.

## Authority Boundary

This skill MAY:

- Preserve the raw request and relevant context references.
- Normalize wording without changing meaning.
- Separate explicit statements from inferences.
- Identify constraints, exclusions, unknowns, and conflicts.
- Identify the observable problem separately from a presumed cause.
- Mark whether an unknown is blocking or non-blocking for the next lifecycle step.
- Hand off the Intent Contract to `project-intake` or the existing-project change flow.

This skill MUST NOT:

- Define functional or non-functional requirements.
- Define acceptance criteria.
- Choose architecture, libraries, models, vendors, implementation methods, or solutions.
- Expand project scope or create new deliverables.
- Convert a likely cause into a confirmed diagnosis.
- Change an approved requirement, sealed plan, revision, SHA, or orchestration state.
- Decide which implementation harness must execute the work beyond identifying the appropriate next lifecycle owner.
- Treat an unresolved conflict as a safe assumption.

## Intent Contract

Use the following structure where applicable:

```yaml
intent_contract:
  raw_request: verbatim-or-lossless reference to the user's request
  normalized_intent: concise statement of the requested outcome
  observable_problem:
    - what is known to be happening
  explicit:
    - directly stated goals or instructions
  inferred:
    - statement: bounded interpretation
      basis: supporting context
      confidence: HIGH | MEDIUM | LOW
  constraints:
    - must-preserve condition
  exclusions:
    - explicitly out-of-scope or forbidden action
  unknowns:
    - item: unresolved fact
      blocking: true | false
  conflicts:
    - conflicting statements or constraints
  provenance:
    - source request/context identifiers when available
```

The `normalized_intent` must describe the desired outcome, not a chosen implementation.

## Workflow

1. Preserve the raw request and only the relevant authoritative context.
2. Write a concise normalized intent statement without adding a solution.
3. Separate observable symptoms/problems from presumed causes or user-suggested implementation ideas.
4. Extract `EXPLICIT` goals, constraints, exclusions, and non-goals.
5. Record bounded `INFERRED` interpretations with their basis and confidence.
6. Record `UNKNOWN` items and classify each as blocking or non-blocking.
7. Record `CONFLICT` items without resolving them by invention.
8. Run preservation review: compare the Intent Contract against the raw request and remove any invented requirement, acceptance criterion, solution, or scope expansion.
9. Hand off to `project-intake` for new projects or the appropriate approved change-intake flow for existing projects.

## Outputs

- Raw request reference
- Normalized intent statement
- Observable problem statement
- Explicit vs inferred map
- Constraints and exclusions
- Unknowns with blocking classification
- Conflicts
- Provenance references
- Handoff target: project intake or approved existing-project change intake

## Escalation

Escalate instead of guessing when:

- Two explicit instructions conflict.
- A blocking unknown changes scope, safety, architecture, cost, or external side effects.
- The request conflicts with a sealed or protected project contract.
- The user's stated desired outcome and stated exclusions cannot both be satisfied.

This skill identifies the need for clarification or amendment; it does not authorize one.

## Completion Contract

The skill is complete only when:

- The raw request is preserved or traceably referenced.
- Every material interpretation is clearly `EXPLICIT`, `INFERRED`, `UNKNOWN`, or `CONFLICT`.
- No requirement, acceptance criterion, architecture, implementation method, or new scope was invented.
- Explicit exclusions and modification-forbidden areas survived normalization.
- Blocking unknowns are visible to the next lifecycle owner.
- The output is usable by `project-intake` without needing to reverse-engineer the original request.

## Traceability Goal

Downstream artifacts should be able to maintain this lineage when the orchestration implementation supports it:

`User Statement -> Intent -> Intake -> Requirement -> Plan Item -> Implementation -> Test Evidence`

This skill owns only the first transition: `User Statement -> Intent`.

## Provisional Revalidation

Before promoting this skill to stable/V1.0, re-check it against the completed Full Plan Orchestration implementation for:

- The actual intake/change-request entry point
- Actual provenance and artifact identifiers
- How blocking unknowns and conflicts are represented in orchestration state
- Whether the orchestrator already performs any intent-preservation checks
- Exact traceability field names

Do not duplicate responsibilities that the final orchestrator implements centrally.
