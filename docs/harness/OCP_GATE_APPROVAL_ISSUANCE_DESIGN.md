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
   requirements evidence references, requirements digest and bounded expiry.
   It uses the same requirement-artifact validator as Full Plan activation,
   then returns a preflight digest and
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

## G1-only request route

G1 uses the existing typed `GATE_APPROVAL_ISSUE` envelope through the dedicated
alias `ocp-rdc-exec-canary-20260923-r2-g1`. Its immutable alias record lives in
`HARNESS_CONTRACT_MAPPING_ROOT/g1-approval-registry-main/aliases`; the existing G3
alias registry and its route remain separate. A G1 project/GATE-001 request
resolved through the generic alias is rejected.

The G1 issuer pins project `OCP-RDC-EXEC-CANARY-20260923-R2`, `GATE-001`, branch
`main`, source HEAD `99dc2ff4081cae87bf2d777b8912d25760592b2f`, plan digest
`a2d9b105bafa0e07819d1e35519f59e7e190b18b18223534451dca980241d3fa`, and
requirements digest
`0119f3527f3987eeb4337e7a8c459516d33fb7a077180f448ae49d4a9898b001`. The
source is held in a clean `main` checkout at that exact HEAD. The independent
Owner-anchor heads are read-only and included in the preflight digest.

`OCP_G1_GATE_APPROVAL_ISSUE_ENABLED` and
`OCP_G1_GATE_APPROVAL_ISSUE_POLICY_REF` select the G1 route and remain
disabled by default. The G1 policy reference must differ from the generic Gate
approval policy. The exact personal Owner GitHub comment bound to the DRY_RUN
digest remains the ISSUE authorization. Dashboard WebAuthn approval remains a
separate user-approval workflow; it does not by itself create this Gate
artifact.

An earlier read-only preflight record from 2026-10-23 reported
`EXECUTABLE_REQUIREMENT_BINDING_MISMATCH` and claimed the pinned source lacked
the `TASK-001` / `NFR-001` contract. Direct inspection of the pinned clean
source at `99dc2ff4081cae87bf2d777b8912d25760592b2f` found the committed
`docs/req-task-001.json` artifact, with SHA-256
`0119f3527f3987eeb4337e7a8c459516d33fb7a077180f448ae49d4a9898b001`; the
project-requirement resolver and loader matched its `NFR-001` semantics to the
canonical plan. The earlier diagnosis is therefore stale or incomplete and
does not establish the exact request or runtime cause. The G1 profile now pins
the LV, committed path, and artifact digest, and the route rejects any missing
or different reference before reading the Owner anchor or authority registry.
The candidate test also exercises the generic issuer's real committed-artifact
validation on an isolated Git source fixture. Before enabling the route, repeat
a live DRY_RUN with the pinned request reference against the intended registry,
mapping, source, and Owner-anchor service, and preserve its fresh result as
evidence.

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
must bind the project-specific requirement evidence and digest during both
preflight and activation.

## Deployment

Implement on the OCP successor source line in a separate branch and PR. Merge,
runtime release staging, runtime-current switch, and feature enablement remain
separate gates. The current GitHub control PR cannot issue this artifact until
the deployed OCP contains the G1-specific profile and its isolated alias registry.
