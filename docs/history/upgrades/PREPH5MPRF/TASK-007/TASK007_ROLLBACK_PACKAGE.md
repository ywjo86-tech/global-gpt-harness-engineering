# TASK-007 Rollback Package

Rollback/source baseline remains the sealed `MCP_STABLE_BASELINE` commit `0848dab7596f59a7eae98f223b47636bad27b4bd`, with Full MCP final approval lineage ending at `0bdfad12c438f4f101d3fdeafda9daac8d5069b4`.

TASK-007 performs regression/evidence changes only. If qualification evidence is invalid, preserve the failed evidence, revert only TASK-007 test/evidence adjustments, restore the approved PREFINAL test fixture from the sealed UPGRADE-003 worktree, and re-run TEST-015/016. No destructive reset/history rewrite is authorized.
