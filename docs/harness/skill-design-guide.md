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

## Stateful Continuity Standard

Use this standard for designs that can replace or stop their own durable execution path, including runtime replacement, service restart, supervisor replacement, worktree/repository replacement, deployment activation, migration, server reboot, scheduler/reconciler replacement, and state-store relocation.

- `CI-CONT-01`: Until approved work successfully completes, at least one durable continuation owner or sealed recovery transaction exists.
- `CI-CONT-02`: A predecessor cannot be terminalized for migration until successor identity and recovery material are durably sealed.
- `CI-CONT-03`: Any non-COMPLETED terminal transition binds either a verified successor or a durable user-Attention obligation.
- `CI-CONT-04`: Zero active job/owner and equivalent preconditions require a self-reference/paradox audit against the currently executing owner.
- `CI-CONT-05`: Every self-replacement defines Before -> Quiesce -> Transition -> Successor Verify -> Predecessor Close -> Rollback.

The review must name the durable continuation owner, successor, interruption recovery, orphan detection, Attention obligation, and rollback path. A missing applicable answer is `NOT READY`; never weaken a safety guard with a generic active-job bypass to resolve self-reference.
