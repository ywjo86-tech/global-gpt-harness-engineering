# Provisional Skill Revalidation — 2026-09-10

## Status

This document records provisional skill refinements made before Full Plan Orchestration implementation is considered complete.

These changes are NOT a stable/V1.0 promotion and MUST be revalidated against the implemented orchestrator before merge/promotion to stable use.

## Provisional Candidates

| Skill | Current Provisional Role | Stable Promotion Blocker |
| --- | --- | --- |
| `code-review-harness` | Independent implementation-quality review; no fixes and no gate decision | Verify worker/reviewer separation, blocking semantics, artifact schema, and re-review transitions |
| `request-intent-definition-harness` | Preserve `User Statement -> Intent`; no requirements or solution selection | Verify actual intake/change-request entry point, traceability schema, and central intent checks |
| `technical-docs-harness` | Traceable documentation authoring; expose intended/observed drift | Verify documentation stage, provenance schema, central drift detection, and QA handoff |
| `deep-research-harness` | Conditional bounded evidence sidecar; no plan modification | Verify sidecar invocation, evidence artifact schema, scope controls, and amendment signaling |

## Global Boundary Principles Locked at Provisional Stage

The following principles are implementation-independent and should remain unless a later review finds a concrete contradiction:

1. Skill responsibilities must not duplicate the orchestrator or neighboring lifecycle skills.
2. Reviewer roles must not self-fix and self-certify the same change.
3. Non-gate skills must not issue `GO`, `CONDITIONAL GO`, or `NO-GO` decisions.
4. No candidate skill may silently change a sealed plan, plan revision/SHA, requirement, architecture, or orchestration state.
5. Explicit user constraints and exclusions must survive downstream normalization.
6. Inference, uncertainty, conflict, and evidence gaps must remain visible rather than being converted into invented facts.
7. Plan/implementation drift must be surfaced, not normalized by documentation or research.
8. Conditional specialist skills must not become mandatory gates unless the implemented lifecycle explicitly requires them.

## Full Plan Orchestration Revalidation Gate

Run this review only after implementation and integration tests provide enough evidence of the real orchestration behavior.

### A. Runtime and State Model

- Confirm actual lifecycle/Gate sequence.
- Confirm actual state names and transition rules.
- Confirm retry, resume, cancel, amendment, and re-review behavior.
- Confirm which component owns gate advancement.

### B. Authority Model

- Confirm supervisor, worker, reviewer, stage-gate, and specialist permissions.
- Confirm whether reviewer/fixer separation is enforced by runtime or only by guidance.
- Confirm which operations can mutate sealed plans or orchestration state.

### C. Artifact and Provenance Contract

- Confirm actual plan revision/SHA fields.
- Confirm run/thread/task/artifact identifiers.
- Confirm artifact manifest and handoff schemas.
- Confirm traceability path from user request through requirement, plan, implementation, and evidence.

### D. Responsibility Collision Review

For each candidate ask:

> Is this responsibility owned by the candidate skill, the orchestrator, or an existing neighboring skill?

Remove duplicate responsibilities rather than keeping redundant checks in multiple layers.

Explicitly compare against:

- `project-intake`
- `requirements-analysis`
- `new-project-orchestrator`
- `harness-design`
- `qa-release-review`
- final Full Plan Orchestration runtime controls

### E. Candidate-Specific Revalidation

#### `code-review-harness`

- Does the orchestrator centrally define finding severity/status?
- Does the gate consume `blocking_candidate` or another canonical field?
- Is re-review a first-class transition?
- Is reviewer/fixer separation enforced?
- Does `qa-release-review` remain the sole release-readiness owner?

#### `request-intent-definition-harness`

- Is there already a canonical pre-intake normalization step?
- How are `EXPLICIT`, `INFERRED`, `UNKNOWN`, and `CONFLICT` represented?
- How are blocking unknowns escalated?
- Can raw request provenance be retained without duplicating data?
- Does the skill still own only `User Statement -> Intent`?

#### `technical-docs-harness`

- What is the canonical provenance metadata schema?
- Does the orchestrator already detect plan/implementation drift?
- Which documentation types are required by lifecycle stage?
- How does QA receive documentation gaps/drift?
- Can intended vs observed behavior remain distinct in final docs?

#### `deep-research-harness`

- How are conditional sidecars invoked and resumed?
- What is the canonical research/evidence artifact schema?
- Is scope expansion centrally blocked?
- What is the canonical amendment/change-required signal?
- Are stop conditions runtime-enforced or skill-owned?

## Promotion Decision

After revalidation, each skill must receive exactly one disposition:

- `PROMOTE_TO_V1`: responsibilities fit the implemented orchestrator with no material collision.
- `REVISE_AND_RETEST`: useful skill, but contract/schema/boundary changes are required.
- `MERGE_INTO_EXISTING`: responsibilities are better owned by an existing skill.
- `ABSORB_INTO_ORCHESTRATOR`: responsibilities are infrastructure controls, not specialist skill behavior.
- `RETIRE`: no longer justified after implementation evidence.

Do not rename, merge, delete, or promote these candidates solely from the provisional analysis. Base the final disposition on implemented Full Plan Orchestration evidence.

## Current Decision

As of 2026-09-10:

- All four candidates remain `PROVISIONAL`.
- Their implementation-independent authority boundaries have been strengthened.
- Stable naming, exact Gate placement, runtime field names, and final ownership remain intentionally unresolved until Full Plan Orchestration revalidation.
