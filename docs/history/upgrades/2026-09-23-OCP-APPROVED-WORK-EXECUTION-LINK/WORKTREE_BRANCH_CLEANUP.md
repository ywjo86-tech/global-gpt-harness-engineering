# OCPv2 Worktree / Branch Cleanup — 2026-09-23

## Purpose

Remove obsolete development worktrees and active feature/integration branch names after the RDC-independent stable baseline was integrated, while preserving operational runtime rollback points and non-merged historical provenance.

## Removed development worktrees

- `project-workspace/.worktrees/OCPV2-R2-GATE-B`
- `worktrees/ocp-canary-validation-fix-20260923`
- `worktrees/ocp-host-gateway-lifecycle-20260923`
- `worktrees/ocp-primary-rodiag-integration-20260923`
- `worktrees/read-only-host-diagnostic-live-integration-20260923`
- `worktrees/read-only-host-diagnostic-20260923`
- `/tmp/gch-295367-broad-verify`
- `/tmp/gch-996a8d1-final-verify`

All were verified clean before removal. The canonical OCP worktree remains at `worktrees/ocp-observation-gateway-design-20260923`.

## Branch disposition

Merged local feature/integration branches were deleted after canonical integration. The active remote names for the same branches were deleted after their content was either contained in canonical history or preserved under `archive/*`.
Historical non-merged tips were not discarded. They were moved to archive namespaces:

- `archive/read-only-host-diagnostic-20260923`
- `archive/read-only-host-diagnostic-remote-20260923`
- `archive/read-only-host-diagnostic-plan-20260923`
- `archive/ocpv2-gate-e-canonical-adapter-20260921`
- `archive/ocpv2-durable-ack-20260921`

The only active remote OCP development branch after cleanup is `impl/ocp-rdc-independent-primary-path-20260923`.

## Deliberately retained runtime worktrees

`~/.local/share/global-gpt-harness/runtime-current` resolves to `/home/ywjo/AI-Workspace/runtime/ocpv2-r2-c591b01`. Therefore that worktree is operationally active and must not be removed.

Other `/home/ywjo/AI-Workspace/runtime/ocpv2-r2-*` and `runtime/source-*` worktrees were retained as rollback/provenance artifacts. They are not ordinary feature worktrees and require a separate runtime-retention decision before deletion.

## Unrelated worktrees

AI Office OmniRoute and Durable Continuation Controller worktrees were left untouched because they are outside this OCP cleanup scope.

## Current operating source

See `docs/harness/ocpv2-current-operations.md` and `FINAL_STABLE_BASELINE.md` for the current operational path, feature defaults, acceptance evidence and RDC role.