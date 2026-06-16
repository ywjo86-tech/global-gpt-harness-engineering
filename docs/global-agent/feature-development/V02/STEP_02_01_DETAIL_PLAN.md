# Nested Detail Plan

## 1. Linked Main Plan
- Main Plan: [MAIN_DEVELOPMENT_PLAN.md](MAIN_DEVELOPMENT_PLAN.md)
- Parent Step: [STEP_02_DETAIL_PLAN.md](STEP_02_DETAIL_PLAN.md)
- Phase No: 2.1
- Nested Name: Index Linkage Rules

## 2. Step Objective
- Define the exact linkage rules between the main plan, step detail plans, nested plans, and handoff documents so the index remains the single navigation entry point.

## 3. Requirement Breakdown
- Requirements handled in this nested step:
  - Specify how the plan index points to main, step, nested, and handoff documents.
  - Keep the routing rules short enough to avoid index drift.
  - Preserve one active nested plan at a time.
- Requirements not handled in this nested step:
  - Handoff content itself.
  - QA execution for runtime features.
  - UI implementation or preview work.

## 4. Reasoning and Prediction
- Expected implementation approach:
  - Treat `PLAN_INDEX.md` as the canonical routing table.
  - Keep the nested plan focused only on linkage, not on phase content.
- Expected problems:
  - The index could become a duplicate summary if routing rules are too verbose.
  - Nested plans could multiply without a clear parent linkage.
- Expected dependencies:
  - `MAIN_DEVELOPMENT_PLAN.md`
  - `PLAN_INDEX.md`
  - `STEP_02_DETAIL_PLAN.md`
- High-risk areas:
  - Changing active routing without reflecting the parent step.
  - Introducing nested plans without a clear trigger threshold.
- Prevention measures:
  - Keep the nested plan limited to routing policy.
  - Update the parent step and index together when the nested plan becomes active.

## 5. Files to Create or Modify

| File | Action | Reason |
|---|---|---|
| `MAIN_DEVELOPMENT_PLAN.md` | Read Only | Provides the overall phase map. |
| `PLAN_INDEX.md` | Modify | Holds the active routing entry for the nested plan. |
| `STEP_02_DETAIL_PLAN.md` | Modify | Must acknowledge the active nested routing slice. |
| `STEP_02_01_DETAIL_PLAN.md` | Create/Modify | Defines the linkage rules subplan. |

## 6. One-Loop Breakdown

| Loop | Single Target | Verification | Expected Output |
|---|---|---|---|
| LOOP-01 | Define main-to-step routing | Verify each step has a clear parent plan link | Stable routing baseline |
| LOOP-02 | Define step-to-nested routing | Verify the nested plan is referenced without ambiguity | Clear nested linkage |
| LOOP-03 | Define step-to-handoff routing | Verify the active phase can transition using handoff references | Complete routing slice |

## 7. UI Expected Preview
- Not required.
- Reason: This nested plan is about routing metadata only.

## 8. QA Criteria
- The nested plan must not duplicate the full main plan.
- The parent step and index must agree on the active nested plan.
- The routing table must remain the single entry point for current work.

## 9. Handoff Requirements
- Record:
  - the active nested plan link,
  - the parent step link,
  - any routing ambiguity found during draft,
  - the next document needed for the phase.
- Handoff target:
  - [HANDOFF_STEP_02_01.md](HANDOFF_STEP_02_01.md)
- Next step should receive:
  - the stable routing model,
  - the active nested plan reference,
  - any scope candidates discovered while editing the index.

## 10. Stop Conditions
- Stop if:
  - the index turns into a long-form summary,
  - the nested plan loses its parent link,
  - multiple nested plans are activated at once,
  - a folder restructuring becomes necessary.
- User confirmation needed if:
  - additional nested plan levels become necessary,
  - a repo-wide policy file must be changed,
  - runtime implementation work appears.
