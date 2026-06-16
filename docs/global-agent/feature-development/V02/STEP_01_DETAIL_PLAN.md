# Step Detail Plan

## 1. Linked Main Plan
- Main Plan: [MAIN_DEVELOPMENT_PLAN.md](MAIN_DEVELOPMENT_PLAN.md)
- Phase No: 1
- Phase Name: Planning Foundation

## 2. Step Objective
- Establish the core planning foundation for V02 by confirming the control document, active index behavior, and the first bounded execution target.

## 3. Requirement Breakdown
- Requirements handled in this step:
  - Validate the hierarchical planning structure at the top level.
  - Define the active plan relationship between the main plan and the plan index.
  - Prepare the first step-level planning scope.
- Requirements not handled in this step:
  - Nested detail plans.
  - Handoff document creation.
  - Progress updates beyond the initial control-state definition.
  - Any global agent policy file changes outside the V02 planning folder.

## 4. Reasoning and Prediction
- Expected implementation approach:
  - Keep this step focused on the planning foundation only.
  - Treat the main plan and index as the minimum working set for the next phase.
- Expected problems:
  - Over-expanding into later phases too early.
  - Duplicating content already defined in the main plan.
- Expected dependencies:
  - `MAIN_DEVELOPMENT_PLAN.md`
  - `PLAN_INDEX.md`
- High-risk areas:
  - Adding too many future files into the active step.
  - Misstating the active phase or loop target.
- Prevention measures:
  - Maintain one-loop, one-target execution.
  - Keep this plan short and execution-oriented.

## 5. Files to Create or Modify

| File | Action | Reason |
|---|---|---|
| `MAIN_DEVELOPMENT_PLAN.md` | Read Only | Source of truth for the overall V02 structure. |
| `PLAN_INDEX.md` | Read Only | Defines the active loop and phase routing. |
| `STEP_01_DETAIL_PLAN.md` | Create/Modify | Current step scope and working contract. |

## 6. One-Loop Breakdown

| Loop | Single Target | Verification | Expected Output |
|---|---|---|---|
| LOOP-01 | Confirm plan foundation scope | Check that the main plan and index point to the same active phase | Stable foundation for the first phase |
| LOOP-02 | Keep the active phase narrow | Check that no later-phase artifacts are pulled into the current loop | Clean phase boundary |

## 7. UI Expected Preview
- Not required.
- Reason: This step is document planning only and does not include UI implementation.

## 8. QA Criteria
- Step plan must point to exactly one active phase.
- Step scope must exclude later-phase work.
- Files list must distinguish create/modify from read-only.
- One-loop breakdown must preserve the one-target rule.

## 9. Handoff Requirements
- Step completion should record:
  - the active phase definition,
  - the exact current loop target,
  - the files that remain read only,
  - any scope candidate discovered during planning.
- The next step should receive:
  - the active plan location,
  - the current phase boundary,
  - the reason the next step is still pending.

## 10. Stop Conditions
- Stop if:
  - this step starts referencing later-phase execution details,
  - the active loop expands beyond the planning foundation,
  - a nested plan is needed before the foundation is stable,
  - a policy file outside the V02 planning set becomes necessary.
- User confirmation needed if:
  - the next loop must touch `.codex` or repo-wide harness policy files,
  - a scope expansion candidate becomes urgent,
  - a UI or runtime implementation task appears.

