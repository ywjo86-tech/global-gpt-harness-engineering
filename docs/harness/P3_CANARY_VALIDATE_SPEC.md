# P3 Canary Validate Specification

The validator accepts one candidate only when project alias, candidate ID, Admission
request/evidence/result digests, approval reference, branch, head, committed plan, and
committed specification are exact matches. Any digest, source, or evidence mismatch
fails closed. This specification grants no execution, service-manager, polling,
runtime-current, predecessor, or existing-Run authority.
