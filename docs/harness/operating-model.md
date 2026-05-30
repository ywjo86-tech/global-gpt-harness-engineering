# Operating Model

## Role

This repository is the Global Harness Engineering PMO for Codex-based projects. It defines standards, reusable skills, templates, and project harness patterns.

## Boundaries

- Keep repo-wide guidance concise in `AGENTS.md`.
- Put detailed standards in `docs/harness/`.
- Put reusable workflows in `.agents/skills/`.
- Put Codex custom agent definitions in `.codex/agents/` as TOML.
- Put reusable project starting points in `templates/`.
- Treat `_workspace/` as local handoff material and exclude it from default commits.
- Never create `.claude/` paths in this repository.

## PMO Responsibilities

- Clarify project purpose and success criteria.
- Standardize lifecycle phases and handoff artifacts.
- Design project-specific agent teams.
- Define reusable skills only when work repeats.
- Maintain QA, release, and security expectations.

## Project Repository Responsibilities

Project repositories own implementation code, project-specific docs, project-specific tests, and deployment configuration. This PMO repository should provide portable structure, not absorb project implementation.
