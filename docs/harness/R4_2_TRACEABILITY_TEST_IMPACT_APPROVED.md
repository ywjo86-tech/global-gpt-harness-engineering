# R4.2 Migration Quality Authority — Traceability / Test Impact Candidate

> Status: **APPROVED PLANNING BASELINE**
> Scope: DEC-011 / ISSUE-095 only

## 1. Requirement impact

No Requirement ID or Requirement meaning is changed.

| Requirement | Existing meaning used | Amendment impact |
|---|---|---|
| REQ-030 | Pre-Quality checks completeness, consistency, implementability, dependency, testability, security, semantic integrity, traceability; migration uses deterministic bootstrap | Adds explicit approved recovery authority when concrete legacy policy source is unavailable |
| REQ-037 | Independent Post-Quality; Pre/Post same criteria lineage/digest | Preserved; recovery-mode criteria use exact same lineage |
| REQ-042 | Final cross-check; unresolved blockers prohibit finalization | Preserved; amendment cannot convert blocker to PASS |

## 2. Plan/Semantic impact

| Authority | Impact |
|---|---|
| DP-6.0 6.1A / 8.1 | Add `APPROVED_MIGRATION_BASELINE` as explicitly approved recovery source mode |
| SC-5.0 SEM-067 | Add SEM-067A recovery rule; legacy mode remains default |
| INV-006 | Preserved: criteria still come from approved requirement/plan meanings + versioned policy |
| INV-043 | Preserved as default; INV-043A defines no-silent-fallback recovery rule |
| DEC-007 | No change |
| DEC-008 | No change; automatic remediation remains disabled |
| SEM-065 | No change; migration profile only |
| SEM-070 | No change; Codex readiness remains independent prerequisite |

## 3. New stable test IDs

| Test ID | Scenario | Expected |
|---|---|---|
| TEST-MIG-007 | legacy policy/final quality source unavailable and no approved R4.2 amendment | bootstrap BLOCK |
| TEST-MIG-008 | approved R4.2 + exact HQP-MIGRATION-001 version/digest + migration profile | recovery-mode contract may materialize |
| TEST-MIG-009 | recovery-mode policy digest/source ref tampered | validation FAIL/BLOCK |
| TEST-MIG-010 | recovery mode introduces new Requirement/scope/permission/completion truth | validation FAIL/BLOCK |
| TEST-MIG-011 | recovery-mode Pre/Post criterion lineage/digest differs | Post-Quality PASS prohibited |
| TEST-MIG-012 | FULL_ORCHESTRATION attempts recovery-mode policy | validation FAIL/BLOCK |

Existing `TEST-MIG-003` and `TEST-MIG-004` remain applicable to deterministic contract generation and durable `PRE_QUALITY_REFERENCE_SATISFIED`.

## 4. Implementation trace

```text
DEC-011
  → R4.2 amendment approval
  → HQP-MIGRATION-001 exact version/digest
  → MigrationQualityCriteriaContract
  → TEST-MIG-003/004/007~012
  → PRE_QUALITY_REFERENCE_SATISFIED
  → canonical Contract/Package path
```

## 5. Out of scope

- product changes;
- new Requirement IDs;
- new Tool authorization;
- proof97 execution;
- Codex live probe/turn;
- push/deploy;
- FULL_ORCHESTRATION policy design.

## Approval note

Approved by user on `2026-09-10`. Runtime implementation remains separately gated.
