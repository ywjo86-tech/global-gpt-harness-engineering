# Orchestration Execution Standard

## Purpose

This standard defines how Codex should execute project work in Global GPT Harness Engineering.
It exists to prevent silent phase skipping, missing fan-out/fan-in, and next-step drift.
The executable local runtime for this standard lives in `runtime/orchestrator/cli.py`.

## Core Rules

1. Read `docs/DEVELOPMENT_PLAN.txt`, `CHANGELOG.txt`, and `logs/app.log` before starting or resuming project work.
2. Treat `docs/DEVELOPMENT_PLAN.txt` as the execution contract for the project.
3. Create or update `docs/harness/orchestration-state.md` for the project before moving between phases.
4. Use `project-orchestrator` to split work into logical threads, then use `project-execution` to materialize runnable worker slices for fan-out/fan-in.
5. Use `stage-gate-reviewer` for an independent phase-transition decision.
6. Do not start the next phase without `GO` or `CONDITIONAL GO`.
7. Record why user intervention is required whenever the workflow cannot proceed safely.
8. Classify each task slice by the highest-risk item it contains and request the appropriate user approval when the slice includes caution or dangerous work.

## Project Start Checklist

For every project, follow this sequence before proceeding:

1. Read global principles.
2. Read orchestration and stage-gate rules.
3. Read project contract, change log, and activity log.
4. Proceed only after the current phase and gate status are clear.

## Preflight Order

When a project is started or restarted, the execution order is:

1. Read the existing development plan.
2. Read the change log.
3. Read the latest log file entries.
4. Identify the current phase and required outputs.
5. Identify which agents are needed for the next work slice.
6. Create or refresh orchestration state.
7. Dispatch bounded threads only after the phase boundary is clear.

## Project-Orchestrator Responsibilities

The project orchestrator owns:

- work decomposition
- agent selection
- logical thread assignment
- fan-out instructions
- output collection
- fan-in synthesis
- user-intervention logging
- stage-gate request routing

The project execution agent owns:

- materializing runnable thread slices from the persisted planning artifact
- preserving the planner/executor boundary
- preparing the runtime thread payloads before dispatch

Each thread must declare:

- thread id or thread name
- assigned agent
- input materials
- expected output
- validation criteria
- merge point
- forbidden areas

## Fan-Out and Fan-In

Fan-out is required when independent work can proceed without editing the same artifact.

For each fan-out thread, record:

- thread id
- owner
- input
- output
- validation criteria
- merge point
- conflict policy

For fan-in, the orchestrator must check:

- missing outputs
- conflicting assumptions
- duplicate work
- requirements coverage
- risk level
- QA need
- whether the merged result still matches the development plan

## Stage Gate Review

The stage-gate reviewer is independent from the project orchestrator.
It decides one of:

- `GO`
- `CONDITIONAL GO`
- `NO-GO`

Rules:

- `GO` means the phase is complete and the next phase may start.
- `CONDITIONAL GO` means the phase may advance only after the listed conditions are satisfied.
- `NO-GO` means the phase is not complete and the next phase must not start.
- If the stage gate reviewer has not issued `GO` or `CONDITIONAL GO`, the workflow must remain in the current phase.

The stage gate reviewer must inspect:

- the current phase in `docs/DEVELOPMENT_PLAN.txt`
- the actual changed files
- the validation method and results
- unresolved risks and open questions
- orchestration state for the current project

## User Intervention

If user input is required, the orchestrator must state:

- why the input is needed
- what decision is blocked
- the options the user can choose from
- the phase that remains paused

Do not ask for vague confirmation when the question is about missing evidence or an unresolved phase gate.

## Approval Boundary

- `GO` and `CONDITIONAL GO` are phase-transition judgments only.
- They do not replace the Safety Warning Protocol.
- General work may continue within the already approved scope.
- Caution work still requires a user `승인`, `진행해`, `계속 진행`, or `OK 진행`.
- Dangerous work still requires `위험 확인 후 승인`.
- If a task mixes categories, classify it by the highest-risk item.

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

### Required Record Shape

Use a consistent record shape so fan-in and stage-gate outcomes can be compared across projects.

#### Fan-Out Thread Record

Each thread record must include:

- `thread_id`
- `assigned_agent`
- `input`
- `expected_output`
- `validation_criteria`
- `merge_point`
- `status`

#### Fan-In Review Record

Each fan-in record must include:

- `threads_received`
- `completed_outputs`
- `missing_outputs`
- `conflicts`
- `duplicate_work`
- `requirement_coverage`
- `risk_summary`
- `qa_required`
- `next_step_decision`
- `final_handoff_readiness`

#### Stage Gate Record

Each stage gate record must include:

- `decision` with one of `GO`, `CONDITIONAL GO`, or `NO-GO`
- `phase`
- `completion_criteria_checked`
- `evidence_reviewed`
- `conditions`, when the decision is `CONDITIONAL GO`
- `remaining_risks`
- `next_step`

#### GO Decision Template

Use this exact shape when the stage gate reviewer returns `GO`:

```text
decision: GO
phase: <current phase>
completion_criteria_checked: yes
evidence_reviewed: <comma-separated evidence list>
fan_in_reviewed: yes
open_questions: none
remaining_risks: <concise risk list or none>
next_step: <authorized next phase>
authorization: next phase may start
```

#### CONDITIONAL GO Decision Template

Use this exact shape when the stage gate reviewer returns `CONDITIONAL GO`:

```text
decision: CONDITIONAL GO
phase: <current phase>
completion_criteria_checked: yes
evidence_reviewed: <comma-separated evidence list>
fan_in_reviewed: yes
open_questions: <brief list or none>
remaining_risks: <concise risk list or none>
next_step: <authorized next phase after conditions are satisfied>
conditions: <explicit condition list>
authorization: next phase may start after conditions are satisfied
```

#### NO-GO Decision Template

Use this exact shape when the stage gate reviewer returns `NO-GO`:

```text
decision: NO-GO
phase: <current phase>
completion_criteria_checked: yes
evidence_reviewed: <comma-separated evidence list>
fan_in_reviewed: yes
open_questions: <brief list or none>
remaining_risks: <concise blocker list>
next_step: <blocked next step or remediation path>
blocker_summary: <concise reason the next phase cannot start>
```

#### Log Line Format

Use one line per validation or gate event:

`timestamp | record_type | project | phase | decision | evidence | next_step`

## Boundaries

- Do not create `.claude/` paths.
- Do not modify runtime code unless a task explicitly requires it.
- Do not bypass the stage gate by continuing directly to the next phase.
- Do not replace the development plan with chat history.
- Do not treat stage-gate approval as a substitute for user safety approval.
