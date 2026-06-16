# Nested Detail Plan

## 1. Linked Main Plan
- Main Plan: [MAIN_DEVELOPMENT_PLAN.md](MAIN_DEVELOPMENT_PLAN.md)
- Parent Step: [STEP_02_DETAIL_PLAN.md](STEP_02_DETAIL_PLAN.md)
- Phase No: 2.3
- Nested Name: Nested Plan Trigger Review

## 2. Step Objective
- Define when a step detail plan is complex enough to justify a nested plan so nested decomposition stays controlled and predictable.

## 3. Requirement Breakdown
- Requirements handled in this nested step:
  - Define trigger conditions for nested plan creation.
  - Prevent overuse of nested plans for simple work.
  - Keep the trigger rule short and reusable.
- Requirements not handled in this nested step:
  - Routing index details.
  - Step template section lists.
  - Handoff content or QA execution.

## 4. Reasoning and Prediction
- Expected implementation approach:
  - Use explicit conditions such as complexity, independent subparts, and QA separation.
  - Keep the trigger rule conservative so nested plans are only created when needed.
- Expected problems:
  - If the trigger is too loose, the plan tree will sprawl.
  - If the trigger is too strict, complex steps may become bloated.
- Expected dependencies:
  - `MAIN_DEVELOPMENT_PLAN.md`
  - `PLAN_INDEX.md`
  - `STEP_02_DETAIL_PLAN.md`
- High-risk areas:
  - Treating every small subtask as a nested plan.
  - Letting the trigger rule turn into a long policy list.
- Prevention measures:
  - Define a small set of clear triggers.
  - Require a parent-step justification before creating a nested plan.

## 5. Files to Create or Modify

| File | Action | Reason |
|---|---|---|
| `MAIN_DEVELOPMENT_PLAN.md` | Read Only | Provides the overall phase map. |
| `PLAN_INDEX.md` | Modify | Must point to the active nested trigger review slice. |
| `STEP_02_DETAIL_PLAN.md` | Modify | Needs to acknowledge the nested trigger rule slice. |
| `STEP_02_03_DETAIL_PLAN.md` | Create/Modify | Defines the nested plan trigger policy. |

## 6. One-Loop Breakdown

| Loop | Single Target | Verification | Expected Output |
|---|---|---|---|
| LOOP-01 | Define size threshold | Verify when a step becomes too long for one document | Clear length trigger |
| LOOP-02 | Define complexity threshold | Verify the trigger covers multi-part or independent work | Clear complexity trigger |
| LOOP-03 | Define QA threshold | Verify separate QA needs can justify a nested plan | Clear QA trigger |

## 7. UI Expected Preview
- Not required.
- Reason: This nested plan is about decomposition policy only.

## 8. QA Criteria
- The trigger rule must be specific enough to apply consistently.
- The trigger rule must not turn every subtask into a nested plan.
- The parent step and active index must point to this nested slice while it is active.

## 9. Handoff Requirements
- Record:
  - the approved nested-plan trigger conditions,
  - any ambiguous cases that need future review,
  - the next document needed for the phase.
- Handoff target:
  - `HANDOFF_STEP_02_03.md`
- Next step should receive:
  - the nested-plan trigger policy,
  - the parent step context,
  - any future trigger refinements as scope candidates.

## 10. Stop Conditions
- Stop if:
  - the trigger rule becomes a duplicate of the main plan,
  - the step template starts absorbing trigger text,
  - the nested plan loses parent linkage,
  - a folder restructure is required.
- User confirmation needed if:
  - the trigger must be expanded into a longer policy,
  - a repo-wide policy file must be changed,
  - another nested level becomes necessary.

