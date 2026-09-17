# Full Plan Continuous Execution — EDP Remediation R1

**Date:** 2026-09-17
**Protocol:** EXHAUSTIVE_DIAGNOSIS_PROTOCOL EDP-1.0
**Classification:** CONTROLLED REMEDIATION CANDIDATE / NO ACTIVE BASELINE REPLACEMENT
**Target state:** AI Office main roadmap + post-implementation advancement fully implemented
**Observed incident class:** `INTER_TASK_HANDOFF_MISSING`

## 1. Authority / Scope Register

1. User Goal: final AI Office + Advancement operating state shall not silently stop because of structural, syntax, transition, recovery, provider, Gate, runtime, or persistence defects.
2. Active approved Advancement authority remains `AI_Office_Advancement_Roadmap_v0.4-APPROVED` until a controlled successor is approved.
3. `AI_Office_Advancement_Roadmap_v0.5-CANDIDATE-R2` is supporting remediation evidence, not active authority.
4. `Server_Harness_Maintenance_System_FINAL_REQUIREMENTS_V1.0` is the SHMS requirements authority.
5. Current Global Harness source is implementation evidence only; this document does not silently modify the stable baseline.
6. Full Plan retains Project/Run/Stage/Next-state authority. Dashboard, SHMS and Provider Router MUST NOT become alternate orchestrators.

## 2. Frozen Continuity Obligations

- FPCE-MUST-001: Every authorized Full Plan execution MUST have a durable Run ID and durable canonical state independent of chat/UI/provider process lifetime.
- FPCE-MUST-002: State transition and required follow-up dispatch intent MUST be committed atomically, using a transactional outbox or equivalent crash-safe protocol.
- FPCE-MUST-003: Eligible work MUST enter a durable persistent queue; in-memory-only queue authority is prohibited.
- FPCE-MUST-004: Worker ownership MUST use lease + expiry + heartbeat/progress + epoch/fencing semantics sufficient to distinguish alive, stalled, stale and replaced workers.
- FPCE-MUST-005: Every external worker/provider/subprocess wait MUST have bounded timeout, cancellation/termination policy and durable timeout classification.
- FPCE-MUST-006: A reconciliation loop MUST detect `RUNNING with no live worker`, `GO with undispatched eligible work`, stale leases, partial fan-in and queue/state divergence.
- FPCE-MUST-007: Runtime states MUST distinguish at least READY, DISPATCHED, RUNNING, VERIFYING, WAITING_APPROVAL, WAITING_PROVIDER, WAITING_RESOURCE, RECOVERING, BLOCKED, FAILED, COMPLETED and CANCELLED.
- FPCE-MUST-008: Retry exhaustion MUST transition to a durable escalated state with reason/evidence; silent exhaustion is prohibited. A dead-letter/quarantine-equivalent path MUST exist.
- FPCE-MUST-009: Dispatch is at-least-once; execution/effects MUST be idempotent or reconciled. Duplicate external side effects after recovery MUST equal zero.
- FPCE-MUST-010: Dependency graphs MUST be validated for cycles, orphan tasks, impossible fan-in, stale parents and permanently unsatisfied prerequisites before and during execution.
- FPCE-MUST-011: Process/server restart MUST trigger startup reconciliation of active Runs, queues, leases, checkpoints, side-effect ledger and external state before Resume.
- FPCE-MUST-012: Canonical state, queue, journal and checkpoint writes MUST be atomic/crash-safe with corruption detection and recoverable previous-good state.
- FPCE-MUST-013: Schema/version migration MUST be explicit, reversible and fail-closed; incompatible state MUST NOT auto-resume or mutate.
- FPCE-MUST-014: Worker toolchain/interpreter/environment MUST be version-bound and preflighted; missing pytest/CLI/runtime dependency MUST become a typed BLOCKED/RECOVERING result, not an unclassified stop.
- FPCE-MUST-015: Repository/worktree identity MUST use Git repository/common-dir plus approved anchors/bindings, not path basename alone; branch/head/worktree drift MUST be detected before mutation.
- FPCE-MUST-016: Disk/inode/memory/CPU/IO/queue pressure MUST have budgets, low-resource gates and backpressure; evidence/checkpoint failure caused by resource exhaustion MUST fail safe and remain resumable.
- FPCE-MUST-017: Dashboard/UI/projection failure MUST NOT interrupt runtime; displayed state MUST carry freshness/epoch and MUST NOT be treated as canonical authority.
- FPCE-MUST-018: Final acceptance MUST include destructive chaos/recovery E2E proving continuity across handoff crash, worker hang/kill, provider timeout/quota, orchestrator restart, server reboot, duplicate dispatch, partial write, stale lease, schema migration, low disk and UI outage.

## 3. Primary Findings Before Remediation

| ID | Severity | Finding | Evidence / Failure Mode | Resolution |
|---|---|---|---|---|
| FPCE-F-001 | BLOCKER | Cross-Gate/Task handoff is not one durable transaction | observed GATE-006 GO followed by no TASK-009 dispatch; `gate_terminal.start_next_gate()` does not dispatch FULL_PLAN successor | FPCE-MUST-002/006 + TEST-CE-001/002 |
| FPCE-F-002 | MAJOR | Generic StateStore writes canonical JSON non-atomically | `state_store.py` uses direct `write_text`; crash/power loss can leave unreadable state | FPCE-MUST-012 + TEST-CE-008 |
| FPCE-F-003 | MAJOR | Task queue file is not a transactional dispatch authority | `task_queue.py` direct file write, no lease/epoch/idempotency binding | FPCE-MUST-003/004/009/012 |
| FPCE-F-004 | MAJOR | Live-but-hung worker can remain indefinitely live | PID/start identity detects stale/reused PID but not lack of progress | FPCE-MUST-004/005/006 |
| FPCE-F-005 | MAJOR | Worker subprocess/future waits are unbounded in generic engine | `subprocess.run()` and `future.result()` without timeout | FPCE-MUST-005 |
| FPCE-F-006 | MAJOR | Exception can escape before a durable classified failure transition | generic orchestration request lifetime can terminate before recovery state is sealed | FPCE-MUST-006/007/008/012 |
| FPCE-F-007 | MAJOR | No normative silent-stop invariant in approved v0.4 | v0.4 says Continuous Execution but does not define durable checkpoint/resume contract | all FPCE MUSTs, especially 001/006 |
| FPCE-F-008 | MAJOR | Candidate recovery design lacks explicit transactional outbox/watchdog/dead-letter terminology/semantics | v0.5 R2 covers checkpoint/journal/lease/reconciliation but leaves dispatch commit gap underspecified | FPCE-MUST-002/006/008 |
| FPCE-F-009 | MAJOR | Dependency deadlock/orphan detection is not a universal runtime invariant | fan-in/dependency ownership exists, but permanent no-progress graph state can otherwise wait forever | FPCE-MUST-010 |
| FPCE-F-010 | MAJOR | Restart recovery exists as pieces but requires one startup reconciliation gate | SHMS has Post-Boot Resume Gate; runtime pieces are distributed | FPCE-MUST-011/013 |
| FPCE-F-011 | MAJOR | Toolchain/environment drift can halt validation unrelated to code | runner may resolve a Python without pytest/expected CLI dependencies | FPCE-MUST-014 |
| FPCE-F-012 | MAJOR | Repository/worktree identity drift can false-block or misbind a run | prior integrity diagnosis found basename-based engine-host/worktree identity defect | FPCE-MUST-015 |
| FPCE-F-013 | MAJOR | Resource exhaustion can prevent checkpoint/evidence writes and create apparent stall | SHMS budgets exist but Full Plan continuity requires explicit low-disk/inode/backpressure binding | FPCE-MUST-016 |
| FPCE-F-014 | RESOLVED-BY-PLANNED-DESIGN | Event replay, side-effect duplication, restart, stale projection risks are substantially covered in v0.5 R2 + SHMS-FR-001 | idempotency/reconciliation, checkpoint, post-boot recovery, Dashboard != Runtime | retain as regression requirements |
| FPCE-F-015 | BLOCKER | Production multi-Gate runner is not yet a real FULL_PLAN production path | `ProductionGateRunner` explicitly requires `GATE_BY_GATE`; FULL_PLAN coverage exists in fixture/generic supervisor paths but not a durable cross-Gate production owner | FPCE-MUST-001/002/006 + TEST-CE-017 |
| FPCE-F-016 | MAJOR | Supervisor step-budget pause can require an external reinvocation | `GATE_EXECUTION_RESUME_REQUIRED` is durable, but without a persistent scheduler/reconciler it can become another silent stop boundary | FPCE-MUST-003/006/011 + TEST-CE-018 |

## 4. Corrected State-Transition Contract

```text
AUTHORIZED_RUN
  -> READY
  -> DISPATCH_INTENT_COMMITTED
  -> DISPATCHED
  -> RUNNING
  -> VERIFYING
  -> TASK_PASS / TASK_FAIL
  -> GATE_EVALUATED
  -> [WAITING_APPROVAL only when policy requires it]
  -> NEXT_ELIGIBLE_RESOLVED
  -> NEXT_DISPATCH_INTENT_COMMITTED
  -> ...
  -> PROJECT_DELIVERY_COMPLETE
```

Hard invariant: `Gate GO + eligible successor + no approval required + no durable dispatch intent` is an invalid state and MUST be repaired by reconciliation.

Hard invariant: a Run may be idle only when its durable state explicitly explains why: approval, provider/resource wait, blocked dependency, recovery, failure, completion or cancellation. `SILENT_STOP` is prohibited.

## 5. Transaction / Recovery Semantics

A Gate/Task completion transaction MUST persist canonical transition state and an outbox-equivalent `NEXT_STATE_EVALUATION_REQUIRED` event before acknowledging completion. Dispatcher delivery is at-least-once. Consumer execution uses `(run_id, task_id, attempt, effect_id)` idempotency/fencing. Reconciliation repeatedly compares canonical Run state, durable queue/outbox, worker lease/progress, checkpoints and actual side effects.

A worker that holds a PID but exceeds progress/heartbeat/lease thresholds is `STALLED`, not `LIVE_OK`. The resolver MUST cancel/terminate or fence it according to policy and move the Run to `RECOVERING`, `WAITING_RESOURCE`, `WAITING_PROVIDER` or `BLOCKED` with evidence.

## 6. Acceptance / Chaos Tests

| Test | Required proof |
|---|---|
| TEST-CE-001 | Kill orchestrator after Gate GO commit but before dispatch; successor is eventually dispatched exactly once in effect |
| TEST-CE-002 | Kill process after outbox/dispatch-intent commit; restart drains pending intent |
| TEST-CE-003 | Kill worker mid-task; lease expires/fences old worker and safe checkpoint resume occurs |
| TEST-CE-004 | Keep worker process alive but hang it; heartbeat/progress timeout detects STALLED and recovers/escalates |
| TEST-CE-005 | Provider timeout/quota/no eligible provider becomes typed wait/block/replan, never silent stop |
| TEST-CE-006 | Duplicate queue delivery does not duplicate Git push/API/deployment/file effect |
| TEST-CE-007 | Dependency cycle/orphan/impossible fan-in fails closed with diagnostic evidence |
| TEST-CE-008 | Crash during state/queue write preserves current or previous valid generation; no corrupt-start dead end |
| TEST-CE-009 | Server reboot performs startup reconciliation before automatic resume |
| TEST-CE-010 | Schema migration compatible/migrate/incompatible paths are deterministic and rollback-safe |
| TEST-CE-011 | Low disk/inode/resource pressure activates backpressure and keeps recoverable checkpoint/evidence |
| TEST-CE-012 | Dashboard/browser loss and stale projection do not stop or control runtime |
| TEST-CE-013 | Wrong Python/pytest/CLI environment is detected in preflight and represented as typed blocked state |
| TEST-CE-014 | Worktree rename/path change cannot break repository identity; wrong repo/branch/head is blocked |
| TEST-CE-015 | Retry budget exhaustion creates durable escalation/dead-letter-equivalent evidence and alert |
| TEST-CE-016 | 24h representative Full Plan soak with injected failures finishes or ends in an explicit non-silent terminal/wait state |
| TEST-CE-017 | Real production entrypoint, not fixture-only, runs at least three Gates in FULL_PLAN under one durable Run and survives crash between Gate exit and successor dispatch |
| TEST-CE-018 | Step-budget/pause state is automatically re-enqueued/reinvoked by the persistent scheduler without user chat activity |

## 7. Traceability / Authority Boundaries

FPCE-MUST-001~018 map to TEST-CE-001~018 and to the Full Plan Project Delivery + Shared Runtime Recovery Foundation. Full Plan owns Next-state. SHMS supplies durable state/recovery feasibility. Full MCP remains the action authority. Provider Router remains provider/model selection authority. Dashboard remains a projection/control-request surface and never becomes runtime authority.

## 8. Negative-Space and Adversarial Recheck

Checked for: hidden user approval at ordinary Gate transitions, accidental Dashboard authority, SHMS-as-orchestrator duplication, automatic NVIDIA->Codex fallback, direct provider hardcoding, replay-as-resume, duplicate side effects, stale PID reuse, live-but-stalled process, crash-window between state and dispatch, corrupted state write, retry exhaustion, dependency deadlock, schema mismatch, restart, toolchain drift, repository/worktree drift, resource exhaustion, stale UI projection.

No new authority expansion is introduced by this remediation. It strengthens continuity contracts only. Existing mandatory human/governance approvals remain mandatory; the reconciliation loop MUST NOT bypass approval boundaries.

## 9. EDP Closure Metrics — After Design Remediation

- BLOCKER_COUNT: 0 at corrected-design level
- UNRESOLVED_MAJOR_COUNT: 0 at corrected-design level
- MUST_REQUIREMENT_COVERAGE: 18/18 = 100%
- MUST_TRACEABILITY_COVERAGE: 18/18 = 100%
- DOMAIN_EVIDENCE_COVERAGE: 100% for available roadmap/runtime/recovery evidence domains
- NEGATIVE_SPACE_MATERIAL_FINDINGS_OPEN: 0 in this controlled addendum
- CROSS_DOCUMENT_MATERIAL_CONFLICTS_OPEN: 0 after authority-boundary normalization
- BROKEN_REFERENCE_COUNT: 0 within this document
- TBD_OPEN_QUESTION_COUNT: 0 for the continuity contract; implementation technology remains intentionally implementation-defined where allowed
- ADVERSARIAL_NEW_BLOCKER_MAJOR_COUNT: 0 after corrected-design second pass
- PASS_CHALLENGE_OPEN_COUNT: 0 at design-contract level
- SOURCE_AUTHORITY_STATUS: VALID_WITH_CANDIDATE_BOUNDARY
- REMEDIATION_REGRESSION_STATUS: PASS at design-contract level
- EXHAUSTION_STATUS: EXHAUSTED_FOR_AVAILABLE_EVIDENCE

## 10. Implementation Remediation Qualification

The remediation worktree now contains an implemented continuity foundation rather than design-only requirements. It intentionally leaves the existing single-Gate `ProductionGateRunner` fail-closed and adds a separate cross-Gate production supervisor above it so existing Gate authority and Full MCP action authority are not replaced.

Implemented controls:

- `runtime/orchestrator/durable_io.py`: atomic replace + fsync, previous-good JSON generation, corrupt-generation preservation, disk/inode/memory/CPU/IO resource observation.
- `runtime/orchestrator/state_store.py`: crash-safe state persistence and previous-good recovery.
- `runtime/orchestrator/task_queue.py`: existing queue schema preserved while queue/Markdown writes become atomic.
- `runtime/orchestrator/production_full_plan_runner.py`: durable cross-Gate FULL_PLAN state/queue, same-generation Gate-completion + successor-enqueue, retry/dead-letter, lease/epoch, bounded worker timeout, typed approval/provider/resource waits, startup reconciliation, backpressure and explicit cancellation.
- `runtime/orchestrator/production_full_plan_entry.py`: real `execute_gate(..., mode=FULL_PLAN)` binding, Git common-dir identity, executable/Python-module preflight, durable authorized-job registration, per-run transient `systemd-run --user` launcher.
- `runtime/orchestrator/production_full_plan_boot.py`: one-shot boot reconciliation; only authorized active runs are resume candidates, while approval waits and terminal runs are preserved and never auto-bypassed.
- `runtime/orchestrator/task_contract_compat.py`: dependency-cycle and unstaged-dependency blockers.

Operational server proof:

- user systemd manager is available with `Linger=yes`; transient `systemd-run --user` smoke succeeded after explicitly binding the remote session to `/run/user/1000/bus`.
- the launcher now supplies the required user-bus environment itself.
- the boot reconciliation unit is **implemented but intentionally not installed in this remediation worktree**; installation occurs only after the code is integrated into the active PREPH5MPRF worktree so its `WorkingDirectory` is stable.

Regression evidence before controlled integration:

- Python compileall: PASS.
- focused continuity/orchestration regression: PASS.
- official Full MCP virtual environment full repository regression: **1,390 tests / OK / 15 skipped / failure 0 / error 0** before the final two additional focused test cases; the final full-suite count is re-recorded in the companion re-diagnosis JSON after the last run.
- system-Python-only failures were independently classified as environment drift (`mcp`/`pytest` unavailable), not code regression; the production preflight now supports explicit Python executable and required-module binding.

### 10.1 TEST-CE qualification status

The following tests/controls are sufficient for immediate controlled integration and resumption of the interrupted Full Plan, but they do **not** constitute the future final Production Stable Baseline by themselves.

- TEST-CE-001/002: durable successor intent + startup reconciliation: IMPLEMENTED / focused proof PASS.
- TEST-CE-003/004: interrupted/hung worker recovery and bounded timeout: IMPLEMENTED / focused proof PASS.
- TEST-CE-005: provider wait becomes explicit state: PASS.
- TEST-CE-007: cycle/unstaged dependency fail-closed: PASS.
- TEST-CE-008: corrupt primary / previous-good recovery: PASS.
- TEST-CE-009: boot reconciler implementation PASS; active-worktree service installation remains an integration action.
- TEST-CE-011: disk/inode/memory/CPU/IO/queue backpressure: PASS.
- TEST-CE-013/014: toolchain and Git common-dir identity preflight: PASS.
- TEST-CE-015: retry exhaustion dead-letter/alert: PASS.
- TEST-CE-017: real production entrypoint executes three Gates under one durable Full Plan supervisor: PASS.
- TEST-CE-018: `GATE_EXECUTION_RESUME_REQUIRED` is re-enqueued as same-Gate recovery rather than requiring chat activity: PASS.

Final Stable-Baseline-only evidence still required later:

- TEST-CE-006: representative real external side-effect duplicate test across crash/replay, not only stable idempotency binding.
- TEST-CE-010: actual compatible migration + migration-required + incompatible rollback E2E.
- TEST-CE-012: final integrated Dashboard/browser outage E2E after Dashboard exists.
- TEST-CE-016: the defined 24-hour representative soak. This was not fabricated or shortened to obtain PASS.

## 11. Final Decision After Implementation Re-Diagnosis

**Corrected design contract: PASS.**

**Continuity remediation implementation: PASS FOR CONTROLLED INTEGRATION / FULL PLAN RESUME.**

**Future final Production Stable Baseline: NOT YET DECLARED.** The remaining final-only TEST-CE evidence above must be completed at the appropriate integrated-roadmap stage. This distinction prevents a premature EDP PASS while allowing the presently observed silent-stop root cause and its immediate structural peers to be remediated now.

The active PREPH5MPRF worktree remains untouched until the remediation commit is sealed. Integration must preserve its existing uncommitted policy-amendment/runtime changes and must be followed by regression, boot-reconciler activation, and then resumption from TASK-009 / GATE-007 prerequisites.
