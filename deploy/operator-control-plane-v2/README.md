# OCPv2 user-service bootstrap package

This directory contains the fail-closed user-level deployment package for Operator Control Plane v2. Preparing or installing these files does **not** by itself authorize service activation, mutation canary execution, production activation, credential creation, or migration changes.

The default configuration is `DISABLED`. A separately authorized Gate B may prepare the user service in `OBSERVE_ONLY`; the installer intentionally rejects `CONTROL_MUTATION_CANARY` and `ACTIVE`. The public source repository is not a valid control repository. A dedicated private control repository and an explicitly provisioned token file with owner-only permissions (for example `0600`) are required before any control mode can pass validation.

`bootstrap.py check` validates bootstrap configuration only. `bootstrap.py render` writes review artifacts only to an explicitly supplied output directory. `bootstrap.py install-user-service` writes the reviewed user-level environment and unit files, but it never invokes systemd. `manual_deploy.py` contains only reviewable activation/rollback command projection and likewise invokes no service manager.

The installed systemd unit runs `python3 -m runtime.orchestrator.ocpv2_runtime_service`. In `OBSERVE_ONLY` and `CONTROL_READ_ONLY`, that runtime has no state-changing execution path. In a separately authorized `CONTROL_MUTATION_CANARY` or `ACTIVE` mode, a state-changing directive can call only the canonical registered-Full-Plan resume adapter. That adapter cannot register a new Job, choose an LV, construct a WorkerRequest, or select a provider; it verifies the exact registered Job, Full Plan state SHA, next continuation-owner epoch, Gate/gate-run binding, source HEAD, and executor runtime digest under the existing Full Plan run lock, then resumes the existing Full Plan path. Provider/model selection remains solely under Provider Router and state-changing tool execution remains behind Production Execution Gateway / Full MCP.

Use the public `ocpv2.example.env` only as a template. Replace `/path/to/global-gpt-harness-engineering` with the exact validated local repository root at deployment time. Do not commit local paths, credentials, token contents, live run identifiers, approval digests, migration transaction hashes, or queue contents to this repository.

After a separately authorized Gate B has validated and installed the user-level files, activation remains an explicit local user action:

```bash
systemctl --user daemon-reload
systemctl --user enable --now ocpv2.timer
```

The timer invokes the one-shot service every 30 seconds. These commands are documentation only and are not executed by repository implementation or CI.

Initial manual deployment should remain `OBSERVE_ONLY`. Promotion to `CONTROL_MUTATION_CANARY` is a separate authorization boundary and requires an exact canary scope in the service environment: `OCP_CANARY_PROJECT_ID`, `OCP_CANARY_RUN_ID`, `OCP_CANARY_TASK_ID`, `OCP_CANARY_GATE_ID`, and `OCP_CANARY_DIRECTIVE_ID`. Missing scope fields fail closed. Promotion from a successful canary to `ACTIVE` is another explicit operational decision; bootstrap installation never performs either promotion automatically.

Rollback after activation is explicit and non-destructive:

```bash
systemctl --user disable --now ocpv2.timer
systemctl --user stop ocpv2.service
```

Restore the last reviewed `ocpv2.env` only if configuration rollback is also required. Rollback must not edit canonical Harness task, Gate, checkpoint, migration, provider, completion, or recovery state. OCP transport receipts/outbox remain non-authoritative bookkeeping.
