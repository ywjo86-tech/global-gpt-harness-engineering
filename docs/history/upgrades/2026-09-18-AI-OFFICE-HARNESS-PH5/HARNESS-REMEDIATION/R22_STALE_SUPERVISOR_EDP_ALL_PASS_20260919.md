# R22 Stale Supervisor Recovery — EDP ALL PASS

Status: **ALL PASS for the supervisor-recovery boundary only**  
Protocol: `standards/EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` (EDP-1.0)

## Authority / evidence
- Current user instruction to diagnose, write a correction plan, apply generic diagnosis, and solve the issue.
- Canonical EDP-1.0 common diagnosis standard.
- R22 durable state/events and rollback evidence.
- `production_full_plan_runner.py` startup reconciliation and adoption guards.
- `production_full_plan_entry.py` transient systemd launcher.
- `d13027d` candidate pre-effect verification and its regression evidence.

## Findings and disposition
- F1 semantic candidate defect: CLOSED by `d13027d`; focused 236/1-skip and full 1610/12-skip PASS.
- F2 stale RUNNING after process disappearance: CLOSED operationally by startup reconciliation; R22 now explicit BLOCKED, lease cleared.
- F3 unsafe continuation across changed HEAD: CLOSED by adoption fail-closed; old R22 not reused.
- F4 recurrence risk from foreground launcher: CLOSED for next run by verified transient systemd `Restart=on-failure` launch path.

## Negative-space / adversarial pass
No retry count, sanitizer limit, provider authority, owned scope, mutation authority, Broker authority, or canonical plan was widened or changed. A controlled restart probe proved the chosen durable launcher actually restarts a failed process. Startup reconciliation and adoption protection were verified from code and live R22 behavior.

`BLOCKER=0`, `UNRESOLVED_MAJOR=0`, `ADVERSARIAL_NEW_BLOCKER_MAJOR=0`, `PASS_CHALLENGE=0` for the stale-supervisor recovery boundary. TASK-015/GATE-005 are **not** declared complete; fresh R23 production evidence is still required.

Diagnostic-skill note: no separate installed generic diagnosis `SKILL.md` was found on the server, so the canonical EDP-1.0 common diagnosis protocol that such a skill must bind was applied directly.
