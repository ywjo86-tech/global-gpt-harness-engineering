# TASK-002 PCA-001 Rollback Package

Rollback anchor: GATE-001 GO commit `d8bde04`.
Controlled implementation scope: `runtime/orchestrator/provider_router.py`, `tests/test_provider_router.py`, and TASK-002 evidence files only.

If GATE-002 qualification fails due to PCA-001, preserve failure evidence first and restore only the TASK-002 controlled changes to the rollback anchor. Do not reset/clean unrelated dirty work, rewrite history, activate MPRF failover, add providers, or alter Full MCP action authority.

After rollback/remediation, rerun TEST-004~006 focused qualification plus the Router/HYBRID compatibility regression before GATE-002 is evaluated again.
