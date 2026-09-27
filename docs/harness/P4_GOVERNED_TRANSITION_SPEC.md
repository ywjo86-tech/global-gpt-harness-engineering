# P4 Governed Transition Specification

P4 transition consumes an exact P4 read-only entry and immutable source and target
runtime releases. Observe-only preflight and one bounded health probe grant no
mutation. Cutover admission is ready only when no active registered Full Plan job,
service, timer, polling loop, unsealed source, or lineage mismatch remains.

Cutover atomically retargets runtime-current, verifies the target, rehearses atomic
rollback to the sealed source, and then reapplies the target. Predecessor shutdown,
existing Run migration, and polling are separate authorities and are never implied.
Any mismatch or partial evidence fails closed.
