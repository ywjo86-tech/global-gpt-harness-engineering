# Template Usage Guide

Use `templates/project-harness-template/` when starting a new Codex-managed project repository.

## Files to Copy

Copy these files into the target project repository:

- `AGENTS.md`
- `README.md`
- `requirements.md`
- `design.md`
- `test-plan.md`
- `release-handoff.md`

Place them according to the target repository's conventions. For small repositories, root-level docs are acceptable. For larger repositories, place project docs under `docs/`.

## Required Replacements

After copying, update:

- Project name
- Business purpose
- Users or stakeholders
- Build, test, and verification commands
- Repository-specific paths
- Release and deployment notes
- Owner or handoff contact

## Suggested Project Flow

1. Start with `README.md` and `AGENTS.md`.
2. Fill `requirements.md` after intake.
3. Fill `design.md` after requirements are stable.
4. Fill `test-plan.md` before or during implementation.
5. Fill `release-handoff.md` before release or operational handoff.

## Local Handoff Files

Use `_workspace/` in the target project only for local handoff artifacts such as:

- `intake.md`
- `requirements-analysis.md`
- `implementation-plan.md`
- `qa-review.md`

Do not commit `_workspace/` by default.

## Safety Checks

- Keep `AGENTS.md` concise.
- Do not copy secrets, raw emails, customer data, or confidential procurement data.
- Do not create `.claude/` paths.
- Confirm the target project's `.gitignore` excludes `_workspace/`.
