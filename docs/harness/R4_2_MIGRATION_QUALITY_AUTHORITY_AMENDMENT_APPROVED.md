# R4.2 MIGRATION QUALITY AUTHORITY AMENDMENT — APPROVED

> Approval status: **APPROVED**
> Approval date: `2026-09-10`
> Approval actor: `USER`
> Decision: `DEC-011 (A → B)`
> Scope: **PLANNING AUTHORITY ONLY**
> Supersedes: none
> Preserves: R4, R4.1, FINAL Requirement Baseline 1.0, FINAL DP-2.0, FINAL SC-1.0
> Approved policy: `HQP-MIGRATION-001`
> Approved policy version: `1.0`
> Approved policy digest: `f4418d48899917bfea40185d3d9e71f73ff50a729187e9f5dca3443cf34fccc7`

## 1. Approval effect

The user explicitly approved the R4.2 Migration Quality Authority Amendment Candidate and
the associated migration-only Harness Quality Policy.

This approval:

- activates the approved planning authority for ISSUE-095 recovery mode;
- approves `APPROVED_MIGRATION_BASELINE` as a valid source mode only for
  `MIGRATION_APPROVED_PLAN`;
- approves `HQP-MIGRATION-001` version `1.0` with the exact digest above;
- approves SEM-067A and INV-043A as the R4.2 migration-only amendment;
- preserves `LEGACY_REFERENCE_BOOTSTRAP` as the default when genuine legacy authority exists;
- does not reconstruct or assert unavailable FINAL DP-2.0 / SC-1.0 bytes;
- does not change product Requirements, product scope, Worker permissions, DEC-007,
  Completion truth, security model, or DEC-008 HOLD;
- does not authorize FULL_ORCHESTRATION use of this recovery mode.

## 2. Gate separation

This approval is **not** implementation/deployment/proof approval.

It does not authorize:

- runtime code modification beyond a separately approved implementation Gate;
- Codex live probe or turn;
- proof97 execution;
- git push;
- deployment;
- main-branch merge;
- FULL_ORCHESTRATION activation.

## 3. ISSUE-095 state transition

`ISSUE-095` changes from:

`Major / BLOCKED`

to:

`Major / IMPLEMENTATION-READY`

It is not RESOLVED until runtime materialization, tamper/negative tests, regression,
and production canonical quality binding all pass.

## 4. Exact approved authority chain

```text
DEC-011 (A → B)
  → ISSUE-095 Option-A bounded recovery report
  → R4.2 Migration Quality Authority Amendment APPROVED
  → HQP-MIGRATION-001 v1.0
  → future MigrationQualityCriteriaContract
       source_mode=APPROVED_MIGRATION_BASELINE
       activation_profile=MIGRATION_APPROVED_PLAN
```

## 5. Required implementation invariants

The implementation must fail closed when:

- the amendment approval ref is absent or mismatched;
- policy version/digest differs;
- profile is not `MIGRATION_APPROVED_PLAN`;
- criterion set is incomplete/duplicated/drifted;
- Pre/Post criterion lineage differs;
- new Requirement/product scope/permission/Completion truth is introduced;
- security obligations are weakened;
- automatic remediation becomes enabled;
- `FULL_ORCHESTRATION` attempts to use this policy;
- unresolved Critical/Major blockers are promoted to PASS.

## 6. Historical preservation

R4 and R4.1 remain immutable historical freezes.
This file is a new approved amendment and must not overwrite those artifacts.
