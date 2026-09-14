# ORCH04 Actual Evidence Record

> Recorded: `2026-09-12`
>
> Scope: installed Codex transport and actual child-worker boundary checks.
> This record contains bounded results only; no authentication output or secret value
> is retained.

## Executed checks

### Installed Codex dynamic transport

```text
HARNESS_RUN_ACTUAL_CODEX_TRANSPORT=1 python3 -m unittest -v tests.test_codex_dynamic_transport.CodexDynamicTransportTests.test_installed_codex_01501_actual_dynamic_transport
```

Result: exit code `0`, `1 PASS`, elapsed `11.606s`.

This proves the installed Codex dynamic transport reaches the provider-neutral
transport boundary under the pinned version test. It does not prove actual WRITE,
completion authority, or auth-recovery import.

### Actual Codex child-worker fixture

```text
HARNESS_RUN_ACTUAL_CODEX_FIXTURE=1 python3 -m unittest -v tests.test_production_worker_executor.ProductionWorkerExecutorTests.test_actual_codex_child_implements_tests_and_commits
```

Result: exit code `0`, `1 PASS`, elapsed `17.987s`.

This proves the actual child-worker fixture can implement the bounded task, run its
tests, and produce the fixture checkpoint evidence. The fixture is isolated and does
not prove the complete ORCH04 capability/revision loop or Full Plan closure.

## Issue impact

- `ISSUE-065`: separately closed by the separate-process A-crash/B-resume evidence
  recorded in the deferred evidence scan.
- `ISSUE-071`: strengthened by actual child-worker execution, but remains `DEFERRED`
  because the complete capability/revision loop is not evidenced.
- `ISSUE-064`: transport reachability is evidenced, but the required independent
  Worker/Reviewer security provenance closure is not established by these checks.
- `ISSUE-056`, `ISSUE-059`, `ISSUE-063`, `ISSUE-066`, `ISSUE-067`, `ISSUE-069`,
  `ISSUE-070`, `ISSUE-075`: no direct closure evidence was produced by these checks.

No product checkout files were modified by either test. No disposition was changed by
this record.

## Additional actual security/effect revalidation

```text
HARNESS_RUN_ACTUAL_CODEX_TRANSPORT=1 python3 -m unittest -v tests.test_production_tool_transport.ProductionToolTransportTests.test_installed_codex_duplicate_write_after_restart_is_broker_blocked tests.test_production_tool_transport.ProductionToolTransportTests.test_installed_codex_secret_like_write_is_blocked_without_raw_persistence
```

Result: exit code `0`, `2 PASS`, elapsed `76.380s`.

The restarted actual transport blocked the duplicate governed WRITE, and the
secret-like WRITE was blocked without persisting the sentinel. These results reinforce
the actual effect/security boundary and ISSUE-025 evidence. They do not by themselves
close the broader Worker/Reviewer provenance requirement for ISSUE-064 or the
completion/capability loop requirements for ISSUE-059 and ISSUE-070.

## Actual readiness import and canonical recheck

```text
HARNESS_RUN_ACTUAL_CODEX_TRANSPORT=1 python3 -m unittest -v tests.test_canonical_launch_bridge.CanonicalLaunchBridgeTests.test_actual_readiness_is_consumed_by_canonical_launch_authority
```

Result: exit code `0`, `1 PASS`, elapsed `1.627s`.

The actual readiness evidence was consumed by the canonical launch authority. The
launch-adjacent recheck produced a distinct evidence reference, preserved the package
readiness reference, and preflight remained ready. No raw authentication output was
persisted. This closes the actual readiness import/recheck evidence gap for
`ISSUE-075`.

## Remaining-issue contract and integration revalidation

```text
python3 -m unittest -q tests.test_canonical_contract_bridge tests.test_canonical_migration_quality_binding tests.test_gate_orchestrator tests.test_global_gate_integration tests.test_canonical_capability_contract tests.test_operational_capability tests.test_effect_evidence_bridge tests.test_completion_authority tests.test_completion_contract_bridge
```

Result: exit code `0`, `139 PASS / 1 skipped`, elapsed `5.236s`.

This directly revalidates the local unified contract, migration-quality binding,
Gate-controller hard stops, capability routing, effect evidence, and completion
authority paths. The evidence strengthens `ISSUE-056`, `ISSUE-059`, `ISSUE-063`,
`ISSUE-066`, `ISSUE-067`, `ISSUE-069`, `ISSUE-070`, and `ISSUE-071`, but remains
deterministic/local evidence and does not promote those issues without their required
actual-boundary proof.

## Fresh combined actual-boundary run

The five approved installed-Codex transport, Broker, crash/resume, security, and
separate-process checks were rerun together.

Result: exit code `0`, `5 PASS`, elapsed `184.968s`.

This reconfirms the actual boundaries already recorded for transport, governed effect,
security blocking, and resume. It produces no new direct closure for the remaining
deferred issues because their required source provenance, Worker/Reviewer provenance,
completion authority, capability/revision loop, unified contract, or Full Plan
end-to-end evidence is not covered by these five checks.

## Actual product frozen completion verification

```text
HARNESS_PROOF97_PRODUCT_ROOT=<approved product checkout> python3 -m unittest -v tests.test_completion_authority.CompletionAuthorityTests.test_proof97_actual_product_frozen_nodes_from_opt_in_root
```

Result: exit code `0`, `1 PASS`, elapsed `0.861s`.

The verifier executed the frozen completion nodes against the approved product
checkout and both criteria were satisfied. Combined with the actual governed effect
and duplicate-prevention evidence above, this closes the machine-verifiable
completion/effect evidence requirement for `ISSUE-070`.

## Actual Worker source-provenance revalidation

```text
HARNESS_RUN_ACTUAL_CODEX_FIXTURE=1 python3 -m unittest -v tests.test_production_worker_executor.ProductionWorkerExecutorTests.test_actual_codex_child_implements_tests_and_commits
```

Result: exit code `0`, `1 PASS`, elapsed `25.675s`.

The actual Worker result was independently checked for matching baseline source
HEAD, changed current HEAD, baseline/current tree identifiers, checkpoint commit,
PASS review verdict, and the request/process evidence hash chain. This strengthens
`ISSUE-056`, `ISSUE-059`, and `ISSUE-071`, but it is still a bounded Worker run; it
does not establish shell-node output provenance, an independent security Reviewer
closure, unified-contract consumption across every boundary, or a product-level
Full Plan end-to-end loop.

## ORCH04 authority-chain integration check

```text
python3 -m unittest -v tests.test_orch04_evidence_chain
```

Result: exit code `0`, `1 PASS`, elapsed `0.040s`.

This test connects the existing source snapshot, WorkerAuthority result evaluation,
independent Reviewer/quality evaluation, contract/package digest binding, and the
existing FULL_PLAN supervisor in one bounded chain. It is an integration regression
fixture, not proof of the installed production shell-node or product checkout
boundary; no remaining disposition is changed on this evidence alone.

## Product source provenance read-only check

The canonical `IMPLEMENTATION_PLAN.md` SHA-256 in the repository mapping matched the
actual approved product checkout (`CANONICAL_SOURCE_HASH_MATCH=YES`). The product
checkout was also clean (`PRODUCT_REPO_STATUS=CLEAN`). This is direct read-only
source provenance evidence for `ISSUE-056`; it does not authorize a Worker mutation
or close the separate output, Reviewer, contract-consumption, or Full Plan-loop
evidence gaps.
