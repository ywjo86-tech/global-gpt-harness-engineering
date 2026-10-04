# AI Office / Full Plan Hybrid / Harness Operations Deep Diagnosis — 2026-10-04

## Status
- Scope: AI Office operational health, Full Plan Hybrid, OCPv2, Harness-wide control/execution/monitoring/recovery chain.
- Mode: diagnosis and evidence recording only. No runtime/code repair, restart, cleanup, merge, commit, or push performed.
- Initial verdict: CORE HEALTHY / OPERATIONAL ACCEPTANCE BLOCKED.

## Phase 1 — AI Office operational diagnosis already confirmed
1. OCPv2 control path is active and healthy.
   - ocpv2.timer: active, 30-second poll cadence.
   - ocpv2.service: last result success, ExecMainStatus=0.
   - ocpv2-host-runner.service: active/running.
2. Full Plan reconcile is active.
   - global-gpt-harness-full-plan-reconcile.timer: active, 60-second cadence.
   - reconcile service latest result success.
3. Latest AI Office PR33 successor Full Plan run completed.
   - Run: AI-OFFICE-PR33-B986450-SUCCESSOR-20261003-01
   - Gates: 2, 5 completed.
   - recovery_count=0, last_error=null, terminal_reason=ALL_GATES_COMPLETED.
4. Current operational regression on runtime 478dc312 passed.
   - False-Green / Post-Change tests: 10 PASS.
   - PR33/OCP/Recovery/Read Model/Boot/Reporting/Capability tests: 113 PASS.
   - Total targeted operational tests: 123 PASS.
5. Live Post-Change Gate is currently BLOCKED.
   - OCP timer/service, host runner, reconcile timer/service, diagnostic coverage all PASS.
   - Blocking reason: ATTENTION_WATCH_DISABLED.
6. Harness Reconcile Timer Watch is enabled, but Harness Attention Watch is disabled.
   - Manual attention discovery found no current PR33 / 2026-10-04 AI Office incident.
   - Returned pending incidents were historical deferred evidence from mainly 2026-09-18~19.
7. Structural gap: operational_post_change_gate exists and is tested, but is not invoked by the production Full Plan completion path.
   - FULL_PLAN_COMPLETED / ALL_GATES_COMPLETED can therefore exist while live operational acceptance is BLOCKED.
   - Execution completion and operational acceptance are not yet mechanically bound.
8. Runtime/release identity:
   - OCP serving runtime: 478dc312f4c0f6808eab0b21775362c6ff0541bb
   - Harness runtime-current: d3317010112384b3e86d3c68bd0708f05de5558c
   - PR33 remote HEAD: b9864506a1a07e2e7500a3b1dda80cf6db42bf29
   - Different OCP/Harness release identities are explicitly allowed by design if source-tagged.
9. Reproducibility gap:
   - Serving OCP commit 478dc312 is present locally but not retrievable from GitHub remote.
   - Current service works, but exact remote reconstruction is not guaranteed.
10. Durable transport pending:
   - github-delivery-acks.json.pending contains 8 entries with zero exact overlap against durable ACKs.
   - Includes one historical AI Office request and one AI Commerce recovery request.
   - These are durable pending records, not temporary files; lifecycle retirement/expiry is not evidenced.
11. Dashboard smoke residue:
   - Test listeners remain active on ports 8014, 8017, 8018.
   - No current functional failure is proven, but unmanaged smoke listeners create port/resource/identity ambiguity.
12. Legacy AI Office checkout:
   - implementation-ai-office-harness-ocp-20260924 local checkout is behind remote and has unrelated uncommitted changes.
   - It is not the current serving runtime, but it is a baseline-confusion risk.

## Phase 1 conclusion
AI Office execution and recovery core are healthy, but full operational GREEN must not be declared while Attention Watch is disabled and operational acceptance is not mechanically coupled to Full Plan completion.

## Phase 2 — Full Plan Hybrid + Harness-wide diagnosis
IN PROGRESS. Findings below will be appended after live evidence collection.


## Phase 2 — Full Plan Hybrid + Harness-wide live diagnosis

### 2.1 Canonical Hybrid authority model
Current D1.5 execution contract preserves the intended authority split:
- GPT_OPERATOR: operator authority.
- Full Plan: planning, task decomposition, final Task-to-Agent assignment, Gate lifecycle and fan-in.
- Multi-Provider Router: provider/model selection, reselection and failover.
- MPRF: provider runtime/eligibility/recovery facts.
- Full MCP / execution backend: state-changing effects and effect reconciliation.
- AI Office / OCP: request, state, governance, activation and observation boundary; no new provider/model/effect authority.

Historical EDP evidence confirms prior structural Hybrid defects were remediated:
- canonical Operator -> durable Full Plan WAITING_PROVIDER resume bridge;
- concurrency lock for operator resume;
- immutable run authority / rebinding prevention;
- stale package rejection;
- positive AI Office Full Plan assignment/completion binding;
- semantic-progress vs liveness separation;
- attention outbox for stalls and silent loss.

### 2.2 Current registered Full Plan estate
Live state scan:
- registered jobs: 94
- COMPLETED: 14
- BLOCKED: 60
- CANCELLED: 20
- nonterminal/missing: 0
- duplicate run IDs: 0

Therefore no canonical registered Full Plan run is currently active or waiting.

D1.5 final successor is durable and complete:
- run: D15-FULL-PLAN-R02-SUCCESSOR-D331701-20261003-12
- execution_owner: AUTO_RECONCILE
- state: COMPLETED
- completed Gates: GATE-R02, GATE-R03, GATE-R04, GATE-R05
- recovery_count: 0
- last_error: null
- terminal_reason: ALL_GATES_COMPLETED
- lifecycle_mode: V2
- exact activation approval, authority-core digest, runtime digest and per-Gate authority digests are present.

### 2.3 Current Hybrid regression
On serving 478dc312 source:
- targeted Hybrid suite executed: 119 tests.
- one test failed only when run from the packaged release directory because that directory intentionally has no .git and the test performs Git ancestry checks.
- the exact same pre-MPRF integration module was rerun from a Git worktree at exact HEAD 478dc312 and all 4 tests passed.
- one opt-in proof test was skipped as designed.

Material Hybrid controls verified green include:
- governed Router required for Hybrid state change;
- no silent provider fallback after governed action block;
- Router-bound model cannot be replaced by environment model;
- read-only vs mutation provider separation;
- MPRF supplies eligibility facts but does not gain provider-selection authority;
- invalid/missing secret state fails closed;
- WAITING_PROVIDER operator resume exact binding, stale-head rejection and concurrency serialization;
- duplicate-effect prevention and checkpoint/CAS/epoch fencing;
- fork/orphan continuation chain fail-closed;
- completion authority snapshot/tamper protection;
- AI Office manual-action continuation binding.

Conclusion: core Hybrid authority/continuity/replay-fence logic is healthy on the current source.

### 2.4 OCP remains the primary operating path
Live process/unit/code inspection:
- OCPv2 service/timer and OCP host control runner are active.
- host inspection, work activation and Full Plan activation flags are enabled.
- no Harness execution path using RDC/Remote Desktop was found in the serving runtime.
- GNOME remote desktop system daemon is OS infrastructure only and is not the Harness execution path.

Conclusion: OCP remains the primary control/activation route. RDC has not re-entered as the Harness default execution path.

### 2.5 CONFIRMED MAJOR — canonical Registry vs OS process drift
Although the canonical Full Plan Registry has zero nonterminal jobs, three Full Plan canary processes remain alive outside that Registry:
- PID 550360: started 2026-09-23, DCC_LIVE_AUTO_CANARY/canary-retention.
- PID 3521156: started 2026-10-01, DCC_LIVE_AUTO_CANARY/canary-retention.
- PID 1079401: started 2026-10-03, DCC_LIVE_AUTO_CANARY/canary-retention.

For all three:
- parent is PID 1;
- referenced /tmp job roots no longer exist;
- held supervisor.lock file descriptor is deleted;
- no child process remains.

This is direct evidence of Registry <-> OS lifecycle drift.

### 2.6 CONFIRMED MAJOR — process lifecycle diagnostic exists but is not wired into operations
The serving source contains runtime/diagnostics/process_lifecycle.py.
It explicitly classifies missing owner-state + missing lock as ORPHAN_SUSPECTED and requires cleanup authorization.

The corresponding regression test uses real observed PID 550360 as the example and passes.

However, repository-wide runtime search found no production caller of:
- diagnose_process_lifecycle
- ORPHAN_SUSPECTED
- OWNERSHIP_DEGRADED

It is not connected to:
- production_attention_watch,
- operational post-change gate,
- AI Office operations read model,
- periodic reconcile.

Therefore the system already knows how to diagnose this defect class, but the live operations chain does not invoke that knowledge.

### 2.7 CONFIRMED MAJOR — HOST_GATEWAY accept timeout is not enforced
Two proof host runners remain live:
- PID 38602, listening since 2026-09-05.
- PID 1336197, listening since 2026-09-07.

There are 31 /tmp/harness-host-gateway-* socket files, but only 2 live listeners; the rest are stale socket artifacts.

Root cause confirmed in serving source:
- host_runner_entry exposes --timeout, default 1800 seconds.
- UnixSocketHostRunner.serve_once(timeout=1800) calls server.listen(1) and then blocking server.accept().
- no socket timeout is applied before accept().
- timeout is only passed later to the connected execution/runtime handler.

Therefore a host runner that never receives a client can wait indefinitely despite the nominal timeout. Socket cleanup occurs only when serve_once exits. This matches the observed multi-week listeners.

### 2.8 CONFIRMED MODERATE — stale provider-wait active pointers
Eight provider-wait/**/active.json pointers remain.
Every associated canonical Full Plan job is already terminal:
- CANCELLED and superseded, or
- BLOCKED / RETRY_BUDGET_EXHAUSTED.

Safety check:
production_full_plan_boot consults provider-wait active evidence only when canonical state is a WAIT_STATE. Terminal states are handled first/independently and are never resumed from these stale pointers.

Therefore this is not a current duplicate-execution path, but it is an auxiliary-state lifecycle/observability defect. External tooling that reads active.json without joining canonical state can report false activity.

### 2.9 CONFIRMED MODERATE — activation receipt canonical path can become dangling after supersession
64 Full Plan activation receipts were inspected for run-to-job presence.
Two receipts report FULL_PLAN_REGISTERED but their recorded canonical_job_path no longer exists:
- AI-COMMERCE-V040-TASK010-SUCCESSOR-08A5F4D-20261003-18
- AI-COMMERCE-V040-TASK010-SUCCESSOR-B920E90-20261003-17

The jobs are not lost:
- preserved copies exist as superseded-job-18.json and superseded-job-17.json;
- durable Full Plan state exists;
- both runs are terminal BLOCKED / RETRY_BUDGET_EXHAUSTED.

The defect is traceability indirection: an immutable activation receipt points to a path that later became invalid after supersession. Recovery/evidence readers following only canonical_job_path cannot reconstruct the preserved job without separate supersession knowledge.

### 2.10 CONFIRMED MODERATE — operational completion is not mechanically bound to Post-Change acceptance
Previously confirmed Phase 1 finding remains valid at Harness-wide level:
- production Full Plan records FULL_PLAN_COMPLETED / ALL_GATES_COMPLETED;
- operational_post_change_gate is not called by that completion path;
- live Post-Change Gate is currently BLOCKED because Attention Watch is disabled.

Therefore Full Plan execution completion and Harness operational acceptance are distinct but not mechanically chained.

### 2.11 CONFIRMED MODERATE — monitoring coverage gap
Reconcile Timer Watch is enabled.
Attention Watch is disabled.

Manual production_attention_watch currently returns:
- pending_total: 33
- after the historical watch cutoff 2026-09-19T04:11:28Z: 2
- both are old 2026-09-19 terminal MVP blocked incidents.
- current 2026-10-03/04 active-run attention incidents: 0.

So there is no evidence of a current hidden active-run failure, but the notification layer is incomplete.

### 2.12 CONFIRMED MODERATE — stale operational residue
AI Office dashboard smoke processes from 2026-09-28 remain resident.
Live smoke listeners remain on:
- 8014
- 8017
- 8018

This creates resource, port and serving-identity ambiguity.

Old proof host-runner processes and numerous stale UDS files show the lifecycle residue is Harness-wide, not only Dashboard-specific.

### 2.13 CONFIRMED MODERATE — serving release reproducibility gap
Serving OCP runtime is 478dc312f4c0f6808eab0b21775362c6ff0541bb.
GitHub remote does not contain this exact commit.
The local runtime and local Git worktree currently preserve it, but exact reconstruction from remote source is not guaranteed after host loss.

This does not break current execution, but it weakens disaster recovery and audit reproducibility.

### 2.14 CONFIRMED LOW/MODERATE — approved contract status vs actual execution state drift
Current docs/DEVELOPMENT_PLAN.txt records:
- FINAL_EXECUTION_APPROVAL: APPROVED
but also:
- TARGET_MUTATION_STATUS: NOT_PERFORMED
- FULL_PLAN_EXECUTION_STATUS: NOT_STARTED
- EXECUTION_HANDOFF_STATUS: READY_FOR_FULL_PLAN_EXECUTION

Actual durable evidence shows D1.5 activation/execution and final successor completion already occurred.

The approved semantic contract should remain immutable, so the safe correction is not to rewrite approval history. The gap is the absence of a bound post-execution/operational-acceptance record that clearly supersedes the draft handoff status for current-state readers.

### 2.15 Runtime / host resource state
Current host health:
- failed user systemd units: 0
- disk usage: 50%, ~111 GiB available
- inode usage: 16%
- load average: approximately 0.20 / 0.25 / 0.35
- memory available: ~4.0 GiB
- swap usage: ~3.0 GiB of 4.0 GiB

No present resource gate failure was observed. Swap usage is worth watching but is not currently blocking execution.

## Phase 2 verdict

### Core execution verdict
FULL_PLAN_HYBRID_CORE = HEALTHY

The approved authority model, Router/MPRF separation, durable supervisor, checkpoint/recovery, operator resume, duplicate-effect prevention and final D1.5 successor execution are functioning and have both regression and live durable evidence.

### Whole-Harness operating verdict
HARNESS_OPERATIONAL_STATE = DEGRADED
OPERATIONAL_ACCEPTANCE = BLOCKED

Primary reasons:
1. Attention Watch disabled.
2. Post-Change operational gate not mechanically chained to Full Plan completion.
3. Registry-to-OS process lifecycle drift exists.
4. Process-lifecycle orphan diagnostic exists but is not wired into operations.
5. HOST_GATEWAY accept can block indefinitely despite configured timeout.
6. Serving OCP release is not remotely reproducible.
7. stale provider-wait, transport pending, smoke process/socket and receipt-path residue remain.

### Reverse verification
The system can execute approved Hybrid work safely, but it cannot yet prove that every completed execution leaves the whole Harness in a clean, observable, reproducible operating state. Therefore declaring overall GREEN would be a false-green risk.

## Recommended repair order (not executed in this diagnosis)
1. Freeze current operational snapshot/evidence.
2. Restore Harness Attention Watch.
3. Bind Full Plan terminal completion -> Post-Change Operational Gate -> explicit OPERATIONAL_ACCEPTED state, without changing Full Plan execution semantics.
4. Wire process_lifecycle diagnostics into the read-only operations/attention/post-change path.
5. Fix HOST_GATEWAY pre-connect accept timeout and add orphan/stale-socket regression.
6. Evidence-review and retire confirmed orphan canary/proof/smoke processes; no blind cleanup.
7. Add terminal/supersession lifecycle handling for provider-wait active pointers.
8. Preserve immutable activation receipts while adding durable supersession resolution so canonical_job_path remains reconstructable.
9. Publish/remote-bind the exact serving release or produce an equivalent immutable disaster-recovery artifact.
10. Add a post-execution operational acceptance record rather than rewriting the approved D1.5 semantic contract.
11. Rerun targeted Hybrid regression, failure-injection, orphan-process reproduction, live Post-Change Gate and end-to-end AI Office/Harness acceptance.

No repair, kill, restart, cleanup, merge, commit or push was performed during this diagnosis.
