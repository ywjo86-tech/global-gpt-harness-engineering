# R4 Orchestration Authority Index

> Status: **ACTIVE AUTHORITY INDEX**
>
> Recorded: `2026-09-10`
>
> Scope: R4 Architecture Freeze lineage, R4.1 amendment, and R4.2 migration-quality amendment

## 1. Purpose

This index fixes the authority order used by the ORCH04 implementation and Gate review.
It is an index only: it does not rewrite frozen meanings, close runtime issues, authorize
`proof97`, or authorize deployment/push.

## 2. Authority order

Apply the narrowest later approved amendment over the preserved earlier authority:

```text
R4 canonical Architecture Freeze package
  + R4.1 approved Architecture Freeze amendment
  + R4.2 approved migration-quality authority amendment
  = current layered authority for MIGRATION_APPROVED_PLAN
```

Neither R4.1 nor R4.2 supersedes R4 as a whole. R4.1 changes only the approved
test-ownership/completion-marker interpretation stated in its approval. R4.2 changes only
the `ISSUE-095` migration-quality recovery authority stated in its approval. In every
other respect, the earlier authority is preserved.

## 3. Canonical artifacts and exact digests

### 3.1 R4 base package

Canonical package: `R4 Architecture Freeze/REVISED_CANDIDATE_PACKAGE_R4.zip`

Package SHA-256: `0f03698ffa1bcc438c8f0d97260d930b969da9983052eac50b69344a6c34d4f8`

The ZIP contains the canonical filenames below. Files with `(1)`, `(2)`, `-1`, or `-2`
suffixes in the upload folder are not canonical names for digest binding.

| Canonical ZIP member | SHA-256 |
|---|---|
| `01_CRB-2.0-CANDIDATE.md` | `71897df1376fcdccba6365f1624c45e706647b674c9fd2de3b81f747f27f9879` |
| `02_DP-6.0-CANDIDATE.md` | `c9beb03a9a7142f1f485829249342ed33527db1b01c127653940088462981df4` |
| `03_SC-5.0-CANDIDATE.md` | `f8c14a3763b7996a7cfe80c89b2689be73c4d837487b816cdc349b3697c1d55f` |
| `04_FULL_PLAN_ORCHESTRATION_IMPLEMENTATION_DESIGN_V2.0-CANDIDATE.md` | `297f2c734e7dfe98e64e369f68daa89ec9fe03beed0d52b970c0aac917085b0f` |
| `05_TRACEABILITY_MATRIX_V2.0-CANDIDATE.md` | `a41a84741d7438d0ea20900a1431fcb3027c4bdc1c8485ae642f5851b784484a` |
| `06_ARCHITECTURE_INVARIANTS_OUT_OF_SCOPE_V2.0-CANDIDATE.md` | `8cedbe7bc643f29f6f4b807d35a22e8a29c5919a8fc1b5a83fe0719900c3678a` |
| `07_IMPLEMENTATION_GATE_TEST_MATRIX_V2.0-CANDIDATE.md` | `92ccf292037ebd6fae11dd301b7fee72720a604aaf9a6cd00d02da3b2275598b` |
| `FULL_CANDIDATE_PACKAGE_COMBINED_R4.md` | `e1b76755d8969e62d7fc9165a873c48041d35fad4aa02c6ae7fc889759ef91c6` |
| `PACKAGE_VALIDATION_REPORT.md` | `6c19ab42ef081ab12a18e7a2c2d53a86db9e509febb43cc749905986e945e275` |

The member digests are the canonical `SHA256SUMS.txt` entries and are also preserved in
`R4_1_MIGRATION_AUTHORITY_MANIFEST.json`.

### 3.2 R4.1 approved amendment

- Approval: `R4_1_ARCHITECTURE_FREEZE_AMENDMENT_APPROVAL.md`
- Approval content SHA-256: `1d586a0fb3e3e6fa0874cc452b103699b25ed8f09418ce460bb785930ebbcc92`
- Machine-readable authority: `R4_1_MIGRATION_AUTHORITY_MANIFEST.json`
- R4.1 package SHA-256 recorded by that manifest:
  `9ae0e4bfe62caaf92afb7e81a1d66a373701c8082f56775d2225feed6ca4ca3b`
- Scope: `TEST-AUTH-003` ownership normalization and clarification of
  `HARNESS_COMPLETION_CRITERIA_CLEAR=YES`
- Effect: R4 preserved; no Requirement meaning, Semantic Contract, or product scope change

### 3.3 R4.2 approved amendment

- Approval: `R4_2_MIGRATION_QUALITY_AUTHORITY_AMENDMENT_APPROVED.md`
- Approval content SHA-256 before this index: `c49ee359a4178dbeb055a52e74141da8b7e5b058d773217238466ca5a433c15c`
- Traceability/test impact: `R4_2_TRACEABILITY_TEST_IMPACT_APPROVED.md`
- Approved policy: `HQP-MIGRATION-001` version `1.0`
- Approved policy SHA-256:
  `f4418d48899917bfea40185d3d9e71f73ff50a729187e9f5dca3443cf34fccc7`
- Approved policy JSON artifact file SHA-256:
  `aff3d2919a77bd95046d0e5ac6c105504306d27d8f35bd285f9b3f4410fd377e`
- Scope: `DEC-011 (A → B)` / `ISSUE-095` and `MIGRATION_APPROVED_PLAN` only
- Effect: `ISSUE-095` is `IMPLEMENTATION-READY`, not resolved
- Preserved: R4, R4.1, product Requirements, Worker permissions, Completion truth,
  security model, and `DEC-008 HOLD`

## 4. Historical inputs

The separately uploaded early/revision files under `R4 Architecture Freeze/`, including
filenames containing `(1)` or `(2)`, are historical design inputs. They may explain design
evolution but do not override the exact R4 ZIP members or later approved amendments.

## 5. Issue and Gate interpretation

- The R4 canonical issue register keeps `ISSUE-025` Critical/Open and the recorded runtime
  and actual-evidence Major issues open until their own closure evidence passes.
- `ISSUE-092` is not present in the R4 canonical package, R4.1 authority, or substantive
  R4.2 approval/traceability documents. Its isolated line in the digest-bound R4.2 status
  summary is administratively retired by the later append-only `ISSUE-092_DISPOSITION.md`.
  The sealed status-summary bytes remain unchanged for authority validation.
- That disposition is not an alias, renumbering, or closure of `ISSUE-025` or any other issue.
- `proof97` remains `HOLD` until the prerequisites in the canonical Gate/Test Matrix pass.
- This index grants no implementation, live Codex, proof, deployment, merge, push, or
  automatic-remediation authority.

## 6. Verification boundary

Directly verified while creating this index:

- the local R4 ZIP SHA-256 matches the R4.1 authority manifest;
- all nine canonical member digests agree between the R4 `SHA256SUMS.txt` and the R4.1
  authority manifest;
- the approval content digests match the local approval files, and the approved policy
  digest agrees between the R4.2 approval and the policy JSON `policy_digest` field;
- repository search found `ISSUE-092` only in the prior R4.2 status summary, not in the
  canonical R4 package or substantive R4.1/R4.2 authority documents.

Not executed by this index update: source/deep validators, runtime regression, live Codex
readiness, `proof97`, deployment, commit, and push.
