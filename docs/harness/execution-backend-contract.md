# GCH Execution Backend Contract

Project: `GCH-EXEC-BACKEND`
Upgrade: `UPGRADE-002`
Document role: TASK-012 technical contract and Known Issue closure record
Runtime Authority: `docs/DEVELOPMENT_PLAN.txt`

This document records the implemented execution-backend compatibility boundary. It does not replace or modify the Runtime Authority, Stage Gate authority, Provider Router authority, Worker/Fan-in governance, or approved Full Plan semantics.

## Architecture boundary

The compatibility remediation is bounded to the Codex Launcher/Adapter edge plus provider-neutral call context.

- Codex CLI syntax is isolated to `runtime/orchestrator/codex_launcher.py` and `runtime/orchestrator/codex_adapter.py`.
- Engine, Provider Executor, and Stage Gate pass project root and required capabilities only; they do not construct Codex CLI command strings.
- Provider Router remains the authority for HYBRID provider eligibility.
- State-changing capabilities include `filesystem_write`, `shell`, `test`, `git`, `implementation`, and `integration`; they are never NVIDIA-eligible.
- Safe read-only reasoning/evidence-analysis work may route to NVIDIA under HYBRID.
- NVIDIA to Codex automatic fallback is prohibited and remains absent.
- Codex to manual fallback is preserved.

## Current Codex launcher contract

The supported non-interactive runtime is detected from the installed CLI rather than pinned to a compiled version.

- Required command family: `codex exec`.
- Prompt transport: stdin; prompt text must not appear in argv.
- Project root: explicit `-C <project-root>`.
- Sandbox: capability-derived `read-only` or `workspace-write`.
- Structured output: `--output-schema <schema>` plus `-o <final-output>`.
- Automatic retry inside the launcher: `0`.
- Default timeout: 600 seconds.
- Process cancellation/timeout uses bounded terminate then kill behavior.
- Generated root structured-output schema is closed with `additionalProperties: false`, matching the actual Codex response-format requirement observed during TASK-007.
- Dangerous bypass flags are rejected.
- Legacy or unsupported `CODEX_CLI_COMMAND` forms fail closed; the launcher does not silently rewrite them.

## Fail-closed and fallback rules

Compatibility detection, invocation resolution, process execution, and structured-output validation use deterministic failure taxonomy.

Representative classes include `CLI_NOT_FOUND`, `VERSION_PROBE_FAILED`, `HELP_PROBE_FAILED`, `MISSING_REQUIRED_CAPABILITY`, `OVERRIDE_INVALID`, `OVERRIDE_LEGACY_UNSUPPORTED`, `NONZERO_EXIT`, `TIMEOUT`, `CANCELLED`, and `STRUCTURED_OUTPUT_INVALID`.

A Codex backend failure does not authorize provider-policy bypass. The Adapter produces `manual_fallback` and a manual execution artifact while preserving launcher diagnostics. Actual process evidence such as return code, stdout/stderr, timeout/cancel state, and taxonomy is retained in `codex_launcher.log` when available.

## Graphify PHASE 2 Known Issue lineage

Known Issue ID: `GRAPHIFY_PHASE2_LAUNCHER_MISMATCH`

Observed phase: Graphify PHASE 2.

Observed defect: the historical generated Codex launcher used the legacy form `codex run --prompt-file <prompt> --output-dir <dir>`, while the installed Codex CLI supported the `codex exec` command family. The historical live attempt therefore failed at the CLI boundary before normal Worker execution.

Temporary recovery: manual recovery was used to complete the bounded PHASE 2 work.

Historical status preservation: Graphify PHASE 2 remains `GRAPHIFY_DECISION_CLOSED` with decision `GO`; the defect does not retroactively change that completion status.

No-core-modification history: the PHASE 2 recovery did not modify protected Full Plan Core to force compatibility.

Required PHASE 3 action: establish a capability-detected Codex Launcher Contract, structured result path, deterministic fallback taxonomy, actual read-only/state-changing smoke, Provider Separation smoke, and result-flow convergence without changing Core authority.

Closure status: runtime compatibility defect CLOSED by UPGRADE-002 evidence through GATE-003; regression/Core-preservation review remains governed separately by GATE-004.
## Closure evidence references

- Execution-start preflight: `_workspace/execution-backend-contract/gch-exec-backend-task015-20260915T003023/preflight.json`
- Focused compatibility / GATE-002: `_workspace/execution-backend-contract/gch-exec-backend-implement-20260915/gate002_evidence.json`
- Actual runtime smoke / GATE-003: `_workspace/execution-backend-contract/gch-exec-backend-smoke-20260915/gate003_final_evidence.json`
- TASK-011 regression/Core preservation evidence: `_workspace/execution-backend-contract/gch-exec-backend-gate004-20260915/task011_regression_evidence.json`
- Historical Graphify completion record: `docs/harness/graphify/phase2-20260914/GIT_FINAL_RECORD.json`

## Regression interpretation

The historical Graphify final record states `58 PASS`, while its independent regression record captured a broader core run of 235 tests / 1 skipped and the final summary record states 147 PASS / 1 skipped. UPGRADE-002 does not rewrite those historical artifacts.

For TASK-011, the current Graphify inventory still contains 58 checks. Two historical assertions intentionally expected the pre-PHASE3 protected baseline to remain byte-identical. Because UPGRADE-002 contains approved, semantics-preserving changes to `stage_gate.py` and `provider_router.py`, those assertions now correctly detect `CONTROLLED_CHANGE_REQUIRED`. Coverage-equivalent replacement checks verify that the only guard mismatches are those two approved paths and that a Graphify PoC-only request itself introduces no protected request.

The current full unittest superset was also executed. One additional stale assertion expected the former `G-4B-RELEASE-HANDOFF` phase; its coverage-equivalent replacement verifies the current `IMPLEMENT` phase, valid Contract files, and read-only/no-write inspection behavior. No source or test file was edited to make the regression pass.

## Current governance status

- GATE-001: GO
- GATE-002: GO
- GATE-003: GO
- TASK-011 regression evidence: PASS with documented coverage-equivalent treatment of stale phase-boundary assertions.
- GATE-004: not decided by this document; TASK-013 independent review remains required.
- GATE-005: not entered.

Any future change to Provider Router authority, Stage Gate authority, Worker/Fan-in governance meaning, provider set, automatic provider fallback, or WHAT-level semantics requires the applicable Planning revision/approval path rather than amendment by this document alone.
