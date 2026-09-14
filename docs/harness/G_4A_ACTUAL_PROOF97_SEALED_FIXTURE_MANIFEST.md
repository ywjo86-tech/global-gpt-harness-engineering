# G-4A-ACTUAL Proof97 Sealed Fixture Manifest

> Status: **POST-QUALITY / HANDOFF SEALED — AWAITING INDEPENDENT G-4A RE-REVIEW**
>
> Sealed: `2026-09-11`
>
> Scope: proof97 fixture identity, readiness binding, current runtime/test digests,
> and post-remediation WRITE/duplicate evidence

## 1. Fixture Identity

| Field | Value |
|---|---|
| proof id | `proof97` |
| Gate | `G-4A-ACTUAL` |
| run id | `proof97-g4a-actual-20260910-01` |
| worker task id | `TASK-4A-08` |
| package id | `proof97-g4a-actual-package` |
| package revision | `1` |
| required operation | actual Broker WRITE |
| required crash behavior | expected crash after durable evidence commit |
| required resume behavior | same `RUN_ID`, same package lineage |
| proof status | actual WRITE/crash/resume, product frozen-node evidence, Post-Quality, and handoff seal collected; independent G-4A re-review returned `CONDITIONAL GO` |

## 2. Live Readiness Evidence

Readiness was collected outside the restricted sandbox because the sandbox changes the
observable auth status to `NOT_READY`. The outside-sandbox readiness collection and
adjacent recheck both returned `READY`.

Initial readiness:

| Field | Value |
|---|---|
| evidence id | `CAE-ddeffdab701a09946cf4ac818b333fb1` |
| verified at | `2026-09-10T14:59:44.006307Z` |
| auth status | `READY` |
| CLI version | `0.150.1` |
| environment fingerprint | `0d21dc8f1d49483f89bed9149298dd67fc8022b93afab3f673c85c12686a898b` |
| transport schema digest | `e9bad0a20736e7d3aba18c0f04bef59856fb212ae21049fe17d786682203cfae` |
| launch binding digest | `5329f1e4cb2a2af0a7efdc503fdff1d9f8fbeec5c60ffa20f24e84928d0119f3` |
| recheck policy | `ALWAYS_BEFORE_CODEX_LAUNCH` |

Adjacent recheck:

| Field | Value |
|---|---|
| evidence id | `CAE-8de16eae1ce52019c61b8f6ce7326db4` |
| verified at | `2026-09-10T14:59:44.819849Z` |
| auth status | `READY` |
| launch binding digest | `5329f1e4cb2a2af0a7efdc503fdff1d9f8fbeec5c60ffa20f24e84928d0119f3` |
| stable binding | `YES` |

No raw auth text, token, API key, password, or secret value is recorded in this manifest.

## 3. Pinned Authority and Evidence Inputs

| File | SHA-256 |
|---|---|
| `docs/harness/R4_AUTHORITY_INDEX.md` | `4ee7e9dd7f325e22eb0202699749ec5c7a9d21a19b52775189d1ab191852334e` |
| `docs/harness/G_ORCH_01_STAGE_GATE_DECISION.md` | `d025e2374c2416c9788dcf4e13ccff73578baf0e34197f5811756e2e6255b085` |
| `docs/harness/G_ORCH_02_STAGE_GATE_DECISION.md` | `979749fe54bcbe611abda33a9e824bb59bdfb65dd62328abf3578c9459699a4a` |
| `docs/harness/G_ORCH_03_STAGE_GATE_DECISION.md` | `5b75ee49da813a68a401ebb5a4832ea27771776cbe6b0a34e60de2313227dc3a` |
| `docs/harness/G_4A_ACTUAL_STAGE_GATE_DECISION.md` | `ebbceefa51a32160ad91153b5399ede1fc6cbb7ff487cefbdcd116d0cbf66be1` |
| `docs/harness/G_4A_ACTUAL_PROOF97_FIXTURE_PLAN.md` | `2bcc769f9edd55ebfd8548531a1eb03b8c236a2f97b63e9348c7ea42ae99c28f` |
| `docs/harness/G_4A_ACTUAL_LIVE_READINESS_COMMAND_PACKAGE.md` | `33d5367575932253e5e0ca4bd8d15c0502d204011ea39a3f0ac5857ec265b97e` |
| `docs/harness/G_4A_ACTUAL_PROOF97_ATTEMPT_EVIDENCE.md` | `33ff4fddc871d2dafcdcb140b4ac5ff8eaa38a5cb9457f8710bc0953455d529c` |
| `docs/harness/G_4A_ACTUAL_DESIGN_DIAGNOSIS.md` | `91ee920f21f335e598b4f965bb93d366fe35395256e71bb2c37ed75791fbd1d0` |

## 4. Pinned Runtime/Test Inputs At Seal Time

| File | SHA-256 |
|---|---|
| `runtime/orchestrator/codex_readiness.py` | `e32481104c9398bc85a6548206eb791cd13e35a406be52c77da0bcadf84b323f` |
| `runtime/orchestrator/production_execution_gateway.py` | `38de3e793443423d7e69333848fbbf9d0ff73ea8ed7bcb5e5d88ef1d89a940df` |
| `runtime/orchestrator/production_tool_transport.py` | `06798704c6d9a9df549c72650fa93ff6802e0b9c4ece342656642ec8846c6a82` |
| `tests/test_production_tool_transport.py` | `229bad8458c33762dcda3b64533cdb2eeb669c5e8606414b05ebdbd933d3fc91` |
| `tests/test_production_execution_gateway.py` | `217198387c25dc7dc8c0e497fc4208e6907495e3db252d5135b9ec2838d0a5d9` |

## 4.1 Seal Invalidation and Post-Remediation Evidence

This manifest was invalidated by a same-stage remediation that added a closed dynamic
registry subset option for proof97 WRITE probing. The remediation was necessary because:

- direct Broker WRITE with the original test identity was correctly blocked;
- direct Broker WRITE with exact proof identity passed;
- actual Codex WRITE with exact proof identity did not call the WRITE tool and timed out.

The final bullet records an intermediate result and is superseded by the current
post-remediation rerun below. The seal remains invalidated because runtime/test files
changed after the original seal.

Changed runtime/test digests after the latest remediation:

| File | SHA-256 |
|---|---|
| `runtime/orchestrator/codex_dynamic_transport.py` | `19dadaabf1f46ea29cee295db984b75d2d90ad50a39c8bef445fd2e00044d270` |
| `runtime/orchestrator/effect_evidence_bridge.py` | `40f8167e8c7ba2fff29f30c372a610e969ef1018a26dedbe5cb15e567e7f5699` |
| `runtime/orchestrator/tool_authorization.py` | `a623a4c5d6ca9a6bdcb99baf7c046beba3b2326e7b32ac3747f3f73e3a66f4e4` |
| `runtime/orchestrator/production_tool_transport.py` | `365cb38b9e76a019072011afac187653a097b55c04142cf3801e685ed7df51e4` |
| `tests/test_codex_dynamic_transport.py` | `db892dbf2fe22534753051d6a07e9155ac63bd231faef583c134cdcdbf7338c4` |
| `tests/test_completion_authority.py` | `d954912d16d92547b20c074bf03071e9f459af501b27403e1a122756fadcc493` |
| `tests/test_effect_evidence_bridge.py` | `da94cc97cfb2d5ce05411543b80da2a2c355ac336bc5fd85656647441cd342fa` |
| `tests/test_production_tool_transport.py` | `beb93f51357095121ce377048ecd8e7531597b5ba26f485d171263654467af37` |

Post-remediation regression:

```text
Ran 1067 tests in 51.779s
OK (skipped=5)
```

The WRITE-only registry remediation does not complete proof97, but the current bounded
actual WRITE probe now passes with the exact proof97 identity and only
`PROJECT_OWNED_FILE_WRITE` exposed.

Latest actual WRITE result:

```text
completion: COMPLETED
tool call count: 1
intent count: 1
receipt count: 1
governed effect count: 1
target changed: true
final_sha256: f6736de90675fb0671577d4a1312ef6ee784d9e5697fea991ff8b9ae504b7231
```

After actual WRITE passed, an additional same-`RUN_ID` duplicate WRITE risk was found:
a new provider call id could perform a second WRITE. The latest remediation binds WRITE
identity to `RUN_ID` + operation + owned-file scope, and the direct duplicate probe now
shows one intent, one receipt, and duplicate reruns blocked for both same and new
provider call ids.

Latest actual WRITE after duplicate-WRITE remediation:

```text
completion: COMPLETED
tool call count: 1
intent count: 1
receipt count: 1
governed effect count: 1
target changed: true
final_content_sha256: d09d4e0e8b231cb96fdfbba5e7bb7f3522c333f87b7d502d9feaaffae4bce2b5
```

## 4.2 Current Reseal Boundary

This section defines the current resealed input boundary for the next crash/resume proof
attempt. The original seal remains historically invalidated, but the current runtime/test
digests above are the active input boundary for the next attempt.

The latest actual duplicate probe after a durable first WRITE produced:

```text
first_status: COMPLETED
second_call_count: 1
second_blocks: ToolAuthorizationError
second_completion: BROKER_BLOCKED
final_equals_first: true
intent_count: 1
receipt_count: 1
governed_effect_count: 1
final_sha256: 74775adf4f05d9380830cd37a8ebd2dff54f02c7444895bc3c6f2b5dd63c10e0
```

Reseal interpretation:

- actual WRITE is proven for the bounded fixture.
- same-`RUN_ID` duplicate WRITE is blocked at the Broker/effect layer even when actual
  Codex attempts the duplicate dynamic tool call after restart.
- the duplicate-blocked Codex turn now terminates as bounded `BROKER_BLOCKED`.
- the next proof runner must demonstrate the full expected crash/resume boundary, not
  merely duplicate-block idempotence.

The duplicate probe is now codified as an opt-in actual Codex crash/resume test:

```text
HARNESS_RUN_ACTUAL_CODEX_TRANSPORT=1 python3 -m unittest -v tests.test_production_tool_transport.ProductionToolTransportTests.test_installed_codex_duplicate_write_after_restart_is_broker_blocked
```

Result:

```text
Ran 1 test in 7.720s
OK
```

The codified opt-in test uses the proof97 tuple:

```text
gate_id: G-4A-ACTUAL
lv_id: TASK-4A-08
run_id: proof97-g4a-actual-20260910-01
package_binding: d...d
```

The codified test also verifies the durable WRITE intent identity, not only the
surrounding request tuple.

The same opt-in test now also invokes the independent
`single_governed_write_effect.v1` verifier and requires verifier `PASS`.

A direct non-opt-in crash/resume duplicate test is also present:

```text
tests.test_production_tool_transport.ProductionToolTransportTests.test_proof97_crash_after_durable_write_resume_blocks_duplicate_effect
```

It injects the expected crash immediately after durable WRITE intent/receipt commit,
then resumes with the same proof97 run identity and verifies duplicate WRITE blocking
with one intent, one receipt, one governed effect preserved, and the independent
single-WRITE verifier passing.

Frozen product-node verifier structure check:

```text
Ran 17 tests in 0.268s
OK
```

This validates frozen completion authority and frozen-node verifier mechanics. The
engine-host checkout itself does not contain the product project
`tests/test_deduplicator.py` source file, so product-owned frozen-node execution is
completed through the opt-in product-root test below.

An opt-in product-root test now exists for the actual product checkout:

```text
HARNESS_PROOF97_PRODUCT_ROOT=<product-root> python3 -m unittest -v tests.test_completion_authority.CompletionAuthorityTests.test_proof97_actual_product_frozen_nodes_from_opt_in_root
```

After explicit dangerous-work authorization, the opt-in product-root test was executed
against the actual product checkout.

Result:

```text
test_proof97_actual_product_frozen_nodes_from_opt_in_root ... ok

Ran 1 test in 0.903s
OK
```

This clears the previously recorded missing product frozen-node execution evidence.

## 5. Required Next Execution

The next proof attempt must execute, without changing this manifest or pinned inputs:

1. actual Broker WRITE to an owned fixture file.
2. bounded Intent/Receipt and effect evidence persistence.
3. expected crash after durable evidence commit.
4. same-`RUN_ID` resume.
5. duplicate Worker/effect/checkpoint count of zero.
6. product-owned frozen node execution. **Collected after explicit dangerous-work
   authorization.**
7. independent verifier. `single_governed_write_effect.v1` now passes for the
   governed WRITE invariant, frozen-node verifier structure passes, and actual product
   frozen-node execution now passes through the opt-in product-root test.
8. Post-Quality and handoff seal. **Collected in
   `G_4A_ACTUAL_PROOF97_POST_QUALITY_HANDOFF.md`.**
9. independent G-4A re-review.

The remaining proof97 progression work is independent G-4A re-review using the
post-remediation digests and collected evidence.
