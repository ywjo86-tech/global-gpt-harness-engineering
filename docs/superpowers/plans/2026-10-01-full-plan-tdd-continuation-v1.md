# Full Plan TDD Continuation V1 Implementation Plan

1. RED: durable Expected RED contract/checkpoint classification tests.
2. GREEN: pure `implementation_continuation` contract/store; no execution authority.
3. RED/GREEN: opt-in Full Plan supervisor integration using existing run lock.
4. RED/GREEN: boot blocks blind retry of `GREEN_RUNNING` while leaving `GREEN_READY` resumable.
5. RED/GREEN: operator-plan and AUTO_RECONCILE builders expose explicit `TDD_V1`; omission remains LEGACY.
6. Verify legacy/per-Gate, two-action dangerous approval and P5/P6 boundaries.
7. Run compile/diff checks, full regression and regression-delta; require current-only failure count zero.
8. Publish a dependent draft PR against PR #38 branch; do not merge or perform runtime/production/P5/P6 effects.
