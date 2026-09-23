# Approved Work Execution Link — EDP Pre-Remediation Diagnosis

**Date:** 2026-09-23
**Protocol:** `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` / EDP-1.0
**Protocol SHA-256:** `7a74df80220143f3b5aaad9d7d67285f955156b95df885690b52fec76d427baf`
**Target:** Approved Work Activation → executable Full Plan connection in `docs/superpowers/specs/2026-09-23-ocp-observation-gateway-design.md`
**Target pre-remediation SHA-256:** `0611c4566bec661984cd369a0ae2ae168acb78109a0f5a34f99f63eb30f663df`
**Verified source HEAD:** `14656be825714177615400380b35510ad56a3e47`
**Decision:** `REVISION_REQUIRED`

## Decision Boundary

This diagnosis evaluates the architecture/design contract and the current source interfaces needed to connect an already-approved remote work activation to the existing canonical Full Plan execution path. It does not authorize implementation, live feature enablement, runtime mutation, a new canary, merge, or push.

The prior Host Inspection implementation is outside the defect except where final RDC-independence depends on successful state-changing execution.

## Canonical Source Register

Authority precedence for this run:

1. Current user goal: make OCP + Harness the normal GPT local-work path and reduce RDC to optional recovery only after real no-RDC execution proof.
2. Approved OCPv2 invariants in `2026-09-21-operator-control-plane-v2-r2-approved.md`.
3. Single-execution-owner design in `2026-09-22-ocpv2-single-execution-owner-design.md`.
4. Verified current source at HEAD `14656be`.
5. Existing top-down design SHA `0611c456...` as the target claim under diagnosis.
6. Live canary evidence already recorded in the acceptance ledger; it is evidence, not authority.

## Frozen Material Obligations

| ID | Obligation |
|---|---|
| AWEL-O-001 | OCP remains transport/control and gains no planner, provider, shell, filesystem-write, or Full MCP effect authority. |
| AWEL-O-002 | New approved work must reach the existing normal `AUTO_RECONCILE` Full Plan path without RDC. |
| AWEL-O-003 | Existing OCPV2-owned continuation control remains separate and single-owner. |
| AWEL-O-004 | New work may execute only from canonical committed plan, exact source/runtime identity, and explicit approval evidence. |
| AWEL-O-005 | TASK/Gate/LV execution authority must come from existing Harness mapping/projection contracts, not caller text or OCP synthesis. |
| AWEL-O-006 | Gate approval, requirement evidence, owned scope, validation and provider capability authority must reuse existing canonical contracts. |
| AWEL-O-007 | Activation registration must remain create-once/replay-safe and use existing `register_job()` authority sealing. |
| AWEL-O-008 | Boot/reconcile owns launch/recovery for normal new work; OCP must not spawn workers. |
| AWEL-O-009 | Actual mutation must remain Full Plan → Router/MPRF → Production Worker/Gateway → Full MCP. |
| AWEL-O-010 | V1 activation and existing durable receipts cannot silently change semantic meaning. |
| AWEL-O-011 | Missing executable mapping/projection/approval evidence fails closed; no auto-bootstrap, Manual Action, shell, or RDC fallback. |
| AWEL-O-012 | Old live canary is immutable failure evidence and cannot be authority-rebound. |
| AWEL-O-013 | AI Office may carry governance refs but cannot become a second execution/requirement authority. |
| AWEL-O-014 | Existing shared OCP result outbox is reused; no second delivery lifecycle. |
| AWEL-O-015 | Final RDC=OPTIONAL_RECOVERY promotion requires a fresh, distinct, no-RDC mutation canary after implementation. |

## Primary Findings

| Finding | Severity | Status | Problem | Evidence / impact |
|---|---|---|---|---|
| AWEL-F-001 | MAJOR | OPEN | The design assumes `build_operator_plan_job()` produces executable new-work Full Plan authority. | Source sets `executor_kind=GPT_OPERATOR_PLAN`; its executor only loads external PASS receipts and otherwise returns `OPERATOR_TASK_RECEIPT_PENDING`. Live canary stopped exactly there. |
| AWEL-F-002 | MAJOR | OPEN | Activation V1 treats Markdown `Task` headings as executable Gate IDs. | `_approved_task_ids()` only regex-parses headings; it does not derive canonical Gate/LV authority. |
| AWEL-F-003 | MAJOR | OPEN | Alias registration is treated as sufficient executable project authority. | `OnboardingRegistry` binds alias/plan only; `load_gate_plan()` separately requires `load_project_mapping()`. Live onboarding root contains aliases only and canary is blocked with `project declarative mapping is required`. |
| AWEL-F-004 | MAJOR | OPEN | Opaque `approval_ref` is treated as enough to activate executable work. | `execute_gate()` requires `validate_global_gate_bindings()` and active canonical Gate authorization; `gate-approval.v1` binds Gate, plan, source, LV order and owned files. |
| AWEL-F-005 | MAJOR | OPEN | The current single requirement artifact is insufficient to express all executable requirement scopes. | `execute_gate()` distinguishes engine conformance evidence and per-LV project requirement contracts; activation V1 validates only one engine R01-R25 artifact. |
| AWEL-F-006 | MAJOR | OPEN | Runtime-launched Full Plan can lose mapping identity. | `run_job()` uses a job-bound `mapping_root` when present; OCP process environment is not authority for the later transient worker. Activation jobs currently omit it. |
| AWEL-F-007 | MAJOR | OPEN | Reinterpreting Activation V1 in place would change durable/replay semantics. | V1 already has create-once receipts and `REGISTERED` projections for receipt-tracking jobs. Same schema cannot safely mean a different executor profile after upgrade. |
| AWEL-F-008 | MAJOR | OPEN | Activation result does not distinguish tracking registration from executable Full Plan registration. | Existing projection reports `REGISTERED` without an execution profile, enabling a false acceptance interpretation. |
| AWEL-F-009 | MAJOR | OPEN | AI Office activation context does not bind an executable Gate authority bundle. | Context binds plan/spec/requirement digest/approval ref/head, but no Gate sequence, mapping/projection or Gate approval bundle digest. |
| AWEL-F-010 | MAJOR | OPEN | Final acceptance assumed activation could flow directly into governed mutation. | The live canary proved registration/replay but `canary.txt` remained `baseline`; no Gateway/Full MCP effect occurred. |

## Focused Baseline Evidence

Focused source regression executed before correction:

```text
python3 -m unittest \
  tests.test_approved_work_binding tests.test_plan_activation \
  tests.test_ocpv2_approved_work_activation_integration \
  tests.test_ocpv2_gate_e_canonical_path tests.test_task_contract_compat \
  tests.test_production_full_plan_entry tests.test_ocpv2_single_execution_owner -v

Ran 66 tests in 3.182s
OK
```

This is an important adversarial fact: green existing tests do **not** prove the missing new-work execution link. The tests validate their current contracts, including the receipt-tracking semantics that caused the live acceptance stall.

## Negative-Space Audit

Missing material elements in the pre-remediation design:

- no executable project mapping requirement;
- no TASK-to-LV projection requirement for TASK/STAGE-GATE plans;
- no exact Gate approval artifact/canonical state binding;
- no multi-scope requirement-artifact binding;
- no durable mapping-root binding in the new job;
- no semantic distinction between tracking activation and executable activation;
- no AI Office executable-authority-bundle digest;
- no explicit fail-closed disposition when any executable authority artifact is absent;
- no requirement to restart final live acceptance with a fresh run identity.

## Cross-Document Audit

- OCPv2 R2 says state changes remain through Production Gateway / Full MCP: pre-remediation design intent agrees, implementation connection does not reach it.
- Single Execution Owner says `production_full_plan_entry.run_job()` is the normal `AUTO_RECONCILE` Full Plan path: this is the correct new-work execution owner.
- The same document requires OCP canonical resume to reject `AUTO_RECONCILE`: therefore new approved work must not be forced into the OCPV2-owned continuation path.
- `task_contract_compat` explicitly fails closed without an approved TASK-to-LV projection: activation cannot synthesize one.
- `register_job()` forbids run authority rebind: the old canary cannot be converted into the repaired profile.

## Adversarial Second Pass

Counterexample searches changed the initial repair conclusion:

1. “Just replace `GPT_OPERATOR_PLAN` with generic Full Plan” is insufficient because the live project lacks executable mapping/projection authority.
2. “Use the existing OCP Gate-E remote ACTION helper for all new work” would move normal new-work execution toward OCP-owned continuation semantics and conflict with the `AUTO_RECONCILE` owner boundary.
3. “Treat `approval_ref` as approval evidence” fails because it lacks Gate/LV/source/scope/time bindings required by the execution path.
4. “Reuse the old canary after changing its owner” is prohibited by immutable run authority and `RUN_ID_REBIND_FORBIDDEN`.

`ADVERSARIAL_NEW_BLOCKER_MAJOR=3` at the pre-remediation stage (F-003/F-004/F-007 were surfaced or strengthened by the second pass).

## Pre-Remediation Metrics

```text
BLOCKER_COUNT=0
UNRESOLVED_MAJOR_COUNT=10
UNRESOLVED_MINOR_COUNT=0
MUST_REQUIREMENT_COVERAGE=100%
MUST_TRACEABILITY_COVERAGE=0%
DOMAIN_EVIDENCE_COVERAGE=100%
NEGATIVE_SPACE_OPEN_MATERIAL_COUNT=9
CROSS_DOCUMENT_CONFLICT_COUNT=3
BROKEN_REFERENCE_COUNT=0
UNRESOLVED_MATERIAL_TBD_COUNT=0
UNRESOLVED_MATERIAL_OPEN_QUESTION_COUNT=0
ADVERSARIAL_NEW_BLOCKER_MAJOR=3
PASS_CHALLENGE_OPEN_COUNT=10
SOURCE_AUTHORITY_STATUS=AVAILABLE_AND_VALID
REGRESSION_REDIAGNOSIS_STATUS=NOT_YET_RUN
MATERIAL_DEFECT_SEARCH=NOT_EXHAUSTED
```

## Pre-Remediation Decision

`REVISION_REQUIRED`

The architecture must be corrected before implementation planning resumes. The corrected design must preserve Activation V1 as tracking/manual semantics, introduce an additive executable activation contract, bind existing mapping/projection/Gate-approval/requirement authority, register only a normal `AUTO_RECONCILE` Full Plan job, and require a fresh live acceptance run.
