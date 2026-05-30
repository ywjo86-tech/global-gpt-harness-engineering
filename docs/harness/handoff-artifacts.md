# Handoff Artifacts

## Purpose

Handoff artifacts preserve reasoning, decisions, QA evidence, and project state between Codex sessions and human review.

## Default Location

Use `_workspace/` for temporary handoff artifacts.

## Commit Policy

`_workspace/` is excluded from default GitHub commits because it can contain sensitive business context, procurement data, raw emails, or unfinished analysis.

Commit a handoff artifact only after explicitly confirming that it contains no secrets, private customer data, raw email content, or confidential commercial information.

## Naming Convention

Use descriptive markdown names such as:

- `intake.md`
- `requirements-analysis.md`
- `implementation-plan.md`
- `qa-review.md`
- `release-handoff.md`

## Review Rules

- Keep handoffs concise.
- Label assumptions and open questions.
- Remove sensitive source data before sharing or committing.
