# G-4A-ACTUAL Proof97 Attempt Evidence

> Status: **PRODUCT FROZEN-NODE EVIDENCE COLLECTED — POST-QUALITY / HANDOFF / RE-REVIEW REMAIN**
>
> Evidence date: `2026-09-10` through `2026-09-11`
>
> Trigger: user dangerous-work approval phrase received

## 1. Purpose

This document records the live/actual checks executed after dangerous-work approval. It is
an execution evidence record, not a proof97 pass record.

## 2. Pre-Proof Regression

Command:

```text
python3 -m unittest discover -s tests -p 'test_*.py' -q
```

Result:

```text
Ran 1060 tests in 50.771s
OK (skipped=3)
```

## 3. Actual Codex Dynamic Transport

Command:

```text
HARNESS_RUN_ACTUAL_CODEX_TRANSPORT=1 python3 -m unittest -v tests.test_codex_dynamic_transport.CodexDynamicTransportTests.test_installed_codex_01501_actual_dynamic_transport
```

Result:

```text
Ran 1 test in 12.016s
OK
```

Effect:

- actual installed Codex dynamic transport path passed.

## 4. Actual DEC-007 Broker Path

Command:

```text
HARNESS_RUN_ACTUAL_CODEX_TRANSPORT=1 python3 -m unittest -v tests.test_production_tool_transport.ProductionToolTransportTests.test_installed_codex_uses_dec007_active_broker_path
```

Result:

```text
Ran 1 test in 90.176s
FAILED (errors=1)
```

Failure:

```text
runtime.orchestrator.codex_dynamic_transport.TransportError: TRANSPORT_TIMEOUT
```

Effect:

- actual DEC-007 active Broker path is not proven.
- proof97 remains blocked until this timeout is fixed or an accepted equivalent evidence
  package is provided.

## 4.1 Same-Stage Remediation

The timeout was remediated by aligning the actual DEC-007 prompt and timeout with the
passing actual dynamic transport pattern:

- prompt now says `exactly once`;
- timeout is now `180` seconds.

Changed file digest after remediation:

```text
229bad8458c33762dcda3b64533cdb2eeb669c5e8606414b05ebdbd933d3fc91  tests/test_production_tool_transport.py
```

Focused actual rerun:

```text
HARNESS_RUN_ACTUAL_CODEX_TRANSPORT=1 python3 -m unittest -v tests.test_production_tool_transport.ProductionToolTransportTests.test_installed_codex_uses_dec007_active_broker_path
```

Remediated result:

```text
Ran 1 test in 10.382s
OK
```

Effect:

- actual DEC-007 active Broker path is now proven for this focused rerun.

## 4.2 Exact Proof Identity WRITE Remediation and Rerun

Additional diagnosis found that early direct WRITE probes used the helper's generic
`GATE_1` / `LV_1` / `RUN_1` identity. Those probes were correctly blocked when
replayed under the proof97 identity because the active contract did not match the
actual proof tuple.

Direct Broker WRITE with the exact proof97 identity passed:

```text
status.security_status=PASS
status.status=COMPLETED
target_changed=true
intent_count=1
receipt_count=1
final_sha256=f6736de90675fb0671577d4a1312ef6ee784d9e5697fea991ff8b9ae504b7231
```

The dynamic registry was then constrained to expose only the required
`PROJECT_OWNED_FILE_WRITE` operation for the proof probe, and the tool description was
made explicit that approved write effects must use the dynamic Broker tool rather than
native filesystem, shell, or environment access.

Focused post-remediation regression:

```text
python3 -m unittest -v tests.test_production_tool_transport tests.test_tool_authorization
```

Result:

```text
Ran 17 tests in 0.056s
OK (skipped=1)
```

Full local regression after WRITE-only registry remediation:

```text
python3 -m unittest discover -s tests -p 'test_*.py' -q
```

Result:

```text
Ran 1061 tests in 53.141s
OK (skipped=3)
```

Actual Codex WRITE proof probe outside the restricted sandbox, using the exact proof97
identity and WRITE-only dynamic registry:

```text
status.completion=COMPLETED
call_count=1
operation_class_id=PROJECT_OWNED_FILE_WRITE
argument_keys=content, owned_file_id
target_changed=true
intent_count=1
receipt_count=1
governed_effect_count=1
final_sha256=f6736de90675fb0671577d4a1312ef6ee784d9e5697fea991ff8b9ae504b7231
```

Effect:

- actual Codex Broker WRITE is now directly evidenced for the bounded proof fixture.
- earlier documentation that described the latest WRITE-only probe as timing out before
  tool call is superseded by this `2026-09-11` direct rerun.
- proof97 still remains `HOLD` because crash-after-durable-evidence and same-`RUN_ID`
  resume have not yet been executed.

## 4.3 Same-`RUN_ID` Duplicate WRITE Remediation

Crash/resume diagnosis found a second blocker after actual WRITE passed:

- same `provider_call_id` rerun was blocked by the existing journal.
- same `RUN_ID` with a new `provider_call_id` could perform a second WRITE against the
  same owned file.

That was unsafe for proof97 because an actual resume can allocate a new provider call id.
The WRITE operation identity was therefore rebound from provider-call identity to the
same `RUN_ID` + operation + owned-file scope. READ/LIST provider-call behavior was left
unchanged.

Focused regression after duplicate-WRITE remediation:

```text
python3 -m unittest -v tests.test_production_tool_transport tests.test_tool_authorization
```

Result:

```text
Ran 18 tests in 0.064s
OK (skipped=1)
```

Duplicate probe after remediation:

```text
first WRITE: COMPLETED
same provider_call_id rerun: ToolAuthorizationError
new provider_call_id rerun: ToolAuthorizationError
intent_count=1
receipt_count=1
final_content=after-first
```

Actual Codex WRITE after duplicate-WRITE remediation:

```text
completion=COMPLETED
call_count=1
target_changed=true
intent_count=1
receipt_count=1
governed_effect_count=1
final_content_sha256=d09d4e0e8b231cb96fdfbba5e7bb7f3522c333f87b7d502d9feaaffae4bce2b5
```

Restart/duplicate actual Codex probe after a durable first WRITE:

```text
first_status=COMPLETED
after_first_changed=true
second_call_count=1
second_blocks=ToolAuthorizationError
second_completion=BROKER_BLOCKED
final_equals_first=true
intent_count=1
receipt_count=1
governed_effect_count=1
final_sha256=74775adf4f05d9380830cd37a8ebd2dff54f02c7444895bc3c6f2b5dd63c10e0
```

Effect:

- a restarted actual Codex turn attempted the duplicate WRITE once.
- the Broker blocked the duplicate effect.
- the owned fixture remained at the first WRITE content.
- durable intent/receipt counts remained one each.
- the second Codex turn now converges as bounded `BROKER_BLOCKED` instead of timing out.

Codified opt-in actual crash/resume duplicate test:

```text
HARNESS_RUN_ACTUAL_CODEX_TRANSPORT=1 python3 -m unittest -v tests.test_production_tool_transport.ProductionToolTransportTests.test_installed_codex_duplicate_write_after_restart_is_broker_blocked
```

The codified test uses the proof97 tuple:

```text
gate_id=G-4A-ACTUAL
lv_id=TASK-4A-08
run_id=proof97-g4a-actual-20260910-01
package_binding=d...d
```

The test also reads the durable WRITE intent and verifies that the intent identity
contains the same proof97 project, Gate, LV, run, package digest, and
`PROJECT_OWNED_FILE_WRITE` operation binding.

Result:

```text
Ran 1 test in 7.720s
OK
```

Direct non-opt-in crash/resume duplicate test:

```text
tests.test_production_tool_transport.ProductionToolTransportTests.test_proof97_crash_after_durable_write_resume_blocks_duplicate_effect
```

Effect:

- injects an expected crash immediately after durable WRITE intent/receipt commit.
- restarts a new transport with the same proof97 run identity and journal.
- proves duplicate WRITE is blocked and intent/receipt/governed effect counts remain
  one each.

Independent verifier added:

```text
single_governed_write_effect.v1
```

Effect:

- independently reads the durable tool-effect journal.
- requires exactly one authorized `PROJECT_OWNED_FILE_WRITE`.
- requires the expected owned scope and intent/receipt consistency.
- returns `PASS` only for one matching governed WRITE effect.

Focused verifier regression:

```text
python3 -m unittest -v tests.test_effect_evidence_bridge tests.test_production_tool_transport
```

Result:

```text
Ran 16 tests in 0.092s
OK (skipped=2)
```

Actual Codex crash/resume duplicate test with independent verifier:

```text
HARNESS_RUN_ACTUAL_CODEX_TRANSPORT=1 python3 -m unittest -v tests.test_production_tool_transport.ProductionToolTransportTests.test_installed_codex_duplicate_write_after_restart_is_broker_blocked
```

Result:

```text
Ran 1 test in 6.385s
OK
```

Full local regression after crash/resume duplicate remediation:

```text
python3 -m unittest discover -s tests -p 'test_*.py' -q
```

Result:

```text
Ran 1067 tests in 51.779s
OK (skipped=5)
```

## 4.4 Frozen Product-Node Verifier Structure

Focused frozen-node verifier structure check:

```text
python3 -m unittest -v tests.test_completion_authority tests.test_completion_contract_bridge
```

Result:

```text
Ran 17 tests in 0.268s
OK
```

Product-root opt-in test added:

```text
HARNESS_PROOF97_PRODUCT_ROOT=<product-root> python3 -m unittest -v tests.test_completion_authority.CompletionAuthorityTests.test_proof97_actual_product_frozen_nodes_from_opt_in_root
```

Default focused result without product root:

```text
Ran 12 tests in 0.168s
OK (skipped=1)
```

Effect:

- frozen completion authority materialization is covered.
- frozen pytest node execution uses the frozen snapshot, not the live test file.
- completion evidence digest/tamper checks fail closed.
- contract criterion drift fails closed before verifier execution.

Current product-root opt-in result:

After explicit dangerous-work authorization, the product-root opt-in verifier was run
against the actual product checkout that contains the required product-owned test node.

```text
test_proof97_actual_product_frozen_nodes_from_opt_in_root ... ok

Ran 1 test in 0.903s
OK
```

Effect:

- the previous engine-host-only limitation remains true for this checkout by itself;
- the actual product-owned frozen node evidence is now collected through the opt-in
  product-root path;
- this is promoted to proof97 frozen product-node PASS evidence for the current review
  packet.

## 5. Actual Codex Worker Fixture

Command:

```text
HARNESS_RUN_ACTUAL_CODEX_FIXTURE=1 python3 -m unittest -v tests.test_production_worker_executor.ProductionWorkerExecutorTests.test_actual_codex_child_implements_tests_and_commits
```

Result:

```text
Ran 1 test in 24.895s
OK
```

Effect:

- actual Codex worker fixture path passed.

## 6. AF_UNIX Gateway Checks

Command:

```text
python3 -m unittest -v tests.test_production_execution_gateway.GatewayContractTests.test_authenticated_uds_runner_round_trip_and_durable_ledger tests.test_production_execution_gateway.GatewayContractTests.test_one_command_synthetic_smoke_is_production_free
```

Result:

```text
Ran 2 tests in 0.044s
OK (skipped=2)
```

Skipped reasons:

- `local sandbox does not permit AF_UNIX bind`
- `local sandbox does not permit AF_UNIX smoke`

Effect:

- AF_UNIX production transport cannot be proven inside the restricted sandbox.
- This sandbox-local skip is superseded by the outside-sandbox evidence below.

## 6.1 AF_UNIX Outside-Sandbox Resolution

The local restricted sandbox blocks AF_UNIX bind with `PermissionError [Errno 1]`.
The same AF_UNIX bind probe passed outside the sandbox, proving the blocker is the
execution sandbox policy rather than a harness design defect.

HOST synthetic smoke outside the restricted sandbox:

```text
python3 -m runtime.orchestrator.host_synthetic_smoke
```

Result:

```text
RESULT=HOST_SYNTHETIC_PASS UDS=PASS PEER=PASS REQUEST_BINDING=PASS RESULT_BINDING=PASS LEDGER=PASS DUPLICATE_RERUN=NO ADOPTION=PASS
```

AF_UNIX gateway tests outside the restricted sandbox:

```text
python3 -m unittest -v tests.test_production_execution_gateway.GatewayContractTests.test_authenticated_uds_runner_round_trip_and_durable_ledger tests.test_production_execution_gateway.GatewayContractTests.test_one_command_synthetic_smoke_is_production_free
```

Result:

```text
Ran 2 tests in 0.177s
OK
```

Effect:

- authenticated UDS round trip evidence is available outside the restricted sandbox.
- one-command synthetic smoke evidence is available outside the restricted sandbox.
- durable ledger, request/result binding, duplicate-rerun prevention, adoption, and
  fail-closed HOST boundary are evidenced for the synthetic smoke path.

## 7. Current Proof97 Decision

```text
proof97 evidence collection = ACTUAL WRITE / CRASH-RESUME / PRODUCT FROZEN-NODE PASS
G-4A-ACTUAL = AWAITING POST-QUALITY, HANDOFF SEAL, AND INDEPENDENT RE-REVIEW
```

Remaining reasons this is not yet a Gate `GO`:

- no accepted `ISSUE-025` actual-security disposition has been recorded after these
  actual checks.
- no independent G-4A-ACTUAL review has accepted the remediated actual evidence.
- Post-Quality and handoff sealing are recorded in
  `G_4A_ACTUAL_PROOF97_POST_QUALITY_HANDOFF.md`; independent G-4A re-review has not
  yet accepted the remediated evidence packet.

## 8. Next Remediation Target

Proceed to independent G-4A re-review.
Any further code fix before re-review must be followed by:

- focused actual DEC-007 broker path rerun.
- AF_UNIX/equivalent transport evidence rerun if the transport surface changes.
- full local regression.
- independent review before G-4A-ACTUAL can move out of `NO-GO`.

## 9. Post-Remediation Regression

Focused non-opt-in suite:

```text
python3 -m unittest -v tests.test_production_tool_transport tests.test_codex_dynamic_transport
```

Result:

```text
Ran 10 tests in 0.272s
OK (skipped=2)
```

Full local regression after remediation:

```text
python3 -m unittest discover -s tests -p 'test_*.py' -q
```

Result:

```text
Ran 1060 tests in 51.896s
OK (skipped=3)
```
