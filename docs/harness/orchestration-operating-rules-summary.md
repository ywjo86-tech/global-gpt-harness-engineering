# Orchestration Operating Rules Summary

## Purpose

This one-page summary captures the final operating rules for project orchestration in Global GPT Harness Engineering.
It is a quick reference, not a replacement for the detailed execution standard.

## Core Flow

1. Read `docs/DEVELOPMENT_PLAN.txt`, `CHANGELOG.txt`, and `logs/app.log` first.
2. Treat `docs/DEVELOPMENT_PLAN.txt` as the execution contract.
3. Create or refresh `docs/harness/orchestration-state.md`.
4. Split work into logical threads and run fan-out.
5. Collect outputs and run fan-in.
6. Request an independent stage-gate review.
7. Move to the next phase only after `GO` or `CONDITIONAL GO`.

## Approval Rules

- Classify mixed tasks by the highest-risk item.
- General work may continue inside the approved scope.
- Caution work still needs `승인`, `진행해`, `계속 진행`, or `OK 진행`.
- Dangerous work still needs `위험 확인 후 승인`.
- Stage-gate `GO` never replaces the Safety Warning Protocol.

## Project Start Checklist

- Global principles first.
- Orchestration and gate rules second.
- Project contract, change log, and activity log last.

## Role Split

- `project-orchestrator`: decomposes work, assigns threads, coordinates fan-out/fan-in, and requests the gate review.
- `stage-gate-reviewer`: independently decides `GO`, `CONDITIONAL GO`, or `NO-GO`.
- `qa-release-reviewer`: decides release and handoff readiness, not phase advancement.

## Fan-Out Rules

- Each thread must declare `thread_id`, assigned agent, input, expected output, validation criteria, merge point, and status.
- Fan-out only when work can proceed independently without editing the same artifact.
- Record the thread owner and conflict policy before execution.

## Fan-In Rules

- Check missing outputs, conflicts, duplicate work, requirement coverage, risk level, QA need, and alignment with the development plan.
- Do not treat thread outputs as final until fan-in synthesis is complete.
- Preserve the merged result in the orchestration state and report it explicitly.

## Stage Gate Rules

- The gate reviewer must inspect the current phase, changed files, validation method, evidence, and unresolved risks.
- The gate decision must be one of `GO`, `CONDITIONAL GO`, or `NO-GO`.
- `GO` and `CONDITIONAL GO` are the only decisions that allow progress.
- `NO-GO` means stop and remediate before the next phase.

## Required Records

- `docs/DEVELOPMENT_PLAN.txt`
- `CHANGELOG.txt`
- `logs/app.log`
- `docs/harness/orchestration-state.md`

## Standard Record Shape

- `decision`
- `phase`
- `completion_criteria_checked`
- `evidence_reviewed`
- `fan_in_reviewed`
- `open_questions`
- `remaining_risks`
- `next_step`
- `authorization` or `conditions` or `blocker_summary`

## Reporting

Every orchestration run should report:

- changed files
- validation method or commands
- validation results
- fan-out threads used
- fan-in decision
- stage-gate outcome
- remaining risks
- next step

## Boundaries

- Do not modify runtime code unless explicitly required.
- Do not bypass the stage gate.
- Do not replace the development plan with chat history.
- Do not create `.claude/` paths.
- Do not treat phase approval as safety approval.

## Quick Decision Guide

- `GO`: phase complete, next phase may start.
- `CONDITIONAL GO`: phase may advance only after listed conditions are satisfied.
- `NO-GO`: phase cannot advance.
