# FULL_PLAN_STABLE_BASELINE — Gate / Regression Report

**Report date:** 2026-09-14  
**Baseline commit:** `958d335c2d85dfbbe4ed5a45bf6d78f14bdc9c37`  
**Decision:** `PASS_READY_FOR_CONTROLLED_REAL_E2E`

## 1. Gate Summary

| Gate / Boundary | Decision | Final State | Evidence |
|---|---|---|---|
| ORCH04 G-4B Final Handoff | `APPROVED` | `CLOSED` | Final approval record SHA-256 `0c6187...81c6` |
| ORCH04 r15 Stage Gate | `CONDITIONAL GO` | Accepted within G-4B handoff semantics | Gate result SHA-256 `3f06cd...b8a0` |
| FP-MPEB Phase 1 GATE-004 | `GO` | `CLOSED / STOP-GATE SATISFIED` | STOP-GATE evidence SHA-256 `82212a...c0aa` |
| Provider Expansion Boundary | `STOPPED_UNDER_CURRENT_PLAN` | Preserved | No unauthorized provider expansion |
| Ubuntu Operational Adoption | `UBUNTU_OPERATIONAL_ADOPTION_CLOSED` | `CLOSED` | Closure SHA-256 `ccea82...150b4` |
| Pre-Operational Full Plan Diagnostic | `PASS_READY_FOR_CONTROLLED_REAL_E2E` | `PASS` | Diagnostic SHA-256 `945fd8...6075` |

### Gate interpretation note

The ORCH04 r15 `CONDITIONAL GO` and FP-MPEB `GATE-004 GO` are different authority surfaces. r15 governed the G-4B release-handoff decision and was subsequently accepted by the explicit G-4B final approval. GATE-004 is the separate Multi-Provider Phase 1 STOP/Resume gate and is `GO / CLOSED`.

## 2. Regression Results

| Validation | Result |
|---|---|
| Focused Full Plan regression | **233 tests PASS** |
| Tests explicitly named for `full_plan` contracts | **24 / 24 PASS, 0 skipped** |
| Canonical full repository regression | **1,141 tests OK, skipped=10** |
| Clean-clone full repository regression | **1,141 tests OK, skipped=15** |
| Post-release focused validation | **97 tests OK, skipped=1** |
| Linux installer runtime smoke | **PASS** |
| Engine-host read-only inspection | **PASS** |
| `git diff --check` | **PASS** |

Clean-clone regression was executed from the same baseline commit without the sibling `wallet-affiliate-collector` checkout. Additional skips are explicit external-integration smoke skips rather than errors.

## 3. Synthetic Full Plan Runtime Validation

A standalone `/tmp` synthetic runtime exercised the Full Plan state machine without mutating the repository.

- Four-Gate Full Plan execution: **4 / 4 Gates completed**
- Resume after interrupted execution: **COMPLETED**
- Terminal replay child invocations: **0**
- Terminal replay mutation: **false**
- Bounded repeated failure: retry budget **1** then **HARD_STOP**
- Synthetic runtime overall result: **PASS**

The first two fixture attempts were rejected before execution because of test-script/fake-root setup errors; no repository mutation occurred. The corrected fixture completed successfully.

## 4. Authorization / Safety / Recovery Coverage

The diagnostic coverage includes:

- explicit Full Plan opt-in and final-validation requirement
- missing approval denial
- Gate approval cannot substitute for Full Plan approval
- Full Plan approval cannot substitute for capability/discovery approval
- Task/Provider routing and Hybrid runtime paths
- Fan-out / Fan-in / Stage Gate flows
- worker authority and ownership boundaries
- handoff sealing and persisted-state verification
- tampered/resealed preflight rejection
- restart/resume and deterministic terminal replay
- duplicate/loop protection and bounded retry → HARD_STOP
- secret/failure-isolation evidence from Multi-Provider Phase 1
- no NVIDIA→Codex automatic fallback

## 5. Platform / Runtime Boundary

Operational host: `jarvis-server` — Ubuntu 24.04.4 LTS, x86_64.

Ubuntu/Linux runtime validation is complete. Windows PowerShell runtime smoke is categorized as an optional cross-platform compatibility check and is not a blocker for the current Ubuntu operational baseline.

## 6. Known Residual Validation Boundary

The following has intentionally **not** yet been executed:

- a real new project running Intake → Requirements → Plan → Full Plan approval → Task execution → Provider routing → Review → Gate transitions → Final Handoff
- real external Provider/network failure conditions during that new-project Full Plan run

Therefore the correct readiness statement is:

`PASS_READY_FOR_CONTROLLED_REAL_E2E`

not “all possible defects are proven absent.”

## 7. Final Regression Verdict

**PASS — 0 blocking defects found in the pre-operational validation scope.**

The baseline is suitable to be sealed as `FULL_PLAN_STABLE_BASELINE` and then used for a controlled real-project Full Plan E2E test.
