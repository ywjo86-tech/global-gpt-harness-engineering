# Approved Work Execution Link Remediation Design Contract

**Date:** 2026-09-23
**Design ID:** `AWEL-20260923`
**Protocol:** `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` / EDP-1.0
**Pre-remediation diagnosis:** `docs/history/upgrades/2026-09-23-OCP-APPROVED-WORK-EXECUTION-LINK/EDP_PRE_REMEDIATION_DIAGNOSIS.md`
**Parent architecture:** `docs/superpowers/specs/2026-09-23-ocp-observation-gateway-design.md`
**Status:** DESIGN CANDIDATE — authority-artifact boundary amended after Task 3 implementation finding; implementation of the amended boundary requires renewed written-spec review

## 1. Goal and Scope

Repair the missing link between remote activation of already-approved work and the existing executable Full Plan path without granting OCP a new execution authority.

The repaired primary path is:

```text
USER approval
  -> GPT / GitHub private control
  -> OCPv2 typed executable activation
  -> Approved Full Plan Binding Validator
  -> AI Office governance reference
  -> Executable Full Plan Activation Adapter
  -> existing register_job()
  -> AUTO_RECONCILE Full Plan boot/reconcile
  -> existing gate_orchestrator.execute_gate()
  -> Multi-Provider Router / MPRF
  -> production worker / Production Execution Gateway
  -> Full MCP
  -> governed product effect + canonical evidence
```

This design does not redesign Host Inspection, Provider Router, MPRF, Production Gateway, Full MCP, AI Office workflow, Jarvis UI, or existing OCPV2-owned continuation control.

## 2. Root Cause

`APPROVED_WORK_ACTIVATION` V1 currently registers `GPT_OPERATOR_PLAN`. That executor is a durable tracking/receipt bridge: without an external PASS receipt it returns `WAITING_RESOURCE / OPERATOR_TASK_RECEIPT_PENDING`. It is not the normal executable Full Plan path.

The live canary correctly exposed this mismatch. Registration and replay succeeded, but no source mutation occurred. The design error was treating “registered production-full-plan job” and “executable normal Full Plan job” as equivalent even though executor profile and required Gate authority differ.

A second-order diagnosis found that replacing the executor profile alone is also insufficient. Executable Full Plan requires a declarative project mapping, TASK-to-LV projection for modern TASK/STAGE-GATE contracts, exact Gate approval/state authority, requirement evidence, source identity, and a durable mapping-root binding.

## 3. Authority Stack

The repair preserves this order:

1. USER — requirements, approvals, scope expansion, dangerous/high-risk authorization.
2. OCPv2 — authenticated typed remote ingress, replay control, bounded activation registration and result delivery.
3. AI Office — requirement/workflow/governance reference coordination only.
4. Full Plan — planning/Gate/continuation and normal run ownership.
5. Multi-Provider Router / MPRF — provider/model selection and provider runtime.
6. Production Worker / Execution Gateway — governed action handoff.
7. Full MCP — effect authorization, execution, reconciliation and validation evidence.

No lower layer may synthesize authority belonging to a higher layer.

## 4. Frozen MUST Requirements

| ID | Requirement |
|---|---|
| AWEL-MUST-001 | OCP SHALL remain transport/control only and SHALL NOT gain shell, filesystem-write, provider/model, planner, worker, Gateway or Full MCP effect authority. |
| AWEL-MUST-002 | Existing `APPROVED_WORK_ACTIVATION` V1 SHALL retain its current tracking/manual semantics and durable replay meaning. |
| AWEL-MUST-003 | Executable new-work activation SHALL use a new explicit request kind `APPROVED_FULL_PLAN_ACTIVATION` with a closed additive schema. |
| AWEL-MUST-004 | Caller-supplied provider, model, backend, command, argv, environment, editable scope, owned scope or arbitrary absolute paths SHALL be rejected. |
| AWEL-MUST-005 | Project identity SHALL be resolved from the existing immutable Onboarding alias registry and cross-checked against the executable contract mapping. |
| AWEL-MUST-006 | The configured `HARNESS_CONTRACT_MAPPING_ROOT` SHALL be system-derived, safe, canonical, and SHALL NOT be supplied by the remote caller. |
| AWEL-MUST-007 | Executable activation SHALL require an existing `load_project_mapping()` contract whose project, canonical plan path and plan SHA agree with the alias entry and request. |
| AWEL-MUST-008 | A modern TASK/STAGE-GATE plan SHALL require an existing approved `task_lv_authority_projection` with exact SHA; activation SHALL NOT synthesize or mutate the projection. |
| AWEL-MUST-009 | Requested Gate IDs SHALL be unique, explicit and resolvable by `load_gate_plan()`; LV order, owned scope, completion criteria, validation IDs and capabilities SHALL be derived only from canonical Harness contracts. |
| AWEL-MUST-010 | Every executable Gate SHALL carry existing Gate approval evidence accepted by `validate_global_gate_bindings()` and SHALL be executable only while canonical Gate authorization remains valid at runtime. |
| AWEL-MUST-011 | Full Plan approval authority SHALL NOT be synthesized from `approval_ref` or translated from a different approval schema. An opaque user approval ref is provenance only. |
| AWEL-MUST-012 | Requirement evidence SHALL use existing schema dispatch/readers; engine R01-R25 evidence and per-LV project requirement contracts SHALL remain distinct. |
| AWEL-MUST-013 | Expected branch/HEAD and runtime release identity SHALL be exact at binding and SHALL be revalidated by existing execution preflight/runtime checks. |
| AWEL-MUST-014 | The executable job SHALL durably bind the exact safe mapping root used during qualification so transient boot/reconcile resolves the same authority mapping. |
| AWEL-MUST-015 | The new job SHALL be a normal generic `production-full-plan-job.v1`, explicitly owned by `AUTO_RECONCILE`; it SHALL NOT use `GPT_OPERATOR_PLAN` and SHALL NOT introduce a new executor kind. |
| AWEL-MUST-016 | `register_job()` SHALL remain the sole job registration/authority sealing boundary; activation replay SHALL remain create-once and conflicting request reuse SHALL fail closed. |
| AWEL-MUST-017 | `production_full_plan_boot` / generic `run_job()` SHALL own launch and recovery; OCP SHALL NOT spawn the Full Plan worker. |
| AWEL-MUST-018 | State-changing work SHALL flow through existing `execute_gate()` → Router/MPRF → production worker/Gateway → Full MCP only. |
| AWEL-MUST-019 | Existing OCPV2-owned continuation control and Gate-E Remote ACTION helpers SHALL remain separate and SHALL NOT be used to seize an `AUTO_RECONCILE` new-work run. |
| AWEL-MUST-020 | AI Office executable-activation context SHALL bind the executable authority bundle digest while persisting no second approved-requirement source of truth. |
| AWEL-MUST-021 | Executable activation result/receipt SHALL identify its execution profile and authority-bundle digest while reusing the existing OCP durable outbox lifecycle. |
| AWEL-MUST-022 | Missing mapping, projection, Gate approval, requirement evidence, source/runtime binding or executable qualification SHALL return a typed fail-closed result; no auto-bootstrap, Manual Action, arbitrary shell, V1 downgrade or RDC fallback is permitted. |
| AWEL-MUST-023 | The existing failed live canary SHALL remain immutable evidence; no owner/executor rebind under its run ID is allowed. |
| AWEL-MUST-024 | Live acceptance SHALL use a fresh activation/run identity and prove a bounded effect plus validation without RDC before `RDC=OPTIONAL_RECOVERY`. |
| AWEL-MUST-025 | Executable activation SHALL have a separate OFF-by-default feature flag and authorization policy from V1 tracking activation. |

## 5. Alternatives Considered

### A. Selected — additive executable Full Plan activation

Validate existing executable authority, build a generic `AUTO_RECONCILE` production Full Plan job, register it, then let existing boot/reconcile and `execute_gate()` own execution.

This adds only a validation/builder adapter and preserves every downstream authority boundary.

### B. Rejected — make OCP a new-work ACTION executor

Using `execute_remote_action_through_canonical_full_plan()` for all new work would require OCP to acquire/drive continuation authority and resolve canonical WorkerRequests for newly activated plans. The helper remains correct for OCPV2-owned existing continuations, but making it the normal new-work owner would conflict with the explicit `AUTO_RECONCILE` normal-run boundary.

### C. Rejected — extend `GPT_OPERATOR_PLAN` to execute work

This would combine external receipt tracking with task planning/execution, duplicate `gate_orchestrator`, and blur executor ownership. V1 remains a tracking/manual compatibility path.

## 6. Remote Contract

Introduce a distinct request kind:

```text
APPROVED_FULL_PLAN_ACTIVATION
```

with payload schema:

```text
orchestration.approved-full-plan-activation-request.v1
```

Minimum fields:

- `activation_request_id`
- `project_alias`
- committed approved plan path + SHA-256
- committed approved spec path + SHA-256
- `expected_branch` + `expected_head`
- `runtime_release_digest`
- `approval_ref` as user-decision provenance
- ordered `gate_bindings`

Each `gate_binding` contains only authority references and digests, never derived execution scope:

- `gate_id`
- `approval_evidence = {relative_path, sha256}` where `relative_path` is resolved only under the system-derived Harness `approval` namespace
- `engine_requirement_evidence = {relative_path, sha256} | null` resolved only under the system-derived Harness `artifact` namespace
- `project_requirement_evidence_by_lv = [{lv_id, path, sha256}, ...]` where `path` remains a committed project-relative file

The request schema therefore distinguishes Harness authority references from project artifact references. Harness authority refs never accept an absolute path or caller-supplied namespace/root.

The caller cannot provide LV order, owned paths, validation commands, capabilities, provider/model, backend, or mapping root. Those are derived from canonical Harness sources.

Existing `APPROVED_WORK_ACTIVATION` V1 remains valid and unchanged. A caller cannot convert V1 into executable activation by adding a flag or changing `state_change_required`.

## 7. Executable Binding Validation

The new `ApprovedFullPlanBindingValidator` is pure/read-only. It performs:

1. Parse closed request schema and digest.
2. Resolve alias through `OnboardingRegistry(<mapping-root>/aliases)`.
3. Resolve the system-configured safe mapping root; caller cannot override it.
4. Load `load_project_mapping(project_root, mapping_root=<root>)`.
5. Require alias and mapping to agree on project ID/root and canonical plan path/SHA.
6. Require plan/spec and per-LV project requirement contracts to be committed regular project files with exact digests. Require mapping-bound TASK-to-LV projection source/digest through the existing mapping contract.
7. Verify branch/HEAD.
8. For each requested Gate, call `load_gate_plan()` under the exact mapping root.
9. For TASK/STAGE-GATE plans, require mapping-bound `task_lv_authority_projection`; its existing validator derives LV authority.
10. Resolve Gate approval evidence only from the system-derived `namespace_root(harness_state_root, project_id, "approval")`; require a safe namespace-relative path, regular non-symlink file, exact digest, `gate-approval.v1` schema, and exact current source/Gate/LV binding via `validate_global_gate_bindings()`. Activation never creates or relocates this evidence.
11. Resolve engine R01-R25 conformance evidence, when supplied, only from the system-derived `namespace_root(harness_state_root, project_id, "artifact")`; require a safe namespace-relative path, regular non-symlink file, exact digest and existing engine evidence schema. Per-LV project requirement contracts remain committed project files and are validated with the existing project requirement reader.
12. Verify runtime release manifest/root identity.
13. Produce an immutable in-memory `ExecutableAuthorityBundle` and its digest.

The validator performs no onboarding/bootstrap, projection generation, approval creation, requirement creation, job registration, provider routing, filesystem mutation or process launch.

## 8. Full Plan Approval Boundary

The normal executable new-work path intentionally uses the existing normal Full Plan runner identified by the Single Execution Owner contract: `production_full_plan_entry.run_job()` with effective owner `AUTO_RECONCILE`.

For this path, the Gate authority consumed by `execute_gate()` is authoritative. The separate `production-gate-run` / production-approval-v2 path remains authoritative for its GATE_BY_GATE flow; this repair SHALL NOT translate a production-approval-v2 event into `gate-approval.v1` or vice versa.

If a project has only an approval form belonging to another execution path, executable activation fails closed until the appropriate existing Full Plan Gate authority is available. Cross-schema approval synthesis is prohibited.

`approval_ref` carried by remote activation is a provenance reference to the user's decision. It is not executable Gate approval by itself.

## 9. Mapping and TASK-to-LV Projection

Onboarding alias registration and executable mapping are distinct contracts:

```text
alias registry
  = remote project identity / canonical plan reference

contract mapping
  = Harness execution source paths, Gate state/approval source,
    optional TASK-to-LV projection and canonical plan bindings
```

Executable activation requires both and cross-checks them.

For TASK/STAGE-GATE plans:

```text
canonical plan
  + mapping.task_lv_authority_projection path/SHA
  -> validate_task_lv_authority_projection()
  -> resolve_task_lv_projection()
  -> GatePlan/LV authority
```

No OCP-specific parser, editable-scope list or duplicate projection registry is introduced.

## 10. Requirement Evidence

The executable authority bundle classifies requirement artifacts by existing schema **and authority domain**:

- `orchestration.requirement-evidence.v1` → engine/Harness R01-R25 conformance evidence, resolved from the system-derived Harness `artifact` namespace;
- `orchestration.project-requirement-contract.v1` → project/Gate/LV requirement contract, resolved as a committed project-relative file.

For every Gate/LV that requires project requirements, the request supplies only the project-relative artifact reference/digest. The validator derives expected requirement IDs and scope from the canonical plan/projection and validates with the existing reader. Engine conformance evidence is never required to be committed into the product repository.

Unknown schemas, wrong authority domain, missing LV coverage, digest drift or scope mismatch block activation. No requirement or approval artifact is synthesized.

## 11. AI Office Boundary

Add an additive executable activation context, not a mutation of the existing V1 context semantics.

The context binds:

- activation request ID / project / office run identity;
- approved plan/spec and requirement source digests;
- user approval provenance ref;
- expected source HEAD;
- `executable_authority_bundle_digest`;
- ordered Gate IDs;
- workflow snapshot digest.

AI Office still creates only request-local intake approval context from already-validated evidence. It does not persist a new approved-register database, choose Gate/LV scope, select providers, register jobs, launch workers or own effects.

## 12. Executable Full Plan Job Builder

A new narrow builder consumes only the validated executable binding/context and emits the existing generic `orchestration.production-full-plan-job.v1` shape.

Required properties:

```text
execution_owner = AUTO_RECONCILE
executor_kind   = absent (generic existing path)
project_root    = registry/mapping-derived canonical root
harness_state_root = existing Harness durable state root
runtime_code_root  = validated release root
mapping_root       = exact validated system-configured mapping root
run_id             = activation_request_id
expected_branch    = validated branch
```

Each Gate entry is constructed from validated canonical evidence:

- `gate_id`
- exact absolute Gate approval evidence path resolved from the system-derived Harness approval namespace
- `requirements_sha256` derived from validated approval/requirement binding
- exact branch/head
- `full_plan_opt_in=true`
- `project_final_validation=true`
- engine requirement evidence path when applicable
- per-LV project requirement evidence paths when applicable

The job also seals activation provenance (`activation_binding_digest`, executable authority bundle digest, AI Office context digest) into the authority core so registration cannot later refer to different activation evidence.

Before registration, existing `preflight_job()` must return PASS. Registration remains `register_job()` only.

## 13. Registration, Replay and Ownership

Executable activation uses a create-once receipt store keyed by activation request ID + executable binding digest. It may reuse/refactor the existing activation receipt implementation, but it must not create a second independent recovery/outbox state machine.

Rules:

- same request/binding replay → return same sealed registration result;
- same request ID with different binding → `ACTIVATION_REPLAY_CONFLICT`;
- same project/run authority with different owner/executor/evidence → existing `RUN_ID_REBIND_FORBIDDEN`;
- OCP never changes `AUTO_RECONCILE` to `OCPV2` after registration;
- background boot/reconcile owns launch/recovery;
- OCPV2 canonical resume continues to reject this run because it is not OCP-owned.

This is intentional single-owner separation, not a gap.

## 14. Execution Data Flow

```text
Executable activation accepted
  -> generic production-full-plan job registered
  -> initial durable state materialized
  -> production_full_plan_boot discovers AUTO_RECONCILE owner
  -> generic run_job()
  -> build_gate_executor() generic branch
  -> gate_orchestrator.execute_gate(... mode=FULL_PLAN)
  -> canonical GatePlan / GateAuthorization / requirement evidence
  -> provider eligibility + Multi-Provider Router
  -> MPRF/provider runtime binding
  -> canonical production worker authority
  -> execute_production_worker()
  -> Production Execution Gateway / Full MCP
  -> effect + validation/review/checkpoint/handoff evidence
  -> Full Plan Gate exit / continuation
```

OCP participates only before registration and in result delivery/status inspection. It does not call `execute_production_worker`, `dispatch_action_through_production_gateway`, `FullMCPRuntime.call`, a shell, Git mutation, or provider execution for this path.

## 15. Existing OCPV2 Continuation Path

Preserve unchanged:

```text
EXISTING_RUN_CONTROL / RemoteOperatorEnvelopeV2
  -> exact OCPV2-owned registered run
  -> continuation state SHA + owner epoch + source/runtime CAS
  -> execute_registered_full_plan_continuation()
```

`execute_remote_action_through_canonical_full_plan()` remains a valid OCPV2-owned canonical WorkerRequest boundary where its existing contracts apply. It is not repurposed as the normal new-work activation engine.

No failure may fall from the executable activation path into the existing-run path or vice versa.

## 16. Durable Result Contract

Add a typed executable activation projection, for example:

```text
orchestration.remote-full-plan-activation-projection.v1
```

Required result identity includes:

- message ID / activation request ID;
- `activation_profile=AUTO_RECONCILE_FULL_PLAN`;
- executable binding digest;
- executable authority bundle digest;
- canonical job path;
- run ID;
- job authority digest;
- registration status (`FULL_PLAN_REGISTERED` / idempotent equivalent);
- projection digest.

The projection is stored/published through the existing `RemoteResultOutbox` lifecycle. Existing V1 `remote-activation-projection.v1` remains unchanged and cannot satisfy executable-activation acceptance.

## 17. Feature and Mode Gates

Add a separate OFF-by-default gate:

```text
OCP_FULL_PLAN_ACTIVATION_ENABLED=0
```

and an exact policy ref binding dedicated to executable activation.

Mode rules:

| OCP mode | Tracking Activation V1 | Executable Full Plan Activation |
|---|---|---|
| DISABLED | blocked | blocked |
| OBSERVE_ONLY | blocked | blocked |
| CONTROL_READ_ONLY | blocked | blocked |
| CONTROL_MUTATION_CANARY | existing policy only | blocked unless separately qualified executable-activation canary policy exists |
| ACTIVE | existing V1 rule | allowed only with feature flag + exact executable policy + complete canonical authority bundle |

Enabling Host Inspection or V1 activation never enables executable activation.

## 18. Fail-Closed Error Taxonomy

At minimum distinguish:

- `EXECUTABLE_FULL_PLAN_REQUIRED` — required executable contract/mapping/projection absent;
- `EXECUTABLE_MAPPING_MISMATCH` — alias and mapping/canonical plan disagree;
- `EXECUTABLE_GATE_BINDING_MISMATCH` — Gate cannot be resolved from canonical plan;
- `EXECUTABLE_APPROVAL_REQUIRED` — Full Plan Gate authority missing/invalid/expired;
- `EXECUTABLE_REQUIREMENT_BINDING_MISMATCH` — requirement artifact missing/wrong schema/scope/digest;
- `SOURCE_BINDING_MISMATCH`;
- `RUNTIME_RELEASE_MISMATCH`;
- `ACTIVATION_REPLAY_CONFLICT`;
- existing `RUN_ID_REBIND_FORBIDDEN`.

Every error is terminal for that request generation. There is no fallback to GPT_OPERATOR_PLAN, Manual Action, shell, auto-bootstrap or RDC.

## 18A. Authority Artifact Boundary Amendment

Task 3 implementation exposed an impossible self-reference in the earlier wording that required Gate approval evidence to be committed in the same product Git repository whose exact HEAD the approval seals. Committing such an approval changes the HEAD it contains. The canonical `gate-approval.v1` validator intentionally compares the sealed `head` to the execution head, so weakening that check is prohibited.

The corrected authority boundary is:

```text
product repository (Git-committed)
  -> approved plan/spec
  -> TASK-to-LV projection source referenced by mapping
  -> per-LV project requirement contracts

Harness authority state (system-derived, outside product Git)
  -> global-gate/<project_id>/approval/<relative>   # gate-approval.v1
  -> global-gate/<project_id>/artifact/<relative>   # engine R01-R25 evidence
```

Remote callers never supply either namespace root or an absolute host path. The request may supply only a safe relative name plus digest inside the field-implied namespace. The validator derives the roots from `harness_state_root` with the existing `namespace_root()` contract, rejects symlink traversal and missing/non-regular files, verifies the exact digest, then applies the existing schema/scope/HEAD validators. Activation is read-only over these namespaces and SHALL NOT create approval or engine evidence.

This amendment supersedes only prior statements that all authority artifacts are project-committed. It does not relax committed plan/spec/project-requirement evidence, Gate approval HEAD/scope/expiry validation, mapping/projection validation, or the prohibition on caller-supplied absolute paths.

## 19. Old Canary Disposition

`GPT-ACT-20260923-02` remains historical failure evidence:

```text
profile: GPT_OPERATOR_PLAN
state: WAITING_RESOURCE / OPERATOR_TASK_RECEIPT_PENDING
product effect: none
canary.txt: baseline
```

Its job/receipt/state/evidence must not be edited or rebound. A repaired acceptance run uses a fresh activation request/run ID and a newly qualified project contract.

## 20. Acceptance Criteria

| ID | Acceptance criterion |
|---|---|
| AWEL-AC-001 | V1 activation regression remains byte/semantic compatible and produces only tracking-profile registration. |
| AWEL-AC-002 | New executable request rejects caller provider/model/backend/scope/shell fields. |
| AWEL-AC-003 | Alias without executable mapping blocks before job registration. |
| AWEL-AC-004 | TASK/STAGE-GATE plan without approved projection blocks before job registration. |
| AWEL-AC-005 | Mapping/projection/plan/source digest drift blocks before job registration. |
| AWEL-AC-006 | Missing/expired/wrong-scope Gate approval or approval path outside the system-derived Harness approval namespace blocks before job registration. |
| AWEL-AC-007 | Missing/wrong-profile/wrong-authority-domain requirement evidence blocks before job registration. |
| AWEL-AC-008 | Valid executable binding builds one generic `AUTO_RECONCILE` job with exact mapping/runtime/source/Gate authority. |
| AWEL-AC-009 | Replay registers no second job; conflicting request reuse blocks. |
| AWEL-AC-010 | Boot reconciler accepts the valid AUTO_RECONCILE job while OCP canonical resume rejects ownership. |
| AWEL-AC-011 | Generic Gate executor reaches existing Router/MPRF/production worker/Gateway/Full MCP path without OCP direct effect calls. |
| AWEL-AC-012 | AI Office executable context exactly binds the executable authority bundle and introduces no second approval/requirement store. |
| AWEL-AC-013 | Shared outbox recovers executable activation projection without duplicate registration/effect. |
| AWEL-AC-014 | Forbidden-path source audit finds no OCP shell/direct Full MCP/provider selection/new executor owner/duplicate outbox/auto-bootstrap. |
| AWEL-AC-015 | Fresh live no-RDC canary performs one bounded effect plus validation through canonical execution, then feature flags roll back OFF. |
| AWEL-AC-016 | Broad regression and EDP closure pass before RDC is promoted to OPTIONAL_RECOVERY. |

## 21. Test / Failure-Injection Strategy

Implementation planning must include TDD for:

1. request-schema and V1 compatibility;
2. alias↔mapping↔plan identity mismatch;
3. missing/symlinked/drifted mapping and projection;
4. Gate ID/order and derived LV authority mismatch;
5. approval missing/expired/head/scope drift and approval namespace traversal/symlink/wrong-root;
6. engine vs project requirement schema/coverage/authority-domain drift;
7. mapping-root binding surviving transient launch;
8. AUTO_RECONCILE vs OCPV2 ownership separation;
9. crash after `register_job()` but before projection publication;
10. activation receipt/outbox replay;
11. source/runtime drift between binding and execution preflight;
12. Router/Gateway/Full MCP authority negative-space;
13. full repository regression;
14. fresh live no-RDC mutation/validation/rollback acceptance.

## 22. Rollout and Rollback

Rollout sequence:

1. implement with executable feature OFF;
2. qualify focused and full regression;
3. deploy successor with V1/Host Inspection policy unchanged and executable feature OFF;
4. qualify OFF behavior;
5. create a fresh disposable project with pre-existing executable mapping/projection/project requirement contracts plus sealed Harness Gate approval/engine evidence through the normal approved onboarding/governance process;
6. explicitly authorize bounded executable canary;
7. enable only executable canary flag/policy;
8. submit one request, observe one normal Full Plan effect and canonical validation;
9. replay request and prove no duplicate;
10. disable executable activation flag;
11. run post-rollback health/regression and no-RDC evidence audit;
12. only then continue final RDC-independent acceptance.

Rollback is feature-OFF first. Registered canonical Full Plan state is preserved; rollback never rewrites a run owner or deletes evidence.

## 23. Negative-Space Guarantees

This design introduces none of the following:

- new planner;
- new provider/model router;
- new production worker;
- new Execution Gateway;
- new Full MCP runtime;
- new arbitrary shell/process API;
- new OCP filesystem/Git write API;
- new project registry;
- new TASK-to-LV projection semantics;
- new approval schema or approval translation;
- new requirement schema;
- new execution owner;
- second result outbox;
- automatic project bootstrap/onboarding;
- implicit RDC fallback;
- owner rebinding of existing runs.

## 24. Requirement Traceability Matrix

| MUST | Target representation | Planned proof |
|---|---|---|
| AWEL-MUST-001 | §§3,14,23 | OCP negative-space source tests |
| AWEL-MUST-002 | §§5,6,16 | V1 schema/receipt/projection compatibility regression |
| AWEL-MUST-003 | §6 | new request-kind/schema tests |
| AWEL-MUST-004 | §6 | forbidden caller-field tests |
| AWEL-MUST-005 | §7 | alias↔mapping identity tests |
| AWEL-MUST-006 | §7 | caller mapping-root rejection + safe configured-root tests |
| AWEL-MUST-007 | §§7,9 | mapping/canonical-plan path+SHA cross-check tests |
| AWEL-MUST-008 | §§7,9 | missing/drifted TASK-to-LV projection tests |
| AWEL-MUST-009 | §§7,9 | GatePlan-derived LV/scope/capability tests |
| AWEL-MUST-010 | §§7-8 | system-derived Harness approval namespace + Gate approval/global binding/current-state tests |
| AWEL-MUST-011 | §8 | opaque approval-ref and cross-schema translation negative tests |
| AWEL-MUST-012 | §§7,10 | Harness-artifact engine evidence vs committed-project requirement dispatch/domain/coverage tests |
| AWEL-MUST-013 | §§7,12 | source HEAD/runtime release drift tests |
| AWEL-MUST-014 | §§7,12 | mapping-root durable launch/preflight tests |
| AWEL-MUST-015 | §12 | generic job shape + AUTO_RECONCILE owner tests |
| AWEL-MUST-016 | §13 | register_job create-once/run-rebind tests |
| AWEL-MUST-017 | §§13,14 | boot/reconcile launch ownership tests |
| AWEL-MUST-018 | §14 | execute_gate→Router→worker→Gateway/Full MCP integration tests |
| AWEL-MUST-019 | §15 | OCPV2-owner vs AUTO_RECONCILE separation tests |
| AWEL-MUST-020 | §11 | AI Office executable context exact-bundle/negative-space tests |
| AWEL-MUST-021 | §16 | profile-distinct shared-outbox crash/replay tests |
| AWEL-MUST-022 | §18 | fail-closed error/no-fallback matrix |
| AWEL-MUST-023 | §19 | old-canary immutability and owner-rebind rejection evidence |
| AWEL-MUST-024 | §§19,20,22 | fresh live no-RDC mutation/validation/rollback evidence |
| AWEL-MUST-025 | §17 | independent OFF-by-default feature/policy tests |

All 25 MUST requirements have an explicit one-to-one design target and planned proof. No implementation proof is claimed by this design document.

## 25. Supersession of Parent Design

This document supersedes only the parent design statements that assumed executable new-work activation could be built via `build_operator_plan_job()` / `GPT_OPERATOR_PLAN`.

Specifically amended concepts are parent §§8-9, §18B-C, acceptance Gates 5/8, and migration Phases E/F. Host Inspection, existing-run OCPV2 control, authority boundaries, shared outbox principle, Jarvis convergence and RDC break-glass goals remain in force.

The corrected semantic split is:

```text
APPROVED_WORK_ACTIVATION V1
  -> GPT_OPERATOR_PLAN
  -> tracking/manual receipt compatibility only

APPROVED_FULL_PLAN_ACTIVATION
  -> validated executable authority bundle
  -> generic AUTO_RECONCILE production-full-plan job
  -> existing normal Full Plan execution path

EXISTING_RUN_CONTROL
  -> exact OCPV2-owned registered continuation only
```

## 26. Design Closure Boundary

A design EDP PASS means the repaired architecture is internally traceable against available source authority and is ready for implementation-plan authoring after user review.

It does **not** mean:

- executable activation code exists;
- runtime acceptance has passed;
- the current main project is executable under the new contract;
- a TASK-to-LV projection or Gate approval has been created;
- a live mutation has occurred;
- RDC is already optional.

Those claims remain blocked by implementation and fresh live evidence.
