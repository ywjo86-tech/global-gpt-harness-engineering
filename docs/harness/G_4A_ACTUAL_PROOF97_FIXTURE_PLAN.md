# G-4A-ACTUAL Proof97 Fixture Plan

> Status: **DRAFT FIXTURE PLAN — G-4A REVIEWED NO-GO**
>
> Prepared: `2026-09-10`
>
> Authority basis: G-ORCH-01 `GO`, G-ORCH-02 `GO`, G-ORCH-03 `GO`,
> `G_4A_ACTUAL_READINESS_PLAN.md`

## 1. Purpose

This document fixes the proposed proof97 fixture shape. Partial actual-readiness probes
have now run under user dangerous-work approval, but the fixture itself is still not
sealed or executable as proof97 evidence. It does not authorize actual Broker WRITE,
product mutation, proof97 completion, deployment, commit, push, package installation, or
external network use.

## 2. Fixture Identity

The actual proof fixture must be immutable before execution:

| Field | Planned value |
|---|---|
| proof id | `proof97` |
| Gate | `G-4A-ACTUAL` |
| task reference | `TASK-ORCH-04 / TASK-4A-08` |
| run mode | actual proof with crash/resume |
| run identity | fixed once at approval time; must not be regenerated during resume |
| execution profile | installed Codex + canonical Broker path |
| mutation scope | workspace-owned fixture files only |
| proof status before approval | `HOLD` |

## 3. Immutable Inputs Required Before Execution

The proof package must pin these inputs by exact value and digest:

- current authority index and Gate decision documents.
- active contract/package digest.
- run-specific plan digest and requirement digest.
- owned-file manifest and expected before/after digest set.
- frozen completion criteria snapshot.
- product-owned frozen test node list.
- expected mutation description.
- crash injection point.
- resume cursor expectation.
- expected final verifier command set.
- reviewer hard-stop criteria.

Any byte change in a pinned input requires rebuilding the fixture and re-running the
pre-proof regression.

## 4. Required Execution Story

The actual proof must demonstrate this exact sequence:

1. collect fresh live `CodexAuthReadinessEvidence=READY` adjacent to launch.
2. build canonical package and preflight with the approved run identity.
3. launch the installed Codex worker through the canonical Broker path.
4. perform exactly one approved Broker WRITE against an owned fixture file.
5. persist bounded Intent/Receipt and effect evidence without raw secret retention.
6. force the expected crash point after durable evidence is committed.
7. resume with the same `RUN_ID` and same package lineage.
8. prove no duplicate Worker, effect, or checkpoint occurred after resume.
9. execute product-owned frozen test nodes.
10. execute the independent verifier.
11. seal Post-Quality and handoff evidence.

## 5. Pre-Proof Commands To Authorize Later

These commands were candidates for the live-proof approval package. Some have now been
executed as partial probes and are recorded in `G_4A_ACTUAL_PROOF97_ATTEMPT_EVIDENCE.md`.
They are not sufficient proof97 evidence because the immutable WRITE/crash/resume story
has not run.

```text
HARNESS_RUN_ACTUAL_CODEX_TRANSPORT=1 python3 -m unittest -v tests.test_codex_dynamic_transport.CodexDynamicTransportTests.test_installed_codex_01501_actual_dynamic_transport
```

```text
HARNESS_RUN_ACTUAL_CODEX_TRANSPORT=1 python3 -m unittest -v tests.test_production_tool_transport.ProductionToolTransportTests.test_installed_codex_uses_dec007_active_broker_path
```

```text
HARNESS_RUN_ACTUAL_CODEX_FIXTURE=1 python3 -m unittest -v tests.test_production_worker_executor.ProductionWorkerExecutorTests.test_actual_codex_child_implements_tests_and_commits
```

The AF_UNIX gateway checks skipped in the local sandbox must either run in an environment
that permits AF_UNIX bind/smoke or receive an equivalent reviewer-accepted production
transport evidence package.

## 6. Acceptance Criteria

The proof fixture is acceptable only if all conditions hold:

- live readiness is fresh and secret-free.
- package, preflight, Worker, Review, checkpoint, exit, and handoff records are digest
  bound.
- Worker cannot self-approve completion.
- unknown, unowned, wildcard, or sensitive paths fail closed.
- exact Broker WRITE count is one for the approved mutation.
- resume consumes the prior durable attempt rather than launching a blind duplicate.
- post-resume duplicate Worker/effect/checkpoint count is zero.
- frozen product tests pass from frozen nodes, not live-edited test definitions.
- independent actual verifier passes.
- security evidence is bounded and contains no raw secret values.
- `ISSUE-025` actual-security requirement is either satisfied by evidence or explicitly
  dispositioned by the Gate reviewer.

## 7. Blockers

proof97 must remain `HOLD` if any of these are true:

- fresh live readiness is absent or stale.
- fixture identity is mutable or regenerated during resume.
- installed Codex/Broker evidence is missing.
- AF_UNIX or equivalent production transport evidence is missing.
- actual Broker WRITE evidence is absent or duplicated.
- crash/resume lineage changes `RUN_ID`, package, task, or owned-file scope.
- product frozen nodes are not executed.
- independent verifier is missing.
- `ISSUE-025` remains without accepted actual-security evidence or disposition.
- Safety Warning Protocol approval has not been granted.

## 8. Required Approval Text Before Execution

Because the actual proof can run live Codex and perform actual Broker WRITE/product
mutation, it is dangerous work. The required user approval phrase is:

```text
위험 확인 후 승인
```

Without that phrase, the next allowed work remains preparation, review, and documentation
only.
