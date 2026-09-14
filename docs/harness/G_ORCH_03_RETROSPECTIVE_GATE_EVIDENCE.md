# G-ORCH-03 Retrospective Gate Evidence

> Status: **REVIEWED — GO**
>
> Gate: `G-ORCH-03 — Worker, Post-Quality, Remediation, and Security`
>
> Evidence date: `2026-09-10`
>
> Scope: ORCH04 worker authority, effect evidence, post-worker authority, gateway,
> production executor, remediation, recovery, and bounded security provenance

## 1. Purpose

This evidence package records local mechanism-level verification for the G-ORCH-03
runtime path after G-ORCH-01 and G-ORCH-02 both reached `GO`.

It does not authorize live Codex execution, actual Broker WRITE, product mutation,
proof97, deployment, commit, push, or closure of issues that require actual proof.

## 2. Test Scope

The focused G-ORCH-03 suite covers:

- WorkerAuthority, PostQuality, and Remediation policy behavior.
- governed effect intent/receipt projection and tamper checks.
- DEC-007-style exact tool authorization and single-broker path checks.
- production transport, gateway request/result binding, and mandatory canonical authority.
- production worker executor security provenance, structured event validation, bounded
  metadata, timeout/cancel handling, and no local fallback.
- gate controller lifecycle, review/remediation loop, checkpoint/recovery lineage, and
  production runner replay behavior.
- integration wiring between production prompt builders, reviewers, and workers.

## 3. Direct Verification

Command executed by the root orchestrator:

```text
python3 -m unittest -v tests.test_worker_authority tests.test_post_worker_authority_bridge tests.test_effect_evidence_bridge tests.test_effect_projection_transport tests.test_tool_authorization tests.test_production_tool_transport tests.test_production_execution_gateway tests.test_production_worker_executor tests.test_production_canonical_authority tests.test_production_canonical_projection tests.test_production_canonical_provider_wiring tests.test_production_worker_canonical_mandatory tests.test_gateway_canonical_binding tests.test_gateway_canonical_mandatory tests.test_gate_canonical_worker_injection tests.test_gate_controller tests.test_production_gate_runner tests.test_production_integration
```

Current direct result:

```text
Ran 260 tests in 6.169s
OK (skipped=4)
```

Skipped tests:

- actual installed Codex broker integration is opt-in.
- local sandbox does not permit AF_UNIX bind.
- local sandbox does not permit AF_UNIX smoke.
- actual Codex fixture is opt-in.

## 4. Exact Evidence Digests

| File | SHA-256 |
|---|---|
| `runtime/orchestrator/worker_authority.py` | `17310f9c9b7c5fe99d0c23aacf3c89968a13ccdcde392e2928475a0ecd29a725` |
| `runtime/orchestrator/post_worker_authority_bridge.py` | `64309b21553ccb1faf81f6d7d89fa4792e335b840458b1765a95bd821aef283c` |
| `runtime/orchestrator/effect_evidence_bridge.py` | `30755a60fc5a937339b20548a42b1beef13ba5f21543f2b7e2f6c4ccd8ea18da` |
| `runtime/orchestrator/tool_authorization.py` | `01def18f86fe7b93a9c8c24a7b4e45294ac5b5a908cb123bfa18fb1875809b58` |
| `runtime/orchestrator/production_tool_transport.py` | `06798704c6d9a9df549c72650fa93ff6802e0b9c4ece342656642ec8846c6a82` |
| `runtime/orchestrator/production_execution_gateway.py` | `38de3e793443423d7e69333848fbbf9d0ff73ea8ed7bcb5e5d88ef1d89a940df` |
| `runtime/orchestrator/production_worker_executor.py` | `a05a337fdd20a86ed223e202c4804ac40e88abebb428ad73043961c452f2388d` |
| `runtime/orchestrator/production_canonical_authority.py` | `4fee993fdec67a257a5bddffc1b84665957d2bf5c170019bb7cdaa509fe42fe6` |
| `runtime/orchestrator/production_context.py` | `2fe36dd93234c479716c54b8344c9a26303534277372ff4b467eb12867b1e799` |
| `runtime/orchestrator/production_gate_runner.py` | `8138995e5dd061b9c026730d9657b6d92fc06751bec75cffe4dcdc7704f0a10b` |
| `runtime/orchestrator/gate_controller.py` | `1fdfc655e2cc39f092d4e8f76fa1ff4fe2cfb5fbfb0d4d13cc0631d13f452c1b` |
| `tests/test_worker_authority.py` | `bb8af8de27cd6320ece4294591a3faed17f98ab6435e1bdb751856d2c4316635` |
| `tests/test_post_worker_authority_bridge.py` | `9764fdd66cba9fdbbb8cf61400567e99f1b2a2988e1cfb7d06679b754fa5c489` |
| `tests/test_effect_evidence_bridge.py` | `62d545a50c331ad205090358ea880702b1e9861d3a1782f80dc13a20b4e16ce8` |
| `tests/test_effect_projection_transport.py` | `81fa72d27acad6e02a72aa1bc2ba3960d2a65c62b8af1ecb989d70feaa0779ab` |
| `tests/test_tool_authorization.py` | `5c1a9a0c2c41164e308931864026ca3d52300fcf2b7eb610e99e53e06d70f270` |
| `tests/test_production_tool_transport.py` | `3c9ef4db4b083297eb48825c5a58f0cea9ab6884970734bc5f1863df3611f9bd` |
| `tests/test_production_execution_gateway.py` | `217198387c25dc7dc8c0e497fc4208e6907495e3db252d5135b9ec2838d0a5d9` |
| `tests/test_production_worker_executor.py` | `12f2c2d33cb9fa56e0cd971a03edaef0f106fdd5447932c17741fd4bea4eb6cc` |
| `tests/test_production_canonical_authority.py` | `a150b690e0257de3bdd2eff045b04f17649e035cfb76a46851c770f57a71a41b` |
| `tests/test_production_canonical_projection.py` | `42e629a5414638ca340527fb4df14630a3571ed5260a0a1a9f342e0b9a478b5a` |
| `tests/test_production_canonical_provider_wiring.py` | `63235ddb9df32b0e60a5a58586d84f3232d049d66d3ff5517b279555a7c05677` |
| `tests/test_production_worker_canonical_mandatory.py` | `a883367b39c79b263dc8713b4cacc60a80f6ec875b550e0b4751f7b2fc9c4d8c` |
| `tests/test_gateway_canonical_binding.py` | `50eb274b1d28af6c57acae20a02740e8782e4f60982e86542bebd1c151fc8fc9` |
| `tests/test_gateway_canonical_mandatory.py` | `e7a283a3767b5247df1871b914cb46397b4c373a0503baf537ea453603659832` |
| `tests/test_gate_canonical_worker_injection.py` | `102beffaa07f51ffeb63e0f64adf4b432e7489599ee468d5baee2b1c9bb79706` |
| `tests/test_gate_controller.py` | `a2a3a9a0050bdafcd65bbae91cf43cc07dec63991291f62c394fae59f47709de` |
| `tests/test_production_gate_runner.py` | `6b20aafd3434b3f06821c97f809efafbc9e3f947845a60c89cf83b8bd2eec7f1` |
| `tests/test_production_integration.py` | `abf61c77245df6c3f4f1aef9dc8dbf2c4ddeca174e098f4e896abbd435894032` |

## 5. Boundaries and Non-Claims

- The passing suite validates local deterministic Worker/Post-Quality/remediation/security
  mechanics and production-boundary fail-closed behavior.
- The four skipped tests are opt-in or sandbox-constrained actual-integration checks.
- This Gate does not prove current live Codex authentication state.
- This Gate does not perform actual Broker WRITE or product mutation.
- This Gate does not run proof97.
- This Gate does not close `ISSUE-025` unless the independent reviewer explicitly accepts
  the bounded local security-provenance scope as sufficient for its current subcause.

## 6. Requested Gate Decision

Request independent stage-gate review for G-ORCH-03.

Recommended decision if the reviewer confirms the evidence:

```text
GO
```

Recommended proof effect if the reviewer confirms the evidence:

- local Worker/Post-Quality/remediation/security mechanism review is complete.
- proof97 remains `HOLD` until live readiness, actual-proof authorization, immutable
  fixture, and any remaining issue dispositions are satisfied.
