# Skill Continuity Pressure Test

Incident fixture: active Full Plan retargets its own runtime while activation requires zero active jobs.

RED: pre-remediation design contract lacked self-reference, successor, and rollback closure.

GREEN: tests/test_harness_design_continuity_skill.py requires Stateful Continuity Review, CI-CONT-01..05, self-reference, successor, rollback, and NOT READY.

Adversarial variants cover service restart, supervisor replacement, worktree deletion, server reboot, scheduler replacement, and state-store relocation.
