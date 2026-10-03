# Two-Action Full Plan Governance V1

## Goal

Make one Full Plan run require exactly two user actions:

1. implementation approval: review the plan and authorize ordinary implementation work;
2. dangerous-work approval: review one sealed dangerous-work package and authorize every protected operation explicitly listed in that package.

After action 2 the run must never ask for a third approval. Any new scope, risk escalation, stale evidence, drift, or ambiguous dangerous effect must fail closed and terminate/block the run.

## Non-goals

- Do not weaken exact approval provenance, digest, freshness, replay, or source-lineage checks.
- Do not treat ChatGPT GitHub App comments as user approval.
- Do not merge PRs, switch runtime-current, activate production, restart/reboot services, or enter OCP P5/P6 as part of this implementation.
- Do not replace existing per-Gate approval compatibility.
- Do not create a new orchestration engine.

## User interaction contract

### Action 1 — implementation approval

The approved implementation scope may cover normal Full Plan work including read/reason, bounded writes, tests, remediation, local commits, exact feature/work-branch push, PR/CI preparation, and qualification evidence.

Protected/main branch mutation, PR merge, tag/release publication, runtime-current switch, production activation/cutover, service restart, bounded reboot, predecessor quiesce, and predecessor retirement are excluded.

### Action 2 — dangerous-work approval

Full Plan materializes a canonical `DangerousWorkPackageV1`. The user approves the package digest once. Approval authority is derived only from the sealed package; callers cannot expand allowed operations or risk classes after approval.

## DangerousWorkPackageV1

Canonical fields:

- schema_version
- project_id
- run_id
- plan_digest
- source_head
- target_ref
- operations
- risk_classes
- precondition_evidence
- required_post_verifiers
- recovery_refs
- created_at
- expires_at

The package digest is SHA-256 of the canonical projection.

### Closed protected-operation vocabulary

- `PROTECTED_PUSH`
- `PR_MERGE`
- `TAG_RELEASE`
- `RUNTIME_CURRENT_SWITCH`
- `PRODUCTION_ACTIVATION`
- `SERVICE_RESTART`
- `BOUNDED_REBOOT`
- `P5_PREDECESSOR_QUIESCE`
- `P6_PREDECESSOR_RETIREMENT`

Operations are ordered, unique, and non-empty.

## P5/P6 lifecycle rule

P5/P6 stay HOLD during this implementation.

A package containing P6 must also contain P5 before it and must require the post-P5 verifier `SUCCESSOR_HEALTH_AFTER_PREDECESSOR_QUIESCE`. P6 can be authorized only after that verifier is recorded as PASS by execution-time evidence. Package approval alone never bypasses that barrier.

PR #33 dangerous work and OCP P5/P6 retirement must be separate packages/runs because they are separate rollback domains.

## DangerousWorkApprovalV1

Runtime-side verified evidence binds:

- approval_ref
- project_id
- run_id
- package_digest
- issued_at
- expires_at
- issuer_identity
- approval_evidence_digest

The current external OAuth issuer does not yet expose a dedicated dangerous-work issuance method. Repository code therefore defines and verifies the closed contract/bridge now; actual issuer transport must provide evidence matching this contract before protected execution can pass.

## ApprovalCoverage bridge

A verified dangerous-work package plus verified approval produces `ApprovalCoverageEvidence`:

- approved_semantic_digest = package_digest
- reviewed_semantic_digest = package_digest
- allowed_operations = package.operations only
- allowed_risk_classes = package.risk_classes only

No caller-supplied expansion is permitted.

## Protected-operation guard

`authorize_protected_operation(...)` validates:

- package/approval exact project and run identity;
- exact package digest;
- approval and package not expired;
- requested operation exists in package;
- requested risk class exists in package;
- current source head and target ref match sealed values where supplied;
- execution-time preconditions are satisfied;
- P6 post-P5 barrier is satisfied;
- dangerous re-execution has safe effect reconciliation.

Failure is fail closed. After the final user approval, the policy returns a terminal/block directive rather than requesting another approval.

## Compatibility

Existing `evaluate_user_decision()` behavior remains unchanged for legacy callers. A separate two-action policy adapter converts post-final-approval scope/risk failures into fail-closed outcomes instead of `USER_DECISION_REQUIRED`.

## Acceptance criteria

- implementation user action count: 1
- dangerous approval user action count: 1
- intermediate user approvals: 0
- user terminal: 0
- user GitHub approval comment: 0
- RDC: 0
- package digest drift invalidates approval
- package operation expansion invalidates authority
- P6 cannot proceed without P5 and post-P5 successor verification
- P5/P6 remain unexecuted in this change
- existing per-Gate/legacy policy remains compatible
