# TASK-007 Full MCP Regression / Baseline Reconfirmation

Status: PASS
Date: 2026-09-17

## Regression environment
Python: approved Full MCP UPGRADE-003 virtual environment with `mcp==2.2.0` available.
Approved PREFINAL evidence fixture was materialized read-only from the approved Full MCP worktree into ignored `_workspace/full-mcp/...` for qualification tests. PREFINAL SHA-256 matched source exactly: `323e879f8905272ca4d1e9fda6280440a3ab77980a11064c83558db0feffd196`.

## Regression results
- Full MCP corpus (`tests/full_mcp/test_*.py`): 78 PASS / 0 FAIL / 0 ERROR.
- Pre-PHASE-5 runtime/provider compatibility corpus: 42 PASS / 0 FAIL / 0 ERROR.
- CT-041 public request -> AdapterToolCall bridge: PASS.
- CT-042 representative lifecycle and current worktree lineage: PASS.

## Controlled-diff verification
Full MCP final approval ref: `0bdfad12c438f4f101d3fdeafda9daac8d5069b4`.
MCP stable baseline ref: `0848dab7596f59a7eae98f223b47636bad27b4bd`.
Changed tracked paths from Full MCP final approval to current candidate: 45.
Unexpected paths outside approved PREPH5MPRF Change Targets / evidence paths: 0.
Controlled diff: PASS.

## Execution Backend Contract reconfirmation
UPGRADE-002 sealed history differs by 0 files from the Full MCP final approval lineage.
Historical GCH-EXEC-BACKEND GATE-005 decision remains `GO`, TEST-017 PASS, TEST-018 PASS, auto NVIDIA->Codex fallback false, gate bypass false, final state `UPGRADE-002_FINAL_GATE_CLOSED_GO`.
Execution Backend Contract: RECONFIRMED.

## MCP stable baseline reconfirmation
Historical manifest binds `MCP_STABLE_BASELINE` to `0848dab7596f59a7eae98f223b47636bad27b4bd`, status `APPROVED_SEALED`, technical eligibility `ELIGIBLE`, and Full MCP final project approval reports 0 new functional regressions.
Both the stable baseline ref and Full MCP final approval ref are ancestors of the controlled candidate.
MCP_STABLE_BASELINE: RECONFIRMED as rollback/source baseline; the current candidate is not declared a new stable baseline by this task.

## TEST disposition
TEST-015 Full MCP regression corpus: PASS.
TEST-016 MCP / Execution Backend baseline reconfirmation: PASS.
