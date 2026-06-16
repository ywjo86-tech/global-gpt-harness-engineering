# Nested Detail Plan

## 1. Linked Main Plan
- Main Plan: [MAIN_DEVELOPMENT_PLAN.md](MAIN_DEVELOPMENT_PLAN.md)
- Parent Step: [STEP_03_DETAIL_PLAN.md](STEP_03_DETAIL_PLAN.md)
- Phase No: 3.1
- Nested Name: Step Handoff Content

## 2. Step Objective
- Define what must be recorded in a step handoff so phase completion is factual, compact, and reusable.

## 3. Requirement Breakdown
- Requirements handled in this nested step:
  - Record completion facts only.
  - Capture verification result and next-step note.
  - Include scope and risk notes when needed.
- Requirements not handled in this nested step:
  - Progress calculation rules.
  - Final deployment handoff.
  - QA for runtime features.

## 4. Reasoning and Prediction
- Expected implementation approach:
  - Keep the handoff format concise and phase-oriented.
  - Use the handoff as the transition record, not as a full phase summary.
- Expected problems:
  - Handoff notes can become too verbose if they absorb planning detail.
  - Progress and QA sections can drift if not kept separate.
- Expected dependencies:
  - `MAIN_DEVELOPMENT_PLAN.md`
  - `PLAN_INDEX.md`
  - `STEP_03_DETAIL_PLAN.md`
- High-risk areas:
  - Mixing planning notes with completion records.
  - Letting the handoff become a substitute for the detail plan.
- Prevention measures:
  - Keep the handoff fields fixed and factual.
  - Treat the detail plan as the only source of phase intent.

## 5. Files to Create or Modify

| File | Action | Reason |
|---|---|---|
| `MAIN_DEVELOPMENT_PLAN.md` | Read Only | Defines the overall phase map. |
| `PLAN_INDEX.md` | Modify | Must point to the active nested handoff slice. |
| `STEP_03_DETAIL_PLAN.md` | Modify | Needs to acknowledge the nested handoff content slice. |
| `STEP_03_01_DETAIL_PLAN.md` | Create/Modify | Defines the step handoff content rules. |

## 6. One-Loop Breakdown

| Loop | Single Target | Verification | Expected Output |
|---|---|---|---|
| LOOP-01 | Define completion facts | Verify the handoff includes only factual completion info | Compact handoff structure |
| LOOP-02 | Define verification notes | Verify verification is recorded separately from plan intent | Clear verification record |
| LOOP-03 | Define transition note | Verify next-step guidance is concise and bounded | Stable transition handoff |

## 7. UI Expected Preview
- Not required.
- Reason: This nested plan is about handoff metadata only.

## 8. QA Criteria
- The handoff must remain shorter than the parent detail plan.
- The handoff must not duplicate the full planning logic.
- The parent step and active index must point to this nested slice while it is active.

## 9. Handoff Requirements
- Record:
  - the completion fact fields,
  - the verification result fields,
  - the next-step note,
  - any scope or risk note that changes the transition.
- Handoff target:
  - `HANDOFF_STEP_03_01.md`
- Next step should receive:
  - the bounded handoff content policy,
  - the parent step context,
  - any handoff format refinements as scope candidates.

## 10. Stop Conditions
- Stop if:
  - the handoff becomes a full phase report,
  - the nested plan loses parent linkage,
  - verification and progress sections are merged,
  - a folder restructure is required.
- User confirmation needed if:
  - the handoff must absorb runtime QA details,
  - a repo-wide policy file must be changed,
  - another nested level becomes necessary.

