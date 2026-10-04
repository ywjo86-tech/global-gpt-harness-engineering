# AWEL Authority Artifact Boundary Amendment

**Date:** 2026-09-23
**Trigger:** Task 3 implementation-time architectural finding
**User decision:** Authority artifact boundary correction approved
**Runtime mutation:** none

## Finding

The prior AWEL wording required Gate approval evidence to be a committed project file while `gate-approval.v1` seals and validates the exact project Git HEAD. Committing an approval that contains HEAD `H` necessarily creates a later HEAD, so the evidence can never simultaneously be committed in that repository and bind the current execution HEAD.

Available canonical evidence confirms that `validate_approval_evidence()` compares the approval payload `head` to the execution head, while existing Full Plan integration fixtures place Gate approval evidence outside the project Git tree. Weakening the HEAD check or synthesizing a replacement approval is prohibited.

## Corrected Boundary

```text
Project Git / committed project authority
  - approved plan
  - approved spec
  - mapping-bound TASK-to-LV projection source
  - per-LV project requirement contracts

Harness authority state / sealed external authority
  - global-gate/<project_id>/approval/<relative> : gate-approval.v1
  - global-gate/<project_id>/artifact/<relative> : engine R01-R25 evidence
```

Harness roots are system-derived from `harness_state_root` using the existing `namespace_root()` semantics. Remote requests may carry only safe namespace-relative names plus exact SHA-256 digests; they never carry an absolute path or namespace root. Activation reads but does not create, move, or rewrite these authority artifacts.

## Preserved Invariants

- Gate approval exact HEAD, project, Gate, LV scope, expiry and record-hash checks remain mandatory.
- Project plan/spec/project-requirement evidence remains committed and digest-bound.
- Mapping and TASK-to-LV projection authority remains unchanged.
- No new approval schema, approval database, requirement schema, execution owner, worker, Gateway, Full MCP path, outbox, shell path or RDC fallback is introduced.
- Existing `APPROVED_WORK_ACTIVATION` V1 and old canary evidence remain unchanged.

## Implementation Impact

Task 1's provisional executable request contract must distinguish Harness authority refs (`relative_path`, `sha256`) from committed project artifact refs (`path`, `sha256`). Task 3 must resolve Gate approval through the fixed `approval` namespace and engine conformance evidence through the fixed `artifact` namespace. Offline/live fixtures must place these sealed artifacts outside the product Git tree before activation.

The existing implementation plan is therefore stale from Task 3 onward until regenerated/amended from the revised written spec. Task 1 and Task 2 commits remain useful evidence but Task 1 requires a compatibility-preserving follow-up adjustment before the executable path can be considered complete.
