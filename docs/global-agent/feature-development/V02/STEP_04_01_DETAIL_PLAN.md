# Nested Detail Plan

## 1. Linked Main Plan
- Main Plan: [MAIN_DEVELOPMENT_PLAN.md](MAIN_DEVELOPMENT_PLAN.md)
- Parent Step: [STEP_04_DETAIL_PLAN.md](STEP_04_DETAIL_PLAN.md)
- Phase No: 4.1
- Nested Name: Artifact-Consistency QA

## 2. Step Objective
- Verify that the planning documents point to each other correctly and that the hierarchy is internally consistent.

## 3. Requirement Breakdown
- Requirements handled in this nested step:
  - Check main-to-step links.
  - Check step-to-handoff links.
  - Check that the active index points to the current active document set.
- Requirements not handled in this nested step:
  - Scope-control policy beyond link consistency.
  - Release-readiness closure.
  - Runtime or UI validation.

## 4. Reasoning and Prediction
- Expected implementation approach:
  - Read the planning set as a linked graph.
  - Verify that each file points to its parent or next record without contradiction.
- Expected problems:
  - A handoff or index entry can drift out of sync with the parent plan.
  - The final handoff may be referenced before it is ready.
- Expected dependencies:
  - `MAIN_DEVELOPMENT_PLAN.md`
  - `PLAN_INDEX.md`
  - `STEP_01_DETAIL_PLAN.md`
  - `STEP_02_DETAIL_PLAN.md`
  - `STEP_03_DETAIL_PLAN.md`
  - `STEP_04_DETAIL_PLAN.md`
- High-risk areas:
  - Missing or stale file references.
  - Index rows that do not match the active phase state.
- Prevention measures:
  - Use a single consistency pass across the whole planning tree.
  - Keep this nested plan limited to references and routing.

## 5. Files to Create or Modify

| File | Action | Reason |
|---|---|---|
| `MAIN_DEVELOPMENT_PLAN.md` | Read Only | Source of the hierarchy. |
| `PLAN_INDEX.md` | Modify | Must reflect the active phase and nested slice. |
| `STEP_04_DETAIL_PLAN.md` | Modify | Needs to acknowledge the artifact-consistency slice. |
| `STEP_04_01_DETAIL_PLAN.md` | Create/Modify | Defines artifact-consistency QA checks. |

## 6. One-Loop Breakdown

| Loop | Single Target | Verification | Expected Output |
|---|---|---|---|
| LOOP-01 | Verify plan-chain links | Confirm each step plan points to the right parent and index state | Consistent plan graph |
| LOOP-02 | Verify handoff links | Confirm each handoff file belongs to the right phase | Valid transition map |
| LOOP-03 | Verify index alignment | Confirm current active state matches the actual active documents | Stable QA baseline |

## 7. UI Expected Preview
- Not required.
- Reason: This nested plan is about document consistency only.

## 8. QA Criteria
- Every active file reference must resolve to the intended document.
- The index must match the actual active phase and nested slice.
- No phase should point to a future handoff as if it were already complete.

## 9. Handoff Requirements
- Record:
  - the verified link set,
  - any stale or missing references,
  - the next document needed for the phase.
- Handoff target:
  - `HANDOFF_STEP_04_01.md`
- Next step should receive:
  - the confirmed artifact-consistency baseline,
  - the parent step context,
  - any unresolved link candidates as scope notes.

## 10. Stop Conditions
- Stop if:
  - a required file is missing,
  - the active index conflicts with the actual document state,
  - the nested plan starts drifting into scope-control policy,
  - a folder restructure is required.
- User confirmation needed if:
  - a broken link requires broader repository restructuring,
  - a repo-wide policy file must be changed,
  - another nested level becomes necessary.
