---
name: qa-release-review
description: Review Codex harness changes for structure, security, documentation coverage, GitHub readiness, and release handoff quality.
---

# QA Release Review

Use this skill before committing or releasing PMO, harness, skill, template, or agent changes.

## Required Inputs

- Changed file list
- Intended purpose
- Relevant docs or templates
- Verification commands or manual checks

## Workflow

1. Check that files live in the expected repository paths.
2. Confirm `.codex/agents/` definitions use TOML.
3. Confirm `.agents/skills/` contains only approved reusable skills.
4. Confirm `_workspace/` is excluded from default commits.
5. Check for secrets, sensitive business data, raw emails, and private procurement data.
6. Verify docs and templates point to the same lifecycle.
7. Summarize findings, verification, and release readiness.

## Expected Output

- Findings
- Changed-file purpose summary
- Verification summary
- Release readiness decision
- Follow-up items

## Validation

- Security issues are listed before style issues.
- Any blocked release decision includes a concrete reason.
- Follow-up items are scoped and actionable.
