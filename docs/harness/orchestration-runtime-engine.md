# Orchestration Runtime Engine

## Purpose

This document describes the executable runtime that applies the orchestration standards in this repository.
The runtime is local, file-based, and CLI-invoked. It does not require a server, queue, or external API to run the minimum fan-out/fan-in loop.

## Runtime Surface

- `python -m runtime.orchestrator.cli inspect --project <project_path>`
- `python -m runtime.orchestrator.cli plan --project <project_path>`
- `python -m runtime.orchestrator.cli run --project <project_path>`
- `python -m runtime.orchestrator.cli approve --project <project_path> --approval "..."`
- `python -m runtime.orchestrator.cli gate --project <project_path>`
- `python -m runtime.orchestrator.cli status --project <project_path>`
- `python -m runtime.orchestrator.cli gate-dry-run --project-root <project_path> --gate-id <gate_id>`
- `python -m runtime.orchestrator.cli gate-validate --project-root <project_path> --gate-id <gate_id> --requirements-sha256 <sha256> --approval-evidence <path> --requirement-evidence <path> --branch <branch> --head <head> --harness-root <harness_path>`
- `python -m runtime.orchestrator.cli gate-run --project-root <project_path> --gate-id <gate_id> --run-id <run_id> --requirements-sha256 <sha256> --approval-evidence <path> --requirement-evidence <path> --branch <branch> --head <head> --harness-root <harness_path>`

## Runtime Responsibilities

- Read the execution contract from `docs/DEVELOPMENT_PLAN.txt`, `CHANGELOG.txt`, `logs/app.log`, and `docs/harness/orchestration-state.md`.
- Ask the `project_orchestrator_agent` for a persisted planning artifact before any worker execution starts.
- Ask the `project_execution_agent` to materialize execution tasks from that planning artifact before dispatch.
- Let the `project_execution_agent` split materialized tasks into general runnable slices and approval-gated pending slices.
- Build an explicit fan-out plan with thread ids, assigned agents, expected outputs, validation criteria, editable scope, and forbidden scope.
- Run worker tasks as isolated local subprocesses.
- Record worker outputs as files under the project runtime directory.
- Collect worker results into a fan-in report.
- Call the stage gate reviewer as a separate execution unit.
- Persist runtime state in machine-readable JSON and human-readable Markdown.
- Validate the sealed fixed-command registry, canonical Gate approval, requirements/plan SHA, Git baseline, LV scope, and isolated project namespace before a real Gate lifecycle starts.
- Execute package, preflight, sealed worker result, independent review, same-LV remediation when required, append-only checkpoint, Exit, handoff, and `SYSTEM_TRANSITION`; a missing worker result is a distinct hard stop and never a successful handoff.

## Safety Boundaries

- The runtime does not replace Safety Warning Protocol approval.
- `GO` and `CONDITIONAL GO` are phase-transition judgments only.
- Caution and dangerous work still require user approval.
- General work within the approved scope is executed automatically without repeated user confirmation.
- Obsidian app settings, sync settings, and vault-opening actions remain outside the runtime.

## Storage

- Machine-readable state: `runtime/orchestrator_state.json`
- Human-readable mirror: `docs/harness/orchestration-state.md`
- Fan-out plan: `runtime/fanout_plan.json`
- Fan-in report: `runtime/fanin_report.json`
- Stage gate record: `runtime/stage_gate.json`

## Related Documents

- `docs/harness/orchestration-execution-standard.md`
- `docs/harness/orchestration-approval-rules.md`
- `docs/harness/orchestration-runtime-work-items.md` — global Gate orchestration requirements SHA-256 `f734be6f2a81c89428f28605a1ffcd12234a511e69ded4c607041a2e0b367361`
- `docs/harness/orchestration-jarvis-bridge.md`
- `docs/harness/stage-gate-reviewer.md`
- `docs/harness/stage-gate-final-report-template.md`

## Validation Checklist

- Confirm the CLI commands run locally.
- Confirm fan-out creates at least two worker threads for the sample project.
- Confirm worker output files are written.
- Confirm fan-in and stage gate records are written.
- Confirm fan-in, collection, and stage-gate summary markdown uses the standard summary format.
- Confirm approval-gated work remains blocked until the right approval is provided.
- Confirm bridge snapshots can be generated from runtime state for Jarvis consumption.

## Last Updated
2026-08-28
