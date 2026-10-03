# Full Plan TDD Continuation V1 Design

## Goal
Persist pre-declared TDD RED intent and continuation evidence so approved implementation work can resume after session/runner interruption without creating new execution or approval authority.

## Authority boundary
- Full Plan remains continuation/single-writer authority.
- Existing worker/Router/MPRF/Gateway/Full MCP remain the only execution/effect paths.
- OCP remains control transport; AI Office remains governance/read-model.
- `next_action` is evidence only; resume revalidates source, approval, authority and environment.
- Dangerous operations and P5/P6 remain outside TDD expected-RED semantics.

## Mode
`LEGACY` is the default and does not add fields to legacy job policy. `TDD_V1` is explicit and authority-core sealed.

## Durable contract
`ExpectedRedContractV1` binds project/run/task/cycle, source SHA, authority digest, focused test selector, test-command digest, dependency/environment digest, expected failure semantic signature/count/error allowance, validity boundary, remediation path scope and attempt budget.

## State machine
`RED_ARMED -> RED_RUNNING -> GREEN_READY -> GREEN_RUNNING -> FOCUSED_VALIDATION -> REGRESSION_VALIDATION -> COMPLETED`.
Any unplanned RED observation, validation failure, drift, expiry or unsafe reconciliation fails closed to `BLOCKED`.

## Crash/restart
Contract and checkpoint are durable under the Harness state root. Full Plan run lock protects mutations. `GREEN_RUNNING` is never blind-retried; boot reports reconciliation required until a canonical effect receipt is supplied.

## Compatibility
Legacy jobs omit the mode field and retain existing semantics. Existing Gate continuation, per-Gate approvals, dangerous-work approval and P5/P6 migration controls are unchanged.
