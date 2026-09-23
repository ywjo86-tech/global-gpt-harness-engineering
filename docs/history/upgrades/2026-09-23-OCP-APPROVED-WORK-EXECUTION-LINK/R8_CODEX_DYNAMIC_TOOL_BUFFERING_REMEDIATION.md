# R8 Codex Dynamic Tool Buffering Remediation — 2026-09-23

## Stop point and evidence

Fresh canary `GPT-FP-ACT-20260923-R8` registered one `AUTO_RECONCILE` job and launched GATE-001/TASK-001 through the governed HOST_GATEWAY path. The worker remained `RUNNING / WORKER_STARTED` while heartbeat timestamps continued to advance. `canary.txt` stayed at the committed baseline.

Codex App Server session evidence showed the first `PROJECT_OWNED_FILE_LIST` call completed and the model then emitted a valid `PROJECT_OWNED_FILE_WRITE` call for the approved `OWNED_0001 -> canary.txt` mapping. The host effect journal contained only the completed LIST intent/receipt; no WRITE intent existed. Process evidence showed the host runner waiting for App Server stdout while Codex itself remained alive. Therefore the WRITE request had not reached `SingleToolBroker`.

R8 was closed as immutable incident evidence. Full Plan activation was disabled, the transient R8 unit was stopped, and the durable R8 state was sealed `CANCELLED / R8_STALLED_CODEX_APP_SERVER_SECOND_DYNAMIC_TOOL_DISPATCH` before the periodic reconciler was resumed.

## Root cause

`CodexAppServerAdapter.run_turn()` mixed `select.select(process.stdout)` with `TextIOWrapper.readline()`. A text `readline()` may prefetch multiple newline-delimited JSON-RPC messages into Python's user-space buffer. When that occurs, the OS pipe can appear empty to `select()` even though another complete protocol line is already buffered in `TextIOWrapper`. If App Server is waiting for the response to that buffered dynamic-tool request, both sides wait until the global transport timeout.

A real OS-pipe regression reproduced this as `TRANSPORT_TIMEOUT` before the production change.

## Remediation

The App Server stdout path now has one daemon reader thread that continuously calls `readline()` and places complete lines into a queue. The protocol loop waits on the queue using the existing absolute turn deadline. This removes the kernel-fd/user-buffer split without changing JSON-RPC contracts, tool authorization, Broker ownership, execution backend selection, provider policy, or timeout authority.

## Verification

- RED: real buffered text-pipe regression reproduced `TRANSPORT_TIMEOUT`.
- GREEN: the same regression passes and consumes two buffered dynamic-tool calls.
- `tests.test_codex_dynamic_transport`: 8 PASS, 1 opt-in test skipped in the normal run.
- Focused transport/gateway/worker/review regression: 230 PASS, 7 skipped.
- Installed Codex 0.150.1 single-tool dynamic transport smoke: PASS.
- Installed Codex 0.150.1 multi-call smoke: `COMPLETED`, 3 sequential governed dynamic-tool calls; PASS criterion was >=2 calls and terminal completion.
- `git diff --check`: PASS before broad regression.

## Recovery rule

R8 is never resumed. A successor canary must use a new activation/run/message identity, a clean deliberately restored baseline, and an immutable runtime release containing this transport remediation. Full Plan activation remains OFF outside the successor canary window.
