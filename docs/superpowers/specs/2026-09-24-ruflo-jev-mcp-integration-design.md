# RUFLO-MCP / JEV-MCP Integration Design Candidate v0.2

Status: DESIGN CANDIDATE / EDP SELF-REVIEWED / NOT IMPLEMENTATION APPROVED
Date: 2026-09-24
Repository baseline: `main@c591b01e8a1d9d9bb2dc438ca85f6c2ffcc79a03`
Scope: AI Office Harness / Full Plan / Provider Router / MPRF / Execution Backend Contract / Full MCP / OCPv2 compatibility

## 1. Purpose

Introduce Ruflo and Jev as external MCP-delivered advisory capabilities without creating a second orchestrator, bypassing provider/model selection authority, bypassing execution/effect authority, or weakening existing approval and recovery semantics.

Primary rule:

> External MCP may advise. Harness decides. Full MCP acts when a side effect is required.

This document is architectural design only. It does not authorize package installation, production registration, API-key changes, daemon activation, provider-routing changes, or live traffic.

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

## 3. EDP Corrections to the Initial Concept

### 3.1 Jev cannot sit in front of Provider Router

An earlier conceptual sketch placed Jev before the Provider Router as a routing signal. That is not acceptable if Jev is model-backed, because invoking Jev is itself a provider/model call.

Correct authority flow:

```text
Full Plan
  -> declares typed-judgment capability
Provider Router
  -> resolves an authorized specialized provider/model decision
MPRF / approved provider runtime boundary
  -> supplies provider runtime decision/evidence
Execution Backend Contract
  -> invokes the approved read-only external capability adapter
Jev MCP Adapter
  -> TypeSafe Jev API
```

Jev output may inform a later Harness decision, but Jev does not select itself, another provider, an agent, a gate outcome, or an execution action.

### 3.2 Advisory MCP calls should not expand Full MCP core responsibility

The v0.1 draft put every external MCP invocation inside Full MCP. EDP re-review found that this is broader than necessary and weakens Stable Core Protection.

The approved architecture already separates read-only execution from state-changing authority. Therefore v0.2 uses an additive read-only adapter behind the existing Execution Backend Contract:

```text
Execution Backend Contract
   |-- Full MCP Adapter
   |     -> state-changing / canonical action-effect path
   |
   `-- External Advisory MCP Adapter
         -> read-only / non-authoritative capability path
```

The External Advisory MCP Adapter has no mutation authority. If a requested capability requires a side effect, the advisory adapter MUST reject it and the task must re-enter the existing authorization path to Full MCP.

## 4. Integration Approaches Considered

### Approach A — Directly register Ruflo and Jev into the Operator environment

Rejected because:
- Ruflo can become a second orchestration plane;
- policy-rich Jev community MCP packages can embed fallback/gating outside Harness governance;
- the tool surface is too broad;
- direct registration weakens correlation, version governance and fail-closed controls;
- hidden side effects or nested provider calls are difficult to prove absent.

### Approach B — Filtered External Advisory Capability Gateway through Execution Backend Contract

Selected because:
- preserves single-authority architecture;
- creates no Full MCP core dependency for read-only advisory work;
- supports zero-trust allowlisting;
- keeps all calls evidence-bound and auditable;
- preserves Provider Router authority for Jev;
- permits shadow/canary rollout;
- allows external implementation replacement without changing core authority.

### Approach C — Absorb Ruflo/Jev functionality into Harness source

Rejected for initial integration because:
- increases Harness size and maintenance burden;
- duplicates external projects;
- increases regression blast radius;
- violates Stable Core Protection unless later proven necessary.

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
        +-------------------------------+
        |                               |
        | model-backed advisory         | non-model advisory
        v                               v
Provider Router                    Capability Eligibility
  - sole model/provider                 |
    selection authority                 |
        |                               |
        v                               |
      MPRF                              |
        |                               |
        +---------------+---------------+
                        |
                        v
              Execution Backend Contract
                 /                \
                /                  \
               v                    v
      External Advisory MCP      Full MCP Adapter
      Adapter (read-only)        (state-changing)
          /           \                 |
         v             v                v
   Ruflo Proxy      Jev Adapter    Canonical effects
   advisory only    typed judgment / reconciliation
         |             |
         v             v
       Ruflo       TypeSafe Jev API
```

Neither OCPv2 nor Full Plan calls Ruflo/Jev directly.

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
- read-only task-local memory lookup only if proven non-canonical and non-mutating;
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

If a Ruflo tool internally invokes a model/provider, it is ineligible in v1. A future version may support provider-bound delegated Ruflo execution only through a separately approved authority-contract extension.

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

Preferred production shape is a thin in-house MCP adapter around the TypeSafe API, not a policy-rich community MCP package. Community MCP implementations may be used only as reference/test fixtures unless independently qualified.

Minimal stable adapter surface:
- `jev.health`
- `jev.choice`
- `jev.score`
- `jev.noul`
- optional composed `jev.verify` only after primitives are stable

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

## 8. Data, Secret and Untrusted-Input Policy

- API keys remain in approved environment/secret storage and never enter prompts, MCP tool arguments, logs, reports or Git.
- External payloads MUST pass existing secret/redaction checks.
- Credentials, tokens, private keys and unrelated workspace data are forbidden.
- Source code or business data sent externally follows the same approved external-provider data policy as other cloud model traffic.
- Payload logging stores digests/metadata by default; full external request bodies are not canonical observability requirements.
- Ruflo local memory cannot become source of truth for PCM, Harness durable state or LLMWiki.
- All MCP tool descriptions, returned text and model-generated fields are untrusted data.
- External text MUST NOT be interpreted as Harness control instructions, approval state, provider-binding commands or authorization tokens.
- Control fields come only from canonical Harness envelopes, never from tool-returned prose.
- Response schema validation happens before the result is admitted as evidence.

## 9. Decision Semantics

External advice never directly transitions Harness state.

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
  -> validated evidence/advice
  -> Harness / Full Plan / Governance evaluates
  -> canonical decision
  -> if side effect required, normal authorization path
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
- `CAPABILITY_EGRESS_DENIED`
- `CAPABILITY_BUDGET_EXCEEDED`
- `CAPABILITY_QUARANTINED`

Rules:
- Optional advisory failure may return control to Full Plan with evidence that advice was unavailable.
- Required advisory failure must not be silently skipped.
- Jev low confidence never auto-escalates to a hard-coded provider; existing planning/routing policy re-evaluates the task.
- Ruflo behavior contradicting declared read-only metadata immediately quarantines that capability version.
- Restart/recovery preserves pending external capability state and correlation ids.
- Completed external calls are not replayed without explicit idempotency/replay policy.
- External service failure cannot stop unrelated Harness tasks.

## 11. Runtime Isolation, Egress and Resource Budgets

### 11.1 Network egress

- External MCP process egress is deny-by-default.
- Jev may reach only approved TypeSafe API host(s) through an approved outbound path.
- Ruflo lab mode is local/isolated by default; arbitrary Internet egress is denied unless separately qualified.
- Redirects to unapproved hosts fail closed.
- DNS/TLS target identity is recorded as qualification evidence where practical.

### 11.2 Concurrency and latency

- Every capability has an explicit deadline.
- Maximum in-flight calls are bounded per task/run.
- No autonomous retry loops.
- Retries, if later enabled, are bounded and owned by the appropriate existing runtime/policy rather than the external adapter.
- Timeout never implies permission to bypass to another provider or tool.

### 11.3 Cost/usage budget

- Model-backed advisory capabilities carry usage/cost metadata when available.
- Per-run invocation count and budget ceilings are enforceable configuration, not prompt instructions.
- Budget exhaustion produces `CAPABILITY_BUDGET_EXCEEDED`; it does not silently choose a cheaper provider.

## 12. Capability Lifecycle

External capability versions use an explicit lifecycle:

```text
DISCOVERED
   -> QUALIFIED
   -> SHADOW
   -> CANARY
   -> ACTIVE

Any state
   -> QUARANTINED
   -> DISABLED
```

Rules:
- only approved Governance transitions can promote a capability toward ACTIVE;
- version/schema/tool-set drift forces requalification or QUARANTINED state;
- QUARANTINED capabilities cannot be selected by Full Plan or invoked by the adapter;
- disabling one external capability does not alter core Harness routing or Full MCP operation;
- production registration never follows an unpinned `latest` tag.

## 13. Observability

For every call record:
- project_id
- project_run_id
- task_id
- task_execution_id
- correlation_id
- operation_request_id
- capability_id
- lifecycle state
- MCP server id/version
- MCP tool id/version/schema digest
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

Do not duplicate Full MCP/MPRF source-of-truth events; external capability records are correlated evidence/projections only.

## 14. Security / Negative-Space Requirements

The integration MUST prove the following remain impossible:

1. Ruflo cannot spawn provider/model workers in the initial profile.
2. Ruflo cannot edit files, run shell, publish Git or start a daemon through the allowed profile.
3. Jev cannot invoke itself independently of an authorized Provider Router decision in production mode.
4. Jev/Ruflo cannot transition approval state.
5. Jev/Ruflo cannot trigger Full MCP actions directly.
6. OCPv2 cannot call external MCP tools without Harness authority.
7. External MCP cannot write canonical Harness, Full Plan, MPRF, Full MCP, PCM or LLMWiki state.
8. Tool schema changes fail closed until requalified.
9. An unapproved package/version cannot activate.
10. External service outage does not stop unrelated Harness work.
11. Tool-returned text cannot mutate control/authorization fields.
12. External MCP cannot egress to unapproved hosts.
13. Budget/timeout exhaustion cannot create provider/tool fallback authority.
14. Advisory adapter cannot perform state-changing operations even when an external server exposes them.

## 15. Package / Version / Supply-Chain Governance

- No `latest` in production registration.
- Pin exact package version or immutable Git commit.
- Record package hash where feasible.
- Maintain approved version allowlist.
- Tool-schema digest is part of qualification evidence.
- Any tool-set expansion is a controlled capability change.
- Community Jev MCP packages are not production trust roots.
- Ruflo's large tool surface is never bulk-exposed to Harness.
- Qualification records license, provenance and dependency inventory.
- Run available vulnerability/advisory checks before qualification and on version change.
- Prefer a minimal thin adapter over importing policy-rich external server code.

## 16. Rollout Gates

### RJI-0 — Authority Fit / Design Gate

Pass conditions:
- no authority overlap;
- Jev is behind provider/model authority;
- read-only MCP uses additive External Advisory MCP Adapter;
- state-changing authority remains Full MCP;
- OCPv2 untouched;
- no production activation.

### RJI-1 — Read-Only Discovery

Actions:
- inspect exact Ruflo MCP tool list and schemas;
- inspect Ruflo version/runtime requirements and nested-call behavior;
- inspect Jev API/OpenAPI and candidate adapter behavior;
- record dependencies, license/provenance, egress and tool-schema digests;
- execute no state-changing external tool.

Pass conditions:
- capability taxonomy complete;
- allowlist/denylist candidate complete;
- unknown side-effect tools denied;
- no unreviewed package/version trusted.

### RJI-2 — Jev Thin Adapter Lab

Actions:
- implement deterministic mock first, then minimal thin adapter;
- enforce `provider_decision_ref` contract;
- add choice/score/noul schema tests;
- verify timeout/auth/rate-limit/budget/egress handling.

Pass conditions:
- typed results only;
- no embedded policy authority;
- no fallback outside Provider Router;
- model/provider binding is traceable;
- regression tests green.

### RJI-3 — Ruflo Filtered Proxy Lab

Actions:
- run Ruflo MCP in isolated lab profile;
- expose zero tools by default;
- admit individual tools only after schema + side-effect + nested-call proof;
- prove agent spawn/provider launch/filesystem/shell/git/background loop are blocked.

Pass conditions:
- allowlist-only proxy;
- nested provider count = 0;
- mutation count = 0;
- unapproved tool invocation fails closed;
- arbitrary egress count = 0.

### RJI-4 — External Advisory MCP Adapter

Actions:
- add backend-neutral read-only capability handler through Execution Backend Contract;
- bind request/result envelope and evidence;
- add correlation/restart handling;
- deny all mutation classes before external invocation.

Pass conditions:
- no direct Harness->external MCP bypass;
- no Full MCP core rewrite;
- evidence digest recorded;
- typed error mapping complete;
- read-only mutation count = 0.

### RJI-5 — Shadow Mode

Jev/Ruflo results are recorded but do not affect planning, routing, approval or execution.

Pass conditions:
- canonical decision delta = 0;
- latency/cost/error/confidence telemetry available;
- authority violation count = 0.

### RJI-6 — Bounded Canary

Initial candidates:
- Jev: claim/evidence verification or bounded classification only;
- Ruflo: one independently verified read-only advisory tool only.

No autonomous swarm, no provider execution, no Ruflo daemon.

### RJI-7 — EDP Integrated Qualification

Run:
- functional regression;
- authority matrix regression;
- negative-space tests;
- prompt/tool-output trust-boundary tests;
- crash/restart/replay tests;
- schema/version drift tests;
- auth/secret/egress tests;
- timeout/rate-limit/budget tests;
- optional capability outage tests;
- observability traceability;
- rollback/quarantine tests.

Exit condition:
- blocker/major = 0;
- authority bypass count = 0;
- unapproved mutation count = 0;
- external provider bypass count = 0;
- unapproved egress count = 0;
- ALL PASS.

### RJI-8 — Live Activation

Requires separate explicit user/governance approval.

Design or implementation approval does not authorize RJI-8.

## 17. Rollback

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
- no durable canonical-state migration is required.

This is a required design property.

## 18. Recommended Implementation Order

1. RJI-1 read-only discovery.
2. Define/verify the minimal provider-routing contract needed to represent Jev as a specialized model-backed capability.
3. Build deterministic Jev mock and thin adapter.
4. Build the additive External Advisory MCP Adapter behind Execution Backend Contract.
5. Jev shadow integration.
6. Build Ruflo zero-tool proxy and qualify tools individually.
7. Ruflo shadow integration.
8. Combined observability + EDP qualification.
9. Bounded canary.
10. Separate live-activation approval.

Jev is implemented first because its bounded typed-judgment surface is easier to constrain. Ruflo follows only after the external capability boundary is proven.

## 19. EDP Self-Review

### PASS

- Single planning/orchestration authority preserved.
- Provider Router remains sole provider/model selection authority.
- Full MCP remains canonical state-changing action/effect/reconciliation authority.
- Read-only and state-changing execution are separated.
- OCPv2 gains no new authority.
- Ruflo cannot become a second Harness under the initial profile.
- Jev cannot become a hidden routing/fallback authority.
- Failure is typed and fail-closed.
- External outputs are treated as untrusted data.
- Capability rollback is additive and does not require Harness-core rollback.
- Version/schema drift has an explicit quarantine path.
- External outage is isolated from unrelated work.

### CONDITIONAL / must be resolved in implementation planning

1. **Jev Provider Router representation** — the existing Provider Router contract must be inspected to determine whether a specialized judgment provider can be represented without modifying core selection semantics. Prefer an additive capability/adapter extension; core change requires controlled-change justification.
2. **Execution Backend Contract extension point** — confirm the current contract supports a read-only external capability handler without leaking backend-specific details into AI Office.
3. **Ruflo exact allowlist** — cannot be finalized until the installed/pinned Ruflo version's actual MCP schemas and nested behavior are inspected.
4. **Jev privacy/retention and account policy** — must be reviewed before production data is sent.
5. **Secrets/egress** — no live API key or outbound permission is approved by this design.

### Production blockers intentionally deferred to later gates

- no Ruflo package/server installed;
- no Jev production adapter installed;
- no Jev API credential provisioned;
- no Ruflo tool qualified;
- no external egress opened;
- no shadow/canary evidence exists yet.

These are not design defects; they are explicit RJI-1 through RJI-7 prerequisites.

## 20. Acceptance Criteria for This Design

This design is acceptable only if all statements remain true:

- Ruflo is not a second Harness.
- Ruflo is not an autonomous executor in the initial profile.
- Jev is not a hidden provider-selection bypass.
- external MCP invocation is observable and evidence-bound.
- Provider Router remains sole provider/model selection authority.
- Full MCP remains sole canonical state-changing action/effect/reconciliation authority.
- Full Plan remains final task/agent assignment authority.
- Governance/Human approval remains authoritative.
- OCPv2 remains non-authoritative transport/control plane.
- read-only external advisory execution cannot mutate system state.
- external service outage is isolated and typed.
- rollback does not require Harness-core rollback.

## 21. External Source Notes

Verified on 2026-09-24:

- Ruflo exposes a broad MCP surface and supports coordination/memory/security capabilities; production integration therefore requires a filtering proxy and exact version qualification.
- TypeSafe Jev exposes typed decision primitives and is model-backed; it must not bypass the existing provider/model authority.
- Community Jev MCP packages exist, but their policy/fallback surfaces vary; they are reference implementations rather than production trust roots in this design.

References:
- https://github.com/ruvnet/ruflo/wiki/Installation
- https://github.com/ruflo-app/ruflo
- https://api.typesafe.ai/docs
- https://typesafe.ai/blog/introducing-system-one-models-and-jev
- https://github.com/jkudish/jev-mcp

## 22. Decision

Recommended architecture: **Filtered read-only External Advisory MCP Adapter behind the existing Execution Backend Contract, with state-changing execution remaining exclusively on the Full MCP path.**

Recommended trust model:

```text
Ruflo = advisory coordination capability
Jev   = typed judgment capability
Harness / Full Plan / Governance = decision authority
Provider Router = model/provider authority
External Advisory MCP Adapter = read-only invocation boundary
Full MCP = state-changing action/effect authority
```

Next step after user review/approval of this written design: create a detailed implementation plan. No implementation begins before that approval.
