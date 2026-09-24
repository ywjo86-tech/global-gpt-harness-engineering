# RUFLO / JEV Integration v0.4 — Approved Architecture Contract

**Status:** APPROVED FOR IMPLEMENTATION / RJI-8 SAFETY APPROVAL GRANTED  
**Date:** 2026-09-24  
**Repository:** `ywjo86-tech/global-gpt-harness-engineering`  
**Baseline:** `main@c591b01e8a1d9d9bb2dc438ca85f6c2ffcc79a03`  
**Design branch:** `design/ruflo-jev-mcp-integration-20260924`  
**Source diagnosis:** `RUFLO_JEV_MCP_INTEGRATION_v0.4_EDP_R2_ALL_PASS_2026-09-24.md`  
**Supersedes for implementation:** v0.2 design candidate and v0.3 EDP design for this integration.

## 1. Goal

Add Ruflo and Jev as optional, non-authoritative external advisory capabilities without creating a second orchestrator, second provider router, alternate effect path, or new canonical state owner.

Canonical rule:

> External capability may advise. Harness decides. Provider Router selects model/provider. Full MCP remains the state-changing effect path.

## 2. Frozen authority boundaries

- User: request/approval source. Dangerous activation was explicitly approved on 2026-09-24, but this approval does not waive technical qualification gates.
- GPT Logical Operator / AI Office Harness: workflow and governance; no bypass of Router, Tool Authorization, Full MCP, or Completion Authority.
- Full Plan / Stage Gate: decomposition, progression, readiness only. Stage Gate does not manufacture Safety Approval.
- Provider Router: sole authority for initial provider/model selection and cross-provider reselection.
- MPRF: lifecycle, health, quota, failure, recovery-eligibility, checkpoint/resume facts only. MPRF never selects a replacement provider.
- Provider execution registries: resolve an already-selected provider to an execution mechanism only. Registration does not imply admission or routing authority.
- Tool Authorization / closed operation registry / SingleToolBroker: canonical admission path for Ruflo read-only tools.
- Production Execution Gateway / Execution Authorization / Full MCP: sole canonical state-changing effect and reconciliation path.
- Completion Authority: sole completion proof authority.
- OCPv2: transport/input only; no direct Ruflo/Jev invocation.
- RDC: emergency recovery only and not a normal runtime dependency.

## 3. Current source reconciliation

The R2 diagnosis was correct for its observed source snapshot, but the current design branch now contains concrete provider-neutral execution seams:

- `runtime/orchestrator/provider_adapter_registry.py`
- `runtime/orchestrator/provider_execution_registry.py`
- `tests/test_provider_execution_registry.py`

The current `ProviderRunnerRegistry` explicitly has no routing, approval, or effect authority and exposes separate read/action runner resolution. Therefore the approved Jev implementation seam is:

`RouterDecisionV2` -> `ProviderRunnerRegistry.resolve_read(provider_ref)` -> Harness-owned Jev provider-bound read runner -> normalized advisory evidence.

Jev MUST NOT be registered as a provider selector, MUST NOT create its own fallback list, and MUST NOT invoke the action runner path.

## 4. Ruflo locked v1 profile

Canonical capability id: `external.ruflo.coordination_advisory.v1`

Initial profile:

```text
exposed_tools = 0
autonomous_loop = false
daemon = false
hooks = false
agent_spawn = false
worker_spawn = false
swarm_execution = false
provider_call = false
model_call = false
filesystem_write = false
shell_execution = false
git_write = false
memory_read = false
memory_write = false
canonical_state_write = false
network_egress = deny_by_default
max_delegation_depth = 0
```

A Ruflo tool can be exposed only after exact pinned tool schema and transitive behavior are qualified as read-only, bounded, non-delegating, non-provider-calling, non-mutating, and egress-controlled. Bulk registration is forbidden.

Current upstream qualification pin observed on 2026-09-24:

- repository: `ruvnet/ruflo`
- version: `3.44.0`
- commit: `0a96fb8857dabd343d71d76c3ca703100a2923bc`

Any package/commit/schema/tool-set drift moves the capability to requalification/quarantine; production registration must never use `latest`.

## 5. Jev locked v1 profile

Canonical capability id: `external.jev.typed_judgment.v1`

Jev is a model-backed typed advisory endpoint. Required invariants:

- consumes an eligible immutable `RouterDecisionV2` binding;
- request digest must match the Router request;
- selected `provider_ref`, `model_ref`, and Router decision digest are immutable input bindings;
- actual response route/model identity mismatch fails closed;
- no provider selection, substitution, cross-provider fallback, hidden retry, tool selection, approval, gate, merge, ship, patch, execution, or completion authority;
- default attempt count is one;
- result always has `non_authoritative=true`;
- low confidence is evidence only.

Current official TypeSafe API qualification facts observed on 2026-09-24:

- OpenAPI version observed: `0.2.0`
- typed decision endpoint: `POST /v1/systemone`
- model discovery endpoint: `GET /v1/models`
- credential transport: `Authorization: Bearer <API_KEY>`

Private source/business/user payloads remain denied until account/privacy/retention/region/security qualification is explicitly complete. Credentials/secrets are always excluded from prompts, tool args, logs, reports, and Git.

## 6. Common advisory contract

Create Harness-owned immutable contracts using these schema identities:

- `external-capability.descriptor.v1`
- `external-capability.request.v1`
- `external-capability.result.v1`

Every request binds at minimum:

- project/run/task/task_execution identities;
- correlation and operation request ids;
- capability id and pinned version/digest;
- request/input/source snapshot digests;
- schema/tool/endpoint digest;
- lifecycle state, trust class, effect class;
- policy/admission/egress/budget/deadline/attempt;
- Router decision ref, provider id and model id for model-backed requests.

Every result:

- forces `non_authoritative=true`;
- verifies request/input/source bindings;
- verifies Router/provider/model identity for Jev;
- contains a result digest;
- rejects unknown control semantics;
- cannot populate routing, approval, authorization, lifecycle, action, merge/ship, or completion fields from external prose.

## 7. Failure semantics

Normalize at least:

`CAPABILITY_UNAVAILABLE`, `CAPABILITY_TIMEOUT`, `CAPABILITY_RATE_LIMITED`, `CAPABILITY_AUTH_MISSING`, `CAPABILITY_SCHEMA_MISMATCH`, `CAPABILITY_VERSION_UNAPPROVED`, `CAPABILITY_SIDE_EFFECT_DENIED`, `CAPABILITY_NESTED_PROVIDER_DENIED`, `CAPABILITY_DELEGATION_DENIED`, `CAPABILITY_PROVIDER_BINDING_MISMATCH`, `CAPABILITY_PROVIDER_EXECUTION_SEAM_UNVERIFIED`, `CAPABILITY_LOW_CONFIDENCE`, `CAPABILITY_RESULT_INVALID`, `CAPABILITY_EVIDENCE_STALE`, `CAPABILITY_REPLAY_DENIED`, `CAPABILITY_EGRESS_DENIED`, `CAPABILITY_BUDGET_EXCEEDED`, `CAPABILITY_PRIVACY_POLICY_UNQUALIFIED`, `CAPABILITY_QUARANTINED`.

Optional advisory failure returns to existing Harness behavior with explicit unavailable evidence. Required advisory failure is explicit. No external layer may create an autonomous fallback or timeout-to-authority escalation.

## 8. Lifecycle

```text
DISCOVERED
  -> QUALIFIED
  -> SHADOW
  -> CANARY
  -> READY_FOR_ACTIVATION
  -> ACTIVE

Any state -> QUARANTINED -> DISABLED
```

Disable must restore pre-integration behavior without stable-core rollback or canonical state migration.

## 9. Rollout gates

- **RJI-0 Design EDP R2:** PASS.
- **RJI-1 Discovery / Provenance:** exact package/API/schema/license/privacy/security identity, no production data or state change.
- **RJI-2 Deterministic Contract Lab:** request/result schemas, control-field rejection, freshness, replay/restart, timeout/rate/budget, provider-decision binding mocks.
- **RJI-3 Ruflo Zero-Tool Proxy Lab:** zero-tool baseline; forbidden classes blocked; only individually qualified read-only tools may be admitted.
- **RJI-4 Jev Exact Seam + Provider-Bound Adapter:** use existing `ProviderRunnerRegistry` read seam; prove Router/MPRF authority unchanged; no invented registry.
- **RJI-5 SHADOW:** result recorded only; canonical decision delta = 0; no side effect.
- **RJI-6 Bounded CANARY:** narrow typed judgment and/or independently qualified Ruflo read-only tool; no autonomy/provider routing/memory/daemon/effect expansion.
- **RJI-7 Runtime EDP:** focused tests + full regression + authority negative-space + failure injection + restart/replay + drift + secret/egress/privacy + stale evidence + identity + rollback/quarantine + disable-to-baseline.
- **RJI-8 Live Activation:** dangerous-work user approval has been granted. Activation may execute only after RJI-7 PASS and only for the technically qualified slice; missing credentials, endpoint/account qualification, or runtime evidence remains fail-closed.

## 10. Mandatory negative space

Tests must prove that Ruflo/Jev cannot:

- become an orchestrator or provider router;
- mutate Harness/Full Plan/MPRF/Full MCP/PCM/LLMWiki canonical state;
- bypass Tool Authorization, Provider Router, Production Execution Gateway, or Completion Authority;
- create approval or completion proof;
- recursively delegate external work;
- use unapproved egress or credentials;
- silently replay stale completed calls;
- silently choose alternate providers because of rate, timeout, cost, or low confidence.

## 11. Activation stop conditions

Fail closed and do not activate the affected capability if any of the following remains true:

- exact package/API/tool schema identity is not pinned;
- Ruflo tool transitive behavior is not proved read-only;
- Jev Router/provider/model identity cannot be verified end-to-end;
- secret handling or egress policy is not qualified;
- private/business payload qualification is incomplete;
- focused or full regression is red;
- disable-to-baseline or quarantine proof fails.
