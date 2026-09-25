# Governed Successor Release Staging — Design

Status: WRITTEN SPEC / PENDING USER REVIEW
Date: 2026-09-25
Scope: OCPv2 P2 Side-by-Side Deployment only
Related PR: #18 `Add governed OCP successor self-staging seam`
Durable RCA: `5831219756` — governed successor-release staging capability absent

## 1. Purpose

P2 needs one narrowly governed capability that can synchronize an already registered successor workspace to one exact reviewed release and stage successor-only user-service artifacts without activating them.

This capability exists to close the P2/L7-L8 bootstrap gap. It does **not** expand OCP into a general host mutation agent and does **not** advance the lifecycle into P3.

The authoritative flow is:

```text
GPT / OCP
  -> SUCCESSOR_RELEASE_STAGE admission
  -> Production Execution Gateway
  -> SuccessorReleaseStager
  -> Full MCP bounded operations
```

OCP remains the logical admission and verification authority. It must not acquire arbitrary Git, shell, or systemd mutation authority. All state-changing host work remains behind the existing Production Execution Gateway / Full MCP boundary.

## 2. Existing boundaries preserved

`PROJECT_ONBOARDING` remains responsible for declarative project/alias contract registration and related bootstrap validation. It is not repurposed into remote release synchronization and must not become a clone/fetch/worktree/HEAD-movement mechanism.

`HOST_INSPECTION` remains read-only and receives no mutation scope.

Existing successor `stage-user-service` behavior remains successor-profile-specific and stage-only. This design governs when and how that existing staging behavior may be reached; it does not turn staging into activation.

RDC remains break-glass only and is not part of the normal P2 path.

## 3. Goals

The capability must:

1. accept only a registered successor identity;
2. bind one request to an exact expected branch and current HEAD;
3. bind one reviewed remote ref to one exact approved target SHA;
4. prove the target is reachable by fast-forward from the admitted current HEAD;
5. update only the admitted successor workspace;
6. stage only the fixed P2 successor profile `lifecycle-v2-p2`;
7. keep successor service/timer/polling/production effects disabled;
8. prove serving artifacts are byte-identical before and after staging;
9. produce an immutable, replay-safe receipt containing all guards, SHAs, and hashes;
10. fail closed on identity drift, state drift, approval drift, non-fast-forward history, activation attempts, or post-condition failure.

## 4. Non-goals and prohibited transitions

This capability must not perform or authorize:

- `runtime-current` transition;
- P3 Canary entry;
- successor service or timer activation;
- predecessor quiesce or shutdown;
- existing Run migration;
- production polling enablement;
- arbitrary clone or worktree creation;
- arbitrary checkout or branch switching;
- force push, force update, reset, rebase, or history rewrite;
- arbitrary shell execution;
- `systemctl daemon-reload`, `enable`, `start`, `restart`, or equivalent activation paths;
- mutation of serving `ocpv2.env`, `ocpv2.service`, or `ocpv2.timer`.

Any future need for one of these operations requires a separate lifecycle gate and authority decision.

## 5. Request contract

The new request kind is `SUCCESSOR_RELEASE_STAGE`.

The canonical request schema must bind at least:

- `request_id`: unique immutable request identity;
- `schema_version`: successor release stage request schema;
- `project_alias`: registered successor alias;
- `expected_branch`: exact currently checked-out successor branch;
- `expected_head`: exact admitted current commit SHA;
- `target_ref`: exact reviewed remote release ref;
- `target_head`: exact reviewed target commit SHA;
- `successor_profile`: exactly `lifecycle-v2-p2` for P2;
- `approval_policy_ref`: canonical approval/policy reference authorizing this release stage;
- `approval_policy_digest`: immutable digest of the approval binding;
- `mode`: `DRY_RUN` or `STAGE`;
- `preflight_digest`: absent for `DRY_RUN`, mandatory for `STAGE`.

`target_ref` is the reviewed target ref and `target_head` is the exact target SHA. These names preserve the seam already started in PR #18 while making their semantics normative.

Unknown fields, unsafe identifiers, missing fields, malformed SHAs, unsupported profile values, or unsupported modes fail closed.

## 6. Two-phase binding

### 6.1 DRY_RUN

`DRY_RUN` is observation-only. It must not mutate the successor worktree, current branch, HEAD, index, Git refs, Git object database, systemd artifacts, or service-manager state.

It may use read-only local Git inspection and remote observation such as `git ls-remote` to prove that `target_ref` currently resolves to `target_head`.

It validates:

- registered successor identity;
- canonical workspace identity;
- serving/predecessor exclusion;
- clean worktree/index;
- exact branch and `expected_head`;
- exact target-ref/target-SHA remote binding;
- approval policy ref/digest binding;
- fixed successor profile;
- current HEAD is an ancestor of, or equal to, the approved target;
- all P2 authority invariants.

The resulting `preflight_digest` cryptographically binds the normalized request fields and all authoritative observations needed by `STAGE`.

A `DRY_RUN` success may report `STAGE_READY` but confers no mutation authority by itself.

### 6.2 STAGE

`STAGE` requires the exact `preflight_digest` produced by an approved `DRY_RUN` and must pass through the Production Execution Gateway.

Before any mutation, the gateway/stager must acquire the successor staging lock and revalidate all mutable facts. A stale preflight never authorizes mutation.

## 7. Workspace identity and exclusion

`project_alias` must resolve through the canonical onboarding registry. The request may not supply or override an arbitrary filesystem path.

The resolved project root must be absolute, existing, canonical, and consistent with the immutable registry entry.

Admission must derive the current serving and predecessor identities from canonical lifecycle/runtime state, not from caller-supplied exclusions.

The request is rejected when the resolved successor identity or canonical root is the current serving workspace or predecessor workspace. Alias text alone is not sufficient evidence of isolation.

The stager owns only the resolved successor root for this transaction. It receives no generic path authority outside that root except the fixed successor artifact destinations required by the existing stage-user-service contract.

## 8. Concurrency and TOCTOU fencing

`STAGE` uses an exclusive lock keyed to the canonical successor workspace/alias. Only one successor release stage transaction may mutate that workspace at a time.

The transaction must validate state at these fences:

1. admission/preflight observation;
2. after acquiring the exclusive stage lock and immediately before Git mutation;
3. immediately after Git advancement;
4. immediately before successor artifact staging;
5. immediately after successor artifact staging;
6. final post-condition/receipt boundary.

At every applicable fence, branch, HEAD, cleanliness, workspace identity, policy binding, and lifecycle exclusion are rechecked. Any unexpected drift fails closed.

No check-then-act interval may silently inherit authority from an earlier observation.

## 9. Bounded Git mutation

Only `STAGE` may mutate Git state.

The allowed sequence is:

1. revalidate exact `expected_branch`, `expected_head`, cleanliness, identity, and approval binding under lock;
2. fetch **only** the reviewed `target_ref` into a request-scoped temporary namespace such as `refs/ocp/successor-stage/<request_id>`;
3. resolve the fetched object and require exact equality with `target_head`;
4. require the admitted current HEAD to be an ancestor of, or equal to, `target_head`;
5. advance only the currently admitted branch by fast-forward to `target_head`;
6. verify post-advance branch and HEAD exactly.

The temporary ref must never be treated as a new runtime branch or lifecycle authority and must be cleaned up as a bounded staging artifact when safe to do so.

Forbidden Git operations include arbitrary fetch refspecs, arbitrary checkout, branch switching, reset, rebase, force update, detached-HEAD staging, and history rewrite.

If current HEAD already equals `target_head`, a new approved request may proceed with zero Git delta only for a legitimate idempotent/recovery staging case. It must still pass every other guard.

## 10. Successor artifact staging

Only after Git state is proven correct may the stager invoke the fixed successor staging operation equivalent to:

```text
stage-user-service --successor-profile lifecycle-v2-p2
```

This must be represented as a bounded operation/API, not as caller-controlled raw shell text.

The SuccessorReleaseStager API must structurally omit activation operations. It must have no method or option that can request:

- daemon reload;
- enablement;
- start;
- restart;
- timer activation;
- polling activation;
- production activation.

The staged successor profile must remain `DISABLED`.

## 11. Serving preservation and post-conditions

Before Git mutation, capture cryptographic hashes of the serving artifacts:

- serving `ocpv2.env`;
- serving `ocpv2.service`;
- serving `ocpv2.timer`.

After successor staging, hash the same paths again. All three pre/post hashes must be byte-identical.

Capture successor artifact state and hashes for:

- successor env/profile artifact;
- successor service unit;
- successor timer unit.

Final verification must prove:

- successor HEAD equals `target_head`;
- successor worktree/index is clean unless the canonical staging contract explicitly creates tracked-state changes, which this design does not permit;
- successor profile is `lifecycle-v2-p2`;
- successor service is not active;
- successor timer is not active;
- successor service/timer are not enabled for production polling;
- production polling remains disabled;
- serving artifact hashes are unchanged;
- serving runtime identity is unchanged;
- no P3 lifecycle state transition occurred.

Read-only service-manager queries may be used for verification; mutation-capable service-manager operations are not authorized.

## 12. Immutable receipt and idempotency

Every `DRY_RUN` and `STAGE` decision produces or updates the appropriate immutable audit record through the existing canonical receipt mechanism. A successful `STAGE` receipt must include at least:

- request ID;
- canonical request digest;
- project/successor alias and canonical root identity;
- approval policy ref and digest;
- expected branch and pre-HEAD;
- reviewed target ref and approved target SHA;
- remotely observed/fetched SHA;
- ancestor/fast-forward guard result;
- preflight digest;
- Git mutation result and pre/post HEAD;
- successor env/service/timer hashes;
- serving env/service/timer pre/post hashes;
- service/timer active and enabled observations;
- polling/production-disabled observations;
- all guard outcomes;
- final transaction outcome.

A repeated request with the same canonical request digest must not re-execute side effects. It returns the existing immutable receipt/result.

A reused `request_id` with a different canonical request digest is rejected as an identity collision.

## 13. Failure semantics and recovery

The stager fails closed and records the furthest safe phase reached.

Normative outcomes include:

- `FAILED_BEFORE_MUTATION`: no Git or successor artifact mutation occurred;
- `FAILED_AFTER_GIT_ADVANCE`: Git reached the approved target, but successor artifact staging or later verification did not complete successfully;
- `STAGED`: all Git, staging, isolation, disabled-state, and preservation checks passed.

The implementation must not use `reset --hard`, forced checkout, or another compensating history mutation to roll back a Git advance after a later failure.

After `FAILED_AFTER_GIT_ADVANCE`, recovery requires a **new admission** bound to the now-current HEAD. The new request may have zero Git delta if current HEAD already equals the reviewed target, but it must independently re-prove policy, isolation, disabled state, serving preservation, and all post-conditions.

A same-digest replay is audit/idempotency retrieval, not a recovery execution.

## 14. Admission and execution authority split

The authority model is intentionally asymmetric:

### GPT / OCP

May:

- construct/validate the request;
- verify policy and lifecycle eligibility;
- request DRY_RUN/STAGE admission;
- evaluate receipts and post-conditions.

May not:

- execute arbitrary host shell;
- perform raw Git mutation;
- perform raw systemd mutation;
- bypass Production Execution Gateway / Full MCP.

### Production Execution Gateway

Must:

- enforce request kind and schema;
- enforce approval/policy binding;
- enforce bounded capability selection;
- reject any operation outside `SUCCESSOR_RELEASE_STAGE` scope;
- dispatch only the dedicated stager capability.

### SuccessorReleaseStager

May perform only the fixed transaction described in this document. It is not a general Git or service manager facade.

### Full MCP

Provides only the bounded host primitives required by the admitted transaction. Raw/unbounded command execution is not part of this authority.

## 15. RED test contract

Before GREEN implementation, PR #18 must pin at least the following behavior:

1. exact two-phase binding: STAGE without matching preflight digest fails;
2. DRY_RUN is repository/worktree/systemd non-mutating;
3. happy path stages the exact approved target and only successor artifacts;
4. dirty successor worktree fails closed;
5. branch or expected HEAD drift fails closed;
6. non-fast-forward target fails closed;
7. serving alias/root fails closed;
8. predecessor alias/root fails closed;
9. fetched SHA different from approved `target_head` fails closed;
10. target ref drift between DRY_RUN and STAGE fails closed;
11. TOCTOU HEAD/worktree drift after admission and before mutation fails closed;
12. activation/service-manager mutation attempt is structurally unavailable or rejected;
13. serving env/service/timer hash drift fails the transaction;
14. successor active/enabled/polling state fails the transaction;
15. request replay with the same digest is side-effect free and returns the existing receipt;
16. reused request ID with a different digest fails closed;
17. failure after Git advance does not reset/rollback history and requires new admission;
18. successful receipt contains all normative SHA/hash/guard evidence.

Unit tests may instantiate `SuccessorReleaseStager` directly to prove its local contract, but the production integration test must prove that mutation is reachable only through the Production Execution Gateway / Full MCP boundary.

## 16. Relationship to current PR #18

At the current PR head, PR #18 has started the RED seam around:

- request parsing;
- `DRY_RUN` / `STAGE` two-phase binding;
- remote target binding;
- exact expected branch/HEAD;
- safe successor profile;
- fast-forward staging;
- serving file preservation;
- no service-manager invocation.

Those tests are useful but are not the complete approved contract. Before GREEN, the RED suite must be expanded to the normative matrix in Section 15 and aligned with the authority split in Section 14.

No production implementation is authorized merely by the existence of the initial PR tests. This written spec must be reviewed and approved first.

## 17. Rollout sequence

After written-spec approval, the next stages are strictly:

1. produce a separate implementation plan;
2. extend RED tests until the complete contract is pinned;
3. implement the smallest GREEN production path;
4. run focused successor-release-staging regression;
5. run full regression and regression-delta checks;
6. perform self-review and stable integration according to the existing governed development flow;
7. resume P2 host staging only after the source change is integrated and the separately controlled deployment/bootstrap boundary makes it available to the deployed OCP.

P3 remains closed throughout this work.

## 18. Acceptance criteria

This design is satisfied only when the implementation can prove all of the following simultaneously:

- OCP gained no general mutation authority;
- state-changing work remains behind Production Execution Gateway / Full MCP;
- only a registered isolated successor can be targeted;
- request, policy, branch, pre-HEAD, reviewed ref, and exact target SHA are cryptographically bound;
- only fast-forward release synchronization is possible;
- stage-user-service is successor-only and structurally non-activating;
- serving files remain byte-identical;
- successor polling/production effects remain disabled;
- every result is auditable and replay-safe;
- partial failure never triggers unsafe rollback mutation;
- runtime-current, P3, predecessor shutdown, and existing Run migration remain outside this authority.
