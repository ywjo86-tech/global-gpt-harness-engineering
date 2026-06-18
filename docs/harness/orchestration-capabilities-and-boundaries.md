# Orchestration Capabilities and Boundaries

## Purpose

This document explains what the Global GPT Harness orchestration layer can do, what it cannot do, and why it remains a local, file-based runtime instead of a hidden background daemon.

## What Orchestration Can Do

| Capability | What it means | Notes |
| --- | --- | --- |
| Read execution context | Inspect `docs/DEVELOPMENT_PLAN.txt`, `CHANGELOG.txt`, and `logs/app.log` before work starts | This keeps the project contract visible |
| Split work | Break a project into logical threads and bounded slices | Useful for independent analysis, documentation, or QA slices |
| Fan out and fan in | Assign thread owners, collect outputs, and synthesize results | Handoffs stay file-based and reviewable |
| Run local workers | Launch isolated worker subprocesses from the CLI runtime | The engine executes general tasks automatically once invoked and keeps approval-gated slices pending after executor-based classification |
| Gate transitions | Request a stage-gate review and wait for `GO` or `CONDITIONAL GO` | Stage gates decide phase readiness, not safety approval |
| Classify risk | Apply the highest-risk-item rule to mixed work slices | Mixed work is classified by the most restrictive item |
| Stabilize docs | Perform documentation-only cleanup within the approved scope | This is a controlled maintenance mode, not a runtime engine |
| Record evidence | Update orchestration state, changelog, and logs | This makes the run auditable |

## What Orchestration Cannot Do

- It cannot bypass Safety Warning Protocol approval.
- It cannot turn `GO` into a substitute for user safety approval.
- It cannot silently start the next phase without a gate decision.
- It cannot act as an always-on background agent runtime or daemon.
- It cannot configure Obsidian app settings or sync settings.
- It cannot open a vault in Obsidian on the user's behalf.
- It cannot introduce Notion, vector DB retrieval, or AI API automation as the primary memory system.
- It cannot modify runtime code unless the task explicitly requires it.
- It cannot create `.claude/` paths in this repository.

## Why It Stays Local and Controlled

- The harness is designed to be repo-local and portable.
- File-based handoffs are easier to inspect, revise, and audit than hidden runtime state.
- The runtime executes automatically when invoked, but human approval remains separate from phase advancement so risk classification stays explicit.
- General work inside the approved scope proceeds automatically once the runtime is invoked.
- Minimal runtime assumptions make the workflow easier to maintain as models and tools change.

## Operating Model

- The orchestrator runtime coordinates explicit threads through local worker subprocesses.
- The stage-gate reviewer is a separate execution unit launched by the runtime.
- Workers are used only when the work can be split into bounded, independently reviewable slices.
- Execution is explicit and local, not hidden inside a background daemon or remote service.

## Related Documents

- `AGENTS.md`
- `docs/harness/orchestration-execution-standard.md`
- `docs/harness/orchestration-approval-rules.md`
- `docs/harness/stage-gate-reviewer.md`
- `docs/harness/stage-gate-final-report-template.md`

## Validation Checklist

- Confirm the document distinguishes capabilities from boundaries.
- Confirm safety approval remains separate from stage-gate approval.
- Confirm Obsidian configuration and vault-opening actions are explicitly out of scope.
- Confirm the description matches the repository's file-based orchestration model.

## Last Updated
2026-06-18
