# OCP Primary + Read-only Diagnostic Integration — 2026-09-23

## Scope

Integrate the live-qualified read-only host diagnostic line into the newer RDC-independent OCP primary-path line without weakening either authority boundary.

## Lineage

- Primary-path parent: `8c4cfc38a641c99f5e9dc9f07450a915709a55fb`
- Diagnostic parent: `d6ee88d71e9a0d041526a4472516437dc5d4442c`
- Common ancestor: `ac5347bad16c4e594f2e93cec90767177e169329`

## Conflict resolution

Three content conflicts were resolved in `ocpv2_runtime_service.py`, `remote_operator_service.py`, and `test_ocpv2_runtime_service.py`. The merged runtime keeps both the dedicated executable Full Plan activation gate/policy and the typed read-only diagnostic gate/policy. Poll results retain both `full_plan_activated` and `diagnosed` counters.

An auto-merged test helper incorrectly routed the V1 `APPROVED_FULL_PLAN_ACTIVATION` envelope through the diagnostic V2/V3 sealer. It was restored to the V1 control-envelope sealer/validator. A coexistence regression confirms diagnostic and executable Full Plan feature flags can be loaded together without either overwriting the other.

## Verification

- `git diff --check`: PASS
- `python3 -m compileall -q runtime tests deploy/operator-control-plane-v2`: PASS
- Focused merged authority suite: `113` tests, `OK`
- Literal discovery: `2301` tests, four pre-existing `ModuleNotFoundError: No module named 'mcp'`, `15` skipped
- Comparable regression excluding only `tests/full_mcp`: `2275` tests, `OK (skipped=15)`

The external `mcp` package was not installed or altered to conceal the known environment deficiency.

## Deployment boundary

This repository integration does not switch `runtime-current`, edit the live OCP environment, restart services, enable executable work activation, or change canonical Full Plan/provider state. Live deployment of this combined successor remains a separate operational gate.
