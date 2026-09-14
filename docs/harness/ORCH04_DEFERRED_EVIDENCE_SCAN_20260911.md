# ORCH04 Deferred Evidence Scan

> Recorded: `2026-09-11`
>
> This is a current direct-verification record. It does not promote any issue to
> `RESOLVED` and does not authorize deployment.

## Scope

The scan covered local implementation and deterministic evidence related to:

- `ISSUE-060`: completion authority and independent-verifier support
- `ISSUE-065`: recovery/resume bridge behavior
- `ISSUE-070`: completion and effect semantics
- `ISSUE-075`: preflight/evidence binding and recovery review boundaries

## Direct verification

Command executed:

```text
python3 -m unittest -q tests.test_production_resume tests.test_completion_authority tests.test_effect_evidence_bridge tests.test_lv_review
```

Result:

- `68` tests passed
- `1` test skipped
- process exit code: `0`

## Evidence interpretation

The execution confirms that the referenced local deterministic implementations and
negative-path checks remain operational. It does not establish the actual evidence
still required by the R4 traceability records:

- `ISSUE-060`: independent actual verifier reach/result
- `ISSUE-065`: actual startup and A/B resume observability
- `ISSUE-070`: actual machine-verifiable completion closure
- `ISSUE-075`: actual auth-recovery evidence import and recheck

The remaining deferred issues retain their existing dispositions. No runtime code,
authority status, Gate status, deployment state, commit, or push was changed by this
scan.

## Actual transport/readiness attempt

Additional direct checks were attempted without product-file mutation:

- Actual installed Codex crash/resume proof: `TRANSPORT_ERROR` before completion;
  no proof artifact was accepted.
- Actual installed Codex secret-like WRITE boundary proof: `TRANSPORT_ERROR` before
  completion; no security closure was inferred.
- Codex readiness probe: CLI version `0.150.1` matched the pinned version, but
  `auth_status=NOT_READY`; the resulting readiness evidence is not launch-ready.

These results are negative or incomplete evidence. They preserve the deferred status
of `ISSUE-060`, `ISSUE-065`, and `ISSUE-075` and identify an environment/auth readiness
blocker for any subsequent actual proof attempt.

## Readiness diagnosis

The bounded readiness probes were run without printing authentication output:

- CLI version probe: PASS (`0.150.1`)
- App Server schema probe: PASS
- Environment fingerprint probe: PASS
- Auth status probe: `NOT_READY`

The readiness implementation accepts only the bounded login-status result
`Logged in using ChatGPT` as `READY`. No login, credential change, or external
authentication action was performed during this diagnosis.

## Post-login recheck

After the user reported completing device authentication, the same workspace was
rechecked without printing raw authentication output:

- `codex login status` return code: `1`
- readiness status: `NOT_READY`
- expected bounded login-status match: `false`

The current CLI execution environment therefore has no verified login session for
actual proof. The actual Codex proof was not retried after this recheck.

## Actual proof rerun after environment correction

After the Codex state-runtime filesystem restriction was identified, the same
approved proof scope was rerun with the required host-state access:

- Actual installed Codex first-WRITE/crash/same-`RUN_ID` resume: `PASS`
- Actual installed Codex secret-like WRITE boundary: `PASS`
- Test run: `2 PASS`
- Product checkout mutation: none; both tests used temporary fixtures

This directly strengthens the evidence for the actual security boundary and the
crash/resume path. It does not by itself close the independent verifier, complete
startup observability, unified orchestration, or auth-recovery import/recheck gaps.

## Actual product-owned verifier

The opt-in frozen-node verifier was executed against the product checkout:

```text
HARNESS_PROOF97_PRODUCT_ROOT=<product-root> python3 -m unittest -v tests.test_completion_authority.CompletionAuthorityTests.test_proof97_actual_product_frozen_nodes_from_opt_in_root
```

Result:

- `1 PASS`
- Product-owned frozen completion nodes executed and verified
- Product checkout mutation: none

This supplies the previously missing actual verifier reach/result evidence for
`ISSUE-060`. The remaining deferred issues are unchanged.

## Recovery lifecycle support check

The available recovery lifecycle and resume bridge tests were run:

```text
python3 -m unittest -q tests.test_recovery_e2e tests.test_recovery_contract tests.test_production_resume
```

Result: `27 PASS`.

These tests confirm recovery idempotency, lineage, replay, and resume-bridge rules in
the local fixture implementation. They do not execute a separate process startup with
the actual B-resume path; therefore `ISSUE-065` remains `DEFERRED`.

## Source, output, and security provenance regression check

The existing deterministic provenance and security-boundary suites were run:

```text
python3 -m unittest -q tests.test_production_worker_executor tests.test_operational_capability tests.test_host_cplus_smoke tests.test_effect_evidence_bridge
```

Result: `131 PASS / 1 skipped`.

This confirms the bounded source/output attribution, capability provenance, host
security-stage, and effect-evidence regression behavior in the local implementation.
It does not provide the actual independent source, shell-node, or security provenance
evidence required to close `ISSUE-056`, `ISSUE-063`, or `ISSUE-064`; those dispositions
remain `DEFERRED`.

## Completion and capability contract regression check

The existing completion-authority, completion-contract, operational-capability, and
canonical-provider suites were run:

```text
python3 -m unittest -q tests.test_completion_authority tests.test_completion_contract_bridge tests.test_operational_capability tests.test_production_canonical_provider_wiring
```

Result: `38 PASS / 1 skipped`.

These tests confirm the local frozen completion contract, authority assessment,
capability binding, and canonical provider wiring. They use fixtures/dry-run or
mocked boundaries and do not establish actual machine-verifiable closure for
`ISSUE-070` or an actual end-to-end capability/revision loop for `ISSUE-071`.
Both dispositions remain `DEFERRED`.

## Auth readiness and canonical recheck regression check

The existing auth-readiness, launch-bridge, canonical-authority, worker-mandatory,
and gateway-binding suites were run:

```text
python3 -m unittest -q tests.test_codex_readiness tests.test_canonical_launch_bridge tests.test_production_canonical_authority tests.test_production_worker_canonical_mandatory tests.test_gateway_canonical_binding
```

Result: `33 PASS`.

This confirms the local readiness/recheck contract and canonical authority binding.
The earlier invalid module-name collection error was corrected and is not a product
failure. The run still does not establish actual auth-recovery evidence import and
recheck for `ISSUE-075`; its disposition remains `DEFERRED`.

## Fresh ORCH04 focused revalidation

The current repository was revalidated with the combined issue-relevant suites:

```text
python3 -m unittest -q tests.test_production_worker_executor tests.test_operational_capability tests.test_host_cplus_smoke tests.test_effect_evidence_bridge tests.test_completion_authority tests.test_completion_contract_bridge tests.test_production_canonical_provider_wiring tests.test_codex_readiness tests.test_canonical_launch_bridge tests.test_production_canonical_authority tests.test_production_worker_canonical_mandatory tests.test_gateway_canonical_binding tests.test_recovery_e2e tests.test_recovery_contract tests.test_production_resume
```

Result: `213 PASS / 2 skipped`.

The full discovery attempt was not accepted as a fresh regression result because a
CLI-oriented test invoked `lv-review` without its required `--attempt` argument.
The focused suites completed successfully. This fresh run confirms local contract,
provenance, authority, readiness, and recovery behavior, but does not supply the
missing actual-boundary evidence for the remaining deferred issues. No disposition
was promoted by this run.

## Historical SSH/session evidence reconstruction

Historical terminal and interactive records under the shared archive were reviewed
for ORCH04-related execution history. They show prior implementation attempts,
checkpoint/resume proofs, provenance/security regressions, and Gate decisions.

The records also contain non-closure outcomes, including missing-artifact failures,
shell command parsing errors, runner startup failure, baseline mismatch, and prior
`NO-GO` decisions. Because these records are historical and several sessions do not
have a verifiable exit marker or independent current-head recheck, they are retained
as provenance leads rather than promoted to current `RESOLVED` evidence.

## Fresh Gate attempt

A fresh `G-4B-RELEASE-HANDOFF` stage-gate attempt was issued after the focused
revalidation. The repository strict contract loader stopped before Gate evaluation
because the engine-host checkout does not contain the managed-project lifecycle
anchors `docs/DEVELOPMENT_PLAN.txt`, `CHANGELOG.txt`, and `logs/app.log`.

The documented engine-host exception is not applied by the runtime contract loader.
No placeholder contract files were created and no Gate decision was fabricated.

## 2026-09-12 fresh Gate reattempt

The approved Working Revision now accepts the explicit `engine-host` role only when
the checkout identity and required host anchors are verified. The real repository
was checked through:

```text
python3 -m runtime.orchestrator.cli inspect --read-only --project . --role engine-host
```

Result: exit `0`, read-only mode, no runtime mutation authorization. The host role
does not create managed-project lifecycle placeholders; those three files remain
reported as absent by design.

A fresh `G-4B-RELEASE-HANDOFF` Gate was then run with the recorded authority
disposition packet and the current evidence index. Result: `CONDITIONAL GO`.
The same 11 issues remain explicitly unresolved/deferred:
`ISSUE-056`, `ISSUE-059`, `ISSUE-063`, `ISSUE-064`, `ISSUE-065`, `ISSUE-066`,
`ISSUE-067`, `ISSUE-069`, `ISSUE-070`, `ISSUE-071`, `ISSUE-075`.

The first direct retry using `.` exposed a caller-side absolute-path precondition
error; no repository change was made for that transient invocation. The accepted
retry used the resolved repository root and completed Gate evaluation.

## Contract loader boundary revalidation

The contract-loader, production-integration, and stage-gate regression suites were
run with the repository's current files:

```text
python3 -m unittest -q tests.test_contract_loader tests.test_production_integration tests.test_stage_gate
```

Result: `29 PASS` (historical run). The current Working Revision boundary tests
were subsequently rerun with the host-role additions and passed separately.

The historical result confirms the intended fail-closed behavior when a
managed-project contract is absent. The current Working Revision adds a dedicated,
identity-checked host role and host-identity tests; the default managed-project
path remains strict.

## Working Revision and fresh Gate verification

The host-role contract, CLI routing, and Gate phase-result normalization regression
tests were rerun after the Working Revision:

```text
python3 -m unittest -q tests.test_contract_loader tests.test_stage_gate tests.test_production_integration
```

Result: `33 PASS`.

The ORCH04 focused revalidation was also rerun: `213 PASS / 2 skipped`.
The fresh Gate result is recorded as `G-4B-RELEASE-HANDOFF — CONDITIONAL GO`.
No deferred issue was promoted because the run still lacks the required independent
actual-boundary evidence.

## 2026-09-12 actual transport retry

With the bounded auth probe reporting `READY`, the approved actual transport
broker-path test was attempted:

```text
HARNESS_RUN_ACTUAL_CODEX_TRANSPORT=1 python3 -m unittest -v tests.test_production_tool_transport.ProductionToolTransportTests.test_installed_codex_uses_dec007_active_broker_path
```

Result: `1 ERROR`, exit code `1`, after 180 seconds; failure category:
`TRANSPORT_TIMEOUT`. No product checkout mutation or accepted evidence artifact was
produced by this run. The timeout is retained as an environment/transport blocker,
and no deferred issue was promoted.

## 2026-09-12 privileged actual-boundary revalidation

After confirming that the timeout was caused by the sandbox's inability to initialize
the Codex state runtime, the same approved tests were rerun with state-runtime access
available. Raw authentication or provider output was not recorded.

Results:

- Actual DEC-007 broker-path read: `1 PASS` in `43.257s`.
- Actual first-WRITE/crash/same-run resume duplicate prevention: `1 PASS`.
- Actual secret-like WRITE blocking with raw-value exclusion: `1 PASS`.

These results confirm the installed transport can reach the governed broker and that
the existing security/crash protections hold at that boundary. They do not prove
separate-process startup/B-resume observability, unified Full Plan closure, or
auth-recovery evidence import/recheck. No disposition was promoted from `DEFERRED`.

## 2026-09-12 separate-process ISSUE-065 evidence

The actual Codex A-crash/B-resume path was executed in two separate Python processes:

```text
HARNESS_RUN_ACTUAL_CODEX_TRANSPORT=1 python3 -m unittest -v tests.test_production_tool_transport.ProductionToolTransportTests.test_installed_codex_separate_process_crash_then_resume_blocks_duplicate
```

Result: `1 PASS` in `15.603s`.

The first process performed the bounded fixture WRITE and terminated after durable
effect publication. A second process resumed with the same `RUN_ID` and journal; the
duplicate WRITE was blocked, the first content remained, and exactly one Intent and
Receipt remained. This satisfies the previously missing ISSUE-065 startup/B-resume
evidence. ISSUE-065 is promoted to `RESOLVED`; the other deferred issues remain
unchanged.
