# OCPv2 Current Operations

Status: STABLE / RDC-INDEPENDENT PRIMARY PATH
Updated: 2026-09-23

## Current authority

- Canonical branch: `impl/ocp-rdc-independent-primary-path-20260923`
- Stable baseline declaration: `docs/history/upgrades/2026-09-23-OCP-APPROVED-WORK-EXECUTION-LINK/FINAL_STABLE_BASELINE.md`
- Live OCP runtime release: `996a8d1ccc210929ea79db8a7dfb5e3227cdfe5a`
- Live release manifest SHA-256: `4017a848313a3dc640cbb57613ba743700bd2907d1581d1ed3ac441cfd72c449`
- Harness `runtime-current`: `/home/ywjo/AI-Workspace/runtime/ocpv2-r2-c591b01`

## Normal operating path

`GPT -> OCPv2 -> Harness / Full Plan -> Router -> Production Gateway -> governed tool-effect path`

RDC is not part of the normal execution path. Its role is limited to `OPTIONAL_RECOVERY`, `BREAK_GLASS`, and `INTERACTIVE_TERMINAL` maintenance.

## Default feature state

- `OCP_MODE=ACTIVE`
- Host Inspection: ON
- V1 Work Activation: OFF
- Executable Full Plan Activation: OFF outside an explicitly approved activation window
- Read-only Host Diagnostic: ON

## Acceptance evidence

Fresh R9 executable canary completed `ALL_GATES_COMPLETED` with only `canary.txt` changed to the approved value, a clean Git state, zero recovery count, and no RDC use inside the acceptance window. Historical R2-R8 runs remain incident evidence and must never be resumed or reused.

The historical first executable-canary authorization and Attempt-01 failure records are retained under `docs/history/upgrades/2026-09-23-OCP-APPROVED-WORK-EXECUTION-LINK/`. They are not current activation authority.

## Verification boundary

Comparable regression on the integrated canonical tree: `2283 tests PASS / 15 skipped`. Literal full discovery additionally reports four collection errors under `tests/full_mcp` because the optional external Python `mcp` package is not installed; this is tracked as an environment dependency and is not a current OCP runtime failure.

## Operational rules

1. New executable work uses a fresh activation/run/message identity and current Gate approval evidence.
2. Full Plan Activation is enabled only for the approved bounded window and returned to OFF afterward.
3. Do not switch Harness `runtime-current` as part of routine OCP successor deployment.
4. Preserve failed canaries and receipts as immutable evidence; never repair them in place.
5. Use RDC only when the normal OCP/Harness path is unavailable or interactive host recovery is explicitly required.

## Rollback / recovery

Live OCP successor rollbacks are stored under `~/.local/state/gch/ocpv2/successor-rollbacks/`. Runtime worktrees referenced by `runtime-current` or retained as rollback evidence are operational artifacts, not disposable development worktrees.
## Git / worktree hygiene

The canonical OCP development worktree is `worktrees/ocp-observation-gateway-design-20260923`. Historical feature and integration worktrees are removed after integration. Non-merged historical tips live only under `archive/*`; they are evidence, not active implementation branches.

Do not delete `/home/ywjo/AI-Workspace/runtime/*` merely because it is a Git worktree. Runtime worktrees are governed operational artifacts; at minimum the target of `~/.local/share/global-gpt-harness/runtime-current` must remain intact.