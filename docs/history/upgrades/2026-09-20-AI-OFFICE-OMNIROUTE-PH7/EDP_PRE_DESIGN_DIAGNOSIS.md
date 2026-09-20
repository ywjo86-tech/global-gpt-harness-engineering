# OmniRoute PH7 Design — EDP Pre-Remediation Diagnosis

**Date:** 2026-09-20
**Standard:** `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` / EDP-1.0
**Target:** `docs/superpowers/specs/2026-09-20-omniroute-provider-gateway-design.md`
**Decision:** `REMEDIATION_REQUIRED`

## Source Register

| Source | Authority / purpose |
|---|---|
| User directive, 2026-09-20 | Authorizes OmniRoute-based Provider Expansion design continuation and requires duplicate unittest discovery removal in final operational qualification. |
| `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` | Canonical diagnosis and PASS-gate authority. |
| `docs/harness/orchestration-state.md` | Current Harness/AI Office authority projection. |
| `AI_OFFICE_STABLE_BASELINE` declaration/evidence | Predecessor baseline and authority boundary. |
| `omniroute@3.8.50` npm artifact inspected from registry | Exact package/version/runtime/config evidence. |
| Current unittest discovery evidence | Reproduces duplicate `LVPreviewTest` collection caused by direct TestCase import. |

## Frozen Material Obligations

- OMR-001: OmniRoute remains non-authoritative; Harness Router retains Provider/Model selection authority.
- OMR-002: Full Plan, MPRF, Full MCP, and AI Office authority boundaries remain unchanged.
- OMR-003: Initial OmniRoute runtime is loopback-only and requires API-key enforcement.
- OMR-004: Hidden OmniRoute provider fallback/auto-routing must not change the provider selected by Harness.
- OMR-005: Installation is version-pinned, provenance-verified, isolated, reversible, and does not require system-global mutation.
- OMR-006: Secrets remain outside Git with restrictive permissions.
- OMR-007: OmniRoute discovery is evidence only; discovery cannot directly create ACTIVE providers.
- OMR-008: Third-provider selection is evidence-based and provider-neutral.
- OMR-009: Live activation remains blocked without actual credential/access and required cost/risk approval.
- OMR-010: Gateway/provider failures normalize into MPRF while cross-provider reselection remains Router-owned.
- OMR-011: Duplicate unittest discovery must be fixed at source, not masked.
- OMR-012: Final operational qualification MUST prove duplicate discovery count is zero before Provider Expansion ALL PASS.
- OMR-013: Install/start failure must have a defined rollback and evidence-preservation path.
- OMR-014: Current orchestration-state projection must distinguish completed PH5 baseline from newly authorized PH7 Provider Expansion lifecycle.

## Findings

### OMR-F-001 — MAJOR — RESOLUTION REQUIRED
- **Affected:** Test Discovery Cleanup / Final Qualification
- **Related:** OMR-011, OMR-012
- **Problem:** Duplicate discovery cleanup is described but is not a stable MUST requirement with explicit evidence and closure gate.
- **Evidence:** `tests/test_lv_execution_package.py` imports `LVPreviewTest` directly; full discovery collects the same 13 methods twice and duplicates one Wallet skip.
- **Impact:** The cleanup could be omitted while the broader Provider Expansion is still reported complete.
- **Correction:** Add stable requirement IDs, root-cause correction, unique-test-ID proof, skip normalization proof, and a fail-closed final gate.
- **Regression:** RTM, negative-space, PASS challenge, final qualification.

### OMR-F-002 — MAJOR — RESOLUTION REQUIRED
- **Affected:** `docs/harness/orchestration-state.md`
- **Related:** OMR-014
- **Problem:** Current projection still states provider expansion is NOT_AUTHORIZED and requires future approval, while the current user directive authorizes the PH7 Provider Expansion lifecycle.
- **Impact:** Current authority state conflicts with the new design lifecycle.
- **Correction:** Preserve PH5 as historical baseline, but project PH7 design/implementation lifecycle as authorized; no candidate is ACTIVE yet.
- **Regression:** Cross-document authority and scope audit.

### OMR-F-003 — MAJOR — RESOLUTION REQUIRED
- **Affected:** Installation Profile / authority isolation
- **Related:** OMR-003, OMR-004
- **Problem:** Design states loopback/fallback controls abstractly but does not bind them to actual OmniRoute 3.8.50 controls.
- **Evidence:** Package source shows server bind defaults to `0.0.0.0`; `REQUIRE_API_KEY` defaults false; `OMNIROUTE_EMERGENCY_FALLBACK` defaults true.
- **Impact:** An implementation that follows only the abstract text could expose the service or silently change the selected Provider.
- **Correction:** Pin explicit env controls and verify runtime behavior before G1 PASS.
- **Regression:** Security, negative-space, adversarial, PASS challenge.

### OMR-F-004 — MAJOR — RESOLUTION REQUIRED
- **Affected:** Installation / recovery
- **Related:** OMR-005, OMR-013
- **Problem:** Global npm install is broader than needed and rollback/supply-chain proof is underspecified.
- **Evidence:** Package has postinstall/uninstall scripts; npm artifact exposes integrity/shasum but the design does not require evidence capture.
- **Impact:** Host mutation and rollback provenance are not bounded enough for a server Harness baseline.
- **Correction:** Use isolated user-owned prefix/wrapper, capture npm integrity + downloaded artifact SHA-256 before install, define stop/uninstall/restore rollback.
- **Regression:** Install profile, recovery, traceability, PASS challenge.

## Pre-Remediation Metrics

```text
BLOCKER_COUNT=0
UNRESOLVED_MAJOR_COUNT=4
MUST_REQUIREMENT_COVERAGE=71%
MUST_TRACEABILITY_COVERAGE=64%
DOMAIN_EVIDENCE_COVERAGE=100%
NEGATIVE_SPACE_OPEN_MATERIAL_COUNT=3
CROSS_DOCUMENT_CONFLICT_COUNT=1
BROKEN_REFERENCE_COUNT=0
UNRESOLVED_MATERIAL_TBD_COUNT=0
UNRESOLVED_MATERIAL_OPEN_QUESTION_COUNT=0
ADVERSARIAL_NEW_BLOCKER_MAJOR=1
PASS_CHALLENGE_OPEN_COUNT=4
SOURCE_AUTHORITY_STATUS=AVAILABLE_WITH_CURRENT_USER_AMENDMENT
REGRESSION_REDIAGNOSIS_STATUS=REQUIRED
MATERIAL_DEFECT_SEARCH=NOT_EXHAUSTED
```
