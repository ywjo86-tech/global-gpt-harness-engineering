# Exhaustive Diagnosis Protocol

**Document ID:** EDP-1.0  
**Status:** CANONICAL COMMON DIAGNOSIS STANDARD  
**Purpose:** Prevent premature, shallow, or non-reproducible PASS decisions by requiring evidence-backed, adversarial, traceable diagnosis before closure.

> This document is a common protocol, not a standalone execution skill. A diagnosis skill that binds this protocol MUST apply it in addition to its domain-specific rules. Domain-specific rules may strengthen this protocol but MUST NOT weaken, skip, or bypass it.

---

## 1. Applicability

Apply this protocol whenever a bound diagnosis skill is asked to evaluate grammar, structure, semantic consistency, requirements fidelity, traceability, completeness, integrity, handoff readiness, execution readiness, or approval readiness.

The protocol applies to:
- single-document diagnosis,
- cross-document diagnosis,
- planning/design/execution-contract diagnosis,
- general document integrity diagnosis,
- re-diagnosis after correction.

A PASS is valid only within the evidence and authoritative sources actually available to the diagnosis. Do not claim absolute defect-freedom beyond available evidence.

**Independent skill ZIP distribution:** an exact byte-identical copy of this protocol may be bundled inside each independently installable diagnosis skill at `references/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md`. Such bundled copies are synchronized package copies of the same `EDP-1.0` standard, not separate authorities. A package that carries a different protocol version or hash must be treated as drift and revalidated before use.

---

## 2. Non-Negotiable Principles

1. **No premature PASS.** Do not declare PASS until every mandatory phase in this protocol is complete.
2. **Artifact is not truth.** Treat the target artifact as a claim to verify, not as an authority merely because it is well-formed.
3. **Evidence before conclusion.** Every applicable diagnosis domain must have explicit evidence or an explicit `N/A — <reason>` disposition.
4. **No silent repair.** A material defect found during diagnosis must be reported, not silently edited away and treated as if it never existed.
5. **No unsupported authority.** If required authoritative material is unavailable, do not infer or reconstruct it from similarity.
6. **Traceability is mandatory when semantics cross artifacts.** Coverage claims require explicit mappings, not impressionistic review.
7. **Adversarial verification is mandatory.** The first conclusion must be challenged before final closure.
8. **Correction requires regression.** After material correction, re-check affected dependencies and re-run closure checks.
9. **Scope the conclusion.** If evidence is incomplete, report the limitation and prohibit a stronger PASS than the evidence supports.

---

## 3. Canonical Source Resolution

Before content diagnosis, identify the authority stack and freeze it for the run.

### 3.1 Required Source Register

Record, where applicable:
- current explicit user decisions,
- authoritative baseline artifact and version,
- target artifact and version,
- verified current repository/project/source state,
- supporting approved documents,
- verified external research,
- prior diagnosis reports,
- assumptions and their status.

### 3.2 Default Authority Precedence

Unless a domain-specific skill defines a stricter valid order:

1. Current explicit user decision within the permitted authority boundary
2. Approved canonical baseline / contract
3. Verified current source or repository state
4. Verified supporting approved documentation
5. Verified research evidence
6. Clearly labeled assumptions

A lower-level source cannot silently override a higher-level approved authority.

### 3.3 Authority Failure

If an authority required for the requested conclusion is missing, stale, ambiguous, superseded, or conflicting:
- record the exact missing/conflicting source,
- stop the affected fidelity claim,
- return the domain-specific blocked/revision state,
- do not issue an unrestricted PASS.

---

## 4. Requirement / Constraint Extraction and Freeze

Before evaluating the target, extract and freeze the applicable semantic obligations.

Create stable audit IDs for all material obligations, including where applicable:
- explicit requirements,
- non-functional requirements,
- security/permission requirements,
- operational requirements,
- scope inclusions/exclusions,
- constraints,
- success/acceptance criteria,
- deliverables,
- identity/version/root bindings,
- approval boundaries,
- forbidden actions,
- dependencies and preconditions,
- user decisions,
- deferred decisions and open questions.

Do not add new material obligations during diagnosis. If a genuinely new requirement is discovered, route it to the proper revision authority.

---

## 5. Mandatory Evidence Matrix

Every applicable domain MUST produce a record with at least:

| Field | Required content |
|---|---|
| Domain ID | Stable domain/check identifier |
| Claim checked | Exact property being verified |
| Authority / source | Source used for comparison |
| Target location | Section, ID, line, heading, or artifact location |
| Evidence | Concise observed evidence |
| Result | PASS / FAIL / N/A / BLOCKED |
| Finding IDs | Related defects, if any |

A domain without evidence is **not checked** and cannot contribute to PASS.

`DOMAIN_EVIDENCE_COVERAGE` must equal `100%` for all applicable mandatory domains before PASS.

---

## 6. Mandatory Traceability Matrix

When a diagnosis involves transformation, planning, design, execution, or cross-document semantics, build an explicit RTM.

Minimum form:

`Source Obligation → Target Representation → Validation/Proof → Status`

Domain-specific skills may require a richer chain.

Rules:
- every MUST/material obligation must have a target mapping,
- every target material addition must have an authorized source,
- broken, orphaned, duplicated, altered, or unauthorized mappings are findings,
- `MUST_TRACEABILITY_COVERAGE` must equal `100%` before PASS.

---

## 7. Primary Audit Pass

Run every domain-specific diagnosis check in its defined order. At minimum, when applicable, verify:
- grammar/syntax/format validity,
- structural completeness,
- internal consistency,
- semantic consistency,
- scope and authority integrity,
- requirement/constraint preservation,
- identifiers/references,
- dependency/precondition logic,
- verifiability/testability,
- completion/approval criteria,
- change-control boundaries,
- handoff readiness.

Do not compress multiple mandatory domains into an unsupported global statement such as “overall consistent.”

---

## 8. Negative-Space Audit

After the primary pass, search specifically for what **should exist but does not**.

Check, where applicable:
- required sections absent,
- unrepresented requirements or constraints,
- missing definitions,
- missing owner/responsibility,
- missing inputs/outputs,
- missing preconditions/postconditions,
- missing failure/recovery path,
- missing validation/evidence,
- missing approval or completion conditions,
- missing cross-reference or traceability link,
- missing security/permission boundary,
- missing deferred/open-question disposition.

Negative-space findings must be recorded separately so that absence is not hidden by well-written existing content.

---

## 9. Cross-Document Consistency Audit

When more than one authoritative or dependent artifact exists, compare both directions:

1. **Source → Target:** every required semantic item is preserved.
2. **Target → Source:** every material target item is authorized by a source.

Check identity, version, root, scope, requirements, constraints, success criteria, deliverables, design/execution semantics, validation, evidence, gates, permissions, and change-control boundaries as applicable.

---

## 10. Adversarial Second Pass

After the initial findings are complete, assume the current conclusion is wrong.

Mandatory challenge prompt:

> Assume the current diagnosis and tentative PASS/CONDITIONAL/FAIL conclusion is incorrect. Search the entire available authority set and target artifact for counterexamples, overlooked contradictions, hidden omissions, unauthorized additions, dependency breaks, and evidence gaps capable of changing the decision.

Requirements:
- do not reuse only the same evidence path as the primary pass,
- focus on boundary cases and interactions between sections,
- explicitly state newly discovered findings,
- if no new material finding is found, record `ADVERSARIAL_NEW_BLOCKER_MAJOR: 0`.

---

## 11. PASS Challenge

Before PASS, actively attempt to invalidate every PASS-critical claim.

For each closure-critical claim ask:
- What evidence would make this false?
- Did we inspect the location where that evidence could exist?
- Is the conclusion based on absence of evidence rather than evidence of absence?
- Does another section/source contradict it?
- Does a missing dependency make the apparently valid statement non-executable or non-verifiable?

Any unresolved challenge blocks PASS.

---

## 12. Remediation and Regression Re-Diagnosis

If a material finding is corrected:

1. preserve the finding and correction record,
2. identify directly affected domains,
3. identify dependent/downstream domains,
4. re-run those domains,
5. re-run traceability for affected obligations,
6. re-run Negative-Space Audit where structure changed,
7. re-run Adversarial Second Pass,
8. re-run PASS Challenge and Closure Gate.

A correction does not automatically close a finding. Closure requires evidence.

---

## 13. Finding Schema

Every material finding MUST include:
- Finding ID
- Severity
- Status: OPEN / RESOLVED / ACCEPTED_EXCEPTION
- Defect owner / revision authority where applicable
- Affected artifact and section
- Related requirement/constraint/ID where applicable
- Problem
- Evidence
- Why it matters / impact
- Required correction or decision
- Regression scope after correction

Severity minimum:
- BLOCKER
- MAJOR
- MINOR
- NOTE

`ACCEPTED_EXCEPTION` requires explicit authority and must not be used to bypass BLOCKER/MAJOR closure conditions.

---

## 14. Mandatory Closure Metrics

Before final decision, report at least:
- `BLOCKER_COUNT`
- `UNRESOLVED_MAJOR_COUNT`
- `UNRESOLVED_MINOR_COUNT`
- `MUST_REQUIREMENT_COVERAGE`
- `MUST_TRACEABILITY_COVERAGE`
- `DOMAIN_EVIDENCE_COVERAGE`
- `NEGATIVE_SPACE_OPEN_MATERIAL_COUNT`
- `CROSS_DOCUMENT_CONFLICT_COUNT`
- `BROKEN_REFERENCE_COUNT`
- `UNRESOLVED_MATERIAL_TBD_COUNT`
- `UNRESOLVED_MATERIAL_OPEN_QUESTION_COUNT`
- `ADVERSARIAL_NEW_BLOCKER_MAJOR`
- `PASS_CHALLENGE_OPEN_COUNT`
- `SOURCE_AUTHORITY_STATUS`
- `REGRESSION_REDIAGNOSIS_STATUS` when corrections occurred

---

## 15. Universal PASS Gate

A domain-specific skill may impose stricter rules. It MUST NOT impose weaker rules.

PASS is prohibited unless all applicable conditions are satisfied:

- `BLOCKER_COUNT = 0`
- `UNRESOLVED_MAJOR_COUNT = 0`
- `MUST_REQUIREMENT_COVERAGE = 100%` when requirements exist
- `MUST_TRACEABILITY_COVERAGE = 100%` when traceability is applicable
- `DOMAIN_EVIDENCE_COVERAGE = 100%`
- `NEGATIVE_SPACE_OPEN_MATERIAL_COUNT = 0`
- `CROSS_DOCUMENT_CONFLICT_COUNT = 0` for material conflicts
- `BROKEN_REFERENCE_COUNT = 0` for material/binding references
- `UNRESOLVED_MATERIAL_TBD_COUNT = 0`
- `UNRESOLVED_MATERIAL_OPEN_QUESTION_COUNT = 0`
- `ADVERSARIAL_NEW_BLOCKER_MAJOR = 0`
- `PASS_CHALLENGE_OPEN_COUNT = 0`
- required authority is available and valid
- required remediation regression is PASS/NOT_APPLICABLE
- no domain-specific PASS condition is violated

MINOR findings may remain only when they are explicitly recorded, non-material, do not affect semantics/authority/traceability/execution/approval, and the domain-specific skill permits them.

---

## 16. Exhaustion Statement

Before final decision, answer:

> Is there a reasonable remaining path, within the currently available authoritative evidence, by which another review could reveal a previously unchecked material defect?

Allowed status:
- `MATERIAL_DEFECT_SEARCH: EXHAUSTED_FOR_AVAILABLE_EVIDENCE`
- `MATERIAL_DEFECT_SEARCH: NOT_EXHAUSTED`

PASS requires `EXHAUSTED_FOR_AVAILABLE_EVIDENCE`.

This statement does not claim absolute mathematical completeness; it confirms that all defined mandatory search paths were executed against the available evidence.

---

## 17. Final Decision Sequence

The final decision must be produced only after:

`Canonical Source Resolution`
→ `Obligation Extraction & Freeze`
→ `Primary Domain Audit`
→ `Mandatory Evidence Matrix`
→ `Mandatory RTM`
→ `Negative-Space Audit`
→ `Cross-Document Audit`
→ `Adversarial Second Pass`
→ `PASS Challenge`
→ `Regression Re-Diagnosis if applicable`
→ `Closure Metrics`
→ `Exhaustion Statement`
→ `Final Decision`

No earlier step may emit final PASS.
