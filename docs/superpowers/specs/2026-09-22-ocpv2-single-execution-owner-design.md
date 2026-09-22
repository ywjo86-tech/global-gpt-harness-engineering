# OCPv2 Single Execution Owner Design

Date: 2026-09-22
Status: REVIEW_REQUIRED
Branch: `impl/operator-control-plane-v2-r2`

## 1. Problem

Gate E live qualification exposed a dual-authority race: a registered Full Plan job intended for OCPv2 can also be discovered and launched by the normal Full Plan boot/periodic reconciler. Exact state CAS and OCP receipt idempotency prevent many duplicate effects, but they do not establish which execution authority is allowed to initiate a given registered job.

The required invariant is:

> One registered Full Plan run has exactly one execution owner. An owner may not be changed in-place for the same run.

This design closes the race before Gate F / `ACTIVE` activation.

## 2. Goals

1. Prevent boot/periodic Full Plan reconciliation from launching an OCPv2-owned job.
2. Prevent OCPv2 canonical resume from executing a normal auto-reconcile job.
3. Prevent the generic Full Plan `run_job` path from executing an OCPv2-owned job.
4. Preserve current behavior for existing jobs that do not contain an owner field.
5. Make owner selection immutable under the existing production run authority hash.
6. Add no provider/model selection, shell authority, job-registration authority, or tool authority to OCPv2.
7. Preserve the existing Gate E recovery/outbox behavior and all normal Full Plan reconciliation behavior.

## 3. Non-goals

- No automatic migration of an existing run from one owner to another.
- No mutable lease or sidecar authority layer.
- No change to Provider Router, Production Execution Gateway, Full MCP, or provider/model policy.
- No automatic `ACTIVE` promotion.
- No change to OCP transport authority or GitHub control semantics.

## 4. Considered approaches

### A. Separate owner sidecar file

Store execution ownership beside the registered job.

Rejected because it creates a second authority object that can drift independently from the sealed job and adds another reconciliation problem.

### B. Mutable owner in durable Full Plan state

Store the owner in `state.json` and allow it to change during a run.

Rejected because the owner can change after publication/discovery and therefore does not close the registration/discovery race. It also makes takeover semantics ambiguous.

### C. Immutable owner in the registered job authority core — selected

Add an optional `execution_owner` field to the registered job. When present, it is included naturally in the existing authority core hash. Missing owner is interpreted as `AUTO_RECONCILE` for backward compatibility.

Selected because it uses the existing immutable run authority rather than adding another authority layer.

## 5. Ownership contract

Allowed values:

- `AUTO_RECONCILE`
- `OCPV2`

A helper resolves the effective owner:

```text
execution_owner present -> validate and return it
execution_owner absent  -> AUTO_RECONCILE
unknown value           -> fail closed
```

The helper must not mutate old job dictionaries merely to insert the default. This preserves the authority digest of already-registered legacy jobs.

For newly created OCP-controlled jobs, `execution_owner: OCPV2` must be present before `register_job()` seals the authority core.

Because `execution_owner` is part of the authority core when supplied, trying to re-register the same project/run with a different owner changes `authority_core_sha256` and is rejected by the existing `RUN_ID_REBIND_FORBIDDEN` rule.

Owner transfer therefore requires a new run / governed migration rather than an in-place flip.

## 6. Execution-path enforcement

### 6.1 Boot / periodic reconciler

`production_full_plan_boot.reconcile_job()` must resolve the job owner before any Full Plan supervisor load, wait recovery, systemd launch, or canonical state mutation.

If owner is not `AUTO_RECONCILE`, return:

```json
{
  "action": "SKIP_EXTERNAL_OWNER",
  "execution_owner": "OCPV2",
  "launched": false
}
```

This owner check must happen early enough that an OCP-owned job cannot be recovered, resumed, wait-recovered, or launched by the background reconciler.

`reconcile_all()` may count these separately for observability, but `SKIP_EXTERNAL_OWNER` is not a blocked/failure condition.

### 6.2 OCPv2 canonical resume

`execute_registered_full_plan_continuation()` must require effective owner `OCPV2` before owner claim or gate execution.

If the job is `AUTO_RECONCILE` (including a legacy job with no field), OCPv2 fails closed before mutation.

### 6.3 Generic Full Plan runner

`production_full_plan_entry.run_job()` is the normal Full Plan execution path and must require `AUTO_RECONCILE`.

An OCPv2-owned job invoked through the generic CLI/systemd runner must fail closed before gate execution. This prevents a human or background path from bypassing the reconciler owner check.

### 6.4 Runtime-link safety

Runtime-link retarget checks must continue to treat every nonterminal registered job as active regardless of owner. Ownership changes who may execute a job, not whether its runtime generation is still in use.

## 7. Job creation

Normal job builders require no change; missing `execution_owner` continues to mean `AUTO_RECONCILE`.

`LiveAutoCanary` should support an explicit owner parameter so it can be used in both contexts:

- normal Full Plan qualification: `AUTO_RECONCILE`
- OCPv2 qualification: `OCPV2`

OCPv2 qualification scripts/tests must explicitly request `OCPV2`; the default remains `AUTO_RECONCILE` to avoid silently changing existing auto-canary behavior.

## 8. Failure semantics

Fail closed on:

- unknown execution owner,
- OCP attempting an `AUTO_RECONCILE` job,
- generic Full Plan runner attempting an `OCPV2` job,
- owner rebind under an existing project/run.

No failure path may fall back from OCPv2 to auto reconciliation or vice versa.

## 9. TDD / verification matrix

RED tests must cover at least:

1. OCPv2-owned READY job -> boot reconciler returns `SKIP_EXTERNAL_OWNER`, `launched=false`, and never calls `systemd-run`.
2. OCPv2-owned WAIT state -> boot reconciler does not perform typed wait recovery or mutate Full Plan state.
3. OCPv2-owned job -> generic `run_job` refuses before gate mutation.
4. AUTO_RECONCILE / legacy ownerless job -> existing boot `WOULD_RESUME` / resume behavior remains unchanged.
5. AUTO_RECONCILE / legacy ownerless job -> OCP canonical resume refuses before owner claim/mutation.
6. OCPv2-owned job -> OCP canonical resume still succeeds with exact state/head/runtime/epoch bindings.
7. Re-register same run with a different owner -> `RUN_ID_REBIND_FORBIDDEN`.
8. Unknown owner -> fail closed.
9. LiveAutoCanary can explicitly produce either owner and OCP qualification uses `OCPV2`.
10. Existing Gate E durable-state and canonical-result/outbox recovery tests remain green.
11. Focused CI, whole-repository regression, and regression-delta all pass.

## 10. Live qualification before Gate F

After code CI is green and the verified HEAD is redeployed to Jarvis in `OBSERVE_ONLY`:

1. Create a fresh `OCPV2`-owned canary job.
2. Keep OCP and Full Plan timers disabled initially.
3. Run the Full Plan reconciler against the fresh job and require `SKIP_EXTERNAL_OWNER`, `launched=false`, zero receipts/artifacts/commits.
4. Arm an exact OCP mutation-canary envelope for the same job.
5. Run OCP and require exactly one CANARY-A mutation through the canonical OCP path.
6. Re-run the Full Plan reconciler and again require `SKIP_EXTERNAL_OWNER`, zero additional mutation.
7. Restore `OBSERVE_ONLY` and keep `ACTIVE` disabled.

Gate F may be considered only after this live single-owner qualification passes. `ACTIVE` remains a separate explicit operational approval.

## 11. Expected files changed during implementation

- `runtime/orchestrator/production_full_plan_entry.py`
- `runtime/orchestrator/production_full_plan_boot.py`
- `runtime/orchestrator/ocpv2_canonical_resume.py`
- `runtime/orchestrator/live_auto_canary.py`
- focused regression tests under `tests/`
- `.github/workflows/ocpv2-r2-ci.yml` only if a new focused test module is introduced

No other execution subsystem should need modification.

## 12. Success criteria

The change is complete only when all of the following are true:

- every registered run resolves to exactly one execution owner,
- OCPv2 and background reconciliation cannot execute the same run,
- legacy normal Full Plan jobs retain their current auto-reconcile behavior,
- owner identity is immutable for the run,
- no new authority is granted to OCPv2,
- all CI gates pass,
- live Jarvis qualification proves `SKIP_EXTERNAL_OWNER` plus successful OCP canonical mutation on the same OCP-owned job,
- `ACTIVE` is still off pending a separate Gate F decision.
