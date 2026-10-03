# Review Publication Contract Remediation — 2026-09-23

## R3 finding

R3 proved the governed product effect itself: the provider-action worker changed only `canary.txt`, sealed the governed effect receipt, committed checkpoint `ba2d9dded889f40e0803d1aaeba5429309b7339d`, and passed focused/full validation. The Full Plan then blocked during REVIEW publication before Gate completion.

The first blocking error was `EVIDENCE_REQUIRED_FIELD_MISSING` with a producer-contract marker. A retry then produced `SOURCE_HEAD_MISMATCH` only because the successful checkpoint had already advanced the disposable project HEAD; that second error was consequential, not the root cause.

## Root cause

`lv_review._assert_package()` still modeled the older worker package shape. Provider-action execution now legitimately materializes `provider-action-proposal.json`, `provider-action-effects/`, and `provider-action-response-evidence/` beside the sealed package. The review validator rejected those governed runtime outputs as package contamination before evidence publication could begin.

A concurrent uncommitted remediation adding the exact runtime-output names was discovered and preserved rather than overwritten. Qualification exposed an adjacent safety defect: an allowlisted runtime directory could be a symlink because `Path.is_dir()` follows symlinks.

## Remediation

The sealed-package validator admits only the exact known provider-action runtime outputs plus `host-gateway-ledger`, preserves rejection of unknown top-level entries, and now requires every admitted top-level entry to be non-symlinked. Review-attempt directories are also included only when non-symlinked.

## Evidence

- RED: exact runtime-output package with a symlinked `provider-action-effects` directory was incorrectly accepted.
- GREEN: legitimate exact runtime directories pass; symlinked or unknown directories fail closed.
- Historical R3 package: `_assert_package()` now passes.
- Historical R3 preflight with the Job's exact `mapping_root`: PASS; current checkpoint `ba2d9dd...` remains safely distinct from sealed source `5e93d71...` under production review semantics.
- Focused regression: 296 tests PASS, 1 skipped.
- Comparable regression excluding optional `tests/full_mcp`: 2280 tests PASS, 15 skipped.
- `compileall` and `git diff --check`: PASS.

R3 remains immutable failure evidence. It is not resumed.
