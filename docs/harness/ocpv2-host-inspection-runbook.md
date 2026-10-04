# OCPv2 Host Inspection Qualification Runbook

Status: implementation qualification only; no stable-runtime promotion is implied by this document.

## Purpose

Qualify the RDC-independent Host Inspection Port while preserving the existing Full Plan mutation path and keeping RDC outside the normal dependency chain.

The first successor runtime MUST start with `OCP_HOST_INSPECTION_ENABLED=0`. Do not use RDC as evidence for this qualification.

## Preconditions

- Implementation branch and exact HEAD are recorded.
- Full regression is green before live qualification.
- Existing `ocpv2.timer` / `ocpv2.service` are healthy.
- `HARNESS_CONTRACT_MAPPING_ROOT` points to the existing Harness mapping root containing `aliases/`.
- Target project alias is already registered and validates against its canonical plan.
- The GitHub control repository, PR channel, actor allowlist, token file and normal OCP bindings are unchanged.
- No approval is inferred from this runbook; use the already-approved implementation scope only.

## Phase 0 — Feature OFF baseline

1. Ensure the environment file contains exactly `OCP_HOST_INSPECTION_ENABLED=0` or omits the key entirely.
2. Run `systemctl --user daemon-reload` only if the installed unit changed.
3. Confirm `systemctl --user is-active ocpv2.timer` is `active` and inspect the last `ocpv2.service` result.
4. Submit no Host Inspection request yet.
5. Verify legacy V2 read-only/mutation behavior is unchanged by focused regression evidence.

Expected: Host Inspection is unavailable and no inspection callback can execute. Existing V2 control behavior remains unchanged.

## Phase 1 — Bounded observation canary

Enable only the feature flag; do not widen project roots, service units, provider policy, mutation authority, or Full Plan scope.

Use `OCP_HOST_INSPECTION_ENABLED=1` with the existing `HARNESS_CONTRACT_MAPPING_ROOT`. Keep the current OCP mode; `OBSERVE_ONLY` or `CONTROL_READ_ONLY` is preferred for the first inspection smoke.

Trigger one poll after the environment edit. Do not change mutation canary bindings for this test.

## Phase 2 — Single `git.branch` smoke request

Send exactly one typed `HOST_INSPECTION` request with:

- registered `project_alias` only;
- operation `git.branch`;
- empty `arguments`;
- `state_change_required=false`;
- current issue/expiry timestamps;
- existing GitHub transport binding and GPT operator actor;
- an inspection policy reference;
- sealed payload and envelope digests.

Expected result:

- result schema is `orchestration.remote-inspection-projection.v1`;
- request ID, correlation ID, project alias, operation and request digest match the request;
- status is `OK`;
- data contains branch/HEAD information from the registered repository;
- OCP poll evidence increments `inspected` and does not increment `executed` for the inspection.

## Phase 3 — Result digest verification

Verify the durable outbox artifact and the published projection describe the same sealed inspection result.

Use the Harness parser, not ad-hoc field deletion:

```bash
python3 - <<'PY'
import json
from pathlib import Path
from runtime.orchestrator.remote_operator_outbox import parse_remote_projection

p = Path("<OCP_STATE_ROOT>/outbox/published/<PROJECTION_ID>.json")
projection = parse_remote_projection(json.loads(p.read_text(encoding="utf-8")))
print(projection.projection_id)
print(projection.projection_sha256)
PY
```

Parse the published projection body through the same `parse_remote_projection()` path and require the same `projection_id` and `projection_sha256`. Also require its `request_digest` to equal the original Host Inspection request digest.

Any mismatch is a hard stop; do not retry by changing request fields.

## Phase 4 — Mandatory immediate rollback to OFF

After the single smoke request, set `OCP_HOST_INSPECTION_ENABLED=0` even when the smoke passes.

Then trigger/await the next OCP poll and confirm:

- Host Inspection no longer executes;
- the OCP timer/service remain healthy;
- existing V2 control remains available under its prior mode and authorization rules;
- no new project root, provider/model choice, shell capability, Full MCP runtime authority, or job-registration authority was added.

If the canary failed, leave the feature OFF and preserve the pending/published outbox and logs for diagnosis. Do not delete evidence and do not fall through to RDC or Manual Action as an automatic retry.

## Rollback triggers

Rollback immediately on project-binding drift, symlink/sensitive-path violation, unexpected mutation, secret-like projection rejection, output bound violation, transport/digest mismatch, service observer scope escape, or any legacy V2 regression.

## Promotion criteria

Host Inspection may move beyond the one-request canary only after all of the following are recorded:

- focused Host Inspection integration tests PASS;
- complete repository regression PASS;
- forbidden dependency scan is clean;
- one live `git.branch` inspection succeeds without RDC evidence;
- durable result digest matches the published result;
- immediate feature-OFF rollback is demonstrated;
- legacy V2 mutation compatibility remains green;
- the normal mutation path remains Full Plan → Router/MPRF → Production Gateway → Full MCP.

This runbook does not authorize `APPROVED_WORK_ACTIVATION`, arbitrary shell, direct Full MCP invocation, provider/model selection, or new project onboarding.

## RDC role during this qualification

RDC is not part of success evidence. It remains available only as a break-glass recovery mechanism if OCP/Harness itself becomes inaccessible. Using RDC during a smoke invalidates that smoke as RDC-independent evidence and requires a fresh run after recovery.
