# OCPv2 Read-only Host Diagnostic Qualification

Date: 2026-09-23
Qualification target SHA: `1bf66c8bb2166a8f4fb71c1f0b0a2d8fdfc67de2`
Bound base SHA: `c591b01e8a1d9d9bb2dc438ca85f6c2ffcc79a03`

## Result

The bounded read-only host diagnostic implementation is qualified for review while remaining disabled by default. No live activation or stable-runtime mutation was performed.

```text
FEATURE_DEFAULT=OFF
LIVE_ACTIVATION_PERFORMED=NO
FA6_STABLE_RUNTIME_MUTATED=NO
```

## Integrity checks

Command:

```bash
git diff --check c591b01e8a1d9d9bb2dc438ca85f6c2ffcc79a03...HEAD
```

Result: exit `0`, PASS.

Command:

```bash
python3 -m compileall -q runtime tests deploy/operator-control-plane-v2
```

Result: exit `0`, PASS.

## Focused OCP / diagnostic regression

Command:

```bash
python3 -m unittest -v \
  tests.test_read_only_host_diagnostic_contract \
  tests.test_read_only_host_diagnostic \
  tests.test_remote_diagnostic_outbox \
  tests.test_remote_operator_envelope \
  tests.test_remote_operator_ingress \
  tests.test_remote_operator_receipt \
  tests.test_remote_operator_service \
  tests.test_ocpv2_runtime_service
```

Result: exit `0`; `Ran 82 tests`; `OK`.

## Adversarial qualification

Explicit named tests covered absolute and `../` path rejection, intermediate/final symlink blocking, special/binary/sensitive file blocking, secret redaction, truncation semantics, malicious Git diff-helper suppression, fixed non-interactive Git environment, non-allowlisted systemd unit blocking, exact `systemctl --user show` argv with no lifecycle verb, V3 state-change denial, feature-OFF behavior, V2 `READ_ONLY_ACCEPTED` preservation, crash recovery without diagnostic re-execution, canonical mutation delegation, and authority negative-space.

Result: exit `0`; `Ran 17 tests`; `OK`.

## Repository regression

The literal complete discovery command was run:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Result: exit `1`; `Ran 2148 tests`; four import errors; `15 skipped`. All four errors are the same pre-existing test-environment deficiency recorded at baseline: `tests/full_mcp` imports fail because the current shell does not have the external Python package `mcp`. The failing modules are `test_adapter_contract`, `test_e2e_regression`, `test_gate_evidence`, and `test_runtime_server`. No source/test failure outside that dependency boundary was reported.

The comparable repository regression excluding only the same SDK-dependent `tests/full_mcp` directory was then run:

```bash
mods=$(find tests -type f -name 'test_*.py' ! -path 'tests/full_mcp/*' -print | sed 's#^./##;s#/#.#g;s#\.py$##' | tr '\n' ' ')
python3 -m unittest $mods
```

Result: exit `0`; `Ran 2124 tests`; `OK (skipped=15)`.

No package installation or environment mutation was performed to conceal or alter the baseline dependency deficiency.

## Authority invariants

- OCP runtime still has no job-registration, direct `Popen`/`os.system`, or provider-selection authority.
- State-changing work still delegates only to the registered Full Plan continuation path.
- Remote service contains no direct file/Git/systemd diagnostic implementation.
- V2 behavior remains compatible, including non-diagnostic `READ_ONLY_ACCEPTED`.
- V3 diagnostics are typed, non-mutating, policy-bounded and durable before remote publication.
- Diagnostic execution is limited to `CONTROL_READ_ONLY` and `ACTIVE`; other modes remain non-executing/fail-closed.
