# Durable Continuation Controller — EDP Pre-Execution Orchestration Re-Diagnosis

**Date:** 2026-09-21  
**Protocol:** `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` / EDP-1.0  
**Stable operational baseline:** `a40626c31353f90c0d4c9e677d3886ea5ccce393`  
**Reviewed design/plan HEAD:** `1bf75bc4f75fd49790be948be78a5d93304daca4`  
**Target Spec:** `docs/superpowers/specs/2026-09-20-durable-continuation-controller-design.md`  
**Target Plan:** `docs/superpowers/plans/2026-09-21-durable-continuation-controller.md`  
**Scope:** Full Plan orchestration operational readiness before implementation execution approval.

## Decision

`EDP_DECISION=NOT_ALL_PASS`

Implementation execution MUST NOT start from the current Plan revision. The current Harness baseline is healthy, but the Plan contains execution-blocking runtime binding and approved-Spec fidelity defects. The previous pre-implementation-plan `ALL_PASS` remains historical evidence for the earlier design review but is superseded for execution-readiness by this re-diagnosis.

## Fresh Baseline Evidence

- Focused authority/continuity/migration/attention regression: `131/131 PASS`.
- Full repository regression: `1887 tests PASS`, `15 skipped`.
- `python3 -m compileall -q runtime tests`: PASS.
- `git diff --check`: PASS.
- CodeGraph advisory index: 471 files, 9004 nodes, >20k edges; reviewed branch itself is docs-only relative to baseline.
- Direct temporary-repository reproduction was used for executor-runtime drift because that operational coupling is not visible from a docs-only PR risk summary.

## Findings

### DCC-ORCH-F001 — BLOCKER — Implementation Job self-mutates its sealed executor runtime

**Plan evidence:** Task 0 registers the implementation Job with `project_root=root`, `harness_root=root`, and `runtime_code_root=root`. Task 1 then modifies and commits `runtime/orchestrator/operator_plan_execution.py`, `production_full_plan_entry.py`, and `production_run_authority.py`.

**Current runtime invariant:** `executor_runtime_identity()` seals runtime root, Git HEAD, branch, common Git identity, and a digest of the entire `runtime/` tree. `preflight_job()` calls `validate_executor_runtime()` and blocks on runtime source or generation drift.

**Fresh reproduction:** an R1-shaped sealed Job initially returned `PASS`; an uncommitted runtime edit returned `EXECUTOR_RUNTIME_SOURCE_DRIFT`; after committing the runtime edit the same sealed Job returned `EXECUTOR_GENERATION_DRIFT`.

**Impact:** the implementation Full Plan cannot reliably advance beyond the first Task that changes runtime code.

**Required remediation:** decouple execution runtime from the mutating implementation worktree. Bind `runtime_code_root` to an exact immutable known-good release (validated against stable baseline `a40626c...`) while `project_root` remains the implementation worktree. Add a Task-0 RED/preflight test proving multiple local implementation commits do not change executor runtime identity.

### DCC-ORCH-F002 — BLOCKER — Approved Spec contract schema is weakened by the implementation Plan

The approved Spec requires the `GateContinuationContract` minimum schema to contain:

`schema_version`, `gate_id`, `continuation_policy`, `approved_base_head`, `source_lineage_policy`, `allowed_write_paths`, `forbidden_paths`, `required_verifiers`, `required_evidence_classes`, `commit_policy`, `risk_classes`, `approval_coverage_ref`, `approval_coverage_digest`, `external_effect_policy`, `runtime_migration_policy`.

Task 1 of the Plan instead defines a minimum set containing:

`schema_version`, `mode`, `allowed_write_paths`, `forbidden_paths`, `required_verifier_ids`, `commit_policy`, `risk_classes`, `approval_coverage_digest`, `source_lineage_policy`, `continuation_contract_sha256`.

Material Spec fields are therefore absent from the planned authority object, including `gate_id`, `approved_base_head`, `required_evidence_classes`, `approval_coverage_ref`, `external_effect_policy`, and `runtime_migration_policy`. The Plan also changes the serialized names `continuation_policy -> mode` and `required_verifiers -> required_verifier_ids` without a Spec amendment, and uses `NONE` where the approved Spec defines `NO_COMMIT`.

**Impact:** implementation as written would not implement the user-approved authority contract and can weaken source/effect/migration boundaries.

**Required remediation:** Task 1 must implement the exact approved serialized Spec schema or the Spec must be explicitly amended/reapproved first. Internal Python attribute names may differ only if serialization remains byte/field compatible with the approved schema.

### DCC-ORCH-F003 — MAJOR — No concrete production builder path exists to create AUTO Gates

Current `build_operator_plan_job()` has no Gate-continuation-contract input. The Plan states that AUTO authority is omitted unless explicitly supplied by an approved plan builder, but defines no concrete builder interface or per-Gate mapping that supplies and validates those contracts.

**Impact:** DCC could be fully implemented yet normal new Full Plan Jobs would continue to be generated as `MANUAL_OPERATOR`, leaving the original chat-turn dependency unresolved in production use.

**Required remediation:** define an explicit backward-compatible builder interface, for example a closed `continuation_contracts_by_gate` mapping keyed only by known Task IDs. Missing mapping must remain MANUAL. Every supplied contract must be validated and included in `authority_core_sha256` before registration. Add positive production-builder and negative unknown-Gate/replay tests.

### DCC-ORCH-F004 — MAJOR — Source-lineage policy lacks complete executable semantics

The Spec requires `approved_base_head`, permitted ancestry relation, previous-Gate receipt lineage where applicable, actual ancestry proof, and dynamic source evidence. The Plan omits `approved_base_head` from the contract and does not define a closed source-lineage policy enum or an explicit ancestry/previous-receipt-chain verifier. Task 6 provides branch/base CAS and tree equality, which is necessary but not sufficient to prove the Spec lineage model.

**Impact:** source evolution may be mechanically safe at commit time while still not being proven to descend from the user-approved source lineage.

**Required remediation:** add exact lineage policy values and deterministic proof, including `git merge-base --is-ancestor` or equivalent repository-object checks, previous verified receipt source-head linkage where required, and RED tests for non-descendant, rewritten history, wrong previous receipt, and valid descendant chains.

### DCC-ORCH-F005 — MAJOR — Wait-reason semantics diverge from the approved Spec

The Spec preserves `OPERATOR_TASK_RECEIPT_PENDING` as the auto-eligibility entry condition when a valid AUTO contract/transaction exists and describes `CONTINUATION_RECOVERY_PENDING` as a typed continuation-recovery reason. Task 8 instead invents `AUTO_CONTINUATION_PENDING` and declares only that reason auto-recoverable.

**Impact:** this is an unapproved state-machine semantic change across runner/reconciler/attention/exit-guard boundaries and may create compatibility gaps with existing receipt-wait evidence.

**Required remediation:** either align the Plan to the approved Spec reason taxonomy or amend and explicitly reapprove the Spec. Add legacy state and mixed-version compatibility tests.

### DCC-ORCH-F006 — MAJOR — Required durable transaction dispositions are incomplete

The Spec requires terminal failure dispositions `BLOCKED`, `USER_DECISION_REQUIRED`, `DELEGATED_RUNTIME_MIGRATION`, and `ROLLED_BACK`. Task 5 defines only a `BLOCKED` terminal phase and a store API limited to `create/load/advance/block`; `DELEGATED_RUNTIME_MIGRATION` and `ROLLED_BACK` are absent from the Plan transaction model.

**Impact:** decision/migration/rollback outcomes may be represented outside the durable transaction that is supposed to own crash recovery, weakening restart/audit semantics.

**Required remediation:** represent every approved Spec disposition explicitly and test idempotent reload/reconcile behavior for each. Runtime migration remains delegated, but that delegation result must itself be durably represented in the continuation transaction.

### DCC-ORCH-F007 — MAJOR — EDP code-head versus publication-head closure remains ambiguous

Task 13 validates a runtime-code HEAD, then creates a docs-only EDP closure commit. Task 14 later says to compare the "runtime-code HEAD/tree" to Task-13 validated values while also building/pushing the exact closure HEAD. The Plan does not define distinct `validated_code_head`, `closure_head`, and `publication_head` fields or the exact runtime-path diff check between them.

**Impact:** the project can repeat the prior evidence-drift class: either reject a valid docs-only closure because HEAD changed, or accidentally accept later runtime drift because the distinction is informal.

**Required remediation:** bind all three identities explicitly. Require `git diff --quiet <validated_code_head>..<publication_head> -- runtime tests` (plus any other executable surfaces) before publication, and bind the immutable release to `publication_head` while EDP retains `validated_code_head` as measured source.

## Operational Areas That Passed

- Full Plan remains the intended sole Task/Gate/next-state authority.
- GATE_BY_GATE is explicitly excluded from automatic cross-Gate continuation.
- v1 receipt remains manual-only and v2 is intended to be attestation-bound.
- Push, destructive Git, system/network/package/credential effects remain separate authorization boundaries.
- Runtime activation remains delegated to `RuntimeMigrationTransaction`.
- Existing state schema tolerates additive `wait_reason` and additional lease metadata without immediate schema rejection.
- Existing durable JSON primitives provide file and directory fsync; previous-good persistence is already available through `durable_json_save/load`.
- Failure injection, multi-Gate E2E, authority negative-space, full regression, and final runtime convergence are present as intended Plan stages.

## Required Plan Remediation Order

1. Fix Task 0 immutable executor-runtime separation and add direct preflight regression.
2. Restore exact Spec `GateContinuationContract` schema and literals.
3. Define production builder contract injection and authority sealing.
4. Complete source-lineage policy/ancestry/previous-receipt proof.
5. Align wait-reason taxonomy with the approved Spec.
6. Add every Spec transaction failure/delegation/rollback disposition.
7. Make EDP code-head/closure-head/publication-head bindings explicit.
8. Re-run Spec-to-Plan 20/20 RTM, adversarial pass, focused 131 regression, temporary R1 self-mutation reproduction, and full regression.

## Closure Metrics

```text
BLOCKER_COUNT=2
UNRESOLVED_MAJOR_COUNT=5
UNRESOLVED_MINOR_COUNT=0
MUST_TRACEABILITY_COVERAGE=100%_BY_ID_BUT_NOT_BY_IMPLEMENTATION_FIDELITY
DOMAIN_EVIDENCE_COVERAGE=100%
NEGATIVE_SPACE_OPEN_MATERIAL_COUNT=0
CROSS_DOCUMENT_CONFLICT_COUNT=5
BROKEN_REFERENCE_COUNT=0
ADVERSARIAL_NEW_BLOCKER_MAJOR=7
PASS_CHALLENGE_OPEN_COUNT=7
SOURCE_AUTHORITY_STATUS=PLAN_REMEDIATION_REQUIRED
REGRESSION_REDIAGNOSIS_STATUS=BASELINE_PASS_PLAN_FAIL
MATERIAL_DEFECT_SEARCH=EXHAUSTED_FOR_AVAILABLE_EVIDENCE
EDP_DECISION=NOT_ALL_PASS
```

## Disposition

Do not execute Task 0 from the current Plan revision. Revise the Plan (and only amend the Spec where a deliberate design change is desired), then perform the same orchestration-readiness re-diagnosis. Implementation execution approval should be considered only after the revised Plan reaches fresh `EDP_DECISION=ALL_PASS`.
