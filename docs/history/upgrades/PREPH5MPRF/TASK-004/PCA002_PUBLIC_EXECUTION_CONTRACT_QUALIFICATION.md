# TASK-004 PCA-002 Public Execution Contract Qualification

Status: PASS_CANDIDATE_FOR_TASK-005
Date: 2026-09-17
Dependency: TASK-003 complete (`a59b6b4`)

## Public boundary delivered
`PublicExecutionRequest.v1`, `PublicExecutionResult.v1`, `PublicExecutionStatus.v1`, and `PublicReconciliationResult.v1` are versioned public DTOs. Request fields are limited to operation class, public arguments, authorization reference, operation/correlation IDs, policy digests, and expected effect semantics. Result/status/reconciliation projections expose only public status/result/effect/reconciliation/error/audit references.

A future MPRF consumer client exists only as a thin transport boundary and imports the public execution contract. It does not import Full MCP internals, Provider Router, operation registry, ToolEffectJournal, receipt stores, or internal gateway/runtime classes.

## Fail-closed rules
Unsupported schema versions, unsafe identifiers, malformed hashes, duplicate policy digests, invalid status/reconciliation values, response correlation mismatch, and forbidden internal keys/references are rejected.

## Validation
Direct DTO/client roundtrip self-test: PASS.
Forbidden `journal_path` projection test: PASS.
AST import-boundary scan: PASS — no `runtime.full_mcp` imports and no Provider Router import in the consumer client.
Python compile for DTO/client and adapter-contract test source: PASS.
Existing HOST-GATEWAY wire contract and MCP stdio adapter are not modified by TASK-004; integration/application is deferred to TASK-005.

## Authority statement
PCA-002 remains an internal EXEC-AUTH workstream. This contract grants no provider selection and no action authority. Full MCP remains canonical owner of authorization, action execution, effect truth, and reconciliation.
