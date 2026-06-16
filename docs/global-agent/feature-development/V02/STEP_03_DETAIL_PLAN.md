# Step Detail Plan

## 1. Linked Main Plan
- Main Plan: [MAIN_DEVELOPMENT_PLAN.md](MAIN_DEVELOPMENT_PLAN.md)
- Phase No: 3
- Phase Name: Handoff and Progress System

## 2. Step Objective
- Define the step handoff structure, the final deployment handoff structure, and the progress tracking rules used to move from one phase to the next.

## 3. Requirement Breakdown
- Requirements handled in this step:
  - Specify what must be recorded in step handoffs.
  - Specify how progress updates are calculated and retained.
  - Define the boundary between phase completion and final deployment handoff.
- Requirements not handled in this step:
  - Phase 1 or Phase 2 execution details.
  - QA implementation for runtime features.
  - Any code or agent file modification outside the V02 planning artifacts.

## 4. Reasoning and Prediction
- Expected implementation approach:
  - Use step handoffs as the only source of truth for phase completion.
  - Keep progress tracking simple, numeric, and easy to update after each completed phase.
- Expected problems:
  - Progress can become inconsistent if handoffs are not written first.
  - Final deployment handoff can become overloaded if step handoffs are too vague.
- Expected dependencies:
  - `MAIN_DEVELOPMENT_PLAN.md`
  - `PLAN_INDEX.md`
  - `STEP_01_DETAIL_PLAN.md`
  - `STEP_02_DETAIL_PLAN.md`
- High-risk areas:
  - Mixing planning notes with completion records.
  - Updating progress before the phase is actually handed off.
- Prevention measures:
  - Record handoff facts only.
  - Treat progress as derived from completed phase count.

## 5. Files to Create or Modify

| File | Action | Reason |
|---|---|---|
| `MAIN_DEVELOPMENT_PLAN.md` | Read Only | Defines the overall progress framework. |
| `PLAN_INDEX.md` | Modify | Tracks active phase, loop, and last handoff. |
| `STEP_01_DETAIL_PLAN.md` | Read Only | Shows how step-level detail is bounded. |
| `STEP_02_DETAIL_PLAN.md` | Read Only | Shows index and nested-plan linkage rules. |
| `STEP_03_DETAIL_PLAN.md` | Create/Modify | Defines handoff and progress policy. |
| `STEP_03_01_DETAIL_PLAN.md` | Create/Modify | Captures the nested slice for step handoff content. |
| `STEP_03_02_DETAIL_PLAN.md` | Create/Modify | Captures the nested slice for progress calculation. |
| `STEP_03_03_DETAIL_PLAN.md` | Create/Modify | Captures the nested slice for the final handoff boundary. |

## 6. One-Loop Breakdown

| Loop | Single Target | Verification | Expected Output |
|---|---|---|---|
| LOOP-01 | Define step handoff content | Verify the handoff records completion facts only | Stable step handoff shape |
| LOOP-02 | Define progress update rule | Verify progress is based on completed phases | Clear progress calculation |
| LOOP-03 | Define final handoff boundary | Verify final deployment handoff does not replace step handoffs | Separated transition model |

## 7. UI Expected Preview
- Not required.
- Reason: This step is workflow metadata only.

## 8. QA Criteria
- Step handoff content must include verification result, next-step note, and scope candidate record if needed.
- Progress must be updated only after handoff completion.
- Final deployment handoff must remain distinct from step handoffs.

## 9. Handoff Requirements
- Step completion should record:
  - the handoff fields,
  - the progress formula,
  - the phase transition rule,
  - any issues that could cause handoff drift.
- The next step should receive:
  - the confirmed handoff structure,
  - the current progress model,
  - the final deployment boundary rule.

## 10. Stop Conditions
- Stop if:
  - progress is updated before the step handoff exists,
  - the final deployment handoff is made to absorb phase-only records,
  - the step handoff becomes a full project summary,
  - a policy file outside the V02 planning folder becomes necessary.
- User confirmation needed if:
  - a later loop must modify repo-wide harness policies,
  - a nested plan is required to define handoff fields,
  - runtime implementation work appears.
