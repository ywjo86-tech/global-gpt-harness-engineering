# Agent Team Design Guide

## Principle

Use the smallest team that preserves clarity, quality, and accountability.

## Default Roles

- PMO orchestrator: coordinates lifecycle and handoffs.
- Requirements analyst: clarifies goals, constraints, risks, and acceptance criteria.
- Stage gate reviewer: verifies phase completion, evidence, and transition readiness.
- QA release reviewer: checks structure, security, verification, and release readiness.

## When to Add Roles

Add a role only when the work is repeated, specialized, or large enough to create context pressure. Prefer documenting a role before turning it into a custom agent.

Use a stage gate reviewer when a workflow needs an explicit go/no-go decision between phases or milestones. Keep the role separate from QA release review when the decision is about phase advancement rather than release readiness.

## Agent Definition Format

Codex custom agents live under `.codex/agents/` and use `.toml` files.

## Avoid

- Deep routing trees.
- Agents that differ only by wording style.
- Agents for one-off tasks.
- `.claude/` paths.
