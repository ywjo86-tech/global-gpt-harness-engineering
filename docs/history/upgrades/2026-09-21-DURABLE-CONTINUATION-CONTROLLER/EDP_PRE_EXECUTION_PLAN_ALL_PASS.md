# DCC Harness-Wide Remediation — Pre-Execution Plan EDP

**Date:** 2026-09-21
**Protocol:** `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` / EDP-1.0
**Approved Amendment:** `docs/superpowers/specs/2026-09-21-dcc-harness-wide-operational-remediation-design.md`
**Approved Amendment SHA256:** `6a46268f1b0b4a7e23b5be62642bbe8973d2ad6dd9f17534a0032aac56edad03`
**Approval evidence:** `docs/history/upgrades/2026-09-21-DURABLE-CONTINUATION-CONTROLLER/AMENDMENT_USER_APPROVAL_RESEAL.md`
**Stable executable baseline:** `a40626c31353f90c0d4c9e677d3886ea5ccce393`

## Decision

`EDP_PRE_EXECUTION_DECISION=ALL_PASS_PLAN_READY`

The approved Harness-wide Amendment has been translated into one coordination plan plus four bounded implementation subplans with complete requirement/finding traceability, explicit dependency order, authority negative-space boundaries, and separate publication effect gating. No plan-level BLOCKER or MAJOR remains.

This is **not** a claim that the sixteen runtime findings are already fixed. They remain implementation findings until the planned code changes and post-implementation EDP close them. Implementation execution remains `USER_PLAN_REVIEW / EXECUTION_METHOD / EXECUTION_APPROVAL` gated.

## Plan Set and Immutable Digests

| Plan | SHA256 |
|---|---|
| `docs/superpowers/plans/2026-09-21-dcc-hwo-a-continuation-core-authority.md` | `f63cca2afff7386c7b6a9a4b8dfdafc8f2e9927ceae1becd611ada12d5934a2d` |
| `docs/superpowers/plans/2026-09-21-dcc-hwo-b-wait-operator-attention.md` | `595a2eb68a9b4e0c5c7d7c9ee552682b5e5a45fd8a71a7457d7bc5e27b841921` |
| `docs/superpowers/plans/2026-09-21-dcc-hwo-c-evidence-effects-persistence.md` | `0c11a836f0ab0c76a2e71e1f482d4ebc37eb259748d60e60fb8fc3cd38d25304` |
| `docs/superpowers/plans/2026-09-21-dcc-hwo-coordination.md` | `ee9257e4ffda67fca57d78f3d53e601127d414baef675ab09893db48f3099a42` |
| `docs/superpowers/plans/2026-09-21-dcc-hwo-d-publication-rollback-qualification.md` | `b754ed66141e3042f31a4d047e1a4130990b183a47ee670ddd0c4bd08ae9eb15` |

The previous single plan `docs/superpowers/plans/2026-09-21-durable-continuation-controller.md` is marked `SUPERSEDED-FOR-EXECUTION / HISTORICAL-REFERENCE-ONLY`.

## Static Plan Integrity Evidence

- Automated Spec/Plan audit: `26/26 PASS`.
- HWO requirements: `20/20` directly traceable.
- Original DCC MUST requirements: `20/20` directly preserved/mapped.
- HWO acceptance criteria: `15/15` directly traceable.
- Harness-wide findings: `16/16` assigned to closure tasks.
- Plan documents: `5/5` bind approved Amendment SHA and remain `EXECUTION-APPROVAL-PENDING`.
- Placeholder scan: PASS; no `TBD`, `TODO`, `implement later`, ellipsis placeholders, or undefined fixture references.
- Shared test fixture references: all referenced `fixture_*` helpers are declared in the coordination-plan fixture contract.
- `git diff --check`: PASS.

## Dependency / Ownership Diagnosis

Required order is sealed as:

```text
C0 stable state-root foundation
 -> A continuation core & authority
 -> B wait/operator/attention
 -> C1-C4 effect evidence/lock/retention
 -> A+B+C integration regression + pre-publication EDP
 -> D publication/rollback/live qualification
 -> final Harness-wide EDP
```

Key ownership boundaries remain explicit:

- Full Plan: Task/Gate/fan-in/next-state only.
- Router/MPRF: provider/model selection and runtime/health facts only.
- Full MCP: governed effect execution and effect journal only.
- DCC: mechanical continuation inside sealed Full Plan authority only.
- Wait recovery: classification/re-evaluation; no provider or approval authority.
- Operator checkpoint: evidence-only, `control_authority=NONE`.
- Attention: outbound-only, `control_authority=NONE`; live transport needs separate deployment authorization.
- RuntimeMigrationTransaction: runtime activation/successor/reverse-activation authority; Workstream D may not bypass it.

## Finding Closure Plan Coverage

- F001 self-mutating executor runtime -> C0 + A0 immutable runtime/project/state separation.
- F002/F003 contract/builder weakness -> A1 exact wire contract + production per-Gate mapping.
- F004 lineage -> A2 approved-base/ancestry/previous-receipt/tree proof.
- F005/F006 wait/transaction taxonomy -> B0 + A3.
- F007 validation/publication identity -> D0.
- F008 Operator handoff -> B2 evidence-only safe-yield checkpoint.
- F009/F010 Attention delivery/backlog -> B3/B4.
- F011 provider/resource wait owner -> B0/B1.
- F012 effect evidence -> C1 canonical ToolEffectJournal reconciliation.
- F013 worktree-coupled durable state -> C0/C3 stable root and cleanup proof.
- F014 lock hierarchy -> C2 run-lock-first fencing.
- F015 unsafe publication rollback window -> D1/D2/D4 migration-v2 + actual reverse activation.
- F016 no live canary -> D3/D4 active-runtime 3+ Gate AUTO canary.

## Fresh Baseline Regression Evidence

### Cross-domain focused

`235/235 PASS` using current environment for Full Plan, receipts, migration, user policy, exit guard, Attention, Router, Full MCP effect evidence, runtime release, OmniRoute, and continuity surfaces.

### Full repository regression — authoritative environment

Command environment: `/tmp/gch-edp-allpass-venv/bin/python` (contains required `mcp` dependency).

```text
Ran 1887 tests in 64.411s
OK (skipped=15)
FULL_VENV_RC=0
COMPILE_RC=0
DIFF_RC=0
```

### Diagnostic environment RCA

A first full run used system `python3` and produced `1869 tests`, `1 failure`, `4 errors`. The four errors were `ModuleNotFoundError: mcp`. The remaining LV package test also passed when rerun under the authoritative EDP venv. Therefore that failed run is classified as `VALIDATION_ENVIRONMENT_DRIFT`, not source regression. No source fix was applied.

## Adversarial Plan Checks

- Implementation run cannot bind mutable worktree as executor runtime.
- Stable state root precedes new DCC evidence creation.
- AUTO is explicit per-Gate and legacy stays manual.
- Generic `WAITING_RESOURCE` auto-resume is absent.
- Provider recovery reuses sealed Router request/eligibility/output digests.
- Operator checkpoint has no resume/dispatch authority.
- Live notification transport is not authorized by implementation approval.
- Governed effects require canonical journal reconciliation.
- Lock order and stale-epoch checks are explicit.
- Workstream D starts only after A-C integration EDP.
- Publication/runtime/systemd/network effects have a second explicit effect gate.
- Active-runtime qualification occurs before predecessor close.
- Rollback uses reverse activation, not bookkeeping-only `ROLLED_BACK`.
- Live canary requires foreground Operator loss and systemd/reconciler completion.

## Closure Metrics

```text
PLAN_BLOCKER_COUNT=0
PLAN_UNRESOLVED_MAJOR_COUNT=0
PLAN_UNRESOLVED_MINOR_COUNT=0
HWO_MUST_COVERAGE=20/20
ORIGINAL_DCC_MUST_COVERAGE=20/20
HWO_AC_COVERAGE=15/15
FINDING_PLAN_COVERAGE=16/16
PLACEHOLDER_OPEN_COUNT=0
UNDEFINED_TEST_FIXTURE_COUNT=0
CROSS_DOCUMENT_MATERIAL_CONFLICT_COUNT=0
AUTHORITY_NEGATIVE_SPACE_PLAN_STATUS=PASS
BASELINE_FOCUSED_REGRESSION=235/235_PASS
BASELINE_FULL_REGRESSION=1887_PASS_15_SKIPPED
VALIDATION_ENVIRONMENT_RCA=RESOLVED_AS_ENVIRONMENT_DRIFT
RUNTIME_FINDINGS_IMPLEMENTED=0/16
IMPLEMENTATION_EXECUTION_STATUS=NOT_STARTED
EDP_PRE_EXECUTION_DECISION=ALL_PASS_PLAN_READY
```

## Execution Disposition

The plan set is ready for user review and execution-method selection. No implementation source code has been changed. Implementation may begin only after the user approves the plan set/execution method. Workstream D still requires a later separate publication/runtime effect approval even if A-C implementation is approved.
