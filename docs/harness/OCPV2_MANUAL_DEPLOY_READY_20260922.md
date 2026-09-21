# OCPv2 Manual Deployment Readiness — 2026-09-22

## Status

`MANUAL_DEPLOY_PREPARED / LIVE_ACTIVATION_NOT_PERFORMED`

This record closes the source-side Gate E and manual-deployment preparation work. It does **not** authorize or claim a live Jarvis service upgrade, mutation canary, production ACTIVE mode, merge to `main`, or migration change.

## Verified code-bearing baseline

- Branch: `impl/operator-control-plane-v2-r2`
- Exact code-bearing HEAD: `ab184a9293b86524df2e96118bf5815c890a15ab`
- Hosted CI run: `35668309502` (`OCPv2 R2 CI`, run 161)
- Result: workflow `SUCCESS`
- Focused OCPv2/Gate E/deployment/authority tests: PASS
- Whole-repository regression: PASS
- Baseline/current regression-delta: PASS

A final exact-head CI is required after this closure-only documentation is committed. No implementation completion claim may rely only on the code-bearing run above.

## Gate E execution boundary

The deployed OCPv2 runtime can perform a state-changing action only when the selected control mode separately permits it and all canonical bindings are present. The mutation path is:

`GitHub private control transport -> OCPv2 validation -> registered Full Plan exact-state resume -> existing Gate/LV execution -> Provider Router -> Production Execution Gateway -> Full MCP`

OCPv2 does not register a new Full Plan Job, select an LV, construct a WorkerRequest, select a provider/model, or call a tool/shell backend directly. The registered-Full-Plan resume adapter requires the exact project/run/Gate identity, active queue `gate_run_id`, Full Plan state SHA-256, next continuation-owner epoch, project source HEAD, and executor runtime digest. These bindings are checked before the owner-claim write, and mutable external identities are checked again under the existing Full Plan run lock before dispatch.

## Deployment safety boundary

Initial manual deployment remains `OBSERVE_ONLY`.

`bootstrap.py install-user-service` may write the reviewed user environment and systemd user-unit files, but it does not invoke `systemctl` and rejects installation directly into `CONTROL_MUTATION_CANARY` or `ACTIVE`.

The installed one-shot service invokes:

```text
python3 -m runtime.orchestrator.ocpv2_runtime_service --env-file %h/.config/gch/ocpv2.env
```

The user timer invokes the one-shot service every 30 seconds.

Promotion to `CONTROL_MUTATION_CANARY` is a separate approval boundary. It additionally requires an exact five-field canary scope (`project_id`, `run_id`, `task_id`, `gate_id`, `directive_id`) and the state-changing envelope must carry the exact canonical state/runtime bindings. `ACTIVE` remains a later separate operational decision.

## Manual activation boundary

After the exact verified source revision is present on the Jarvis host and the reviewed `OBSERVE_ONLY` environment/unit files have been installed, only the following service-manager actions are required from the user:

```bash
systemctl --user daemon-reload
systemctl --user enable --now ocpv2.timer
systemctl --user status ocpv2.timer --no-pager
```

These commands have **not** been executed by this implementation task.

## Rollback

If the new service fails initial qualification, stop the user timer/service without altering canonical Harness state:

```bash
systemctl --user disable --now ocpv2.timer
systemctl --user stop ocpv2.service
```

If configuration rollback is required, restore the previously reviewed `ocpv2.env` after the timer/service has been disabled. Do not delete or rewrite canonical Full Plan, checkpoint, migration, completion, provider, or recovery state as part of OCPv2 rollback.

## Post-activation qualification

The first qualification after user activation is non-mutating:

1. Confirm `ocpv2.timer` is active.
2. Send one fresh `OBSERVE_ONLY` control envelope through the dedicated private control PR.
3. Require exactly one bounded result projection and no replay churn across subsequent timer cycles.
4. Archive/inert the qualification control after the result.
5. Stop before mutation canary unless the Project Owner separately authorizes Gate E live canary scope.

## Historical note

Task 14 originally ended before creation of a live private control repository/token and before live bootstrap. Subsequent Gate B/C/D work created the dedicated private control channel and proved live `OBSERVE_ONLY` / `CONTROL_READ_ONLY` transport. This readiness record preserves that later history while keeping the present manual upgrade and mutation activation as separate boundaries.
