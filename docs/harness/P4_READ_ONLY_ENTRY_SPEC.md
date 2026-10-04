# P4 Read-Only Entry Specification

P4 entry requires an exact `P3_FINAL_QUALIFIED` receipt for the same project,
candidate, Admission digest, branch, and head. Entry records a create-once
read-only receipt. Runtime-current switching, predecessor shutdown, existing Run
migration, successor polling, generic mutation, and service-manager invocation
remain unauthorized.
