# TASK-017 Rollback Package

Rollback anchor: Full MCP final approved branch lineage `0bdfad12c438f4f101d3fdeafda9daac8d5069b4`.
Rollback scope: TASK-017 controlled runtime compatibility files only.

If GATE-001 re-evaluation fails because of TASK-017 material defect, preserve evidence first, then restore only TASK-017 controlled files to the rollback anchor. Do not reset, clean, rewrite history, touch unrelated dirty work, implement MPRF, or add Git publication authority.

Controlled files are the TASK-017 CT-002~012 and CT-034~037 targets recorded in the approved Development Plan. Any rollback must be followed by TEST-002~006 focused validation and GATE-001 re-evaluation.
