# Orchestration State

> Updated: `2026-09-11`
>
> Scope: Global harness R4/R4.1/R4.2 ORCH04 integration and Gate progression

## Current Phase

- Active Gate: `G-4A-ACTUAL NO-GO remediation`
- Previous Gate: `G-ORCH-03 — GO`
- Output marker: `HARNESS_COMPLETION_CRITERIA_CLEAR=YES`
- Runtime worktree: integrated, dirty, uncommitted
- `proof97`: CONDITIONAL GO after independent G-4A re-review; evidence, Post-Quality, and handoff seal complete
- push: NOT AUTHORIZED

## Authority

- Authority index: `R4_AUTHORITY_INDEX.md`
- R4 base: preserved Architecture Freeze package
- R4.1: approved additive amendment
- R4.2: approved migration-quality authority amendment
- ISSUE-092: retired by append-only disposition; sealed R4.2 source row preserved

## Completed Evidence

- ORCH04 focused integration: 250 PASS / 3 skipped
- integrated root full regression: 1,060 PASS / 3 skipped
- G-ORCH-01 direct focused verification: 36 PASS / 0 skipped
- G-ORCH-01 independent decision: GO
- G-ORCH-02 direct focused verification: 97 PASS / 0 skipped
- G-ORCH-02 independent decision: GO
- G-ORCH-03 direct focused verification: 260 PASS / 4 skipped
- G-ORCH-03 independent decision: GO
- latest full local regression after Gate document updates: 1,060 PASS / 3 skipped
- G-4A-ACTUAL proof97 fixture plan: drafted, not execution-authorizing
- G-4A-ACTUAL live readiness command package: drafted, not executed
- G-4A-ACTUAL pre-proof regression: 1,060 PASS / 3 skipped
- actual Codex dynamic transport: 1 PASS / 0 skipped
- actual DEC-007 active Broker path: remediated and focused rerun PASS
- actual Codex worker fixture: 1 PASS / 0 skipped
- AF_UNIX gateway checks: 0 PASS / 2 skipped
- G-4A-ACTUAL independent decision: NO-GO
- G-4A-ACTUAL design diagnosis: valid direction, documentation-state labels corrected
- HOST synthetic smoke: BLOCKED at `UDS_BIND`
- HOST C+ smoke: BLOCKED at `SETUP`
- AF_UNIX bind outside restricted sandbox: PASS
- HOST synthetic smoke outside restricted sandbox: PASS
- AF_UNIX gateway tests outside restricted sandbox: 2 PASS / 0 skipped
- fresh live readiness outside restricted sandbox: READY plus adjacent recheck READY
- proof97 sealed fixture manifest: created for next proof attempt
- proof97 sealed fixture manifest: invalidated by WRITE-only registry remediation
- direct Broker WRITE with exact proof identity: PASS
- actual Codex WRITE with exact proof identity and WRITE-only registry: PASS
- same-`RUN_ID` duplicate WRITE risk with new provider call id: found and remediated
- actual restarted duplicate Codex WRITE probe: duplicate effect blocked, one
  intent/receipt preserved; second turn ended in `BROKER_BLOCKED`
- direct proof97 crash-after-durable-WRITE resume duplicate regression: PASS
- opt-in actual crash/resume duplicate regression with proof97 tuple: 1 PASS / 0 skipped
- independent single governed WRITE verifier: PASS
- frozen product-node verifier structure: 17 PASS / 0 skipped
- product-root opt-in frozen-node test: added, default skip without
  `HARNESS_PROOF97_PRODUCT_ROOT`
- actual product-owned frozen node execution through opt-in product-root test:
  1 PASS / 0 skipped
- proof97 Post-Quality / handoff seal: READY WITH FOLLOW-UP
- independent G-4A re-review: CONDITIONAL GO
- root post-rereview full regression: 1,067 PASS / 5 skipped
- post-product-root-opt-in-test full regression: 1,067 PASS / 5 skipped

The latest 1,060-test regression was re-run after the G-ORCH-02/G-ORCH-03/G-4A
documentation updates listed in this state file.

## Open Work

1. decide whether to commit the ORCH04 proof97 remediation packet.
2. do not push or deploy without separate authorization.

## Current Gate Boundary

G-4A-ACTUAL dangerous work was approved and actual checks were attempted. The actual
DEC-007 active Broker path timeout was remediated and the focused rerun passed. The
independent G-4A review returned NO-GO. The immutable A-to-B WRITE/crash/resume proof
story, frozen product nodes, independent verifier evidence, Post-Quality, and handoff
seal are now collected. Independent G-4A re-review returned CONDITIONAL GO. The restricted sandbox blocks AF_UNIX bind, but
outside-sandbox AF_UNIX synthetic smoke, gateway tests, and live readiness/recheck passed.
Direct Broker WRITE passes with exact proof identity. The latest actual Codex WRITE
probe also passes with exact proof identity and WRITE-only dynamic registry, producing
one tool call, one intent, one receipt, one governed effect, and the expected fixture
digest. A same-`RUN_ID` duplicate WRITE risk with a new provider call id was found and
remediated; direct duplicate probing now blocks both same-call and new-call reruns with
one intent and one receipt preserved. A restarted actual Codex duplicate probe also
attempted the duplicate WRITE once and preserved one intent/receipt plus the first WRITE
content, with the duplicate-blocked turn now terminating as bounded `BROKER_BLOCKED`.
A direct proof97 crash-after-durable-WRITE test now injects the expected crash after
intent/receipt commit and verifies same-`RUN_ID` resume duplicate blocking. An
independent single governed WRITE verifier now passes for the effect invariant. The
frozen-node verifier structure also passes. After explicit dangerous-work authorization,
the product-root opt-in frozen-node test was executed against the actual product checkout
and passed. Post-Quality and handoff readiness are sealed as READY WITH FOLLOW-UP. The
remaining project-management item is whether to commit the uncommitted remediation packet.
Deployment, commit, and push are not authorized.
