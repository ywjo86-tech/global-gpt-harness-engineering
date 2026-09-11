# G-4A-ACTUAL Design Diagnosis

> Status: **DIAGNOSED — DESIGN VALID, STATE UPDATED**
>
> Date: `2026-09-10`
>
> Scope: G-4A proof97 fixture plan, live-readiness command package, and NO-GO remediation path

## 1. Diagnosis Summary

The G-4A design direction is valid. The plan correctly identifies that proof97 cannot
advance without:

- AF_UNIX or reviewer-accepted equivalent production transport evidence.
- fresh live readiness plus adjacent recheck.
- sealed immutable proof97 fixture.
- actual Broker WRITE.
- expected crash and same-`RUN_ID` resume.
- duplicate Worker/effect/checkpoint count of zero.
- frozen product nodes.
- independent verifier, Post-Quality, and handoff.

No core requirement conflict was found between the fixture plan, command package, and
G-4A NO-GO decision.

## 2. Design Issues Found

Two documentation-state issues were found:

- `G_4A_ACTUAL_LIVE_READINESS_COMMAND_PACKAGE.md` still said `NOT EXECUTED` even though
  partial actual probes had already run.
- `G_4A_ACTUAL_PROOF97_FIXTURE_PLAN.md` still read like a pre-execution-only plan even
  though G-4A had already received a NO-GO review.

These were state-label issues, not proof logic errors. They were corrected so future
handoff does not confuse partial probe evidence with unexecuted planning.

## 3. Direct Follow-Up Evidence

After the documentation-state correction, AF_UNIX/equivalent transport evidence was
attempted.

### One-command HOST synthetic smoke

Command:

```text
python3 -m runtime.orchestrator.host_synthetic_smoke
```

Result:

```text
RESULT=HOST_SYNTHETIC_BLOCKED FAIL_STAGE=UDS_BIND UDS=FAIL PEER=NOT_REACHED REQUEST_BINDING=NOT_REACHED RESULT_BINDING=NOT_REACHED LEDGER=NOT_REACHED DUPLICATE_RERUN=NOT_REACHED ADOPTION=NOT_REACHED
```

Effect:

- local environment still does not provide the required AF_UNIX bind evidence.

### HOST C+ smoke

Command:

```text
python3 -m runtime.orchestrator.host_cplus_smoke
```

Result:

```text
RESULT=HOST_CPLUS_BLOCKED FAIL_STAGE=SETUP JSONL_VALID=NOT_EVALUATED STDERR_SECURITY=NOT_EVALUATED FINAL_MESSAGE=NOT_EVALUATED
```

Effect:

- C+ smoke did not provide equivalent production transport evidence in this environment.

## 4. Resolution Check

The current sandbox blocks AF_UNIX bind, but the same probe succeeds outside the sandbox.
Therefore the blocker is an execution sandbox policy, not a harness design defect.

Direct checks:

```text
AF_UNIX bind inside sandbox: PermissionError [Errno 1] Operation not permitted
AF_UNIX bind outside sandbox: PASS
```

The required AF_UNIX evidence was then executed outside the sandbox.

### HOST synthetic smoke outside sandbox

Command:

```text
python3 -m runtime.orchestrator.host_synthetic_smoke
```

Result:

```text
RESULT=HOST_SYNTHETIC_PASS UDS=PASS PEER=PASS REQUEST_BINDING=PASS RESULT_BINDING=PASS LEDGER=PASS DUPLICATE_RERUN=NO ADOPTION=PASS
```

### AF_UNIX gateway tests outside sandbox

Command:

```text
python3 -m unittest -v tests.test_production_execution_gateway.GatewayContractTests.test_authenticated_uds_runner_round_trip_and_durable_ledger tests.test_production_execution_gateway.GatewayContractTests.test_one_command_synthetic_smoke_is_production_free
```

Result:

```text
Ran 2 tests in 0.177s
OK
```

## 5. Current Design Decision

The AF_UNIX/equivalent transport blocker has a confirmed solution:

```text
run the AF_UNIX evidence commands outside the restricted sandbox
```

The design still is not cleared for proof97 execution, because the remaining proof97
story requires fresh readiness, sealed fixture, actual WRITE, crash, same-`RUN_ID` resume,
duplicate-count evidence, frozen product nodes, independent verifier, Post-Quality, and
handoff.

## 6. Next Practical Options

Next order:

- record the AF_UNIX outside-sandbox evidence in the G-4A attempt evidence package;
- collect and pin fresh live readiness plus adjacent recheck;
- seal the immutable proof97 fixture;
- execute the actual WRITE/crash/resume proof story;
- request independent G-4A re-review.

Until one of these is accepted:

```text
proof97 = HOLD
G-4A-ACTUAL = NO-GO remediation
```
