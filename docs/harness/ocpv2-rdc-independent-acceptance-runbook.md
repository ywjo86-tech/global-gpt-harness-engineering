# OCPv2 RDC-Independent Primary Path Acceptance Runbook

Status: OFFLINE IMPLEMENTATION QUALIFIED / SUCCESSOR FEATURE-OFF DEPLOYMENT PENDING

> The prior V1 activation canary is preserved as failure evidence only. Phases C-D must not resume from that run. A fresh acceptance window is required after implementation and qualification of `docs/superpowers/specs/2026-09-23-approved-work-execution-link-remediation-design.md`.

## Goal

Prove normal GPT operations work through OCP + Harness without RDC participating in the tested path, then and only then promote RDC to `OPTIONAL_RECOVERY`.

## Candidate and current stable baseline

- Successor candidate HEAD: `ac5347bad16c4e594f2e93cec90767177e169329`.
- Current live OCP WorkingDirectory at preflight: `/home/ywjo/AI-Workspace/runtime/ocpv2-r2-c591b01`.
- Preflight timer state: active/waiting; one-shot service polls completed with `status=OK`.
- `OCP_HOST_INSPECTION_ENABLED`, `OCP_WORK_ACTIVATION_ENABLED`, and activation policy ref were unset at preflight, therefore fail-closed. The successor additionally requires `OCP_FULL_PLAN_ACTIVATION_ENABLED=0` with no executable activation policy ref.

The current-state observations above were collected with RDC before the acceptance window. They are preparation only and MUST NOT be counted as RDC-independent acceptance evidence.


## Control request class separation

```text
APPROVED_WORK_ACTIVATION       = V1 tracking/manual receipt only
APPROVED_FULL_PLAN_ACTIVATION = executable generic AUTO_RECONCILE registration
EXISTING_RUN_CONTROL           = OCPV2-owned continuation only
```

The successor MUST be deployed with `OCP_FULL_PLAN_ACTIVATION_ENABLED=0` and without `OCP_FULL_PLAN_ACTIVATION_POLICY_REF`. The successor runtime switch itself is a separate live operational approval; feature-OFF packaging and review do not authorize service installation, reload, start, restart, or a live control request.

## Approval boundary

No successor runtime switch, live feature enablement, live activation request, canary mutation, or RDC bridge stop/disconnect is authorized merely by this runbook.

A separate explicit live-canary approval is required before those actions.

## Acceptance window rule

After the successor is deployed feature-OFF and health is confirmed, record the acceptance-window start marker. From that marker until rollback/end:

- no RDC command/session may provide input, execution, verification, or evidence;
- no silent fallback to RDC is allowed;
- all normal-path requests enter through GitHub private control → OCPv2;
- mutations remain Full Plan → Router/MPRF → Production Gateway → Full MCP;
- any need to use RDC invalidates that acceptance window and requires a fresh run after recovery.

## Phase A — Successor feature-OFF qualification

1. Deploy the exact qualified successor generation with Host Inspection and V1 settings preserved from the predecessor, and with `OCP_FULL_PLAN_ACTIVATION_ENABLED=0`.
2. Keep existing control repository, PR, actor allowlist, token binding, OCP mode, and Full Plan ownership unchanged.
3. Verify timer/service polling, legacy V2 existing-run control, result publication, Full Plan boot reconciliation, and attention/recovery.
4. Record successor runtime identity and exact source HEAD.

Expected: executable Full Plan registration is unreachable while `OCP_FULL_PLAN_ACTIVATION_ENABLED=0`; no executable policy ref is configured, and all pre-existing Host Inspection/V1 settings remain unchanged.

## Phase B — Host Inspection only

1. Enable `OCP_HOST_INSPECTION_ENABLED=1`; keep Work Activation OFF.
2. Through GitHub private control → OCP only, execute bounded probes:
   - `git.branch`, `git.status`, `git.diff`;
   - approved file read/search/metadata;
   - `user_service.properties` for the allowlisted OCP unit;
   - `harness.attention`.
3. Record request digest, projection ID/digest, project alias, operation, source HEAD, and status for each probe.
4. Require `inspected>0` and `executed=0` for inspection polls.
5. Verify durable outbox projection matches the remotely published result.

Expected: all reads return typed bounded results; no mutation callback or new job registration occurs.

## Phase C — Executable Approved Full Plan Activation canary

1. Use one disposable committed canary spec/plan/requirement artifact plus Harness-sealed Gate approval/engine evidence with explicit user approval binding.
2. Enable `OCP_FULL_PLAN_ACTIVATION_ENABLED=1` and one exact executable activation policy ref while Host Inspection and V1 activation remain independently controlled.
3. Submit exactly one typed `APPROVED_FULL_PLAN_ACTIVATION` request.
4. Verify one and only one generic `AUTO_RECONCILE` Full Plan job and one create-once executable activation receipt.
5. Replay the identical sealed request and verify no second job is registered.
6. Verify existing Full Plan boot/reconcile discovers the job; OCP must not launch it directly and OCP existing-run continuation must reject AUTO_RECONCILE ownership.

## Phase D — Governed mutation proof

1. Let the registered canary Full Plan reach the approved mutation Gate through the existing boot/reconcile path.
2. Perform one bounded file mutation and one focused validation through the normal execution chain only.
3. Record Full Plan state/owner evidence, Production Gateway handoff evidence, Full MCP effect/audit evidence, and focused validation result.
4. Use Host Inspection only after the mutation to observe resulting Git state; inspection must not be used as effect authority or completion evidence.

Expected: exactly one execution owner performs the mutation; OCP itself has no direct write, shell, provider/model, or Full MCP authority.

## Phase E — RDC outage tolerance and rollback

1. During the acceptance window, verify audit/history contains no RDC invocation for normal-path work.
2. If explicitly approved and operationally safe, stop only the RDC remote bridge after OCP/Harness health is established; do not stop OCP, Full Plan, or Harness services.
3. Repeat one bounded Host Inspection and confirm control/results still flow through OCP.
4. Roll back executable Full Plan activation to `0`, then restore any separately changed Host Inspection/V1 settings to their approved baseline, preserving registered Full Plan state, activation receipts, outbox evidence, and logs.
5. Confirm legacy V2 control and OCP polling remain healthy after rollback.

Any use of RDC for recovery terminates the current acceptance window; recover first, then start a fresh window.

## Evidence required for PASS

- exact successor runtime identity and source HEAD;
- feature-OFF baseline health;
- Host Inspection request/result digests for every bounded probe;
- one activation request digest, binding digest, activation digest, canonical job path, and authority digest;
- replay evidence proving no duplicate job registration;
- existing-run resume evidence distinct from activation identity;
- governed mutation/effect/validation evidence with single execution owner;
- RDC-exclusion audit for the acceptance window;
- feature-OFF rollback evidence and post-rollback OCP health.

## Promotion rule

Do not change `docs/DEVELOPMENT_PLAN.txt` to `RDC=OPTIONAL_RECOVERY` until every acceptance phase above passes and broad regression is green.

After PASS the intended operating model is:

```text
PRIMARY: GPT -> OCPv2 -> AI Office/Harness -> Full Plan -> Router/MPRF -> Gateway -> Full MCP
READ:    GPT -> OCPv2 -> Host Inspection Port
RDC:     OPTIONAL_RECOVERY / BREAK_GLASS / INTERACTIVE_TERMINAL
```
