# P3 Canary Validate Full Plan

Scope is exactly one fresh P3 candidate admitted through Lifecycle V2. The plan may
register validation work only. It must not switch runtime-current, quiesce or stop the
predecessor, migrate an existing Run, enable successor polling, or mutate unrelated
project state.

The candidate remains blocked until a matching create-once P3_CANARY_VALIDATE evidence
record, this committed plan, its committed specification, and a durable WAIT handoff
are all bound to the same Admission digest.
