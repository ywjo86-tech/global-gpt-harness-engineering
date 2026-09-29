# OCP Gate Approval Issuance

## Purpose

Close the zero-terminal gap between an approved project Gate and
`APPROVED_FULL_PLAN_ACTIVATION`. A canary is a qualification fixture, not a
per-project credential. Each Full Plan activation still requires a fresh,
project-specific Gate approval bound to the exact source HEAD.

## Existing authority

- Full Plan remains final task assignment authority.
- The project mapping and canonical plan remain the source of Gate/LV scope.
- The Gate approval evidence schema is
  `orchestration.gate-approval.v1`; its validator binds project, Gate,
  requirements digest, plan digest, branch, HEAD, LV order, owned files, and
  validity window.
- The Harness approval namespace is the only destination. GitHub comments and
  repository files are transport/evidence references, not replacement authority.
- This feature never activates Full Plan or advances a Gate.

## Proposed bounded control flow

1. `GATE_APPROVAL_ISSUE` in `DRY_RUN` mode verifies the registered project,
   canonical mapping/plan, exact branch/HEAD, clean source, Gate scope,
   requirements digest and bounded expiry. It returns a preflight digest and
   the proposed approval payload without writing.
2. The project owner posts a separate exact approval comment in GitHub PR #1,
   after reviewing the DRY_RUN digest and scope. The comment must have the
   expected owner account ID, exact canonical approval body, no edit history,
   and `performed_via_github_app: null`. Connector-posted control comments
   carry an app identity and cannot act as owner approval. The approval
   reference must be specific to this project/Gate/HEAD; a policy ref alone
   is not user approval.
3. `ISSUE` carries the preflight digest and approval reference. OCP repeats
   every read-only check, verifies the owner approval binding, seals the
   existing Gate approval schema, and writes a create-once file under the
   project approval namespace. Existing identical content is an idempotent
   replay; different content is a conflict.
4. OCP returns the namespace-relative evidence path and SHA-256. A separate
   `APPROVED_FULL_PLAN_ACTIVATION` request uses those exact values.

## Required boundaries

- Feature flag and policy reference distinct from Full Plan activation,
  disabled by default.
- No caller-selected absolute output path, arbitrary filesystem write,
  repository mutation, service restart, or runtime-current switch.
- Never infer owner approval merely from a GPT_OPERATOR envelope posted with
  the owner's GitHub credentials. Verify a distinct owner decision bound to
  the preflight digest before ISSUE.
- Bounded expiry; stale preflight, source drift, mapping drift, and scope drift
  fail closed.
- Durable create-once write, conflict detection, recovery of a completed
  write before result projection, and redacted result.
- Preserve PR #33 HOLD and P5/P6 HOLD during qualification.

## Test gates

- DRY_RUN has zero effects and returns stable scope/digest.
- ISSUE with exact owner approval writes one valid artifact, then activation
  registers against the same HEAD.
- Missing/forged approval, old HEAD, dirty worktree, changed plan/requirements,
  wrong alias/Gate, expired approval, path escape, symlink, concurrent replay,
  conflicting replay, and crash after write all fail closed or reconcile once.
- Existing Work/Full Plan/Project Onboarding requests and remote envelope
  decoding remain compatible.
- CI and a fresh host canary must pass before enabling the feature in OCP.

The GitHub provenance field distinguishes the observed Codex connector from
comments without an app identity. It does not prove a person used the browser;
the owner must keep personal API credentials out of automation. The issuer
must also validate the approved requirements artifact, not just a caller
supplied digest, before production use.

## Deployment

Implement on the OCP successor source line in a separate branch and PR. Merge,
runtime release staging, runtime-current switch, and feature enablement remain
separate gates. The current GitHub control PR cannot issue this artifact until
the deployed OCP supports the new request kind.
