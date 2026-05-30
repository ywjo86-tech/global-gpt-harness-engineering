---
name: harness-design
description: Design a project-specific Codex harness with agent roles, reusable skills, docs, templates, and deterministic handoff artifacts.
---

# Harness Design

Use this skill when creating or updating a Codex project harness.

## Required Inputs

- Project intake summary
- Requirements analysis
- Expected deliverables
- Repository constraints
- Quality and release expectations

## Workflow

1. Choose the smallest useful collaboration pattern.
2. Define agent roles only when they add durable value.
3. Define reusable skills only for repeated work.
4. Place detailed standards under docs, not AGENTS.md.
5. Define handoff artifacts under `_workspace/`, but keep them out of default commits.
6. Record what should be created now and what should remain a future candidate.

## Expected Output

- Harness architecture summary
- Agent role list
- Skill list
- Documentation list
- Template list
- Handoff artifact plan
- Exclusions and risks

## Validation

- The harness can run with a small number of roles.
- Role and skill boundaries do not overlap heavily.
- No `.claude/` paths are introduced.
- Sensitive intermediate artifacts are excluded from default GitHub commits.
