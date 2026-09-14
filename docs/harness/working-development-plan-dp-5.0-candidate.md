# DP-5.0-CANDIDATE — Broker-native Codex Dynamic Tool Transport

Status: Working Candidate
Decision: DEC-006 Option A
Requirement baseline: 1.0 unchanged
Supersedes: DP-4.0-CANDIDATE
Does not modify: FINAL DP-2.0

## TASK-4A-08A — Transport Sealing + Codex Thin Adapter

- Pin the project transport contract to installed Codex 0.150.1.
- Terminate App Server JSON-RPC inside the adapter.
- Expose only provider-neutral session, turn, ToolRequest, and ToolResult contracts.
- Start production threads and turns with no native environment.
- Register only closed client-side dynamic Tools.
- Block before a governed turn on version, capability, or schema mismatch.

## TASK-4A-08B — Provider-neutral Gateway + Single Tool Broker

- Route every production dynamic Tool request through one Gateway and broker.
- Resolve an exact registered operation identity before authorization and effect.
- Require an ACTIVE task, operation, scope, package, and decision-bound contract.
- Keep unknown and unbound operations fail-closed.
- Provide no native command, file mutation, MCP, legacy CLI, or silent fallback.

## TASK-4A-08C — Security + Effect Journal + Resume

- Keep authorization independent from result security.
- Scan private Tool request/result material with the unchanged detector.
- Persist only bounded registry, authorization, security, intent, and receipt evidence.
- Apply FINAL SEM-007 through SEM-010 to Tool effects.
- Block duplicate execution and ambiguous recovery; never blind retry.

## Integrated acceptance

Acceptance is part of TASK-4A-08 and is not a separate micro-task. It requires compatibility,
closed-registry, authorization, security, actual App Server protocol, recovery, concurrency,
and existing ISSUE-025/060/065 regression coverage. Actual proof93 remains a later gate.
