# Two-Action Full Plan Governance V1 Implementation Plan

**Spec:** `docs/superpowers/specs/2026-10-01-two-action-full-plan-governance-design.md`

## Global constraints

- TDD: every production behavior starts with a failing test.
- Preserve existing legacy/per-Gate approval behavior.
- No PR merge, runtime-current switch, production activation, service restart, reboot, P5, or P6 execution.
- No `git reset`, `git clean`, or `git stash` operational dependency.
- Feature/work-branch commits and PR/CI are implementation-scope effects only.
- P5/P6 policy is contract-only in this plan; lifecycle execution remains HOLD.

## Task 1 — RED: two-action post-final-approval policy

Files:
- modify `tests/test_user_interaction_policy.py`

Add failing tests proving:
- legacy `evaluate_user_decision()` still requests risk escalation;
- new two-action adapter returns fail-closed after final approval instead of requesting a third approval;
- before final approval it still requests the dangerous-work approval.

Expected RED: import/attribute or assertion failure because the adapter does not exist.

## Task 2 — GREEN: two-action policy adapter

Files:
- modify `runtime/orchestrator/user_interaction_policy.py`

Implement the smallest adapter and result type needed by Task 1. Do not change legacy evaluator semantics.

Verification:
- `python3 -m unittest -v tests.test_user_interaction_policy`

## Task 3 — RED: dangerous-work package contract

Files:
- add `tests/test_dangerous_work_package.py`

Tests:
- canonical deterministic digest;
- unknown/duplicate operation rejected;
- expiry ordering validated;
- P6 without P5 rejected;
- P6 before P5 rejected;
- P6 package missing `SUCCESSOR_HEALTH_AFTER_PREDECESSOR_QUIESCE` rejected;
- PR #33 package and P5/P6 package can be represented separately without implicit cross-authority.

Expected RED: package module absent.

## Task 4 — GREEN: dangerous-work package contract

Files:
- add `runtime/orchestrator/dangerous_work_package.py`

Implement closed dataclass contract, parsing, canonical projection, digest, and P5/P6 structural invariants only.

Verification:
- `python3 -m unittest -v tests.test_dangerous_work_package`

## Task 5 — RED: dangerous-work approval and coverage bridge

Files:
- add `tests/test_dangerous_work_authorization.py`

Tests:
- package digest mismatch rejected;
- project/run mismatch rejected;
- expired approval rejected;
- coverage operations/risk classes derive only from package;
- requested protected operation outside package rejected;
- source/target drift rejected;
- unsafe dangerous re-execution rejected;
- P6 blocked until post-P5 verifier PASS;
- approved P5/P6 sequence passes only with barrier evidence.

Expected RED: authorization module absent.

## Task 6 — GREEN: authorization bridge and protected-operation guard

Files:
- add `runtime/orchestrator/dangerous_work_authorization.py`

Implement `DangerousWorkApprovalV1`, verification, conversion to `ApprovalCoverageEvidence`, and `authorize_protected_operation()`.

Verification:
- `python3 -m unittest -v tests.test_dangerous_work_authorization`

## Task 7 — RED/GREEN: exact two-action integration contract

Files:
- add `tests/test_two_action_user_contract.py`

Integration tests:
- action #1 ordinary implementation path requires no intermediate approval in policy layer;
- action #2 package approval covers every sealed protected operation;
- any post-action-2 unsealed operation fails closed rather than asking for action #3;
- no path treats GitHub App comment provenance as user approval;
- feature branch push is implementation-scope operation, protected push is dangerous-scope operation.

Add only minimal production helpers required by these tests. Prefer existing modules over new orchestration.

## Task 8 — P5/P6 retirement authority regression

Files:
- add `tests/test_p5_p6_retirement_authority.py`

Prove:
- P5 may be packaged but this implementation does not execute it;
- P6 structurally requires P5 and the post-P5 successor-health barrier;
- separate AI Office release and lifecycle retirement packages cannot share package digest/authority accidentally.

## Task 9 — focused and broader regression

Run:
- new focused tests;
- `tests.test_user_interaction_policy`;
- existing approval/Full Plan/DCC/runtime migration tests;
- repository full regression;
- compileall;
- `git diff --check`.

Document baseline-only failures separately; any current-only failure blocks completion.

## Task 10 — handoff

Feature branch / PR only.

Report:
- exact head;
- focused/full-regression results;
- any baseline failures;
- `P5=HOLD`, `P6=HOLD`;
- external OAuth issuer gap if dedicated dangerous-work issuance remains unavailable.

Do not merge or activate runtime in this plan.
