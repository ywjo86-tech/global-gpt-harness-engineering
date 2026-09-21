# Operator Turn Bounded Execution Policy

Status: ACTIVE
Authority: GPT Operator / Full Plan execution safety policy

## Purpose
Prevent a user-facing execution turn from exhausting its available execution window before durable continuation evidence exists.

## Mandatory rules
1. Each implementation task runs its focused validation before checkpoint/commit.
2. A new task starts only when caller-supplied estimated work plus reserve fits inside the caller-supplied soft turn budget.
3. If the reserve would be crossed, a durable task checkpoint is required before the turn may yield.
4. In-flight long work may yield only when both its durable checkpoint and durable process/log continuation evidence exist.
5. Generic full regression is scheduled at Gate closure and Final EDP, not redundantly after each ordinary task. A separately required acceptance proof remains governed by its explicit plan requirement.
6. A bounded turn yield is a non-terminal report, never successful completion.
7. This policy has no planning, routing, provider-selection, approval, or effect authority.

## Interfaces
`runtime/orchestrator/operator_turn_budget.py` provides budget classification. `runtime/orchestrator/operator_exit_guard.py` may report `REPORT_BOUNDED_CHECKPOINT` only when a durable turn checkpoint exists.

## Durable checkpoint contract
New governed flows use `orchestration.operator-turn-checkpoint.v1` evidence instead of an unbound boolean. The checkpoint binds project/run/stage, `authority_core_sha256`, owner kind/reference, resume-contract digest, and last semantic progress. It has `control_authority=NONE`: it cannot dispatch, resume, approve, route, select a provider, or execute effects. `operator_exit_guard` may accept a bounded yield only when the checkpoint validates and matches the current Full Plan project/run/authority. The legacy `durable_turn_checkpoint` boolean remains compatibility-only for historical callers/tests and does not create authority.
