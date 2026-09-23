# OCPv2 Read-only Host Diagnostic Live Activation — 2026-09-23

## Outcome

`LIVE_ACTIVATION_ACCEPTED / OPERATIONAL_ACTIVE`

The read-only host diagnostic extension is live with its source default still OFF. The deployed environment explicitly enables the feature. Existing OCP host-inspection behavior remains enabled, approved-work activation remains disabled, and ordinary OCP operation has returned to `ACTIVE` after a successful `CONTROL_READ_ONLY` canary.

## Live-base reconciliation

The first activation preflight found that the prepared diagnostic branch had diverged from the newer live OCP baseline. The live baseline already contained RDC-independent host inspection and approved-work activation work that was not present on the diagnostic branch. The attempted activation failed closed on unsupported live environment keys and restored the prior environment/unit files exactly before any diagnostic execution.

The diagnostic changes were then re-integrated from the live baseline `ac5347bad16c4e594f2e93cec90767177e169329`, preserving the existing host-inspection and work-activation paths. The code-bearing live successor after the final canary correction is `d177a68d0c063d90b952a53bad910478751ec36b`.

## Activation-blocker correction

The first typed live canary correctly executed under `CONTROL_READ_ONLY` with zero mutation execution, but three observations returned `UNAVAILABLE`. Two were invalid canary file fixtures. The repository snapshot also exposed a real operational mismatch: the tracked-index output was larger than the public diagnostic payload cap even though that raw index is never projected.

The repository snapshot was corrected without adding shell authority or a new Git command. The existing allowlisted `git ls-files --stage` remains internal-only, is not returned in the projection, and now has a separate 1 MiB hard internal safety cap. A regression proves an index larger than the public payload cap can be summarized while an index above the internal cap still fails closed.

## Qualification evidence

- Integrated focused regression after the correction: `136` tests, `OK`.
- Literal repository discovery after the correction: `2234` tests, four pre-existing import errors from the unavailable external Python `mcp` package, `15` skipped.
- Comparable regression excluding only the same SDK-dependent `tests/full_mcp` directory: `2208` tests, `OK (skipped=15)`.
- Direct preflight against the registered live root: all four diagnostic operations returned `OK` with `execution_owner=NONE`.

## Final live canary

Four fresh typed V3 requests were executed in `CONTROL_READ_ONLY`:

- `repo.snapshot` — `OK`
- `project.file_range` — `OK`, bounded to 20 lines
- `path.metadata` — `OK`
- `user_service.properties` — `OK`

The service reported `received=4`, `validated=4`, `diagnosed=4`, `projected=4`, `acknowledged=4`, `blocked=0`, and `executed=0`. Every projection carried `execution_owner=NONE` and the exact live source provenance. All four transport deliveries had durable acknowledgements.

A second poll of the same controls reported zero received/diagnosed/projected work, and the result count remained unchanged. The canary control comments were then made inert so they cannot re-enter after delivery-ack retention rotates.

## Operational acceptance

After the canary and replay checks passed, OCP returned from `CONTROL_READ_ONLY` to `ACTIVE` while keeping the read-only diagnostic feature explicitly enabled. The successor one-shot completed successfully with zero pending work, and the existing user timer was restored to enabled/active.

No Harness `runtime-current` switch, canonical Full Plan state change, migration transition, provider selection change, or direct mutation path was performed as part of this activation. The pre-activation rollback package remains preserved locally. No remote branch push or merge was performed.
