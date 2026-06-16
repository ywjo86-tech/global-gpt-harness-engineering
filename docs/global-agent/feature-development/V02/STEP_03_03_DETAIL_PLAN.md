# Nested Detail Plan

## 1. Linked Main Plan
- Main Plan: [MAIN_DEVELOPMENT_PLAN.md](MAIN_DEVELOPMENT_PLAN.md)
- Parent Step: [STEP_03_DETAIL_PLAN.md](STEP_03_DETAIL_PLAN.md)
- Phase No: 3.3
- Nested Name: Final Handoff Boundary

## 2. Step Objective
- Define the boundary between step handoffs and the final deployment handoff so the final record stays distinct from intermediate phase records.

## 3. Requirement Breakdown
- Requirements handled in this nested step:
  - Define what belongs in final deployment handoff only.
  - Keep final handoff records separate from phase handoffs.
  - Prevent final handoff content from being copied into phase-level records.
- Requirements not handled in this nested step:
  - Step handoff content.
  - Progress calculation.
  - Runtime QA or implementation work.

## 4. Reasoning and Prediction
- Expected implementation approach:
  - Keep the final handoff focused on release readiness and whole-system closure.
  - Use the nested plan to lock the boundary between phase and final records.
- Expected problems:
  - Final handoff content can bleed back into phase-level records if the boundary is vague.
  - The final record can become too long if it repeats phase details.
- Expected dependencies:
  - `MAIN_DEVELOPMENT_PLAN.md`
  - `PLAN_INDEX.md`
  - `STEP_03_DETAIL_PLAN.md`
- High-risk areas:
  - Mixing phase-level completion facts with final deployment closure.
  - Letting the final handoff override the phase handoff structure.
- Prevention measures:
  - Keep the final deployment handoff as a separate, end-state record.
  - Use the phase handoff as the only transition artifact for intermediate completion.

## 5. Files to Create or Modify

| File | Action | Reason |
|---|---|---|
| `MAIN_DEVELOPMENT_PLAN.md` | Read Only | Provides the overall phase map. |
| `PLAN_INDEX.md` | Modify | Must point to the active final-boundary slice. |
| `STEP_03_DETAIL_PLAN.md` | Modify | Needs to acknowledge the final handoff boundary slice. |
| `STEP_03_03_DETAIL_PLAN.md` | Create/Modify | Defines the final deployment boundary. |

## 6. One-Loop Breakdown

| Loop | Single Target | Verification | Expected Output |
|---|---|---|---|
| LOOP-01 | Define final-only content | Verify what belongs exclusively in the final handoff | Clear final boundary |
| LOOP-02 | Define exclusion rule | Verify phase-only content stays out of the final record | Distinct handoff layers |
| LOOP-03 | Define closure note | Verify the final handoff can close the planning system cleanly | Stable final record policy |

## 7. UI Expected Preview
- Not required.
- Reason: This nested plan is about handoff boundary policy only.

## 8. QA Criteria
- The final handoff must stay separate from step handoffs.
- The nested plan must not repeat the entire plan tree.
- The parent step and active index must point to this nested slice while it is active.

## 9. Handoff Requirements
- Record:
  - the content allowed only in the final handoff,
  - the content excluded from final handoff,
  - any boundary ambiguity discovered during drafting,
  - the next document needed for the phase.
- Handoff target:
  - `HANDOFF_STEP_03_03.md`
- Next step should receive:
  - the finalized final-handoff boundary,
  - the parent step context,
  - any closure refinements as scope candidates.

## 10. Stop Conditions
- Stop if:
  - the final handoff starts duplicating phase records,
  - the nested plan loses parent linkage,
  - closure content becomes a substitute for phase verification,
  - a folder restructure is required.
- User confirmation needed if:
  - the final handoff must absorb runtime QA detail,
  - a repo-wide policy file must be changed,
  - another nested level becomes necessary.

