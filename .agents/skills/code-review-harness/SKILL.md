---
name: code-review-harness
description: Run a reusable code review agent team pattern with parallel architecture, security, performance, and maintainability audits.
---

# Code Review Harness

Use this skill when reviewing code changes, modules, pull requests, or implementation plans that need multi-angle technical review.

## Inputs

- Changed file list or review scope
- Business or technical intent
- Runtime and framework context
- Known risks
- Test results, if available

## Agent Team Pattern

- Review lead: defines scope and consolidates findings.
- Architecture reviewer: checks design boundaries and coupling.
- Security reviewer: checks vulnerabilities and sensitive data handling.
- Performance reviewer: checks bottlenecks and resource usage.
- Maintainability reviewer: checks readability, style, tests, and long-term ownership.

## Workflow

1. Confirm scope, intent, and risk level.
2. Split review into architecture, security, performance, and maintainability lanes.
3. Inspect code and tests for behavior changes.
4. Prioritize findings by severity and evidence.
5. Identify missing tests or verification gaps.
6. Consolidate findings without duplicating issues.
7. Report blockers, non-blocking risks, and recommended fixes.

## Outputs

- Findings ordered by severity
- File and line references where available
- Test and QA gaps
- Open questions
- Release readiness recommendation

## Validation

- Findings are actionable and evidence-backed.
- Security issues are not buried under style feedback.
- Review distinguishes blockers from improvements.
- No unrelated refactor requests are introduced.
