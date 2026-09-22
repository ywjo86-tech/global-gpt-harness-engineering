# OCPv2 Durable Initial State Publication Design

Date: 2026-09-22
Status: Design approved for remediation planning
Scope: Gate E live canary blocker only

## Problem

Gate E live canary exposed two independent races around a freshly registered Full Plan job.

1. The periodic Full Plan reconciler can discover and launch a registered nonterminal job before OCP acquires the intended exact-scope continuation authority.
2. A freshly registered job has no durable `state.json`. `DurableFullPlanSupervisor.load()` therefore synthesizes `_initial()` in memory. `_initial()` contains current timestamps, so repeated calls produce different `state_sha256` values. An OCP envelope bound to the first transient SHA later fails closed with `STALE_DIRECTIVE: Full Plan state mismatch` when OCP synthesizes a second initial state.

The second defect means a fresh registered job cannot safely participate in an external CAS contract until its initial Full Plan state has been persisted durably.

## Goal

Make the first externally observable generation of a registered Full Plan job deterministic and durable before the job becomes discoverable by background reconciliation or OCP.

After registration returns successfully:

- a canonical `state.json` exists;
- repeated loads return the same initial `state_sha256` until a real state transition occurs;
- no Gate executor has run;
- the job is discoverable only after the initial state is durable;
- OCP and the periodic reconciler observe the same initial state generation;
- existing immutable job authority and run-ID rebind protections remain unchanged.

## Non-goals

- Do not alter Provider Router behavior.
- Do not alter Production Execution Gateway or Full MCP semantics.
- Do not grant OCP job-registration authority.
- Do not authorize `ACTIVE` mode.
- Do not change Gate execution semantics, retry policy, or migration behavior except where required to preserve the registration/publication boundary.

## Selected Architecture

Use a two-phase registration/publication boundary inside the existing Full Plan entry layer.

### Phase 1: Prepare immutable job authority and durable initial state

A new internal registration helper prepares the sealed job authority in a non-discoverable staging location under the same state root. It validates the same authority core and runtime bindings used by the current `register_job()` path.

Before the canonical registered-job path is published, create a `DurableFullPlanSupervisor` from the sealed job and materialize exactly one initial state generation to the canonical Full Plan state location.

Materialization rules:

- Acquire the existing Full Plan run lock.
- If `state.json` or a valid previous generation already exists, load and validate it; do not regenerate initial state.
- If no state generation exists, call `_initial()` once and persist it durably with a dedicated non-execution event such as `INITIAL_STATE_MATERIALIZED`.
- Do not call `build_gate_executor()`, `_run_locked()`, Gate preflight, Provider Router, shell, Full MCP, or any worker path.
- Return the persisted state including its fixed `state_sha256`.

### Phase 2: Atomic job publication

Only after the durable initial state is confirmed should the sealed job become visible at the canonical discovery path:

`_workspace/production-full-plan-jobs/<project>/<run>.job.json`

Publish using the existing atomic JSON write mechanism so the reconciler can observe either no job or a complete registered job, never a partially written job.

Because `state.json` already exists before canonical job publication, any reconciler or OCP consumer that discovers the job receives the same persisted state generation and SHA.

## Existing Job / Idempotency Semantics

If the canonical job already exists:

- Preserve the existing `RUN_ID_REBIND_FORBIDDEN` authority-core comparison.
- Load and validate the existing durable Full Plan state.
- Do not replace or regenerate state timestamps.
- Repeated registration of the same authority core is idempotent and returns the same job path/state SHA.
- If the job exists but no durable state exists, fail closed rather than silently synthesizing a new externally bindable generation. This condition indicates a legacy/incomplete publication and requires explicit recovery logic or remediation.

This avoids converting a historical partially published job into a new CAS generation without an audit trail.

## API Boundary

Keep `register_job(job)` as the public registration API for existing callers.

Internally it should delegate to focused helpers, for example:

- `_prepare_sealed_job(job)` — authority validation/sealing and runtime binding checks.
- `_materialize_initial_full_plan_state(sealed_job)` — lock-protected, non-executing durable initialization.
- `_publish_registered_job(sealed_job)` — canonical atomic publication.

Exact helper names are implementation details; the behavioral contract is normative.

Where a caller needs the initial state SHA for an OCP envelope, provide a read-only helper that loads the already durable state after registration rather than recomputing `_initial()`.

## Data Flow

Fresh registration:

1. Validate input job.
2. Seal immutable authority core.
3. Validate canonical target path and run-ID uniqueness.
4. Materialize durable initial Full Plan state under the existing run lock.
5. Verify persisted state identity: project, run, gates, authority core, `READY`, first Gate, one READY queue item, no continuation owner.
6. Atomically publish sealed job to canonical discovery path.
7. Bind runtime/manual-action metadata using the existing binding mechanism.
8. Return canonical job path.
9. OCP envelope construction reads the persisted state SHA.

Consumer path:

1. Reconciler/OCP discovers canonical job.
2. `supervisor.load()` reads existing durable state.
3. CAS comparison uses the stable persisted SHA.
4. Canonical continuation claim/execution proceeds under the existing run lock.

## Failure Handling

The registration transaction must fail closed.

- Initial state persistence failure: do not publish canonical job.
- Authority mismatch: do not modify existing job or state.
- State identity/digest validation failure: do not publish/re-publish job.
- Canonical publish failure after successful state materialization: leave the nonterminal state undiscoverable by the job scanner; retrying identical registration must safely reuse the same durable state.
- Existing canonical job with missing state: block with an explicit error rather than generating a new transient state.

No cleanup path may delete a valid durable state automatically merely because canonical job publication failed; that state is evidence needed for deterministic retry/reconciliation.

## Reconciler Interaction

No change is required to the normal reconciler execution semantics if publication ordering is fixed: it cannot see the fresh job until its durable initial state exists.

Add a regression test that introduces an observation hook between state materialization and job publication and proves the canonical job path is absent during that interval.

## OCP Interaction

OCP remains non-authoritative and may resume only an already registered immutable job.

The Gate E canary preparation flow must stop deriving `canonical_run_state_sha256` from an in-memory `supervisor.load()` when no state file exists. It must instead require the durable state produced by registration and bind the envelope to that persisted SHA.

The existing OCP fail-closed checks for state SHA, owner epoch, source HEAD, runtime release digest, task identity, and Gate identity remain unchanged.

## Tests

### New failing regression tests first

1. `fresh registration persists initial state before returning`
   - register a fresh job;
   - assert canonical state file exists;
   - assert state is `READY`;
   - assert no Gate executor/worker is called.

2. `initial state SHA is stable across time`
   - register job;
   - capture persisted SHA;
   - advance/mock time;
   - instantiate a new supervisor and load;
   - assert identical SHA.

3. `job is not discoverable before initial state durability`
   - instrument publication boundary;
   - assert canonical job path does not exist before state persistence completes.

4. `identical re-registration is idempotent`
   - register the same sealed authority again;
   - assert same state SHA and no new initialization event/state generation.

5. `existing job with missing durable state fails closed`
   - construct legacy/incomplete canonical job without state;
   - assert explicit registration/resume block.

6. `real OCP registered-resume test uses DurableFullPlanSupervisor`
   - remove reliance on only `FakeSupervisor` for the fresh-state CAS case;
   - bind envelope to persisted initial SHA;
   - execute registered continuation;
   - prove owner claim occurs once and state SHA precondition passes.

7. `background reconciliation cannot launch before state publication`
   - scanner sees no canonical job before materialization/publication completes.

### Existing suites

Run at minimum:

- `tests/test_production_full_plan_boot.py`
- `tests/test_ocpv2_registered_full_plan_resume.py`
- `tests/test_ocpv2_gate_e_canonical_path.py`
- `tests/test_ocpv2_runtime_service.py`
- `tests/test_remote_operator_recovery.py`
- `tests/test_ocpv2_replay_churn.py`
- OCPv2 focused CI script
- full regression
- regression-delta

## Gate E Requalification Criteria

After code deployment, use a brand-new disposable Run ID and new envelope sequence.

Gate E PASS still requires all of the following:

1. exactly one canonical mutation through OCP;
2. effect evidence chain present;
3. duplicate delivery produces zero additional mutations;
4. outbox retry produces zero additional mutations;
5. rollback/cleanup path verified;
6. no CANARY-B/C mutation in the one-mutation qualification;
7. periodic reconciler can be restored without creating an additional effect;
8. `ACTIVE` remains disabled until a separate production activation decision.

## Safety Invariants

- OCP does not register jobs.
- Full Plan remains the canonical continuation authority.
- Existing run lock remains the single-writer boundary.
- No provider/model hardcoding is introduced.
- No external effect is added to the disposable canary authority profile.
- Failed or ambiguous CAS continues to block rather than retry a mutation.
- No automatic transition to `ACTIVE`.
