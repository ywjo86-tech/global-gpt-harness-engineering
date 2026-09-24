# RUFLO-MCP / JEV-MCP Integration Design Candidate v0.1

Status: DESIGN CANDIDATE / NOT IMPLEMENTATION APPROVED
Date: 2026-09-24
Repository baseline: `main@c591b01e8a1d9d9bb2dc438ca85f6c2ffcc79a03`
Scope: AI Office Harness / Full Plan / Provider Router / MPRF / Execution Backend Contract / Full MCP / OCPv2 compatibility

## 1. Purpose

Introduce Ruflo and Jev as external MCP-delivered capabilities without creating a second orchestrator, bypassing provider/model selection authority, bypassing execution/effect authority, or weakening existing approval and recovery semantics.

Primary goal:

> External MCP may advise. Harness decides. Full MCP acts.

This document is architectural design only. It does not authorize package installation, production registration, API-key changes, daemon activation, provider routing changes, or live traffic.

## 2. Existing Authority Invariants

The integration MUST preserve the current canonical boundaries:

- GPT remains Logical Operator / decision authority.
- AI Office Harness owns workflow, governance, integration, approval/risk policy and operating state.
- Full Plan owns planning, task decomposition, required capability declaration, and final task-to-agent assignment.
- Provider Router remains the sole provider/model selection authority.
- MPRF owns provider runtime lifecycle, health, quota, transition/failover, checkpoint/resume mechanics and provider runtime events.
- Execution Backend Contract remains the backend-neutral execution handoff boundary.
- Full MCP remains action/effect/reconciliation authority and canonical side-effect evidence owner.
- OCPv2 remains non-authoritative transport/control-plane plumbing and MUST NOT become a second orchestrator.
- State-changing execution continues through Production Execution Gateway / Execution Authorization Binding / Full MCP.
- RDC remains emergency recovery tooling and is not a runtime dependency of OCPv2 or this integration.

Any design that violates one of these invariants is rejected regardless of external-tool capability.

## 3. Important Formalization Correction

An earlier conceptual sketch placed Jev before the Provider Router as a routing signal. Under the current Harness authority model, that placement is not acceptable if Jev is model-backed, because calling Jev itself is a provider/model invocation.

Therefore this design moves Jev behind the existing authority path:

```text
Full Plan
  -> declares typed-judgment capability
Provider Router
  -> resolves authorized model/provider decision reference
Execution Authorization Binding
  -> authorizes bounded external capability call
Execution Backend Contract
  -> Full MCP external-MCP adapter
  -> Jev MCP adapter
  -> TypeSafe Jev API
```

Jev output may inform a later Harness decision, but Jev does not select itself, another provider, an agent, a gate outcome, or an execution action.

## 4. Integration Approaches Considered

### Approach A — Directly register Ruflo and Jev into the Operator environment

Advantages:
- fastest setup;
- minimal adapter code;
- maximum external tool surface.

Rejected because:
- Ruflo can become a second orchestration plane;
- Jev community MCP packages can embed policy and provider fallback logic outside Harness governance;
- tool exposure is too broad;
- observability/effect evidence may bypass canonical Full MCP tracing;
- hidden side effects and nested provider calls are difficult to prove absent.

### Approach B — Filtered External Capability Gateway through Full MCP

Advantages:
- preserves single-authority architecture;
- supports strict allowlisting;
- all external invocations are evidence-bound;
- failure is typed and auditable;
- permits shadow/canary rollout;
- external implementation can be swapped without changing Harness authority.

Selected.

### Approach C — Absorb Ruflo/Jev functionality into Harness source

Advantages:
- maximum control;
- lowest runtime dependency on external MCP servers.

Rejected for initial integration because:
- increases Harness size and maintenance burden;
- duplicates external projects;
- raises regression blast radius;
- violates Stable Core Protection unless proven necessary.

## 5. Target Architecture

```text
User / JARVIS / OCPv2
        |
        v
AI Office Harness
  - Workflow / Governance
  - Approval / Risk Policy
  - Capability Registry
        |
        v
Full Plan
  - Task decomposition
  - Required capability
  - Final agent assignment
        |
        +------------------------------+
        |                              |
        | model-backed capability      | non-model external capability
        v                              v
Provider Router                   Capability Eligibility
  - sole model/provider               |
    selection authority               |
        |                              |
        +--------------+---------------+
                       |
                       v
             Execution Authorization Binding
                       |
                       v
              Execution Backend Contract
                       |
                       v
                    Full MCP
              External MCP Adapter
                 /           \
                /             \
               v               v
       Ruflo MCP Proxy      Jev MCP Adapter
       read-only/advisory   typed judgment
               |               |
               v               v
             Ruflo        TypeSafe Jev API
```

The Full MCP external-MCP adapter is the canonical invocation/effect boundary. Neither OCPv2 nor Full Plan calls Ruflo/Jev directly.

## 6. Capability Registry Entries

### 6.1 Ruflo

Canonical capability id:

`external.ruflo.coordination_advisory.v1`

Required metadata:

```text
mode = advisory
state_change = forbidden
nested_provider_call = forbidden_initially
filesystem_write = forbidden
shell_execution = forbidden
git_write = forbidden
background_daemon = forbidden
autonomous_loop = forbidden
canonical_memory_write = forbidden
human_approval_authority = false
provider_selection_authority = false
agent_assignment_authority = false
```

Ruflo is treated as an External Multi-Agent Coordination Advisor, not an execution harness.

Initial allowlist is intentionally tiny and MUST be discovered/verified against actual MCP tool schemas before activation. Native tool names are not assumed in this design.

Permitted capability classes after verification may include:

- health / doctor / version information;
- read-only topology or coordination analysis;
- read-only security/quality analysis;
- read-only task-local memory lookup if it is proven non-canonical and non-mutating;
- consensus/advisory results that do not launch workers or model calls.

Explicitly blocked initially:

- agent spawn;
- worker spawn;
- background daemon;
- autonomous hooks that cause work;
- direct Claude/Codex/model launch;
- provider routing;
- filesystem/shell/git mutation;
- Ruflo-owned canonical memory writes;
- any tool whose side-effect behavior cannot be proven.

If a Ruflo tool internally invokes a model/provider, it becomes ineligible in Phase 1. A future version may support delegated provider-bound Ruflo execution only after an explicit authority-contract extension.

### 6.2 Jev

Canonical capability id:

`external.jev.typed_judgment.v1`

Required metadata:

```text
mode = advisory
model_backed = true
provider_router_decision_required = true
state_change = forbidden
filesystem_write = forbidden
shell_execution = forbidden
git_write = forbidden
human_approval_authority = false
provider_selection_authority = false
execution_authority = false
```

Jev is treated as an External Typed Judgment Service.

Preferred production shape is a thin in-house MCP adapter around the TypeSafe API, not a policy-rich community MCP package. Community MCP implementations may be used as reference/test fixtures only.

Minimal stable adapter surface:

- `jev.health`
- `jev.choice`
- `jev.score`
- `jev.noul`
- optional composed `jev.verify` after the first three primitives are stable

The adapter MUST NOT implement:

- automatic provider fallback;
- agent selection;
- approval decisions;
- execution gating;
- patch application;
- merge/ship decisions;
- implicit retry to another provider;
- policy escalation outside Harness.

## 7. Common External Capability Contract

Every external MCP request MUST carry an immutable envelope similar to:

```json
{
  "schema_version": "external-capability.request.v1",
  "project_id": "...",
  "project_run_id": "...",
  "task_id": "...",
  "task_execution_id": "...",
  "correlation_id": "...",
  "operation_request_id": "...",
  "capability_id": "external.jev.typed_judgment.v1",
  "request_digest": "sha256:...",
  "policy_ref": "...",
  "authorization_ref": "...",
  "provider_decision_ref": "... or null",
  "deadline_ms": 5000,
  "payload": {}
}
```

Every external MCP response MUST normalize into:

```json
{
  "schema_version": "external-capability.result.v1",
  "capability_id": "...",
  "non_authoritative": true,
  "result": {},
  "confidence": null,
  "evidence_ref": "...",
  "provider_decision_ref": "... or null",
  "external_server_version": "...",
  "external_model": "... or null",
  "latency_ms": 0,
  "usage": null,
  "result_digest": "sha256:...",
  "error": null
}
```

`non_authoritative=true` is mandatory and cannot be overridden by an external MCP response.

## 8. Data and Secret Policy

- API keys remain in environment/secret storage and never enter prompts, MCP tool arguments, logs, reports or Git.
- External payloads MUST pass existing secret/redaction checks.
- Credentials, tokens, private keys and unrelated workspace data are forbidden.
- Source code or business data sent to Jev/Ruflo follows the same approved external-provider data policy as other cloud model traffic.
- Payload logging stores digests/metadata by default; full external request bodies are not required for canonical observability.
- Ruflo local memory, if enabled later, cannot become the source of truth for PCM, Harness durable state or LLMWiki.

## 9. Decision Semantics

External advice never directly transitions Harness state.

Examples:

```text
Jev says SAFE
  != execute

Jev says BLOCK
  != canonical block unless Harness policy independently maps it

Ruflo recommends 4-agent swarm
  != spawn 4 agents

Ruflo proposes parallel tasks
  != Full Plan decomposition
```

Correct pattern:

```text
External result
  -> evidence/advice
  -> Harness / Full Plan / Governance evaluates
  -> canonical decision
  -> if action required, normal authorization path
  -> Full MCP acts
```

## 10. Failure Semantics

All failures are typed. No silent fallback.

Required error classes:

- `CAPABILITY_UNAVAILABLE`
- `CAPABILITY_TIMEOUT`
- `CAPABILITY_RATE_LIMITED`
- `CAPABILITY_AUTH_MISSING`
- `CAPABILITY_SCHEMA_MISMATCH`
- `CAPABILITY_VERSION_UNAPPROVED`
- `CAPABILITY_SIDE_EFFECT_DENIED`
- `CAPABILITY_NESTED_PROVIDER_DENIED`
- `CAPABILITY_LOW_CONFIDENCE`
- `CAPABILITY_RESULT_INVALID`

Rules:

- Optional advisory capability failure may return control to Full Plan with evidence that advice was unavailable.
- Required advisory capability failure must not be silently skipped.
- Jev low confidence never auto-escalates to a hard-coded provider; Full Plan/Provider Router re-evaluates according to existing policy.
- Ruflo tool behavior that contradicts declared read-only metadata immediately disables/quarantines that capability version.
- Restart/recovery preserves pending external capability state and correlation ids; it does not replay completed external calls without idempotency policy.

## 11. Observability

For every call record:

- project_id
- project_run_id
- task_id
- task_execution_id
- correlation_id
- operation_request_id
- capability_id
- MCP server id/version
- MCP tool id/version
- provider_decision_ref when model-backed
- external model/version when applicable
- request digest
- result digest
- policy ref
- authorization ref
- start/end timestamp
- latency
- usage/cost metadata when provided
- confidence/probability when provided
- normalized error class
- `non_authoritative=true`

Do not duplicate Full MCP/MPRF source-of-truth events; external capability records are correlated projections/evidence.

## 12. Security / Negative-Space Requirements

The integration MUST prove the following remain impossible:

1. Ruflo cannot spawn provider/model workers in the initial profile.
2. Ruflo cannot edit files, run shell, publish Git or start a daemon through the allowed MCP profile.
3. Jev cannot select its own transport/provider independently of an authorized routing decision in production mode.
4. Jev/Ruflo cannot transition approval state.
5. Jev/Ruflo cannot trigger Full MCP actions directly.
6. OCPv2 cannot call external MCP tools without Harness authority.
7. External MCP cannot write canonical Harness, Full Plan, MPRF, Full MCP, PCM or LLMWiki state.
8. Tool schema changes fail closed until requalified.
9. An unapproved MCP package/version cannot activate.
10. A missing external service does not stop unrelated Harness work.

## 13. Package / Version Governance

- No `latest` in production registration.
- Pin exact package version or immutable Git commit.
- Record package hash where feasible.
- Maintain approved version allowlist.
- Tool-schema digest is part of qualification evidence.
- Any tool-set expansion is a controlled capability change.
- Community Jev MCP packages are not production trust roots.
- Ruflo 300+ tool surface is never bulk-exposed to Harness.

## 14. Rollout Gates

### RJI-0 — Authority Fit / Design Gate

Pass conditions:
- no authority overlap;
- Jev moved behind provider/model authority path;
- external invocation flows through Execution Backend Contract / Full MCP;
- OCPv2 untouched;
- no production activation.

### RJI-1 — Read-Only Discovery

Actions:
- inspect Ruflo MCP tool list and schemas;
- inspect Ruflo versions and runtime requirements;
- inspect Jev API/OpenAPI and candidate MCP adapter behavior;
- record exact dependencies;
- run no state-changing tool.

Pass conditions:
- capability taxonomy complete;
- candidate allowlist/denylist complete;
- unknown side-effect tools = denied.

### RJI-2 — Jev Thin Adapter Lab

Actions:
- implement minimal adapter or local deterministic mock first;
- enforce provider_decision_ref contract;
- add choice/score/noul schema tests;
- verify timeout/auth/rate-limit handling.

Pass conditions:
- typed results only;
- no embedded policy authority;
- no fallback outside Provider Router;
- regression tests green.

### RJI-3 — Ruflo Filtered Proxy Lab

Actions:
- run Ruflo MCP in isolated lab profile;
- expose zero tools by default;
- admit individual tools only after schema + side-effect proof;
- prove agent spawn/provider launch/filesystem/shell/git/background loop are blocked.

Pass conditions:
- allowlist-only proxy;
- nested provider count = 0;
- mutation count = 0;
- unapproved tool invocation fails closed.

### RJI-4 — Full MCP External Capability Adapter

Actions:
- bind common request/result envelope;
- bind execution evidence;
- add correlation and restart handling;
- preserve existing action authority.

Pass conditions:
- no direct Harness->external MCP bypass;
- evidence digest recorded;
- typed error mapping complete.

### RJI-5 — Shadow Mode

Jev/Ruflo results are recorded but do not affect planning, routing, approval or execution.

Pass conditions:
- no behavior delta in canonical Harness decisions;
- latency/cost/error/confidence telemetry available;
- no authority violations.

### RJI-6 — Bounded Canary

Initial production candidates:
- Jev: claim/evidence verification or bounded classification only;
- Ruflo: one verified read-only advisory tool only.

No autonomous swarm, no provider execution, no Ruflo daemon.

### RJI-7 — EDP Integrated Qualification

Run:
- functional regression;
- authority matrix regression;
- negative-space tests;
- crash/restart/replay tests;
- schema drift tests;
- auth/secret tests;
- timeout/rate-limit tests;
- optional capability outage tests;
- observability traceability;
- rollback test.

Exit condition:
- blocker/major = 0;
- authority bypass count = 0;
- unapproved mutation count = 0;
- external provider bypass count = 0;
- ALL PASS.

### RJI-8 — Live Activation

Requires separate explicit user/governance approval.

This design approval does not authorize RJI-8.

## 15. Rollback

Rollback unit is capability registration, not Harness core.

```text
disable external.ruflo.coordination_advisory.v1
and/or
disable external.jev.typed_judgment.v1
```

After disable:
- Harness core remains operational;
- existing Provider Router path remains unchanged;
- Full MCP action path remains unchanged;
- OCPv2 remains unchanged;
- no durable canonical state migration is required.

This is a required design property.

## 16. Recommended Implementation Order

1. RJI-1 read-only discovery.
2. Jev thin adapter + deterministic mock.
3. Full MCP generic external-MCP adapter contract.
4. Jev shadow integration.
5. Ruflo zero-tool proxy + individual-tool qualification.
6. Ruflo shadow integration.
7. Combined observability and EDP qualification.
8. Bounded canary.
9. Separate live-activation approval.

Jev is implemented first because its bounded typed-judgment surface is easier to constrain. Ruflo follows only after the external capability boundary is proven.

## 17. Acceptance Criteria for This Design

This design is acceptable only if all statements are true:

- Ruflo is not a second Harness.
- Ruflo is not an autonomous executor in the initial profile.
- Jev is not a hidden provider-selection bypass.
- external MCP invocation is observable and evidence-bound.
- Provider Router remains sole provider/model selection authority.
- Full MCP remains sole canonical action/effect/reconciliation authority.
- Full Plan remains final task/agent assignment authority.
- Governance/Human approval remains authoritative.
- OCPv2 remains non-authoritative transport/control plane.
- external service outage is isolated and typed.
- rollback does not require Harness-core rollback.

## 18. External Source Notes

Verified on 2026-09-24:

- Ruflo exposes a large MCP surface and supports memory/swarm/security capabilities; full registration can expose hundreds of MCP tools. Production integration therefore requires a filtering proxy and exact version pinning.
- TypeSafe Jev exposes typed Choice/Score/Noul style decisions through `/v1/systemone` and model discovery through `/v1/models`.
- Multiple community Jev MCP packages exist, but their policy/fallback surfaces differ and their 0.x APIs are not suitable as canonical production authority without a thin local boundary.

References:
- https://github.com/ruvnet/ruflo/wiki/Installation
- https://github.com/ruflo-app/ruflo
- https://api.typesafe.ai/docs
- https://typesafe.ai/blog/introducing-system-one-models-and-jev
- https://github.com/jkudish/jev-mcp

## 19. Decision

Recommended architecture: **Filtered External Capability Gateway through the existing Execution Backend Contract / Full MCP boundary.**

Recommended trust model:

```text
Ruflo = advisory coordination capability
Jev   = typed judgment capability
Harness / Full Plan / Governance = decision authority
Provider Router = model/provider authority
Full MCP = action/effect authority
```

Next step after user review/approval of this written design: create a detailed implementation plan. No implementation begins before that approval.
