# TASK-004 PCA-002 Rollback Package

Rollback anchor: TASK-003 commit `a59b6b4`.
Controlled TASK-004 scope: `runtime/orchestrator/public_execution_contract.py`, `runtime/mprf/execution_client.py`, the PCA-002 additions in `tests/full_mcp/test_adapter_contract.py`, and TASK-004 evidence files.

Rollback/remediation must not remove or rewrite unrelated working-tree changes, activate MPRF runtime ownership, import Full MCP internals into the consumer client, or bypass the public execution boundary. Re-run TEST-007/008 boundary checks before TASK-005 application.
