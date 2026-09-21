# OCPv2 user-service bootstrap package

This directory contains the prepared, fail-closed user-level bootstrap package for Operator Control Plane v2. Preparing these files does **not** authorize installation, service activation, mutation canary execution, production activation, credential creation, or migration changes.

The default configuration is `DISABLED`. A separately authorized Gate B may prepare the user service in `OBSERVE_ONLY`; Gate B does not authorize `CONTROL_MUTATION_CANARY` or `ACTIVE`. The public source repository is not a valid control repository. A dedicated private control repository and an explicitly provisioned token file with owner-only permissions (for example `0600`) are required before any control mode can pass validation.

`bootstrap.py check` validates configuration only. `bootstrap.py render` writes review artifacts only to an explicitly supplied output directory. `bootstrap.py install-user-service` writes user-level environment and unit files, but it does not invoke systemd and must not be run until separate authorization is granted.

Use the public `ocpv2.example.env` only as a template. Replace `/path/to/global-gpt-harness-engineering` with the exact validated local repository root at deployment time. Do not commit local paths, credentials, token contents, live run identifiers, approval digests, migration transaction hashes, or queue contents to this repository.

After a separately authorized Gate B has validated and installed the user-level files, activation remains an explicit local administrative action:

```bash
systemctl --user daemon-reload
systemctl --user enable --now ocpv2.timer
```

These commands are documentation only here and have not been executed by the implementation task. The timer invokes the one-shot service every 30 seconds. Bootstrap composition is restricted to `DISABLED`, `OBSERVE_ONLY`, and `CONTROL_READ_ONLY`; it installs no mutation executor. Provider or model selection is not performed by this package and remains solely under the existing Provider Router.

Rollback before activation is simply to leave the timer disabled and retain `OCP_MODE=DISABLED`. After an authorized activation, rollback should disable the user timer/service and restore the last reviewed environment file without modifying canonical Harness state. Canonical task, Gate, checkpoint, migration, provider, completion, and recovery truth remains outside the transport/bootstrap layer.
