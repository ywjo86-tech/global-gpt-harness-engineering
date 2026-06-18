# Global Operating Principles

## Purpose

These are the default operating principles for Global GPT Harness Engineering. They apply to all Codex work in this repository unless a more specific document narrows the scope.

## Karpathy-Style AI Coding Principles

### Think Before Coding

- Summarize the request before making changes.
- Identify the target files before editing.
- State assumptions and open questions when the scope is not fully certain.
- Do not rush into broad or risky changes without a clear boundary.

### Simplicity First

- Prefer the simplest solution that meets the requirement.
- Avoid unnecessary abstractions, frameworks, APIs, databases, or automation.
- Keep document work Markdown-first and local-first.

### Surgical Changes

- Modify only files that are directly relevant to the request.
- Do not perform unrelated refactors, formatting sweeps, file moves, or renames.
- Preserve the existing repository structure unless a structural change is explicitly required.
- Do not modify runtime code unless the task explicitly calls for it.

### Goal-Driven Execution

- Confirm the completion criteria before starting.
- Report changed files after the work is done.
- Report validation commands or validation method.
- Report any out-of-scope changes, remaining risks, and the next step.

## Reporting Standard

After a task, Codex should report:

- changed files
- validation results
- scope exceptions, if any
- next step
- remaining risks

## Scope Notes

- This document is a global operating baseline, not a domain-specific memory standard.
- Memory-specific rules live in `docs/harness/memory/`.
- Stage boundary decisions belong to the stage-gate reviewer; release and handoff readiness decisions belong to the QA release reviewer.
- Work-risk classification follows the highest-risk-item rule, and stage-gate `GO` or `CONDITIONAL GO` does not replace Safety Warning Protocol approval.
- Runtime code, Jarvis main-brain integration, Notion primary backend changes, vector DB work, and knot tool development stay out of scope unless a later task explicitly authorizes them.
