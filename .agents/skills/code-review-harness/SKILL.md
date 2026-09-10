---
name: code-review-harness
description: Run a reusable, evidence-backed code review agent-team pattern that reviews implementation quality without modifying code or making release-gate decisions.
status: PROVISIONAL
---

# Code Review Harness

Use this skill after implementation work has produced reviewable code and before release-readiness review. This skill evaluates the code itself from multiple technical angles and produces evidence-backed findings for a separate worker to fix and a separate gate to judge.

Do not use this skill as a substitute for `qa-release-review`. Code review asks whether the implementation is technically sound. Release review asks whether the overall change is ready to advance or release.

## Purpose

Identify correctness, architecture, security, performance, maintainability, testability, and contract risks in code without expanding scope, directly fixing findings, or issuing `GO`, `CONDITIONAL GO`, or `NO-GO` decisions.

## Trigger

Use when one or more of the following are true:

- A bounded implementation slice is complete and ready for technical review.
- A pull request or changed-file set needs multi-angle review.
- A defect fix needs independent re-review.
- The supervisor requests an implementation-quality review before QA or release review.

Do not trigger for:

- General project intake or requirements clarification.
- Writing or changing implementation code.
- Release-readiness or deployment approval.
- Unbounded refactoring or architecture redesign requests that are outside the approved plan.

## Required Inputs

- Review scope or changed-file list
- Intended behavior or approved requirement/plan references
- Relevant runtime, framework, API, and data-contract context
- Known risks and modification-forbidden areas
- Test results or verification evidence, if available
- Plan revision/SHA or equivalent provenance identifier when the orchestration runtime provides one

## Agent Team Pattern

Create only the review lanes required by the change.

- Review lead: freezes scope, removes duplicate findings, checks evidence quality, and prepares the handoff.
- Correctness reviewer: checks behavior, state transitions, error handling, edge cases, and contract adherence.
- Architecture reviewer: checks boundaries, coupling, dependency direction, and unintended structural drift.
- Security reviewer: checks secrets, permissions, validation, trust boundaries, sensitive-data handling, and abuse paths.
- Performance reviewer: checks avoidable bottlenecks, blocking work, resource usage, and scaling risks when relevant.
- Maintainability/testability reviewer: checks readability, ownership clarity, test seams, regression risk, and unnecessary complexity.

The reviewer role and fixer role must remain separate. A reviewer may propose a remediation but must not edit implementation files as part of the same review authority.

## Authority Boundary

This skill MAY:

- Inspect code, tests, diffs, plans, and relevant runtime evidence.
- Classify and prioritize technical findings.
- Mark a finding as a potential blocking candidate.
- Request missing evidence or bounded re-review through the supervisor.
- Recommend a fix direction without implementing it.

This skill MUST NOT:

- Modify implementation code, tests, plans, requirements, or architecture.
- Introduce unrelated refactors, enhancements, or new scope.
- Change a sealed plan, plan SHA, revision, gate state, or orchestration state.
- Treat a reviewer suggestion as an approved requirement.
- Issue `GO`, `CONDITIONAL GO`, `NO-GO`, release approval, or deployment approval.
- Self-certify a finding as resolved after editing the same code.

If a finding implies the approved plan itself may be wrong, report `PLAN_CONFLICT_CANDIDATE` to the supervisor. Do not change the plan.

## Finding Contract

Every material finding should use this structure where information is available:

```yaml
finding:
  id: CR-001
  severity: CRITICAL | MAJOR | MINOR | INFO
  status: CONFIRMED | SUSPECTED | REJECTED
  category: correctness | architecture | security | performance | maintainability | testability | contract
  file: path/to/file
  line_or_range: optional
  evidence: concise observable evidence
  impact: concrete consequence
  reproduction_or_reasoning: how the issue was verified
  recommendation: bounded remediation direction
  blocking_candidate: true | false
  confidence: HIGH | MEDIUM | LOW
```

`blocking_candidate: true` is an input to a later gate. It is not a release decision.

## Workflow

1. Freeze the review scope, intended behavior, protected areas, and available provenance.
2. Select only the technical review lanes relevant to the change.
3. Inspect implementation and tests against the intended behavior and public/internal contracts.
4. Record candidate findings with concrete evidence.
5. Perform an evidence check and classify each candidate as `CONFIRMED`, `SUSPECTED`, or `REJECTED`.
6. Remove duplicates and separate defects from optional improvements.
7. Identify missing tests, missing runtime evidence, or plan/implementation mismatches.
8. Produce the Code Review Report without changing code or gate state.
9. After a separate worker fixes confirmed findings, perform a bounded re-review of the affected scope when requested.

## Outputs

- Review scope and provenance summary
- Findings ordered by severity
- Confirmed vs suspected finding status
- File/line references where available
- Test and verification gaps
- `PLAN_CONFLICT_CANDIDATE` items, if any
- Blocking candidates for downstream QA/gate consideration
- Open questions and required re-review scope

## Escalation

Escalate to the supervisor when:

- The review requires changes outside the assigned scope.
- The approved plan conflicts with safe or correct implementation.
- Required source, test, runtime, or contract evidence is missing.
- Multiple reviewers reach materially incompatible conclusions.
- A security issue requires privileged or sensitive validation.

## Completion Contract

The skill is complete only when:

- The review scope has not expanded beyond the assigned boundary.
- Material findings are evidence-backed and de-duplicated.
- Defects are separated from optional improvements.
- Suspected findings are not presented as confirmed defects.
- No implementation file, plan, requirement, or gate state was modified by the review authority.
- Downstream QA can consume the report without interpreting reviewer prose as a release decision.

## Provisional Revalidation

Before promoting this skill to stable/V1.0, re-check it against the completed Full Plan Orchestration implementation for:

- Actual plan revision/SHA field names
- Actual artifact and handoff schema
- Worker/reviewer separation enforcement
- Retry and re-review state transitions
- Gate ownership and blocking semantics

Do not hard-code orchestration implementation details here until that revalidation is complete.
