# Orchestration Jarvis Bridge

## Purpose

This document defines the file-based bridge between the Global GPT Harness orchestrator runtime and a Jarvis Assistant control surface.

The bridge is read-first and command-last:

- Jarvis reads orchestration state, queue state, approval inbox, fan-in results, and stage-gate results.
- Jarvis sends commands through a bridge API or command files.
- The orchestrator remains the final authority for approval boundaries and phase transitions.

## Bridge Responsibilities

- Read current orchestration state from the local runtime files.
- Expose a project orchestration panel snapshot.
- Show active workers, pending approvals, and the current stage-gate decision.
- Track bridge commands and recent events.
- Preserve the Safety Warning Protocol.

## Exposed Snapshot Fields

- project root
- run id
- current phase
- next step
- active workers
- pending approvals
- task queue summary
- worker pool summary
- fan-out status
- fan-in status
- collection status
- stage gate result
- recent logs
- recent audit events

## Bridge Files

- `runtime/jarvis_bridge/dashboard_snapshot.json`
- `runtime/jarvis_bridge/dashboard_snapshot.md`
- `runtime/jarvis_bridge/commands/*.json`
- `runtime/jarvis_bridge/commands/*.result.json`
- `runtime/jarvis_bridge/approval_inbox.json`
- `runtime/jarvis_bridge/approval_inbox.md`
- `runtime/jarvis_bridge/task_queue.json`
- `runtime/jarvis_bridge/task_queue.md`
- `runtime/jarvis_bridge/audit.log`

## Command Scope

Supported bridge commands:

- `inspect`
- `plan`
- `run`
- `collect`
- `fanin`
- `gate`
- `status`
- `approve`

Commands are queued file-first and may be executed only when the runtime path allows it.
Approval rules still apply even when commands are requested from Jarvis.

## Dashboard Contract

The initial Jarvis orchestration panel is read-only.

It should display:

- active project
- current phase
- run id
- active workers
- pending approvals
- fan-out status
- fan-in status
- stage gate decision
- failed workers
- recent logs
- next action

## Validation Checklist

- Confirm the bridge snapshot can be generated from the runtime state.
- Confirm pending approvals are visible.
- Confirm stage-gate results are visible.
- Confirm command requests are written to disk.
- Confirm approval rules remain separate from stage-gate decisions.

## Readiness Reference

Use `docs/harness/orchestration-jarvis-bridge-readiness.md` as the readiness checklist when the bridge is being prepared for ongoing Jarvis consumption.
