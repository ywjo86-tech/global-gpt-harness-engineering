# GitHub Workflow

## Commit Scope

Keep commits focused on one logical PMO, harness, skill, template, or documentation change.

## Commit Candidates

- `AGENTS.md`
- `.gitignore`
- `.codex/agents/*.toml`
- `.agents/skills/**/SKILL.md`
- `docs/harness/**/*.md`
- `templates/**/*.md`

## Default Exclusions

- `_workspace/`
- Secrets and environment files
- Raw customer data
- Raw email content
- Confidential procurement data
- Logs and local cache

## Pull Requests

PRs should state purpose, changed areas, verification performed, and remaining risks.

## Release Reviews

Before release, run a QA review for path conventions, security, docs, templates, and expected project lifecycle coverage.
