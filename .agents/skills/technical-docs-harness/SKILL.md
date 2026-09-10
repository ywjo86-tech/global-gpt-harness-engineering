---
name: technical-docs-harness
description: Author traceable technical documentation from approved plans, implementation, interfaces, and verification evidence without normalizing plan/implementation drift or making release decisions.
status: PROVISIONAL
---

# Technical Docs Harness

Use this skill when a project needs developer-facing or operator-facing technical documentation for APIs, services, libraries, tools, workflows, architecture, configuration, installation, or troubleshooting.

This skill is an authoring and traceability function. It is not the release gate. `qa-release-review` remains responsible for deciding whether documentation coverage and overall release evidence are sufficient.

## Purpose

Produce documentation that is useful, source-grounded, version-aware, and explicit about differences between intended behavior and observed implementation behavior.

## Trigger

Use when one or more of the following are true:

- A bounded implementation slice has stabilized enough to document.
- Public or internal interfaces need reference documentation.
- Installation, operation, configuration, troubleshooting, or handoff instructions are required by the approved plan.
- Existing documentation must be synchronized with approved changes.
- A release candidate needs an updated documentation bundle before QA/release review.

Do not trigger to invent new product behavior, redesign architecture, change implementation, or approve release readiness.

## Required Inputs

- Approved plan, requirements, or authoritative behavior contract
- Current implementation source or public interface specification
- Relevant test/verification evidence
- Target audience
- Documentation scope or `doc_profile`
- Existing documentation, when updating
- Source commit/revision and plan revision/SHA when available
- Known limitations and modification-forbidden areas

## Documentation Profile

Generate only the documentation types required by the project. Do not expand documentation scope by default.

Example:

```yaml
doc_profile:
  architecture: true
  api_reference: true
  installation: false
  configuration: true
  operations: true
  troubleshooting: true
  user_guide: false
  change_summary: true
```

## Agent Team Pattern

Create only the roles needed for the selected documentation profile.

- Docs lead: freezes audience, scope, structure, provenance, and output bundle.
- Source/interface analyst: extracts behavior from approved plans, code, API specs, commands, configs, and tests.
- Explanation writer: writes conceptual, procedural, and operational guidance.
- Example builder: creates bounded examples that match verified interfaces.
- Traceability reviewer: checks that material claims can be traced to plan, code/spec, or test evidence and identifies drift.

The traceability reviewer may identify gaps but does not issue a release decision.

## Authority Boundary

This skill MAY:

- Read approved plans, requirements, source, specs, tests, and existing docs.
- Create or revise documentation within the assigned documentation scope.
- Describe intended behavior and separately describe verified observed behavior.
- Identify missing documentation evidence or plan/implementation/documentation drift.
- Produce examples that use verified interfaces.
- Mark unresolved mismatches for supervisor/QA review.

This skill MUST NOT:

- Change implementation code, tests, architecture, requirements, or sealed plans to make documentation easier to write.
- Treat undocumented implementation behavior as automatically approved behavior.
- Rewrite the approved plan to match unapproved code drift.
- Hide or silently reconcile plan/implementation mismatches.
- Expand the documentation bundle beyond the requested/approved profile without escalation.
- Issue `GO`, `CONDITIONAL GO`, `NO-GO`, release approval, or deployment approval.
- Claim documentation is release-complete on behalf of `qa-release-review`.

## Provenance Contract

Every durable documentation bundle should record the strongest available provenance identifiers:

```yaml
document_metadata:
  plan_revision: optional
  plan_sha: optional
  source_commit: optional
  interface_version: optional
  generated_at: timestamp-or-run-id when available
  verified_against:
    - plan/spec/code/test identifiers
```

Use the actual orchestration field names once Full Plan Orchestration is finalized. Until then, keep this metadata conceptually compatible rather than hard-coding runtime-specific fields.

## Intended vs Observed Behavior

When approved behavior and implementation behavior differ, do not collapse them into a single statement.

Use this distinction:

- `INTENDED_BEHAVIOR`: what the approved plan/requirement/spec says should happen.
- `OBSERVED_BEHAVIOR`: what current implementation or verified runtime evidence actually does.
- `PLAN_IMPLEMENTATION_DRIFT`: a material mismatch between the two.
- `DOCUMENTATION_GAP`: required behavior or operation lacks sufficient source/evidence to document accurately.

A drift record should include:

```yaml
drift:
  id: DOC-DRIFT-001
  intended_source: plan/requirement/spec reference
  observed_source: code/test/runtime reference
  intended_behavior: concise statement
  observed_behavior: concise statement
  impact: documentation/operation/release consequence
  status: UNRESOLVED
```

Do not resolve the drift by choosing one side unless an authoritative artifact has already resolved it.

## Workflow

1. Freeze the target audience, documentation profile, protected areas, and provenance inputs.
2. Read the authoritative approved plan/requirements/spec first to establish intended behavior.
3. Inspect current implementation, interfaces, configuration, and verification evidence to establish observed behavior.
4. Identify `PLAN_IMPLEMENTATION_DRIFT` and `DOCUMENTATION_GAP` items before drafting final claims.
5. Draft only the documentation types enabled by the approved `doc_profile`.
6. Build examples from verified interfaces and include relevant error/edge cases when required.
7. Trace material claims to approved or observed sources.
8. Keep intended and observed behavior explicitly separated when they differ.
9. Produce the Documentation Bundle plus a documentation verification summary and unresolved-gap list.
10. Hand unresolved drift/gaps to the supervisor and `qa-release-review`; do not self-approve completeness.

## Documentation Bundle Outputs

Depending on `doc_profile`, outputs may include:

- Architecture overview
- API/interface reference
- Installation guide
- Configuration guide
- Operations/runbook notes
- Troubleshooting guide
- Usage examples
- Known limitations
- Change summary
- Documentation provenance metadata
- Drift/gap register
- Documentation verification summary

Only create the subset required by the assigned profile.

## Validation

Before handoff, confirm:

- Examples match verified interfaces.
- Required parameters, outputs, errors, and prerequisites are represented when in scope.
- Material claims are traceable to approved sources or clearly labeled observed behavior.
- Unapproved implementation drift has not been normalized into authoritative documentation.
- Intended and observed behavior are separated where necessary.
- No new product requirement, architecture decision, or implementation behavior was invented.
- The skill has not issued a release-readiness decision.

## Escalation

Escalate to the supervisor/QA when:

- Approved plan/spec and implementation materially disagree.
- Source evidence is insufficient to document required behavior accurately.
- A required example cannot be validated against the current interface.
- Documentation requires information from outside the approved scope.
- A documentation request would reveal secrets, credentials, or sensitive operational data.

## Completion Contract

The skill is complete only when:

- The requested documentation profile has been authored or each missing item is explicitly reported.
- Durable outputs carry available provenance.
- Drift and documentation gaps are visible rather than silently reconciled.
- Examples and procedural claims are grounded in actual interfaces/evidence.
- QA can independently evaluate documentation sufficiency from the bundle and gap register.

## Provisional Revalidation

Before promoting this skill to stable/V1.0, re-check it against the completed Full Plan Orchestration implementation for:

- Actual plan revision/SHA and run identifiers
- Artifact-manifest and provenance schema
- Documentation stage placement in the lifecycle
- Whether drift detection is centralized by the orchestrator
- Exact QA handoff and gate-state semantics

Do not duplicate central orchestration capabilities after that revalidation.
