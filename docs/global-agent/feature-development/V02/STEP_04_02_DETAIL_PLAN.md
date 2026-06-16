# Nested Detail Plan

## 1. Linked Main Plan
- Main Plan: [MAIN_DEVELOPMENT_PLAN.md](MAIN_DEVELOPMENT_PLAN.md)
- Parent Step: [STEP_04_DETAIL_PLAN.md](STEP_04_DETAIL_PLAN.md)
- Phase No: 4.2
- Nested Name: Scope-Control QA

## 2. Step Objective
- Verify that scope expansion is controlled and that future ideas are recorded instead of implemented immediately.

## 3. Requirement Breakdown
- Requirements handled in this nested step:
  - Check scope expansion boundaries.
  - Confirm future ideas are written as candidates.
  - Keep the active phase narrow and bounded.
- Requirements not handled in this nested step:
  - Artifact consistency links.
  - Release-readiness closure.
  - Runtime or UI validation.

## 4. Reasoning and Prediction
- Expected implementation approach:
  - Review the planning set for unapproved additions.
  - Confirm that new ideas are deferred, not silently absorbed.
- Expected problems:
  - Scope can creep in through “small” additions.
  - Future candidates can be mistaken for active work.
- Expected dependencies:
  - `MAIN_DEVELOPMENT_PLAN.md`
  - `PLAN_INDEX.md`
  - `STEP_04_DETAIL_PLAN.md`
- High-risk areas:
  - Unapproved scope growth.
  - Ambiguous future-candidate records.
- Prevention measures:
  - Keep only approved content in the active phase.
  - Record all new ideas as scope candidates.

## 5. Files to Create or Modify

| File | Action | Reason |
|---|---|---|
| `MAIN_DEVELOPMENT_PLAN.md` | Read Only | Source of the scope baseline. |
| `PLAN_INDEX.md` | Modify | Must point to the active scope-control slice. |
| `STEP_04_DETAIL_PLAN.md` | Modify | Needs to acknowledge the scope-control slice. |
| `STEP_04_02_DETAIL_PLAN.md` | Create/Modify | Defines scope-control QA checks. |

## 6. One-Loop Breakdown

| Loop | Single Target | Verification | Expected Output |
|---|---|---|---|
| LOOP-01 | Verify allowed scope | Confirm the active plan contains only approved work | Controlled phase boundary |
| LOOP-02 | Verify candidate handling | Confirm new ideas are recorded as candidates | Deferred expansion policy |
| LOOP-03 | Verify stop behavior | Confirm unapproved expansion triggers a stop | Stable scope-control QA |

## 7. UI Expected Preview
- Not required.
- Reason: This nested plan is about scope policy only.

## 8. QA Criteria
- No unapproved work should be folded into the active phase.
- New ideas must appear as scope candidates, not active tasks.
- The parent step and active index must point to this nested slice while it is active.

## 9. Handoff Requirements
- Record:
  - the scope-control rule,
  - the candidate-record rule,
  - any ambiguity found during drafting,
  - the next document needed for the phase.
- Handoff target:
  - `HANDOFF_STEP_04_02.md`
- Next step should receive:
  - the approved scope-control baseline,
  - the parent step context,
  - any future scope refinements as candidates.

## 10. Stop Conditions
- Stop if:
  - an unapproved change is pulled into the active phase,
  - the nested plan loses parent linkage,
  - candidates are silently promoted to active work,
  - a folder restructure is required.
- User confirmation needed if:
  - scope control needs a broader policy rewrite,
  - a repo-wide policy file must be changed,
  - another nested level becomes necessary.
