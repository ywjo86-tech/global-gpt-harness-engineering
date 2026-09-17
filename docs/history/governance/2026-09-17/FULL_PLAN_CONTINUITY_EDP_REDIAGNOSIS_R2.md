# Full Plan Continuity — EDP Re-Diagnosis R2

**Date:** 2026-09-17  
**Protocol:** EXHAUSTIVE_DIAGNOSIS_PROTOCOL EDP-1.0  
**Protocol SHA-256:** `7a74df80220143f3b5aaad9d7d67285f955156b95df885690b52fec76d427baf`  
**Authority:** current explicit user decision to remediate the diagnosed silent-stop and missing-user-call defects  
**Implementation commit:** `4759cc8` (`fix(orchestrator): harden full-plan continuity and attention`)

## Scope

This re-diagnosis covers the Full Plan continuity defects discovered after TASK-011: duplicate supervisor execution, missing successor handoff, unreported terminal/wait states, non-persistent reconciliation, unsupported direct FULL_PLAN entry, worktree-bound systemd recovery, and absence of a durable user-attention path. It does not claim that unrelated Full MCP dependency/toolchain baselines are globally all-green.

## Remediation Evidence Matrix

| Finding | Remediation | Evidence | Result |
|---|---|---|---|
| EDP-F01 unsupported FULL_PLAN bypass | public `gate-run --mode FULL_PLAN` now fails closed and directs execution to the durable production Full Plan entry | `test_public_gate_run_rejects_unsupervised_full_plan` | PASS |
| EDP-F02 duplicate supervisor/effect | per-Run `flock` single-writer guard + systemd control-group kill semantics | concurrent adversarial test produces exactly one effect | PASS |
| EDP-F03 unreported preflight block | preflight BLOCK persists canonical BLOCKED state, alert, durable attention outbox | focused regression | PASS |
| EDP-F04 missing successor silent state | missing successor becomes `BLOCKED / DURABLE_SUCCESSOR_MISSING` with attention event | focused regression | PASS |
| EDP-F05 one-shot-only reconciliation | persistent user systemd timer invokes reconciler every 60 seconds | timer active/waiting, service status 0 | PASS |
| EDP-F06 local alert only | crash-safe idempotent `AttentionOutbox`, delivery interface, periodic repair of missing attention | outbox idempotency/delivery tests | PASS |
| EDP-F07 task/LV continuity bypass | current unsupervised TASK-010/011 progress quarantined; future official FULL_PLAN public entry requires production runner | registered legacy run is explicit BLOCKED, not auto-replayed | PASS |
| EDP-F08 attention state overriding canonical state | attention is separate outbound-only evidence; canonical BLOCKED/WAIT state remains unchanged | `control_authority=NONE` tests | PASS |
| EDP-F09 notifier authority leakage | attention records are `OUTBOUND_ONLY`; no approve/resume/reroute/action callback exists | notifier contract test | PASS |
| EDP-F10 worktree-bound recovery unit | service binds stable `runtime-current` link; retarget is rejected while active jobs exist | stable-link + active-job retarget tests | PASS |

## Negative-Space / Adversarial Recheck

Rechecked duplicate process start, stale/absent successor queue item, preflight failure, startup active state without queue ownership, terminal attention omission, runtime-link retarget during an active job, direct FULL_PLAN CLI bypass, service/timer restart behavior, and notification authority leakage. The previously reproduced two-supervisor side effect now executes once; the second supervisor is rejected before worker effect execution.

The existing TASK-010/TASK-011 manual progress is not converted into fabricated lifecycle evidence. It is registered as `preph5mprf-gate008-legacy-20260917` with canonical state `BLOCKED` and terminal reason `UNSUPERVISED_TASK010_TASK011_PROGRESS_QUARANTINED`. Reconciliation sees `jobs_found=1`, `SKIP_TERMINAL`, so no duplicate task execution occurs.

## Validation

- Focused continuity/Gate/capability regression: **158 tests PASS**.
- Full repository discovery after integration: **1432 tests executed; no new regression failures**.
- Four Full MCP import errors remain identical to the pre-remediation baseline because the current system Python lacks the `mcp` package. Baseline before the patch: 1422 tests with the same four import errors. These are an existing environment limitation, not introduced by this remediation.
- `git diff --check`: PASS.
- Python compile/compileall for changed runtime/tests: PASS.
- systemd service: enabled, one-shot execution success.
- systemd timer: enabled + active(waiting), 60-second reconciliation interval.
- Stable runtime link: `/home/ywjo/.local/share/global-gpt-harness/runtime-current` -> current authorized MPRF worktree.
- ChatGPT condition watch: enabled as a read-only user-facing fallback for pending attention events; maximum scheduled detection latency is approximately one hour.

## Closure Metrics

- `BLOCKER_COUNT = 0` within continuity-remediation scope
- `UNRESOLVED_MAJOR_COUNT = 0` within continuity-remediation scope
- `UNRESOLVED_MINOR_COUNT = 0`
- `MUST_REQUIREMENT_COVERAGE = 100%` for the diagnosed continuity obligations
- `MUST_TRACEABILITY_COVERAGE = 100%`
- `DOMAIN_EVIDENCE_COVERAGE = 100%`
- `NEGATIVE_SPACE_OPEN_MATERIAL_COUNT = 0`
- `CROSS_DOCUMENT_CONFLICT_COUNT = 0`
- `BROKEN_REFERENCE_COUNT = 0`
- `UNRESOLVED_MATERIAL_TBD_COUNT = 0`
- `UNRESOLVED_MATERIAL_OPEN_QUESTION_COUNT = 0`
- `ADVERSARIAL_NEW_BLOCKER_MAJOR = 0`
- `PASS_CHALLENGE_OPEN_COUNT = 0`
- `SOURCE_AUTHORITY_STATUS = VALID`
- `REGRESSION_REDIAGNOSIS_STATUS = PASS_DIFFERENTIAL_WITH_PREEXISTING_MCP_ENV_LIMITATION`
- `MATERIAL_DEFECT_SEARCH = EXHAUSTED_FOR_AVAILABLE_EVIDENCE`

## Final Decision

**PASS — Full Plan continuity remediation scope.**

This PASS means the diagnosed silent-stop and missing-user-attention structural paths are closed for the supported durable Full Plan execution path. It is not a claim that unrelated Full MCP environment dependencies are globally repaired. Before TASK-012 resumes under the durable runner, TASK-010/TASK-011 must be adopted through a validated evidence-preserving recovery/adoption step; they must not be automatically replayed or represented as supervised evidence retroactively.
