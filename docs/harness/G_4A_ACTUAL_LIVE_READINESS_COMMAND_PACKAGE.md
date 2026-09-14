# G-4A-ACTUAL Live Readiness Command Package

> Status: **PARTIALLY EXECUTED — PROOF97 STILL HOLD**
>
> Prepared: `2026-09-10`
>
> Depends on: `G_4A_ACTUAL_PROOF97_FIXTURE_PLAN.md`

## 1. Purpose

This package lists the readiness and actual-proof commands that must be reviewed before
proof97 can leave `HOLD`. Some candidate commands have now been executed under user
dangerous-work approval and are recorded in `G_4A_ACTUAL_PROOF97_ATTEMPT_EVIDENCE.md`.

## 2. Readiness Collection Contract

The actual proof runner must collect `CodexAuthReadinessEvidence=READY` immediately before
launch and recheck it immediately before canonical launch authorization.

Required API surfaces:

- `runtime.orchestrator.codex_readiness.collect_codex_auth_readiness`
- `runtime.orchestrator.codex_readiness.recheck_codex_auth_readiness`
- `runtime.orchestrator.canonical_launch_bridge.build_launch_authorization`
- `runtime.orchestrator.production_canonical_authority.build_production_canonical_authority`

Required evidence properties:

- `auth_status` is `READY`.
- `recheck_policy` is `ALWAYS_BEFORE_CODEX_LAUNCH`.
- evidence is secret-free and bounded.
- launch binding digest matches the exact package revision.
- CLI version, transport schema digest, and environment fingerprint do not drift between
  initial collection and recheck.

## 3. Candidate Commands For Later Approval

These commands were candidates for the dangerous-work approval package. The user provided
the exact Safety Warning Protocol approval phrase, and the actual transport probes below
were partially executed. They still do not by themselves authorize proof97 completion.

### Actual Codex dynamic transport

```text
HARNESS_RUN_ACTUAL_CODEX_TRANSPORT=1 python3 -m unittest -v tests.test_codex_dynamic_transport.CodexDynamicTransportTests.test_installed_codex_01501_actual_dynamic_transport
```

Expected proof contribution:

- installed Codex transport can be reached through the actual dynamic transport path.
- task binding uses `TASK-4A-08`.
- no raw auth or secret text is persisted.

Current evidence:

- executed and passed; see `G_4A_ACTUAL_PROOF97_ATTEMPT_EVIDENCE.md`.

### Actual DEC-007 broker path

```text
HARNESS_RUN_ACTUAL_CODEX_TRANSPORT=1 python3 -m unittest -v tests.test_production_tool_transport.ProductionToolTransportTests.test_installed_codex_uses_dec007_active_broker_path
```

Expected proof contribution:

- installed Codex uses the active Broker path.
- unauthorized, unknown, or unowned operations remain blocked.
- governed effect evidence is bounded.

Current evidence:

- initial execution timed out;
- same-stage prompt/timeout remediation was accepted as a diagnostic/readiness-probe fix;
- focused rerun passed;
- this remains READ-path evidence only, not actual proof97 WRITE evidence.

### Actual Codex worker fixture

```text
HARNESS_RUN_ACTUAL_CODEX_FIXTURE=1 python3 -m unittest -v tests.test_production_worker_executor.ProductionWorkerExecutorTests.test_actual_codex_child_implements_tests_and_commits
```

Expected proof contribution:

- actual child worker performs the expected fixture implementation.
- focused tests and full regression evidence are collected by the harness path.
- commit evidence is collected only as bounded machine evidence.

Current evidence:

- executed and passed; see `G_4A_ACTUAL_PROOF97_ATTEMPT_EVIDENCE.md`.

## 4. Sandbox-Skipped Gateway Evidence

The current local sandbox skipped AF_UNIX bind and smoke checks. Before proof97 can pass,
one of these must be true:

- the AF_UNIX gateway tests run in an environment that permits socket bind/smoke; or
- an equivalent production transport evidence package is accepted by the stage reviewer.

Candidate skipped surfaces:

- `tests.test_production_execution_gateway.GatewayContractTests.test_authenticated_uds_runner_round_trip_and_durable_ledger`
- `tests.test_production_execution_gateway.GatewayContractTests.test_one_command_synthetic_smoke_is_production_free`

## 5. Pre-Run Regression Requirement

Immediately before any actual proof execution, run the full local regression again:

```text
python3 -m unittest discover -s tests -p 'test_*.py' -q
```

The last direct result before this package was drafted was:

```text
Ran 1060 tests in 52.157s
OK (skipped=3)
```

That result is a baseline only. If any relevant source, test, or authority document changes
before proof, it must be re-run and re-reviewed.

## 6. Required Reviewer Outputs

After the command package is eventually executed, the reviewer must record:

- exact command lines executed.
- exit codes and pass/skip/fail counts.
- exact source/test/authority digests.
- readiness evidence id and launch binding digest, without raw secrets.
- Broker WRITE count.
- duplicate Worker/effect/checkpoint count after resume.
- frozen product node results.
- independent verifier result.
- issue effects for `ISSUE-025`, `ISSUE-059`, `ISSUE-060`, `ISSUE-063`,
  `ISSUE-064`, `ISSUE-065`, and `ISSUE-066`.

## 7. Execution Boundary

After the first dangerous-work approval and G-4A review:

```text
partial_actual_transport_probes = EXECUTED
live_readiness_collection = NOT COMPLETE
actual_broker_write = NOT COMPLETE
proof97 = HOLD
```
