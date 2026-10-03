# OCP RDC-Independent Final Stable Baseline — 2026-09-23

## Decision

**STABLE BASELINE / ACCEPTED.** Normal GPT-operated local work is promoted to the OCP + Harness path. Remote Desktop Commander is no longer a normal execution dependency and is classified **OPTIONAL_RECOVERY / BREAK_GLASS / INTERACTIVE_TERMINAL**.

## Qualified normal path

`GPT -> GitHub private control -> OCPv2 -> Full Plan / Harness -> Provider Router -> Production Execution Gateway -> HOST_GATEWAY -> governed Broker/Full MCP effect path`

Read-only observation remains available through the OCP Host Inspection / read-only diagnostic path. OCP does not become a second execution owner and does not bypass Full Plan, Gateway, tool authorization, or evidence gates.

## Live acceptance evidence

Fresh canary `GPT-FP-ACT-20260923-R9` completed `GATE-001` with `ALL_GATES_COMPLETED`, recovery count `0`, and exactly one bounded product file change: `canary.txt -> rdc-independent-full-plan-canary-pass`. The repository was clean at acceptance end, exactly one Full Plan job existed, Full Plan activation returned to OFF, and no RDC session was used inside the acceptance window.

- R9 acceptance evidence SHA-256: `ef1c2aea5c96f7fa531ee5fdd1ce1279b663976fefdf7691ae5a92f428bd1ebe`
- R9 resulting checkpoint: `a363299204e6a6dc652d3ad9fbb3de0e1dd39acb`
- R9 terminal state: `COMPLETED / ALL_GATES_COMPLETED`
- Completed gates: `GATE-001`

Historical R2/R3/R5/R6/R7/R8 attempts remain immutable incident/remediation evidence and are not reused as acceptance runs.

## Final remediation baseline

R8 exposed a buffered JSON-RPC deadlock risk caused by mixing `select()` on the OS pipe with `TextIOWrapper.readline()`. Commit `996a8d1ccc210929ea79db8a7dfb5e3227cdfe5a` replaces that split with a dedicated stdout reader thread plus bounded queue while preserving the existing absolute transport deadline and closed dynamic-tool authorization path.

Immutable runtime release:

- source head: `996a8d1ccc210929ea79db8a7dfb5e3227cdfe5a`
- manifest SHA-256: `4017a848313a3dc640cbb57613ba743700bd2907d1581d1ed3ac441cfd72c449`
- live path: `/home/ywjo/.local/share/global-gpt-harness/releases/996a8d1ccc210929ea79db8a7dfb5e3227cdfe5a`
- rollback snapshot: `/home/ywjo/.local/state/gch/ocpv2/successor-rollbacks/996a8d1ccc210929ea79db8a7dfb5e3227cdfe5a-20260923-233009`

Harness `runtime-current` intentionally remains `/home/ywjo/AI-Workspace/runtime/ocpv2-r2-c591b01`; this rollout changes the OCP successor only.

## Verification

- focused buffering/gateway/worker/review regression: `209 PASS / 2 skipped`
- comparable repository regression excluding the known optional `tests/full_mcp` SDK boundary: `2283 PASS / 15 skipped / 0 failures / 0 errors`
- `compileall`: PASS
- `git diff --check`: PASS
- immutable release verification: PASS
- immutable release `tests.test_codex_dynamic_transport`: `8 PASS / 1 skipped`
- post-deploy OCP polls: repeated `status=OK`
- OCP service: `Result=success`, `ExecMainStatus=0`
- `ocpv2.timer`: active
- `OCP_WORK_ACTIVATION_ENABLED=0`
- `OCP_FULL_PLAN_ACTIVATION_ENABLED=0`

The literal `tests/full_mcp` discovery boundary remains the previously documented environment dependency on the external Python `mcp` package. No SDK was installed merely to convert that optional collection boundary into a green result.

## Operational disposition

`PRIMARY = GPT -> OCPv2 -> Harness / Full Plan -> Router -> Gateway -> governed tool-effect path`

`READ = GPT -> OCPv2 -> Host Inspection / read-only diagnostic`

`RDC = OPTIONAL_RECOVERY / BREAK_GLASS / INTERACTIVE_TERMINAL`

Any future use of RDC during a claimed RDC-independent acceptance window invalidates that window and requires a fresh run. Risk-expanding changes continue to require the normal approval boundary.
