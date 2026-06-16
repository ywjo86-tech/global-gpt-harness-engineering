# Nested Detail Plan

## 1. Linked Main Plan
- Main Plan: [MAIN_DEVELOPMENT_PLAN.md](MAIN_DEVELOPMENT_PLAN.md)
- Parent Step: [STEP_02_DETAIL_PLAN.md](STEP_02_DETAIL_PLAN.md)
- Phase No: 2.2
- Nested Name: Step Template Boundaries

## 2. Step Objective
- Define the reusable step template boundary so the phase plan stays short, execution-oriented, and separate from handoff and QA content.

## 3. Requirement Breakdown
- Requirements handled in this nested step:
  - Define which sections belong in a step detail plan.
  - Keep the step template concise enough for reuse.
  - Prevent the template from absorbing later-phase or handoff content.
- Requirements not handled in this nested step:
  - Routing index rules.
  - Handoff writing.
  - Runtime QA or implementation work.

## 4. Reasoning and Prediction
- Expected implementation approach:
  - Keep the step template focused on objective, breakdown, reasoning, files, loops, QA, handoff, and stop conditions.
  - Use the nested plan only to clarify the template boundary.
- Expected problems:
  - The step template can become too broad if it starts carrying phase-specific outcomes.
  - Template reuse can weaken if the structure is not explicit.
- Expected dependencies:
  - `MAIN_DEVELOPMENT_PLAN.md`
  - `PLAN_INDEX.md`
  - `STEP_02_DETAIL_PLAN.md`
- High-risk areas:
  - Mixing execution detail with planning rules.
  - Repeating index logic inside the step template.
- Prevention measures:
  - Keep the template neutral and reusable.
  - Let the routing index remain the only navigation layer.

## 5. Files to Create or Modify

| File | Action | Reason |
|---|---|---|
| `MAIN_DEVELOPMENT_PLAN.md` | Read Only | Provides the phase structure. |
| `PLAN_INDEX.md` | Modify | Must point to the active nested boundary slice. |
| `STEP_02_DETAIL_PLAN.md` | Modify | Needs to acknowledge the template-boundary nested plan. |
| `STEP_02_02_DETAIL_PLAN.md` | Create/Modify | Defines the reusable step template boundary. |

## 6. One-Loop Breakdown

| Loop | Single Target | Verification | Expected Output |
|---|---|---|---|
| LOOP-01 | Define template sections | Verify the required sections are complete and bounded | Reusable step structure |
| LOOP-02 | Define template exclusions | Verify handoff and QA content stay outside the core template | Narrow step boundary |
| LOOP-03 | Define reuse rule | Verify the template can be reused across later phases | Stable step template policy |

## 7. UI Expected Preview
- Not required.
- Reason: This nested plan is about planning template structure only.

## 8. QA Criteria
- The template must remain shorter than the main plan.
- The template must not duplicate routing or handoff content.
- The parent step and active index must point to this nested slice while it is active.

## 9. Handoff Requirements
- Record:
  - the allowed sections in a step detail plan,
  - the excluded sections,
  - any template drift discovered during drafting,
  - the next document needed for the phase.
- Handoff target:
  - `HANDOFF_STEP_02_02.md`
- Next step should receive:
  - the finalized step-template boundary,
  - the current parent step context,
  - any future template refinements as scope candidates.

## 10. Stage Exit Condition
- [STAGE_EXIT_STANDARD.md](STAGE_EXIT_STANDARD.md)

## 11. Stop Conditions
- Stop if:
  - the step template becomes a full project plan,
  - routing logic starts moving into the template body,
  - the nested plan loses parent linkage,
  - a folder restructure is required.
- User confirmation needed if:
  - the template must absorb runtime execution details,
  - a repo-wide policy file must be changed,
  - another nested level becomes necessary.
