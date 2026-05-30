# Code Review Harness Pattern

## Purpose

Use this pattern to review code through parallel architecture, security, performance, and maintainability audits.

## When to Use

- A pull request or implementation has meaningful risk.
- A module touches shared behavior or data boundaries.
- Security, performance, or maintainability concerns are likely.
- A release decision needs technical review evidence.

## Agent Team Composition

- Review lead: defines scope, consolidates findings, and removes duplicates.
- Architecture reviewer: checks module boundaries, coupling, and design fit.
- Security reviewer: checks auth, secrets, injection, data exposure, and unsafe defaults.
- Performance reviewer: checks bottlenecks, scaling limits, and resource usage.
- Maintainability reviewer: checks readability, tests, style, and operational ownership.

## Workflow

1. Confirm change intent, affected files, and risk level.
2. Split review into parallel lanes.
3. Inspect code, tests, configuration, and documentation.
4. Record findings with evidence and severity.
5. Identify missing tests and verification gaps.
6. Merge duplicate findings and resolve conflicts.
7. Report blockers, non-blocking risks, and suggested fixes.

## Inputs

- Review scope
- Changed file list or diff
- Runtime and framework context
- Business intent
- Test results
- Known risk areas

## Outputs

- Findings ordered by severity
- File and line references
- Missing test list
- Security and performance notes
- Release readiness recommendation

## Validation Criteria

- Findings are actionable and tied to evidence.
- High-severity issues are listed first.
- Review does not mix style preferences with defects.
- Suggested fixes stay within the request scope.

## Cautions

- Do not request broad refactors unless needed for correctness or risk.
- Do not expose secrets found during review.
- Distinguish confirmed bugs from questions.
