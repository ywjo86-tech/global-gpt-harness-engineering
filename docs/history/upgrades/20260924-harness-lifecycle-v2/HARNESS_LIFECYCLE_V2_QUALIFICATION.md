# Harness Lifecycle V2 — Compatibility Qualification

Date: 2026-09-25
Status: SUCCESSOR_QUALIFIED / ACTIVE_PROJECT_MIGRATION_NOT_PERFORMED
Scope: Harness Lifecycle V2 compatibility successor only

## Purpose

Close the approved-plan-to-durable-execution lifecycle gap while preserving the semantics and stored authority of every pre-existing project run.

This qualification does **not** promote the successor to `runtime-current`, rewrite an existing registered job, or migrate an in-flight project. Production Execution Gateway / Full MCP remain the canonical effect path; OCPv2 remains normal ingress; RDC remains break-glass only.

## Qualified behavior

The successor proves the following closed loop for new Full Plan activations:

1. approved Full Plan activation materializes a Lifecycle V2 binding and execution-authority bundle;
2. operator dispatch is durable and create-once;
3. dispatch ACK is represented as a distinct wait state;
4. receipt evidence is bound to the acknowledged dispatch;
5. DCC continuation becomes eligible only after sealed receipt evidence;
6. continuation resumes the exact waiting state generation through the existing CAS path;
7. Provider Router / Production Execution Gateway / Full MCP authority boundaries are unchanged.

Existing jobs with no lifecycle binding continue to resolve as `LEGACY` and are never rewritten because V2-capable code is present.

## Eight-project non-migration matrix

| Project / track | Qualification result | Migration performed? | Preserved boundary |
| --- | --- | --- | --- |
| AI Office Harness Upgrade | PASS | No | Existing activation/run/receipt/runtime pin remain unchanged; successor compatibility canary only. |
| AI Commerce Intelligence | PASS at compatibility/onboarding boundary | No active-run rewrite | Create-once project onboarding recovery is separately admitted; new activation may use V2 after normal authority validation. |
| System Financial Trading Office | PASS | No Tasks 1–9 rerun | Existing prefix-adoption evidence permits Task 10-only successor activation; prefix evidence drift is blocked preflight. |
| OCP Upgrade / global harness engineering | PASS | No runtime-current switch | Successor remains side-by-side and exact-head release qualified. |
| JARVIS / Dashboard | PASS | No authority transfer | JARVIS/Dashboard remain interaction/read-model clients; Harness/OCP/Gateway authority is not absorbed. |
| Ruflo / JEV | PASS after qualification-log repair | No live external activation | RJI boundaries remain advisory; full RJI EDP and canonical regressions pass. |
| Family AI English | PASS | No legacy Task/LV migration | Existing `task_lv_authority_projection` remains read-only LEGACY input and is not rewritten. |
| Legacy / other registered Full Plan runs | PASS | No | Missing lifecycle binding remains LEGACY; registered authority core remains immutable. |

## Authority negative-space evidence

Lifecycle V2 does **not** create, infer, or absorb any of the following authority:

- user approval authority;
- provider or model selection authority;
- final assignee authority;
- completion authority;
- direct side-effect authority;
- Production Execution Gateway / Full MCP authority;
- OCP transport authority beyond its existing admission role.

The registered Full Plan authority seal covers `lifecycle_binding` and `execution_authority_bundle`. Tampering either field after sealing produces `RUN_AUTHORITY_DRIFT`. Only the pre-existing declared runtime gate overlay fields remain outside the immutable authority core.

## Project onboarding authority boundary

The remotely supplied onboarding request cannot choose an arbitrary registry/mapping root in deployed OCP composition.

- deployed `_compose_service()` binds `ProjectOnboardingAdmission` to the validated `HARNESS_CONTRACT_MAPPING_ROOT`;
- a request whose `mapping_root` differs from that configured canonical root fails closed;
- isolated/unit callers retain backward-compatible optional binding behavior;
- project onboarding remains separately feature-gated and grants no Full Plan execution, provider/model, Gateway, Full MCP, or completion authority.

This hardening was required by the final full-branch review before qualification.

## Rollback / default-disable evidence

New Full Plan activations default to Lifecycle V2 only at the **new activation construction/composition seam**.

- `GCH_NEW_ACTIVATION_LIFECYCLE_MODE=V2` is the deployed service default.
- An explicit `GCH_NEW_ACTIVATION_LIFECYCLE_MODE=LEGACY` value provides `NEW_ACTIVATION_DEFAULT_DISABLE` rollback for future new activations.
- Any other value fails closed with `NEW_ACTIVATION_LIFECYCLE_MODE_INVALID`.
- Existing registered jobs are not reinterpreted by this environment setting.
- Existing jobs without a V2 binding continue to resolve as LEGACY.

Project onboarding remains separately feature-gated and fail-closed; adding Lifecycle V2 does not implicitly enable onboarding or activation mutation authority.

## Gate qualification summary

- Gate 4 canaries: PASS — Legacy preservation, existing-run preservation, three-task V2 closed loop with restart/no duplicate dispatch.
- AI Commerce onboarding recovery seam: PASS — canonical onboarding registry reused; no HOST_INSPECTION mutation expansion.
- SFT Task 10 compatibility: PASS — Tasks 1–9 may be adopted as validated prefix evidence without rerun.
- AI Office non-migration canary: PASS.
- Family AI English legacy projection canary: PASS.
- Ruflo/JEV requalification: PASS after repairing approval-log parsing boundary; RJI focused/full EDP/full regression/delta green.
- JARVIS compatibility qualification: PASS.
- Gate 11 successor qualification: PASS.
- Gate 12 new-activation default V2: PASS.
- Gate 13 immutable lifecycle authority seal: PASS.
- Gate 14 exact-head successor runtime release qualification: PASS.
- Gate 15 deployed default/explicit rollback wiring: PASS after fixing the OCP composition seam.
- Gate 16 final compatibility qualification: PASS after final onboarding canonical mapping-root authority hardening and test-fixture correction.

## G16 behavior baseline evidence

PR: `#15 Harness Lifecycle V2 compatibility bridge`

G16 behavior baseline implementation commit: `68b376c3fd6884359f185ca4f276a1e214280918`

G16 baseline GitHub Actions run: `36095889124`

- `focused`: PASS
- `successor-release-qualification`: PASS
- `full-regression`: PASS — `FULL_REGRESSION_SUMMARY run=2392 failures=0 errors=0 skipped=14`
- `regression-delta`: PASS

These identifiers are immutable evidence for the G16 behavior baseline; they are **not** a claim that this branch-resident document names the current PR head.

The focused suite includes Lifecycle V2 G11–G15 coverage, AI Office and Family compatibility canaries, SFT prefix activation bridge, project onboarding remote/envelope/service/runtime/deploy-default checks, OCP transport/authority boundary tests, runtime migration handoff tests, Production Execution Gateway tests, and Full MCP boundary lint. The successor-release job checks out the exact PR head, builds/verifies the immutable runtime release, and confirms the qualification checkout remains clean.

## P0 promotion-readiness interruption record

Detected: 2026-09-25 during Production Promotion Readiness.

Observed state:

- PR #15 had advanced beyond the G16 baseline because completion-record documentation was committed after the baseline qualification.
- The durable qualification/plan text still described `68b376c3fd6884359f185ca4f276a1e214280918` / `36095889124` as the final branch head/run even though later documentation commits had changed the PR head.
- Runtime authority, Legacy preservation, Gateway / Full MCP effect authority, and the rollback seam were not implicated.

Root cause:

A branch-resident mutable document attempted to carry a self-referential "final current HEAD" identity. Any commit that updates that document necessarily creates a new HEAD, so the embedded identity becomes stale by construction.

Resolution:

1. Treat `68b376c3fd6884359f185ca4f276a1e214280918` / `36095889124` as the immutable G16 behavior baseline only.
2. Do not embed the eventual promotion-candidate exact HEAD in a mutable file on that same branch.
3. After this ledger repair lands, run fresh exact-head CI on the resulting PR head.
4. Seal the resulting exact promotion-candidate HEAD + CI run externally on PR #15 after all required jobs pass.
5. Keep merge, side-by-side production deployment, canary traffic, `runtime-current` switching, and existing-run migration outside this P0 repair.

This removes the self-reference loop while preserving a durable root-cause and recovery record.

## Promotion boundary

This document qualifies the successor implementation only. The following are **not performed by this PR** and remain separate controlled rollout steps under normal OCP authority:

1. merge/integration into the selected stable OCP successor branch;
2. build of the final runtime release from that post-integration exact source head;
3. side-by-side deploy / canary;
4. `runtime-current` switch after active-runtime qualification;
5. any explicit migration of an already registered project run.

The existing runtime migration handoff invariants remain the governing mechanism for a future controlled rollout. No new promotion request kind/control plane is introduced by this implementation slice, and no RDC path is required for normal promotion.
