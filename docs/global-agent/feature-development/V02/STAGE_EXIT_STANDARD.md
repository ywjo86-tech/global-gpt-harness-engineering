# Stage Exit Standard

This document is the shared reference for the V02 stage-end policy and handoff review format.

## Stage Exit Condition

At the end of each step, the active detail plan must trigger a Stage Exit Review before moving on.

Required behavior:

1. Review known issues, test failures, security risks, and next-stage recommendations.
2. Fix safe and in-scope issues before advancing.
3. Record unresolved items as Known Issues or Deferred Items in the handoff.
4. Do not mark the step complete if completion criteria are not satisfied.
5. Keep same-stage remediation to one loop and one change target.

## Stage Exit Review

Every phase handoff must capture the stage exit result in a consistent structure.

Required sections:

1. Completion Criteria Check
2. Known Issues
3. Test Failures
4. Security Risks
5. Same-Stage Fixes Applied
6. Deferred Items
7. Next Stage Recommendation
8. Stage Exit Decision
9. Reason for Decision

Shared decision rules:

1. GO means the next stage may proceed.
2. CONDITIONAL GO means the next stage may proceed with recorded deferred items.
3. NO-GO means completion criteria were not met and the next stage must not proceed.
4. The project main agent makes the final stage exit decision.
5. The handoff must preserve the existing scope-control and approval rules.

## Usage Rule

Detail plans and handoff files should keep their local section headers, but the detailed policy lives here so future updates can be made in one place.
