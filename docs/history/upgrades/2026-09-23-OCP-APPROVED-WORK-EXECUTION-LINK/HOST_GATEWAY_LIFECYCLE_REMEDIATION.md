# HOST_GATEWAY Lifecycle Remediation — 2026-09-23

## Diagnosis

The fresh executable Full Plan canary `GPT-FP-ACT-20260923-R2` registered exactly one `AUTO_RECONCILE` job, but GATE-001 exhausted its retry budget with `HOST_GATEWAY_TRANSPORT_FAILURE`. The bounded product effect did not occur and `canary.txt` remained `baseline`.

Root cause: the production worker correctly required `HOST_GATEWAY` and resolved a workspace-bound UDS endpoint, but no production lifecycle owner created the one-shot `UnixSocketHostRunner`. `host_runner_entry.py` existed as a broker-native foreground entrypoint, while no normal Full Plan path invoked it. The client therefore attempted a valid gateway request against a nonexistent socket.

A separate malformed Host Inspection control caused temporary OCP `INGRESS_FAILED`; its envelope digest mismatch was isolated from the gateway failure and the control was made inert. OCP polling returned to `status=OK` before this remediation.

## Remediation

Add `ManagedHostRunner`, a per-request lifecycle wrapper which launches `runtime.orchestrator.host_runner_entry` from the exact executing runtime code root, waits for the authenticated UDS socket, returns the existing `UnixSocketGatewayTransport`, and terminates/cleans the one-shot runner after the request. It is not a persistent daemon and does not introduce a local execution fallback.

`execute_production_worker()` uses this manager only when the caller did not inject an explicit gateway transport. Canonical gateway validation still runs before the managed runner is created. The broker-native runner remains the only effect path and the existing UDS UID/mode/peer checks remain authoritative.

## Qualification

- RED: managed lifecycle test failed because `ManagedHostRunner` did not exist.
- GREEN: managed runner exposes a one-shot socket and cleans it safely.
- RED: repository invariant showed no production wiring to the managed runner.
- GREEN: executor uses exactly one managed-runner callsite when transport is not injected.
- Focused regression: 199 tests PASS, 6 skipped.
- Comparable regression excluding the known optional `tests/full_mcp` SDK import boundary: 2278 tests PASS, 15 skipped.
- Literal discovery: 2304 tests, only the four pre-existing `ModuleNotFoundError: mcp` collection errors, 15 skipped.

## Rollout boundary

Build a new immutable release from this commit and deploy it as the OCP successor with Full Plan activation OFF. Harness `runtime-current` is not switched. A fresh activation request must use the new release digest and a new activation/run/message identity; historical failed canaries are immutable and must not be resumed.
