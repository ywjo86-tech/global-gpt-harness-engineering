# Nested Detail Plan

## 1. Linked Main Plan
- Main Plan: [MAIN_DEVELOPMENT_PLAN.md](MAIN_DEVELOPMENT_PLAN.md)
- Parent Step: [STEP_03_DETAIL_PLAN.md](STEP_03_DETAIL_PLAN.md)
- Phase No: 3.2
- Nested Name: Progress Calculation

## 2. Step Objective
- Define how progress is calculated so phase completion can be tracked numerically without mixing in qualitative handoff notes.

## 3. Requirement Breakdown
- Requirements handled in this nested step:
  - Define the progress formula.
  - Keep progress updates tied to phase completion.
  - Prevent progress from being updated before handoff verification.
- Requirements not handled in this nested step:
  - Handoff content details.
  - Final deployment boundary rules.
  - Runtime QA or implementation work.

## 4. Reasoning and Prediction
- Expected implementation approach:
  - Use a simple completed-phases-over-total-phases formula.
  - Keep the progress field numeric and easy to audit.
- Expected problems:
  - Progress can become misleading if it is updated before verification.
  - Manual adjustments can create drift if not derived from handoff state.
- Expected dependencies:
  - `MAIN_DEVELOPMENT_PLAN.md`
  - `PLAN_INDEX.md`
  - `STEP_03_DETAIL_PLAN.md`
- High-risk areas:
  - Mixing progress commentary with the percentage itself.
  - Treating draft work as completed progress.
- Prevention measures:
  - Update progress only after handoff completion.
  - Keep the calculation rule explicit and stable.

## 5. Files to Create or Modify

| File | Action | Reason |
|---|---|---|
| `MAIN_DEVELOPMENT_PLAN.md` | Read Only | Provides the total phase count baseline. |
| `PLAN_INDEX.md` | Modify | Must point to the active progress-calculation slice. |
| `STEP_03_DETAIL_PLAN.md` | Modify | Needs to acknowledge the progress-calculation nested plan. |
| `STEP_03_02_DETAIL_PLAN.md` | Create/Modify | Defines the progress formula. |

## 6. One-Loop Breakdown

| Loop | Single Target | Verification | Expected Output |
|---|---|---|---|
| LOOP-01 | Define formula basis | Verify progress uses completed phases divided by total phases | Simple progress formula |
| LOOP-02 | Define update timing | Verify progress only changes after handoff completion | Safe update rule |
| LOOP-03 | Define audit note | Verify the progress field can be explained without ambiguity | Auditable progress rule |

## 7. UI Expected Preview
- Not required.
- Reason: This nested plan is about workflow metadata only.

## 8. QA Criteria
- The progress formula must be simple and explicit.
- The progress update must be tied to verified phase completion.
- The parent step and active index must point to this nested slice while it is active.

## 9. Handoff Requirements
- Record:
  - the progress formula,
  - the update timing rule,
  - any ambiguity found during drafting,
  - the next document needed for the phase.
- Handoff target:
  - `HANDOFF_STEP_03_02.md`
- Next step should receive:
  - the approved progress rule,
  - the parent step context,
  - any future progress refinements as scope candidates.

## 10. Stop Conditions
- Stop if:
  - the progress formula becomes a long policy block,
  - the nested plan loses parent linkage,
  - progress updates are separated from handoff verification,
  - a folder restructure is required.
- User confirmation needed if:
  - progress must be tracked with a more complex metric,
  - a repo-wide policy file must be changed,
  - another nested level becomes necessary.

