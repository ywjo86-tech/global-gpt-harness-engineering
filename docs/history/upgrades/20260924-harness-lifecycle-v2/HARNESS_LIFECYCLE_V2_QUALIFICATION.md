# Harness Lifecycle V2 — Compatibility Qualification

Date: 2026-09-25
Status: SUCCESSOR_QUALIFIED / ACTIVE_PROJECT_MIGRATION_NOT_PERFORMED
Scope: Harness Lifecycle V2 compatibility successor only

## Purpose

Close the approved-plan-to-durable-execution lifecycle gap while preserving the semantics and stored authority of every pre-existing project run.

This qualification does **not** promote the successor to `runtime-current`, rewrite an existing registered job, or migrate an in-flight project. Production Execution Gateway / Full MCP remain the canonical effect path; OCPv2 remains normal ingress; RDC remains break-glass only.

## Qualified behavior

The successor now proves the following closed loop for new Full Plan activations:

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

## Rollback / default-disable evidence

New Full Plan activations default to Lifecycle V2 only at the **new activation construction seam**.

- `GCH_NEW_ACTIVATION_LIFECYCLE_MODE=V2` is the deployed service default.
- An explicit `GCH_NEW_ACTIVATION_LIFECYCLE_MODE=LEGACY` value provides the rollback seam for future new activations.
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

## Final CI evidence before this qualification record

PR: `#15 Harness Lifecycle V2 compatibility bridge`

Pre-document qualified implementation head: `c279600c28a307a4a3981b4bb66d709d23950bb3`

GitHub Actions run: `36094778582`

- `focused`: PASS
- `successor-release-qualification`: PASS
- `full-regression`: PASS
- `regression-delta`: PASS

The successor-release job checked out the exact PR head, built and verified a `gch.runtime-release.v2` release, and confirmed the qualification checkout remained clean.

## Promotion boundary

This document qualifies the successor implementation only. The following are **not performed by this PR** and remain separate controlled rollout steps:

1. merge/integration into the selected stable OCP successor branch;
2. build of the final runtime release from that post-integration exact source head;
3. side-by-side deploy / canary under normal OCP authority;
4. `runtime-current` switch after active-runtime qualification;
5. any explicit migration of an already registered project run.

No RDC path is required for normal promotion.
