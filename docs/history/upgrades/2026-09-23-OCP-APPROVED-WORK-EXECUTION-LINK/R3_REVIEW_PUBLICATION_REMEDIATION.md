# R3 Review Publication Remediation — 2026-09-23

## Stop point and diagnosis

Fresh executable canary `GPT-FP-ACT-20260923-R3` performed the bounded `canary.txt` mutation successfully and sealed a completed worker result, but the Full Plan supervisor later entered `BLOCKED / PREFLIGHT_BLOCKED`.

The worker evidence shows one governed `PROJECT_OWNED_FILE_WRITE`, security PASS, focused/full validation PASS, and checkpoint commit `ba2d9dd`. The product diff from the approved baseline contains only `canary.txt`.

Root cause was post-worker review publication. `lv_review._assert_package()` accepted the immutable six-file package and several legacy runtime outputs, but rejected normal provider-action runtime artifacts (`provider-action-proposal.json`, `provider-action-effects/`, `provider-action-response-evidence/`). This produced `EVIDENCE_REQUIRED_FIELD_MISSING` with `producer_contract_error=true`. The supervisor retried, then the worker-created checkpoint naturally made the original source HEAD stale and the retry terminated as `SOURCE_HEAD_MISMATCH`.

## Remediation

Treat only the closed set of known execution-output namespaces as package-adjacent runtime evidence: `provider-action-proposal.json`, `provider-action-effects/`, `provider-action-response-evidence/`, and `host-gateway-ledger/`. Unknown files/directories remain fail-closed.

## TDD / verification

- RED: new regression reproduced the exact sealed-package rejection when provider-action outputs were present.
- GREEN: known output namespaces pass while an arbitrary `unexpected-runtime-output/` directory remains rejected.
- Focused review/gateway regression: 206 tests PASS, 1 skipped.
- `compileall`: PASS.
- `git diff --check`: PASS.
- Literal full discovery: 2306 tests; only the four pre-existing `ModuleNotFoundError: mcp` collection errors under `tests/full_mcp`; 15 skipped.

## Recovery rule

R3 remains immutable mutation evidence and is never rewritten. A fresh acceptance canary must start from a deliberately restored disposable baseline outside the RDC-exclusion window, use a new activation identity bound to the successor release containing this fix, and complete without reusing any R3 job/receipt/control identity.
