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

## Stateful Continuity Review

Apply this review only to stateful, self-replacing designs: runtime replacement, service restart, supervisor replacement, worktree or repository replacement, deployment activation, migration, server reboot, scheduler or reconciler replacement, state-store relocation, or deliberate durable-owner termination.

Before the design can be READY, answer explicitly: who is the durable continuation owner before the transition; whether that owner terminates or changes source/runtime; which successor identity is sealed first; whether ownership can fall to zero; whether a zero active job/owner precondition includes the executing owner itself; how that self-reference is resolved; what survives interruption; who detects successor failure; what Attention obligation exists while the goal is incomplete; and how rollback restores durable ownership.

Use the `CI-CONT-01..05` invariants in `docs/harness/skill-design-guide.md`. The required sequence is Before -> Quiesce -> Transition -> Successor Verify -> Predecessor Close -> Rollback. If any applicable answer or invariant is missing, output `NOT READY`; do not infer continuity from an intended next step. Stateless designs do not trigger this review merely because they mention files or processes.

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
