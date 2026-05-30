# Skill Design Guide

## Principle

Skills capture reusable work methods. Agents capture roles. Do not create a skill for a task that is unlikely to repeat.

## Required Structure

Every `SKILL.md` starts with YAML frontmatter containing at least:

```yaml
---
name: skill-name
description: Short description of when to use the skill.
---
```

## Recommended Sections

- When to use
- Required inputs
- Workflow
- Expected output
- Validation

## First-Wave PMO Skills

- `project-intake`
- `requirements-analysis`
- `harness-design`
- `qa-release-review`

## Domain Skills

Domain-specific skills should stay as candidates until repeated use proves they are worth creating.
