# DEC-011 — ISSUE-095 Migration Quality Authority Recovery

## 1. Decision Metadata

- Decision ID: `DEC-011`
- Status: **DECIDED**
- Type: `Blocking`
- Severity: `Major`
- Raised: `2026-09-10`
- Decided: `2026-09-10`
- Requirement refs: `REQ-030`, `REQ-037`, `REQ-042`
- Plan/task refs: `TASK-ORCH-02`, `TASK-ORCH-04 / 04A-2B-3B-2`, `G-4A-ACTUAL`
- Semantic refs: `SEM-063`, `SEM-065`, `SEM-067`
- Blocking issue: `ISSUE-095`

## 2. User Decision

**A → B**

1. First recover the existing approved Quality Policy / FINAL quality-obligation authority.
2. If it is not found in verified available sources, prepare a migration-only Quality Baseline / Harness Quality Policy amendment candidate.
3. Do not invent missing legacy authority.
4. Do not activate the new authority until explicit user approval of the exact amendment candidate.

## 3. Option A result

`ISSUE-095_AUTHORITY_RECOVERY_REPORT_A.md` records:

**NOT_FOUND_IN_VERIFIED_SOURCES**

The repository searches and R4/R4.1 package inspection show normative references to the required quality authority but no concrete versioned Harness Quality Policy artifact and no recoverable complete prior FINAL quality-obligation bytes.

Therefore the decision advances to Option B preparation.

## 4. Option B constraints

The amendment candidate must:

- remain limited to `MIGRATION_APPROVED_PLAN` / current Phase4A migration;
- remain prohibited in `FULL_ORCHESTRATION`;
- preserve product scope, Requirement meaning, permissions, completion truth, security model and DEC-007 authorization;
- keep DEC-008 automatic remediation `HOLD` / disabled;
- derive only from quality meanings already frozen in R4/R4.1;
- add explicit source provenance, version, digest and deterministic criteria;
- fail closed on missing/tampered authority;
- require explicit user approval before activation.

## 5. Impact

No product Requirement baseline change is proposed by this Decision.

A controlled Semantic/Architecture amendment is required because existing `SEM-067` / `INV-043` currently state legacy FINAL quality authority as the exclusive bootstrap source. The candidate must add an explicitly approved migration-baseline recovery mode rather than silently pretending the new source is legacy.

ISSUE-095 remains BLOCKED until the amendment is approved and implemented.
