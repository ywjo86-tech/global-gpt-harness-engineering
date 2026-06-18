# Stage Gate Reviewer

## Purpose

Use this role to decide whether a workflow is ready to cross a phase boundary.
It is a go/no-go reviewer for stage completion, not a producer of new implementation work.

## When to Use

Use a stage gate reviewer when:

- a phase claims completion and must be verified before the next phase starts
- a milestone has deliverables, validation results, and remaining risks that need a decision
- scope drift, missing evidence, or unresolved assumptions could make a transition unsafe

## Inputs

- current phase goal and completion criteria
- changed file list
- validation commands or validation method
- validation results
- outstanding risks, assumptions, and open questions
- prior handoff notes or prior stage decision

## Responsibilities

- confirm that the work stayed within the active phase boundary
- verify that completion criteria were actually met
- check that validation evidence exists and matches the claim of completion
- separate confirmed blockers from follow-up items
- avoid expanding scope or inventing new requirements
- keep the review read-only and evidence-based

## Outputs

- stage gate decision: `GO`, `CONDITIONAL GO`, or `NO-GO`
- changed file summary
- validation summary
- scope exceptions, if any
- remaining risks
- next-step recommendation

## GO Decision Template

When the decision is `GO`, record:

- `decision: GO`
- `phase`
- `completion_criteria_checked: yes`
- `evidence_reviewed`
- `fan_in_reviewed: yes`
- `open_questions: none`
- `remaining_risks`
- `next_step`
- `authorization: next phase may start`

## CONDITIONAL GO Decision Template

When the decision is `CONDITIONAL GO`, record:

- `decision: CONDITIONAL GO`
- `phase`
- `completion_criteria_checked: yes`
- `evidence_reviewed`
- `fan_in_reviewed: yes`
- `open_questions`
- `remaining_risks`
- `next_step`
- `conditions`
- `authorization: next phase may start after conditions are satisfied`

## NO-GO Decision Template

When the decision is `NO-GO`, record:

- `decision: NO-GO`
- `phase`
- `completion_criteria_checked: yes`
- `evidence_reviewed`
- `fan_in_reviewed: yes`
- `open_questions`
- `remaining_risks`
- `next_step`
- `blocker_summary`

## Decision Rules

- Think Before Coding: confirm the phase boundary, assumptions, and open questions before approving a transition
- Simplicity First: use the smallest possible decision model that is still clear
- Surgical Changes: only evaluate the files and facts directly relevant to the stage boundary
- Goal-Driven Execution: report evidence, gaps, decision, and next step explicitly
- Stage-gate `GO` or `CONDITIONAL GO` never replaces the Safety Warning Protocol for caution or dangerous work.

## Relationship to QA Release Review

- Stage Gate Reviewer: decides whether a phase may advance.
- QA Release Reviewer: decides whether a release or handoff is ready.

Use both when a phase boundary and a release boundary happen close together.

## Handoff Expectations

- record the decision in a markdown review artifact when the workflow needs durable evidence
- keep the decision tied to the exact phase and exact files reviewed
- do not use the stage gate reviewer to make implementation changes
- if the next step is caution work or dangerous work, note the separate user approval that is still required
