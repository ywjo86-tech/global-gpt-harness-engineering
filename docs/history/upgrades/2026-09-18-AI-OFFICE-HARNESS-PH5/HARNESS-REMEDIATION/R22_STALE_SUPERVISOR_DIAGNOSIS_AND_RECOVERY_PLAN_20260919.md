# R22 Stale Supervisor Diagnosis and Recovery Plan

Status: DIAGNOSED / RECOVERY PLAN APPROVED BY CURRENT CONTINUE INSTRUCTION  
Protocol: `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` (EDP-1.0)

## Stop point
- R22 was sealed to HEAD `1ffb4e798219b2101ca63bde5333b44c4daabc21`.
- Initial Provider ACTION generation, Broker effects, and validation-remediation attempt-01 had executed.
- The durable state remained `RUNNING`, but the supervisor/worker processes disappeared without a terminal event.
- Last heartbeat: `2026-09-19T01:55:37Z`; no process was alive when re-diagnosed.
- Generated TASK-015 files had already been preserved under `_workspace/failed-run-rollbacks/r22-task015/`.

## Root causes
1. R22 semantic remediation convergence was insufficient; this was corrected by `d13027d` candidate pre-effect focused verification.
2. R22 had been launched as a foreground process rather than through the available transient systemd durable launcher, so an external/session process loss could leave state stale until startup reconciliation ran.
3. R22 cannot be safely resumed after Harness HEAD advanced: adoption protection correctly rejects unrelated Harness changes outside TASK-015 owned scope.

## Correction / recovery
- Keep `d13027d` candidate pre-effect verification.
- Terminalize the stale R22 state via startup reconciliation; do not adopt or rewrite old product files.
- Preserve rollback/effect evidence.
- Start the next production run with a fresh approval bound to current HEAD.
- Launch the next run with `--launch-transient`; the generated unit uses `Restart=on-failure`, `RestartSec=5s`, and startup reconciliation.
- Keep Router/MPRF/Broker authority, retry counts, sanitizer limits, and owned scope unchanged.

## Verified recovery evidence
- Startup reconciliation converted R22 from stale `RUNNING` to an explicit terminal `BLOCKED` state with `lease=null` and `recovery_count=1`.
- Old-run adoption then failed closed with `production worker adoption scope violation`, proving new Harness commits were not silently adopted.
- Exact user-bus systemd environment was verified on the Jarvis server.
- Controlled restart probe: first process exit=1, systemd restarted it, second exit=0; observed `ATTEMPTS=2` and final service result `success`.
- `d13027d` independent verification: focused `236 PASS / 1 skip`; full repository `1610 PASS / 12 skip / RC=0`.

## Next authorized action
Create fresh R23 approval/job on the current clean HEAD and run it through the transient durable launcher. R22 remains historical evidence only.
