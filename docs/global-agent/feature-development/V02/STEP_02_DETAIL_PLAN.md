# Step Detail Plan

## 1. Linked Main Plan
- Main Plan: [MAIN_DEVELOPMENT_PLAN.md](MAIN_DEVELOPMENT_PLAN.md)
- Phase No: 2
- Phase Name: Plan Index and Step Templates

## 2. Step Objective
- Define the plan index linkage rules, the reusable step template structure, and the conditions for introducing nested detail plans.

## 3. Requirement Breakdown
- Requirements handled in this step:
  - Establish how `PLAN_INDEX.md` links main, step, nested, and handoff documents.
  - Standardize the step-detail-plan structure.
  - Define when nested plans are allowed and how they connect upward.
- Requirements not handled in this step:
  - Phase completion handoffs.
  - Final deployment handoff.
  - Runtime implementation or code changes.
  - UI preview generation.

## 4. Reasoning and Prediction
- Expected implementation approach:
  - Use a single index document as the routing layer.
  - Keep step templates short enough that they can be reused across later phases.
- Expected problems:
  - Index drift if the current phase is not updated after future handoffs.
  - Nested plans being created too early or too often.
- Expected dependencies:
  - `MAIN_DEVELOPMENT_PLAN.md`
  - `PLAN_INDEX.md`
  - `STEP_01_DETAIL_PLAN.md`
- High-risk areas:
  - Defining nested-plan rules too loosely.
  - Allowing the step template to become a full project plan instead of a bounded phase plan.
- Prevention measures:
  - Require an explicit trigger before creating nested detail plans.
  - Keep the index as the only routing source.

## 5. Files to Create or Modify

| File | Action | Reason |
|---|---|---|
| `MAIN_DEVELOPMENT_PLAN.md` | Read Only | Provides the overall phase structure. |
| `PLAN_INDEX.md` | Modify | Holds active routing and status information. |
| `STEP_01_DETAIL_PLAN.md` | Read Only | Shows the current phase style and boundary. |
| `STEP_02_DETAIL_PLAN.md` | Create/Modify | Defines the step-template and nested-plan policy. |
| `STEP_02_01_DETAIL_PLAN.md` | Create/Modify | Captures the nested routing slice for index linkage rules. |
| `STEP_02_02_DETAIL_PLAN.md` | Create/Modify | Captures the nested slice for the reusable step template boundary. |
| `STEP_02_03_DETAIL_PLAN.md` | Create/Modify | Captures the nested slice for nested-plan trigger review. |

## 6. One-Loop Breakdown

| Loop | Single Target | Verification | Expected Output |
|---|---|---|---|
| LOOP-01 | Define index linkage rules | Verify every plan type has a clear routing path | Stable planning index model |
| LOOP-02 | Define step template boundaries | Verify the template does not absorb handoff or QA content | Reusable step detail format |
| LOOP-03 | Define nested plan triggers | Verify the nested plan rules are explicit and limited | Controlled nested-plan policy |

## 7. UI Expected Preview
- Not required.
- Reason: This step is still document and planning policy work only.

## 8. QA Criteria
- `PLAN_INDEX.md` must remain the single navigation entry point.
- The step template must separate objective, reasoning, files, loops, QA, handoff, and stop conditions.
- Nested plans must have a clear trigger and parent linkage.

## 9. Handoff Requirements
- Step completion should record:
  - the approved index linkage rule,
  - the standard step-template shape,
  - the nested-plan trigger conditions,
  - any future plan structures discovered during drafting.
- The next step should receive:
  - the active routing model,
  - the standard phase template,
  - the explicit nested-plan threshold.

## 10. Stop Conditions
- Stop if:
  - the index starts duplicating main-plan content,
  - the step template becomes too broad,
  - nested plans are proposed without an explicit trigger,
  - a policy file outside the V02 planning folder becomes necessary.
- User confirmation needed if:
  - a later loop must update repo-wide harness policies,
  - a nested plan must be created immediately,
  - any UI or runtime implementation work appears.
