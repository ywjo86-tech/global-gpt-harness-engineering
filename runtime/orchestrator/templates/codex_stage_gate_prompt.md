# Codex Stage Gate Prompt

Project path: $project_root
Run root: $run_root
Run ID: $run_id
Current phase: $current_phase

## Required Inputs
- DEVELOPMENT_PLAN: $development_plan_reference
- CHANGELOG: $changelog_reference
- app.log: $app_log_reference
- orchestration-state: $orchestration_state_reference

## Fan-In Summary
- received threads: $received_threads
- completed outputs: $completed_outputs
- missing outputs: $missing_outputs
- conflicts: $conflicts
- duplicate work: $duplicate_work
- requirement coverage: $requirement_coverage
- QA required: $qa_required
- next step decision: $next_step_decision
- final handoff readiness: $final_handoff_readiness

## Worker Handoff Reports
$worker_handoff_reports

## Approval Classification Summary
$approval_classification_summary

## Reviewer Instructions
Use the fan-in evidence and decide exactly one of:
- GO
- CONDITIONAL GO
- NO-GO

## Completion Criteria
$completion_criteria

