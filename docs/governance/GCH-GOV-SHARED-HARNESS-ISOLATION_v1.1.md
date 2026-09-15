# Global GPT Harness Engineering — Project-Isolated Shared Harness Change Governance

Document ID: GCH-GOV-SHARED-HARNESS-ISOLATION
Version: v1.1
Status: APPROVED / REPOSITORY_ADOPTED_LOCAL

## 1. Core invariant

`global-gpt-harness-engineering/main` contains only identified, approved, evidence-bound integration states. New project-specific Shared Harness work must not be implemented directly on `main`.

## 2. Project isolation

- New Shared Harness remediation uses `project/<PROJECT_ID>/harness-remediation` or another approved project-specific branch.
- The branch starts from a verified `origin/main` or approved Stable Baseline SHA.
- A dedicated Git worktree is used where practical.
- One remediation branch has one requesting project unless the work is explicitly escalated to a Global Harness Change.
- Workspace separation alone does not satisfy Git provenance isolation.

## 3. Required provenance

Each remediation records `REQUESTING_PROJECT_ID`, project root, Harness repository, branch, worktree, branch base SHA, change reason, affected components, authority source, and required Gate.

## 4. Main direct-work prohibition

During ordinary child-project execution, source/test edits and commits on GCH `main` are prohibited. If Shared Harness remediation becomes necessary, mutation stops on `main` and resumes in the project-specific branch/worktree.

## 5. Authority escalation

A remediation that changes Provider Router authority, Stage Gate authority, completion/worker authority, fallback semantics, sandbox/security boundary, or approval model is not an ordinary project remediation and must be escalated to a separately approved Global Harness Planning Change.

## 6. Stable Baseline protection

A `FINAL_GATE=GO / STABLE_BASELINE=SEALED` record remains historical authority. Later project changes do not rewrite that evidence. Later changes are classified as `POST_BASELINE_EXTERNAL_CHANGE` or `POST_GATE_EXTERNAL_SHARED_HARNESS_CHANGE`; supplemental binding is used when necessary.

## 7. Evidence immutability

Gate, test, approval, and baseline evidence are not overwritten retroactively. Corrections use superseding records with explicit provenance.

## 8. Shared-file conflict

Concurrent project changes to authority-sensitive Harness files are classified `SHARED_HARNESS_CONFLICT` and require impact analysis, authority comparison, regression, independent merge review, and merge approval.

## 9. Merge readiness

Before integration to `main`, Project Gate, focused regression, required full regression, independent review, changed-file scope, source binding, cross-project contamination check, and ancestor-chain check must pass.

## 10. Merge strategy

Fast-forward or explicit merge commit is preferred to preserve provenance. Rebase, squash, reset, or force-push that rewrites approved project history requires separate explicit authority.

## 11. Ancestor-chain release check

Before `main` push, every `origin/main..main` commit is mapped to `COMMIT_SHA`, `PROJECT_ID`, `CHANGE_CLASS`, `APPROVAL_STATUS`, and evidence. Any `UNKNOWN`, `UNAPPROVED`, or `UNVERIFIED` commit blocks push.

## 12. Stable Baseline staging

`git add -A` is prohibited for Stable Baseline sealing. Explicit file staging, cached-file-set comparison, cached diff review, and manifest exact-match are required.

## 13. Dirty-tree classification

Residual changes must be classified as `OTHER_PROJECT`, `PREEXISTING`, `RUNTIME_TRANSIENT`, or `SUPERSEDED_ARTIFACT`. Any `UNKNOWN` residual blocks sealing.

## 14. Emergency changes

Urgent Harness fixes use `hotfix/<issue-id>` rather than ordinary direct-main mutation, with bounded scope, focused validation, regression, review, and authority evidence.

## 15. Branch/worktree closure

Project Harness worktree/branch cleanup occurs only after merge verification, baseline verification, and requesting-project revalidation.

## 16. Remote main protection

Long-term remote policy should restrict direct push, require reviewed integration and required checks, and prohibit force push. Remote protection activation is a separate operational approval.

## GOV-021 — Current Migration Exception (2026-09-15)

The following local `main` ancestor chain already existed before this governance rule could be repository-enforced. It MUST NOT be rewritten by reset/rebase merely to retrofit the new branch model.

Base: `origin/main = fc015712d94cc46916608ac2a956d1251562b464`

Historical pending chain:

1. `2cffc58` — FAMILY_AI_ENGLISH_COACH / first-Gate canonical-state Shared Harness remediation
2. `b946186` — FAMILY_AI_ENGLISH_COACH / TASK→LV + multi-toolchain Shared Harness stabilization
3. `5e96a35` — GCH-EXEC-BACKEND / UPGRADE-002 FINAL STABLE BASELINE (SEALED)
4. `3961957` — FAMILY_AI_ENGLISH_COACH / TASK execution-entry bridge
5. `38f88f9` — FAMILY_AI_ENGLISH_COACH / TASK review canonical-scope bridge
6. `2b13728` — FAMILY_AI_ENGLISH_COACH / bootstrap directory writes
7. `88dbd05` — FAMILY_AI_ENGLISH_COACH / TASK recovery + Android bootstrap
8. `55d001f` — FAMILY_AI_ENGLISH_COACH / Android bootstrap fail-closed
9. `aaa0fb7` — FAMILY_AI_ENGLISH_COACH / directory-owned scope in fixed runner
10. `60dde73` — FAMILY_AI_ENGLISH_COACH / materialized partial recovery adoption
11. `07ac3a2` — FAMILY_AI_ENGLISH_COACH / recovery write-epoch isolation
12. `df5e82b` — FAMILY_AI_ENGLISH_COACH / failed recovery gateway request reissue
13. `73211fb` — FAMILY_AI_ENGLISH_COACH / recovery read/list epoch handling

Current migration verification:

- Pending commits: 13
- FAMILY_AI_ENGLISH_COACH Shared Harness commits: 12
- GCH-EXEC-BACKEND UPGRADE-002 Stable Baseline commits: 1
- Unknown pending commits: 0
- UPGRADE-002 direct source changed after `5e96a35`: NO
- Family Shared Harness stabilization: PASS
- Current Harness focused regression: 244 PASS
- Current full regression: 1278 tests; 3 known stale assertions; 10 skipped
- Coverage-equivalent full regression: 1278/1278 PASS
- Coverage-equivalent Graphify regression: 58/58 PASS
- Compileall: PASS
- Source/test diff-check: PASS
- Tracked dirty files: 0

Migration rule:

`PRESERVE_EXISTING_LOCAL_CHAIN_NO_REBASE_RESET → classify every ancestor → repository-adopt this governance policy → obtain explicit push approval → push → verify local main == origin/main`.

All NEW Shared Harness work after policy effectiveness MUST use project-specific branch/worktree isolation.

## 17. Effective enforcement

The policy is operationally effective immediately. Repository adoption and remote push remain separate approval boundaries.

## 18. Repository adoption record

- Adoption branch: `governance/shared-harness-isolation-v1.1`
- Branch base: `5e96a35f347a016e24a9e2057661880b8ba32a8c` (`UPGRADE-002 FINAL STABLE BASELINE`)
- Approval authority: `USER_OWNER`
- Approval scope: repository adoption and local governance commit only
- Remote push: NOT AUTHORIZED by this adoption record
- New Shared Harness work must follow this policy immediately.
