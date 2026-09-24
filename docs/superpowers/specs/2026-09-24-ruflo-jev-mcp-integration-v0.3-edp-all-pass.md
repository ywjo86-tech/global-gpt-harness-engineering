# RUFLO-MCP / JEV-MCP Integration v0.3 — EDP-1.0 Diagnosis / Remediation / Re-Diagnosis ALL PASS

**Diagnosis Protocol:** `EXHAUSTIVE_DIAGNOSIS_PROTOCOL EDP-1.0`  
**Diagnosis Date:** 2026-09-24  
**Original Target:** `docs/superpowers/specs/2026-09-24-ruflo-jev-mcp-integration-design.md` v0.2  
**Original Target Blob SHA:** `82f45ef7a8e47525d85ff6a95ff04694c86ec97c`  
**Corrected Target:** this v0.3 document  
**Repository Baseline:** `main@c591b01e8a1d9d9bb2dc438ca85f6c2ffcc79a03`  
**Working Branch:** `design/ruflo-jev-mcp-integration-20260924`  
**Diagnosis Scope:** `CROSS_DOCUMENT_ARCHITECTURE_DESIGN_INTEGRITY`  
**Final Diagnosis:** **DESIGN_EDP_ALL_PASS / READY_FOR_EXPLICIT_USER_APPROVAL**  
**User Approval:** **PENDING**  
**Implementation Authorization:** **NOT GRANTED**  
**Runtime Qualification:** **NOT STARTED**  
**Live Activation:** **NOT AUTHORIZED**  

This ALL PASS is limited to architecture/design integrity against the authoritative evidence available to this diagnosis. It is not a claim that Ruflo or Jev has been installed, credentialed, connected to live traffic, implemented, shadow-qualified, canary-qualified, or production-activated.

---

## 1. GOAL and Diagnosis Scope

GOAL:

> Diagnose the Ruflo/Jev MCP integration design against the full existing Harness authority set using `EXHAUSTIVE_DIAGNOSIS_PROTOCOL EDP-1.0`, explicitly record all material defects, remediate them without weakening the stable core, re-run all affected and dependent diagnosis paths, and close only when every universal EDP PASS condition is satisfied for design scope.

Included:

- authority and responsibility boundaries;
- Ruflo and Jev integration path;
- provider/model selection integrity;
- read-only advisory vs state-changing execution separation;
- tool/provider adapter placement;
- security, secret, egress, supply-chain, version and schema controls;
- freshness, replay, restart and failure semantics;
- lifecycle, qualification, rollback and activation gates;
- negative-space, cross-document consistency and traceability;
- design-level implementation readiness.

Explicitly excluded from this design diagnosis:

- package installation;
- live API credentials or secret handling;
- outbound network activation;
- runtime source-code implementation;
- live Ruflo MCP tool qualification;
- live Jev API/provider qualification;
- shadow/canary evidence;
- runtime regression results for not-yet-implemented code;
- production activation.

Those are downstream RJI implementation/runtime gates and require their own measured evidence.

---

## 2. EDP-1.0 Sequence Executed

The complete required sequence was applied:

`Canonical Source Resolution`
→ `Obligation Extraction & Freeze`
→ `Primary Domain Audit`
→ `Mandatory Evidence Matrix`
→ `Mandatory RTM`
→ `Negative-Space Audit`
→ `Cross-Document Audit`
→ `Adversarial Second Pass`
→ `PASS Challenge`
→ `Remediation`
→ `Regression Re-Diagnosis`
→ `Closure Metrics`
→ `Exhaustion Statement`
→ `Final Decision`

No material defect was silently repaired. The original v0.2 artifact remains preserved as the diagnosed historical target; all material corrections are recorded in this document.

---

## 3. Canonical Source Register

Authority precedence for this run follows EDP-1.0: current explicit user decision > approved canonical baseline/contract > verified repository/current-state evidence > approved supporting documents > verified external research > assumption.

| Priority | Source | State / Role | Disposition |
|---:|---|---|---|
| 1 | Current user directive: full EDP diagnosis → correction → re-diagnosis → ALL PASS document | Current | HIGHEST REQUEST AUTHORITY |
| 2 | `EXHAUSTIVE_DIAGNOSIS_PROTOCOL.md` EDP-1.0 | CANONICAL COMMON DIAGNOSIS STANDARD | VALID |
| 3 | `main@c591b01e8a1d9d9bb2dc438ca85f6c2ffcc79a03` | Verified repository baseline for this design run | VALID |
| 4 | `docs/harness/CURRENT_OPERATIONAL_STATE.json` + final operational baseline declaration | Current Harness operational projection / sealed baseline evidence | VALID |
| 5 | `2026-09-19-ai-office-harness-multiprovider-extensibility-design.md` | Approved provider-neutral Router / Adapter authority contract | VALID |
| 6 | `2026-09-20-diagnostic-intelligence-final-operationalization-design.md` | Approved read-only advisory / freshness / graceful-degradation pattern | VALID |
| 7 | `2026-09-21-operator-control-plane-v2-r2-approved.md` | Approved OCPv2 authority invariants | VALID |
| 8 | `2026-09-20-omniroute-provider-gateway-design.md` | Approved non-authoritative provider gateway pattern | VALID |
| 9 | `docs/history/upgrades/2026-09-20-FINAL-OPERATIONAL/EDP_FINAL_ALL_PASS.json` | Existing runtime authority/effect evidence | VALID |
| 10 | Original Ruflo/Jev design v0.2 | Diagnosis target, not self-authorizing | TARGET ONLY |
| 11 | Current Ruflo project/docs and current community Jev MCP implementation reviewed on 2026-09-24 | External capability/reference evidence only | VALID AS RESEARCH / NON-AUTHORITATIVE |

`SOURCE_AUTHORITY_STATUS = VALID_FOR_DESIGN_SCOPE`

The external projects may describe their own capabilities, but they cannot override Harness authority, policy, provider routing, execution, approval, completion, or canonical-state contracts.

---

## 4. Frozen Authority Matrix

The following authority set is frozen for this integration design.

| Component | Orchestration / progression | Provider/model selection | Provider lifecycle / failover | Read-only tool invocation | State-changing effects | Approval / risk | Completion | Canonical durable state |
|---|---|---|---|---|---|---|---|---|
| GPT Logical Operator | decision/operator role | NO direct bypass | NO | requests within governed path | NO direct effect | participates under policy | NO independent completion | NO |
| AI Office Harness / Governance | workflow/governance | policy input only | policy integration | governs capability admission | governs path | YES | coordinates only | YES for Harness-owned state |
| Full Plan | decomposition/gates/fan-in/assignment | declares requirements only | NO | may request admitted capability | NO direct effect | NO bypass | progression authority only | plan/job state only |
| Provider Router | NO | **SOLE AUTHORITY** | uses lifecycle facts | N/A | NO | NO | NO | decision evidence only |
| MPRF | NO | does not replace Router | **SOLE provider runtime/lifecycle/recovery authority** | N/A | NO | NO | NO | provider runtime facts |
| Provider Adapter Registry | NO | executes already-selected identity only | NO cross-provider reselection | model transport only | NO side effect authority | NO | NO | transport evidence only |
| Tool Authorization / Registry / Broker | NO | NO | NO | **canonical non-provider tool admission/invocation path** | may dispatch only authorized tool class | policy-bound | NO | tool evidence only |
| Production Execution Gateway / Execution Authorization / Full MCP | NO | NO | NO | N/A | **SOLE canonical state-changing effect/reconciliation path** | requires approved authority | NO | effect evidence only |
| Completion Authority | NO | NO | NO | NO | NO | NO | **SOLE completion proof authority** | completion evidence |
| OCPv2 | transport/control-plane plumbing only | NO | NO | NO direct invocation authority | NO | NO | NO | non-authoritative transport state only |
| Ruflo | **NONE** | **NONE** | **NONE** | advisory result producer only | **NONE** | **NONE** | **NONE** | **NONE** in v1 |
| Jev | **NONE** | **NONE** | **NONE** | model-backed typed advisory result only | **NONE** | **NONE** | **NONE** | **NONE** |

Ruflo and Jev are capability implementations, not new authority planes.

---

## 5. Frozen Material Obligation Register

The following 32 material obligations were frozen before final closure.

| ID | Material obligation |
|---|---|
| RJI-O-001 | One orchestration/progression authority chain must remain; no second Harness/orchestrator. |
| RJI-O-002 | Provider Router remains sole provider/model selection authority. |
| RJI-O-003 | MPRF remains sole provider lifecycle/failover/recovery authority. |
| RJI-O-004 | Provider-specific model transport executes only an explicit Router decision through Provider Adapter Registry. |
| RJI-O-005 | Non-provider read-only external tools use existing Tool Authorization/Registry/Broker authority, not a new effect plane. |
| RJI-O-006 | State-changing execution remains exclusively on Production Execution Gateway / Execution Authorization / Full MCP path. |
| RJI-O-007 | OCPv2 remains non-authoritative and cannot directly call external capability implementations. |
| RJI-O-008 | RDC remains emergency recovery tooling and is not a runtime dependency. |
| RJI-O-009 | Ruflo cannot spawn agents/workers, run autonomous swarms, daemons, hooks, background loops, providers or models in v1. |
| RJI-O-010 | Ruflo cannot write filesystem, run shell, mutate Git, write canonical memory/state, or issue side effects in v1. |
| RJI-O-011 | Ruflo starts with a zero-tool allowlist; each tool is admitted individually only after exact-version/schema/behavior qualification. |
| RJI-O-012 | Ruflo internal governance/policy is defense-in-depth only; Harness filtering remains the hard authority boundary. |
| RJI-O-013 | Jev uses an explicit provider/model selected by Provider Router; no auto provider/model selection. |
| RJI-O-014 | Jev has no cross-provider fallback, implicit provider substitution, or adapter-owned reroute. |
| RJI-O-015 | Jev adapter has no approval, gate, merge/ship, patch, completion or execution authority. |
| RJI-O-016 | Community/policy-rich Jev MCP implementations are not production trust roots unless separately stripped and qualified. |
| RJI-O-017 | All external descriptions/results/model text are untrusted data and cannot populate control/authorization fields. |
| RJI-O-018 | Request/result schema and package/tool schema digests are bound and validated. |
| RJI-O-019 | Advisory evidence binds the exact input/source snapshot and becomes stale on material source/input drift. |
| RJI-O-020 | Replay/reuse is deterministic, digest-bound and cannot become effect idempotency or execution authority. |
| RJI-O-021 | Max external delegation depth is zero in v1; no recursive MCP/provider/tool/orchestrator calls. |
| RJI-O-022 | Egress is deny-by-default; host/redirect identity is allowlisted and verified. |
| RJI-O-023 | Secrets remain outside prompts/tool args/logs/reports/Git. |
| RJI-O-024 | Sensitive/private payloads cannot be sent to Jev until privacy/retention/account policy is independently qualified and approved. |
| RJI-O-025 | Package versions/commits and schema/tool-set are pinned; `latest` and hidden self-update are prohibited in production. |
| RJI-O-026 | Version/schema/tool-set drift quarantines the capability before reuse. |
| RJI-O-027 | Deadlines, concurrency, retry and cost budgets are bounded Harness policy, never prompt-controlled. |
| RJI-O-028 | Capability outage/degradation cannot stop unrelated Harness work or silently broaden authority. |
| RJI-O-029 | Capability lifecycle is governed: DISCOVERED → QUALIFIED → SHADOW → CANARY → ACTIVE, with QUARANTINED/DISABLED exits. |
| RJI-O-030 | Design/implementation approval does not imply live activation; ACTIVE requires separate explicit governance/user authorization. |
| RJI-O-031 | Disabling Ruflo/Jev restores original Harness behavior without core rollback or canonical-state migration. |
| RJI-O-032 | Design ALL PASS must remain distinct from implementation/runtime ALL PASS. |

---

## 6. Findings Register — Initial Diagnosis and Remediation

Initial diagnosis produced `BLOCKER=0`, `MAJOR=8`, `MINOR=4`. Every finding below is now `RESOLVED`; no material exception was accepted.

| ID | Severity | Status | Problem | Required correction applied | Regression scope |
|---|---|---|---|---|---|
| RJI-F-001 | MAJOR | RESOLVED | v0.2 retained five material `CONDITIONAL` implementation questions, which blocks unrestricted EDP PASS. | Converted each into an explicit fail-closed design rule/gate with deterministic disposition; no material TBD remains. | D1, D5, D9, D10, D12, D17 |
| RJI-F-002 | MAJOR | RESOLVED | Jev Router decision was not structurally bound to the actual provider-specific transport path. | Jev now executes only via Provider Router → MPRF facts → Provider Adapter Registry → provider-bound Jev adapter. Actual provider/model/route identity must match the Router decision. | D5-D10, D14-D17 |
| RJI-F-003 | MAJOR | RESOLVED | v0.2 introduced a generic External Advisory MCP Adapter behind Execution Backend Contract, unnecessarily expanding a stable effect boundary. | Split paths: Ruflo read-only tooling uses existing Tool Authorization/Registry/Broker; Jev model traffic uses Provider Adapter Registry; effects remain Full MCP only. | D5-D9, D13-D17 |
| RJI-F-004 | MAJOR | RESOLVED | Community Jev MCP behavior can include automatic provider resolution, multi-provider fallback-like behavior, retries and policy/gate surfaces. | Community Jev MCP is reference/test evidence only. Production design uses a minimal provider-bound in-house adapter with explicit provider/model, one-attempt default, no auto/fallback, no gate authority. | D6, D9, D14-D17 |
| RJI-F-005 | MAJOR | RESOLVED | Ruflo exposes orchestration/swarm/background/agent/provider capabilities that could become a second control plane. | Zero-tool filtering proxy; all spawn/swarm/daemon/hooks/background/provider/model/mutation surfaces prohibited in v1. Ruflo policy is non-authoritative defense-in-depth only. | D5-D7, D11, D14-D17 |
| RJI-F-006 | MAJOR | RESOLVED | Recursive delegation/circular orchestration was not explicitly prevented. | `max_delegation_depth=0`; no Ruflo→model, Jev→tool, external→Harness, or external→external nested invocation in v1. | D9, D11, D15-D17 |
| RJI-F-007 | MAJOR | RESOLVED | Advisory evidence lacked mandatory source/input freshness binding. | Added input/source snapshot digest binding and `CURRENT/STALE/INVALID` evidence state; stale evidence cannot drive governed decisions. | D6-D11, D14-D17 |
| RJI-F-008 | MAJOR | RESOLVED | Restart/replay/idempotency rule was too vague to prove no duplicate or stale advisory reuse. | Defined exact reuse tuple and fail-closed replay policy; side-effect idempotency is explicitly out of advisory scope. | D9-D11, D14-D17 |
| RJI-F-009 | MINOR | RESOLVED | Envelope omitted package/schema/trust/effect/lifecycle/egress/budget/source bindings. | Expanded descriptor/request/result contracts with required immutable fields. | D4, D6, D8-D10 |
| RJI-F-010 | MINOR | RESOLVED | Capability promotion authority was not explicit enough at ACTIVE transition. | ACTIVE now requires a separate explicit governance/user activation decision after runtime qualification. | D5, D10, D14, D17 |
| RJI-F-011 | MINOR | RESOLVED | Ruflo task-local memory lookup could create a shadow memory plane. | Ruflo memory read/write is fully disabled in v1; future adoption requires a separate design revision and qualification. | D6, D11, D13-D15 |
| RJI-F-012 | MINOR | RESOLVED | `authorization_ref` on read-only advice could be confused with state-changing Execution Authorization. | Renamed advisory field to `capability_admission_ref`; execution authorization remains exclusive to the side-effect path. | D3, D5, D6, D15 |

Final finding status after remediation:

- `OPEN_BLOCKER = 0`
- `OPEN_MAJOR = 0`
- `OPEN_MINOR = 0`
- `ACCEPTED_EXCEPTION = 0`

---

## 7. Corrected Canonical Architecture v0.3

### 7.1 Ruflo — non-model external advisory tool path

```text
User / JARVIS / OCPv2
        |
        v
AI Office Harness / Full Plan
        |
        | requests admitted read-only advisory capability
        v
Tool Authorization
        |
        v
Tool Registry
  capability = external.ruflo.coordination_advisory.v1
  effect_class = READ_ONLY_EVIDENCE
        |
        v
Production Tool Broker
        |
        v
Ruflo Filtering Proxy
  zero-trust / allowlist-only
  max_delegation_depth = 0
        |
        v
Pinned Ruflo Local MCP Runtime
        |
        v
AdvisoryEvidenceEnvelope
        |
        v
Harness context/evidence only
```

Ruflo does not enter Provider Router because v1 forbids Ruflo model/provider invocation. If a future Ruflo capability internally invokes a provider/model, it is a new authority design and is ineligible under this v1 contract.

### 7.2 Jev — model-backed typed judgment path

```text
Full Plan
  -> declares typed-judgment capability requirement
        |
        v
Provider Runtime Facts / Eligibility Snapshot
        |
        v
Provider Router
  -> selects explicit authorized provider + model
        |
        v
MPRF / Provider Adapter Registry
        |
        v
Provider-Bound Jev Adapter
  thin / explicit provider-model-route
  no auto provider
  no cross-provider fallback
  no gate or effect authority
        |
        v
Qualified Jev Endpoint
        |
        v
Canonical Typed AdvisoryEvidenceEnvelope
        |
        v
Harness / Full Plan consumes as non-authoritative evidence
```

Provider-specific Jev transport belongs in Provider Adapter Registry. If the current registry cannot represent the required Jev transport without changing canonical Router semantics, the capability returns `CAPABILITY_PROVIDER_ADAPTER_UNSUPPORTED`, remains `DISABLED`, and requires a separately approved design revision. It does not bypass the Router or silently modify the stable core.

### 7.3 State-changing action path — unchanged

```text
Validated advisory evidence
        |
        v
Harness / Full Plan / Governance canonical decision
        |
        v
Existing approval / risk rules
        |
        v
Production Execution Gateway
        |
        v
Execution Authorization Binding
        |
        v
Execution Backend / Full MCP
        |
        v
Canonical effect evidence / reconciliation
```

No Ruflo or Jev response can invoke, authorize or shortcut this path.

---

## 8. Canonical External Capability Contracts

### 8.1 Capability descriptor

Every admitted external capability version MUST bind:

```json
{
  "schema_version": "external-capability.descriptor.v1",
  "capability_id": "external.ruflo.coordination_advisory.v1",
  "capability_kind": "EXTERNAL_TOOL_ADVISORY",
  "authority_class": "NONE",
  "effect_class": "READ_ONLY_EVIDENCE",
  "trust_class": "EXTERNAL_UNTRUSTED",
  "model_backed": false,
  "provider_binding_required": false,
  "lifecycle_state": "QUALIFIED",
  "capability_version": "pinned-version-or-commit",
  "package_digest": "sha256:...",
  "tool_or_operation_id": "...",
  "tool_schema_digest": "sha256:...",
  "egress_policy_ref": "...",
  "budget_ref": "...",
  "retry_policy": "NONE",
  "replay_policy_ref": "...",
  "max_delegation_depth": 0,
  "source_binding_required": true
}
```

Jev uses `capability_kind=MODEL_BACKED_TYPED_JUDGMENT`, `model_backed=true`, and `provider_binding_required=true`.

### 8.2 Request envelope

```json
{
  "schema_version": "external-capability.request.v1",
  "project_id": "...",
  "project_run_id": "...",
  "task_id": "...",
  "task_execution_id": "...",
  "correlation_id": "...",
  "operation_request_id": "...",
  "capability_id": "...",
  "tool_or_operation_id": "...",
  "lifecycle_state": "SHADOW",
  "capability_version": "...",
  "package_digest": "sha256:...",
  "tool_schema_digest": "sha256:...",
  "effect_class": "READ_ONLY_EVIDENCE",
  "trust_class": "EXTERNAL_UNTRUSTED",
  "request_digest": "sha256:...",
  "input_set_digest": "sha256:...",
  "source_snapshot_digest": "sha256:... or null",
  "capability_admission_ref": "...",
  "policy_ref": "...",
  "provider_decision_ref": "... or null",
  "provider_id": "... or null",
  "model_id": "... or null",
  "egress_policy_ref": "...",
  "budget_ref": "...",
  "deadline_ms": 5000,
  "attempt": 1,
  "payload": {}
}
```

### 8.3 Result envelope

```json
{
  "schema_version": "external-capability.result.v1",
  "capability_id": "...",
  "tool_or_operation_id": "...",
  "non_authoritative": true,
  "trust_class": "EXTERNAL_UNTRUSTED",
  "freshness_state": "CURRENT",
  "input_set_digest": "sha256:...",
  "source_snapshot_digest": "sha256:... or null",
  "provider_decision_ref": "... or null",
  "provider_id_actual": "... or null",
  "model_id_actual": "... or null",
  "route_identity_actual": "... or null",
  "external_server_version": "...",
  "tool_schema_digest": "sha256:...",
  "result": {},
  "confidence": null,
  "usage": null,
  "latency_ms": 0,
  "result_digest": "sha256:...",
  "error": null
}
```

Rules:

- externally returned prose cannot populate `provider_decision_ref`, admission, approval, lifecycle, policy, authorization or effect-control fields;
- schema validation precedes evidence admission;
- provider/model/route mismatch for Jev fails closed;
- unknown fields with control semantics are rejected or quarantined according to schema policy;
- raw secret-bearing bodies are never canonical evidence.

---

## 9. Ruflo Locked v1 Profile

Ruflo is an **External Multi-Agent Coordination Advisor implementation**, not a Harness, scheduler, agent manager or executor.

Initial state:

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

Qualification rules:

1. Exact package version or immutable commit and package digest are recorded.
2. Actual MCP tool schemas are enumerated from the pinned build.
3. The Filtering Proxy exposes zero tools by default.
4. A candidate tool is admitted individually only after its schema, transitive behavior, filesystem/network behavior and nested invocation behavior are proven compatible with `READ_ONLY_EVIDENCE`.
5. Unknown or opaque side effects are denial conditions.
6. Ruflo-native policy enforcement is optional defense-in-depth only and is not trusted as Harness authorization.
7. Any version/schema/tool-set drift returns the capability to `QUARANTINED` before further invocation.

Potential future allowlist categories are limited to independently proven health/version/read-only analysis. No orchestration or memory surface is implicitly approved by this design.

---

## 10. Jev Locked v1 Profile

Jev is an **External Typed Judgment capability**, not a Router, recovery policy, gate, reviewer authority or executor.

Production design requirements:

- thin Harness-owned/provider-bound adapter;
- explicit Router-selected `provider_id` and `model_id` on every call;
- explicit qualified endpoint/route identity;
- no `auto` provider selection;
- no cross-provider fallback;
- no provider substitution;
- no model alias such as unpinned `latest` in production;
- default `attempt=1`; any later retry must be explicitly bounded by existing MPRF/provider policy and may not switch provider/model;
- response provider/model/route identity must match the Router decision;
- low confidence is evidence, not escalation authority;
- no `gate`, merge/ship, patch, completion, approval or execution authority;
- community/policy-rich Jev MCP packages may be reference/test fixtures only unless separately qualified under this same contract.

If provider binding cannot be proven, production invocation is disabled. If the selected endpoint cannot guarantee the explicit provider/model identity, that route is ineligible.

### Data/privacy fail-closed rule

Until authoritative Jev account/privacy/retention terms applicable to the intended production account and payload class are independently verified and approved:

- only public, synthetic, non-sensitive, or explicitly approved test payloads may leave the local environment;
- private source/business/user data is denied;
- secrets are always denied;
- production data egress cannot activate.

This is an explicit design control, not an unresolved open question.

---

## 11. Freshness, Replay and Restart Semantics

### 11.1 Freshness

Advisory evidence is usable only if its bound input/source identity still matches the consuming task.

Material input or source change yields:

`CAPABILITY_EVIDENCE_STALE`

and the old result cannot drive a governed action.

### 11.2 Deterministic reuse tuple

A completed advisory result may be reused only when all fields below match and the configured freshness/TTL policy remains valid:

```text
request_digest
+ capability_version/package_digest
+ tool_schema_digest
+ input_set_digest
+ source_snapshot_digest (when applicable)
+ provider_decision_ref (when model-backed)
+ provider_id/model_id/route identity (when model-backed)
+ policy_ref
+ egress_policy_ref
```

Any mismatch causes fresh admission/routing/invocation rather than silent replay.

### 11.3 Restart

- pending calls retain correlation and operation IDs;
- completed calls are not blindly repeated after restart;
- ambiguous completion is recorded as such and re-evaluated through the capability replay policy;
- advisory replay never grants effect idempotency or execution permission;
- capability restart/recovery cannot become Full Plan, MPRF or Full MCP recovery authority.

---

## 12. Failure Taxonomy and Degradation

Required normalized errors include:

- `CAPABILITY_UNAVAILABLE`
- `CAPABILITY_TIMEOUT`
- `CAPABILITY_RATE_LIMITED`
- `CAPABILITY_AUTH_MISSING`
- `CAPABILITY_SCHEMA_MISMATCH`
- `CAPABILITY_VERSION_UNAPPROVED`
- `CAPABILITY_SIDE_EFFECT_DENIED`
- `CAPABILITY_NESTED_PROVIDER_DENIED`
- `CAPABILITY_DELEGATION_DENIED`
- `CAPABILITY_PROVIDER_BINDING_MISMATCH`
- `CAPABILITY_PROVIDER_ADAPTER_UNSUPPORTED`
- `CAPABILITY_LOW_CONFIDENCE`
- `CAPABILITY_RESULT_INVALID`
- `CAPABILITY_EVIDENCE_STALE`
- `CAPABILITY_REPLAY_DENIED`
- `CAPABILITY_EGRESS_DENIED`
- `CAPABILITY_BUDGET_EXCEEDED`
- `CAPABILITY_PRIVACY_POLICY_UNQUALIFIED`
- `CAPABILITY_QUARANTINED`

Degradation rules:

- optional advisory outage returns the task to existing Harness behavior with typed evidence;
- required advisory absence is explicit and cannot be silently skipped;
- failure cannot create an alternate provider/tool/executor authority;
- failure of Ruflo/Jev cannot stop unrelated Harness work;
- timeout/budget/rate limit never implies permission to bypass to another provider or tool;
- no autonomous retry loop exists in the external capability layer.

---

## 13. Security, Secret, Egress and Supply-Chain Controls

- deny-by-default egress;
- only exact approved hosts/routes are permitted;
- redirects to unapproved hosts fail closed;
- route identity is retained as evidence where practical;
- secrets remain in approved secret/environment storage and never enter prompts, MCP arguments, evidence, logs, reports or Git;
- source/business/user data follows payload classification and privacy qualification rules;
- exact package version/commit is pinned;
- package integrity/provenance/license/dependency inventory is qualification evidence;
- tool schema digest is qualification evidence;
- no `latest` production registration;
- no hidden self-update;
- available vulnerability/advisory checks run before qualification and on version change;
- capability version/schema/tool drift forces quarantine;
- external tool descriptions/results are untrusted input;
- output-size limits and schema bounds prevent uncontrolled context expansion.

---

## 14. Capability Lifecycle and Rollout Gates

### Lifecycle

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

Promotion toward ACTIVE requires Harness Governance. Entry to `ACTIVE` additionally requires a separate explicit user/governance live-activation decision after runtime qualification.

### RJI-0 — Corrected Design EDP Gate

This document. Exit requires design EDP ALL PASS.

### RJI-1 — Read-Only Discovery / Provenance

- inspect pinned Ruflo package/runtime/tool schemas;
- inspect exact Jev endpoint/API/provider-binding behavior;
- record dependency, license, integrity, privacy/data-policy evidence;
- perform no state-changing integration.

If exact behavior cannot be proven, the candidate remains disabled; RJI-1 does not force activation.

### RJI-2 — Deterministic Mock / Contract Lab

- capability descriptor/request/result schema tests;
- trust/control-field rejection tests;
- freshness/replay tests;
- provider-binding mismatch tests;
- timeout/rate/budget/error tests.

### RJI-3 — Ruflo Zero-Tool Proxy Lab

- zero exposed tools initially;
- prove spawn/swarm/daemon/hooks/model/provider/filesystem/shell/Git/memory/network mutation classes are blocked;
- qualify only individual read-only tools.

### RJI-4 — Provider-Bound Jev Adapter Lab

- integrate through Provider Adapter Registry;
- explicit selected provider/model/route only;
- prove no auto selection, cross-provider fallback or hidden retry;
- prove typed result remains advisory only.

### RJI-5 — Shadow

- record Ruflo/Jev results;
- canonical decision delta must remain zero;
- collect latency/cost/error/freshness/security evidence.

### RJI-6 — Bounded Canary

- Jev: narrow typed verification/classification only;
- Ruflo: one independently qualified read-only advisory tool at a time;
- no autonomous orchestration, memory, daemon, provider execution or side effects.

### RJI-7 — Runtime EDP Qualification

Must include focused + full regression, authority negative-space tests, failure injection, restart/replay, schema/version drift, secret/egress, stale evidence, provider identity, rollback/quarantine and disable-to-baseline tests.

Runtime exit condition includes blocker/major=0, requirement/traceability/domain evidence=100%, and all runtime-specific PASS gates.

### RJI-8 — Live Activation

Separate explicit user/governance approval only.

`DESIGN_EDP_ALL_PASS` or future implementation-plan approval never authorizes RJI-8.

---

## 15. Rollback / Stable-Core Protection

Rollback unit is the external capability registration/adapter, not the Harness core.

```text
disable external.ruflo.coordination_advisory.v1
and/or
disable external.jev.typed_judgment.v1
```

After disable:

- Full Plan remains unchanged;
- Provider Router/MPRF baseline remains unchanged;
- existing Provider Adapter Registry remains available to existing providers;
- Tool Authorization/Registry/Broker baseline remains available to existing tools;
- Full MCP effect path remains unchanged;
- OCPv2 remains unchanged;
- no canonical-state migration is required;
- unrelated Harness tasks continue through the pre-integration behavior.

No existing stable-core contract is reimplemented or transferred to Ruflo/Jev.

---

## 16. Negative-Space Audit

| Negative-space question | v0.3 disposition | Result |
|---|---|---|
| Can OCPv2 directly invoke Ruflo/Jev? | No; no direct authority/path exists. | PASS |
| Can Full Plan bypass Tool/Provider governance and call external MCP directly? | No. | PASS |
| Can Ruflo spawn agents/workers/swarms? | v1 deny. | PASS |
| Can Ruflo run daemon/hooks/autonomous loop? | v1 deny. | PASS |
| Can Ruflo call a model/provider? | v1 deny; such a tool is ineligible. | PASS |
| Can Ruflo write filesystem/shell/Git? | v1 deny. | PASS |
| Can Ruflo use its own memory as canonical or hidden planning state? | v1 memory read/write disabled. | PASS |
| Can Ruflo internal policy replace Harness filtering? | No; defense-in-depth only. | PASS |
| Can Jev choose provider/model automatically? | No; explicit Router binding only. | PASS |
| Can Jev silently fallback across providers? | No. | PASS |
| Can Jev hidden retry change provider/route? | No; default one attempt and no adapter-owned reroute. | PASS |
| Can Jev provider/model/route mismatch be accepted? | No; fail closed. | PASS |
| Can Jev gate/review output become approval/completion authority? | No. | PASS |
| Can external prose mutate control fields? | No; canonical envelope only. | PASS |
| Can an advisory side-effect request pass through? | No; READ_ONLY_EVIDENCE mismatch is denied. | PASS |
| Can external capability recursively delegate? | No; max depth 0. | PASS |
| Can unapproved egress or redirect occur? | Deny-by-default and host/route allowlist. | PASS |
| Can sensitive Jev payload leave before privacy qualification? | No. | PASS |
| Can unpinned/latest package activate? | No. | PASS |
| Can schema/tool-set drift continue running? | No; quarantine. | PASS |
| Can stale evidence drive governed action? | No. | PASS |
| Can crash blindly replay completed advisory work? | No; deterministic reuse policy. | PASS |
| Can timeout/rate/budget create alternate authority? | No. | PASS |
| Can capability outage stop unrelated work? | No; graceful degradation. | PASS |
| Can design approval silently become live activation? | No; RJI-8 separate. | PASS |

`NEGATIVE_SPACE_OPEN_MATERIAL_COUNT = 0`

---

## 17. Cross-Document Consistency Audit

### 17.1 Source → Target

| Authority/source | Required semantic | v0.3 preservation | Result |
|---|---|---|---|
| Multi-provider extensibility design | Router sole provider/model selector; provider-specific transport stays in adapters | Jev is provider-bound via Provider Adapter Registry | PASS |
| Multi-provider extensibility design | MPRF recovery/reroute remains authoritative | external adapter has no cross-provider reroute | PASS |
| Final operational EDP | tool/effect authority remains authorization → registry → broker → journal/effect boundary | Ruflo uses Tool Authorization/Registry/Broker; effects remain Full MCP | PASS |
| Diagnostic Intelligence design | read-only advisory has no control/mutation/recovery/completion authority | Ruflo/Jev authority class NONE; advisory evidence only | PASS |
| Diagnostic Intelligence design | evidence must bind source snapshot/freshness | input/source digests + stale state added | PASS |
| OCPv2 R2 | transport non-authoritative; state change via existing gateway/Full MCP | unchanged | PASS |
| OmniRoute gateway pattern | external provider gateway must not own auto routing/fallback | Jev auto/fallback prohibited; explicit selected identity required | PASS |
| Stable operational baseline | existing current behavior restored when optional advisory subsystem is disabled | capability-level rollback only | PASS |

### 17.2 Target → Source

Every material v0.3 addition is authorized by one of: the current user EDP remediation directive, an existing approved authority boundary, an existing read-only/provider gateway pattern, or a security/fail-closed refinement necessary to preserve those authorities. No target section grants new execution, routing, approval, recovery or completion authority to Ruflo/Jev.

`CROSS_DOCUMENT_CONFLICT_COUNT = 0`

---

## 18. Mandatory Requirements Traceability Matrix

| Source obligation(s) | Target representation | Planned/runtime proof point | Design status |
|---|---|---|---|
| O-001, O-006, O-007, O-008 | §§4, 7.3, 15 | authority negative-space + disable-to-baseline | COVERED |
| O-002, O-003, O-004 | §§4, 7.2, 10, 14 | explicit Router decision/provider identity tests | COVERED |
| O-005 | §§4, 7.1, 9 | Tool Authorization/Registry/Broker tests | COVERED |
| O-009..O-012 | §§7.1, 9, 16 | Ruflo zero-tool/forbidden-surface tests | COVERED |
| O-013..O-016 | §§7.2, 10, 16 | Jev explicit route/no-fallback/no-gate tests | COVERED |
| O-017, O-018 | §§8, 13 | schema/control-field/trust tests | COVERED |
| O-019, O-020 | §§8, 11 | stale/replay/restart tests | COVERED |
| O-021 | §§8, 9, 11, 16 | recursion/delegation denial tests | COVERED |
| O-022..O-024 | §§10, 13, 16 | egress/secret/privacy classification tests | COVERED |
| O-025, O-026 | §§9, 10, 13, 14 | version/schema drift quarantine tests | COVERED |
| O-027, O-028 | §§11, 12, 16 | timeout/rate/budget/outage failure injection | COVERED |
| O-029, O-030 | §14 | lifecycle transition/activation authorization tests | COVERED |
| O-031 | §15 | disable/rollback regression | COVERED |
| O-032 | title, §1, §14, §22 | design-vs-runtime status assertion | COVERED |

`MUST_REQUIREMENT_COVERAGE = 100%`  
`MUST_TRACEABILITY_COVERAGE = 100%`

---

## 19. D1–D17 Domain Evidence Matrix

| Domain | Claim checked | Evidence / target | Result |
|---|---|---|---|
| D1 Source/Authority | Required authority set is available and precedence is frozen | §§3-4 + approved repo artifacts | PASS |
| D2 Intent/Obligations | User requested exhaustive diagnosis/remediation/re-diagnosis; all material obligations frozen | §§1, 5 | PASS |
| D3 Grammar/Terminology | advisory admission vs execution authorization and authority terms are unambiguous | §§4, 8; F-012 resolved | PASS |
| D4 Structural Integrity | required design + EDP closure sections exist and have deterministic order | full document | PASS |
| D5 Internal Consistency | Router, MPRF, Tool Broker, Full MCP and capability roles do not conflict | §§4, 7, 15 | PASS |
| D6 Semantic Integrity | “advisory/non-authoritative/read-only” retains one meaning throughout | §§7-13 | PASS |
| D7 Cross-Document Integrity | source→target and target→source both checked | §17 | PASS |
| D8 Traceability | every material obligation maps to target/proof | §18 | PASS |
| D9 Dependency/Sequence | Ruflo and Jev paths have non-circular governed preconditions | §§7, 14 | PASS |
| D10 Verifiability | each gate/failure/acceptance condition is measurable | §§8, 11-14, 20 | PASS |
| D11 Negative Space | expected forbidden paths and missing protections exhaustively checked | §16 | PASS |
| D12 Ambiguity/TBD | previous material conditionals converted into deterministic fail-closed rules | §6 + relevant corrected sections | PASS |
| D13 Duplication/Conflict/Obsolescence | v0.2 remains historical; v0.3 clearly supersedes for approval; no second core adapter/effect plane | §§6-7, 15 | PASS |
| D14 Operational/Execution Integrity | implementation sequence, failure, rollback and handoff are design-complete without claiming runtime evidence | §§11-15 | PASS |
| D15 Safety/Security/Permissions | trust, secret, egress, effect, activation and supply-chain boundaries defined | §§8-10, 13-16 | PASS |
| D16 Adversarial Integrity | second pass searched authority bypasses, hidden fallback, recursion, stale/replay and data leak | §20 | PASS |
| D17 Closure Integrity | PASS challenge, metrics, exhaustion and final decision executed after remediation regression | §§20-22 | PASS |

`DOMAIN_EVIDENCE_COVERAGE = 100%`

---

## 20. Adversarial Second Pass and PASS Challenge

### 20.1 Adversarial Second Pass

Challenge premise:

> Assume the corrected architecture is still wrong and search for a path by which Ruflo/Jev can become a second orchestrator, provider selector, recovery authority, effect executor, approval/completion source, stale-evidence source, secret/egress bypass or recursive control plane.

Counterexamples actively tested at design level:

1. **Ruflo calls an LLM internally** → forbidden by v1 profile; candidate tool ineligible.
2. **Ruflo uses a swarm/daemon/hook even when exposed tool looks read-only** → transitive behavior qualification + Filtering Proxy deny; zero-tool default.
3. **Ruflo policy enforcement is accidentally disabled** → Harness hard deny remains independent of Ruflo policy.
4. **Community Jev MCP auto-selects another provider** → not a production trust root; provider-bound thin adapter required.
5. **Jev endpoint returns a different model/provider** → response identity mismatch fails closed.
6. **Jev retries through another route** → adapter-owned fallback forbidden; one-attempt default.
7. **External result says “approved/execute now”** → untrusted prose cannot populate control fields.
8. **Stale analysis is reused after source change** → snapshot/input digest mismatch yields stale evidence.
9. **Crash duplicates advisory call** → exact replay tuple required; ambiguous state does not auto-repeat.
10. **Advisory adapter is asked to write a file** → effect class mismatch denies before invocation.
11. **External capability calls another external capability** → delegation depth zero.
12. **Privacy policy evidence is missing** → sensitive/private Jev data egress remains denied, not assumed safe.
13. **Current Provider Adapter Registry cannot express Jev** → capability stays disabled; no core bypass.
14. **Ruflo/Jev is unavailable** → unrelated work returns to existing Harness behavior.
15. **Design is approved** → does not grant live activation; RJI-8 remains separate.

No new BLOCKER or MAJOR remained after remediation.

`ADVERSARIAL_NEW_BLOCKER_MAJOR = 0`

### 20.2 PASS Challenge

| PASS-critical challenge | Evidence against failure | Result |
|---|---|---|
| Could Ruflo become a second Harness? | no spawn/swarm/daemon/hooks/autonomy/provider calls; Tool Broker + zero-tool proxy | CLOSED |
| Could Jev bypass Router? | Provider Adapter Registry binding + explicit selected identity + mismatch denial | CLOSED |
| Could advisory output mutate state? | effect class READ_ONLY_EVIDENCE; state changes remain Full MCP path | CLOSED |
| Could stale evidence influence action? | source/input digest and stale rejection | CLOSED |
| Could hidden fallback change provider? | no adapter auto/fallback; MPRF/Router only | CLOSED |
| Could a community package's own policy become authority? | community/policy-rich package is non-authoritative reference only | CLOSED |
| Could missing privacy evidence be interpreted as approval? | explicit fail-closed data classification | CLOSED |
| Could unsupported integration force stable-core edits? | capability disabled and design revision required | CLOSED |
| Could OCP/RDC acquire new runtime authority? | explicit non-authoritative/no dependency invariants preserved | CLOSED |
| Could approval of this document imply implementation or production? | explicit status separation + RJI-8 | CLOSED |

`PASS_CHALLENGE_OPEN_COUNT = 0`

---

## 21. Regression Re-Diagnosis

Because material corrections were made, the affected domains and all dependent closure domains were re-run.

Re-diagnosed domains:

`D1, D3, D4, D5, D6, D7, D8, D9, D10, D11, D12, D13, D14, D15, D16, D17`

Results:

- Authority overlap after path split: **PASS**
- Provider Router / Provider Adapter Registry preservation: **PASS**
- Tool Broker / Full MCP effect separation: **PASS**
- OCPv2 non-authoritative invariant: **PASS**
- Ruflo second-orchestrator negative space: **PASS**
- Jev hidden routing/fallback negative space: **PASS**
- freshness/replay/restart semantics: **PASS**
- privacy/egress fail-closed semantics: **PASS**
- lifecycle/activation boundary: **PASS**
- source→target cross-document preservation: **PASS**
- target→source authorization: **PASS**
- RTM coverage: **PASS**
- Adversarial Second Pass: **PASS**
- PASS Challenge: **PASS**

No runtime tests are claimed here because implementation has not started. That limitation is explicit and does not weaken the design-scope conclusion.

`REGRESSION_REDIAGNOSIS_STATUS = PASS`

---

## 22. Mandatory Closure Metrics

```text
BLOCKER_COUNT = 0
UNRESOLVED_MAJOR_COUNT = 0
UNRESOLVED_MINOR_COUNT = 0
MUST_REQUIREMENT_COVERAGE = 100%
MUST_TRACEABILITY_COVERAGE = 100%
DOMAIN_EVIDENCE_COVERAGE = 100%
NEGATIVE_SPACE_OPEN_MATERIAL_COUNT = 0
CROSS_DOCUMENT_CONFLICT_COUNT = 0
BROKEN_REFERENCE_COUNT = 0
UNRESOLVED_MATERIAL_TBD_COUNT = 0
UNRESOLVED_MATERIAL_OPEN_QUESTION_COUNT = 0
ADVERSARIAL_NEW_BLOCKER_MAJOR = 0
PASS_CHALLENGE_OPEN_COUNT = 0
SOURCE_AUTHORITY_STATUS = VALID_FOR_DESIGN_SCOPE
REGRESSION_REDIAGNOSIS_STATUS = PASS
MATERIAL_DEFECT_SEARCH = EXHAUSTED_FOR_AVAILABLE_EVIDENCE
```

### Exhaustion Statement

Within the currently available authoritative evidence and the declared architecture/design scope, all mandatory EDP search paths were executed: authority resolution, frozen obligations, D1-D17 evidence, bidirectional traceability, negative-space, cross-document comparison, adversarial second pass, PASS challenge, remediation regression and closure metrics.

There is no remaining reasonable unchecked path within this evidence set by which a new material **design** defect would be expected to alter the conclusion without introducing new runtime/external evidence or changing the approved requirements.

This does not claim mathematical perfection or runtime correctness for code that does not yet exist.

---

## 23. Final Decision

**Final EDP decision:**

`DESIGN_EDP_ALL_PASS / READY_FOR_EXPLICIT_USER_APPROVAL`

Approved-for-review architecture:

```text
Ruflo
  = external read-only advisory tool
  -> Tool Authorization / Registry / Broker
  -> zero-trust Filtering Proxy
  -> NO orchestration/provider/effect/memory authority

Jev
  = model-backed typed judgment
  -> Provider Router
  -> MPRF / Provider Adapter Registry
  -> provider-bound thin adapter
  -> NO auto-routing/fallback/gate/effect authority

Harness / Full Plan / Governance
  = canonical decision/orchestration authority

Provider Router
  = sole provider/model selection authority

MPRF
  = provider lifecycle/recovery authority

Production Execution Gateway / Full MCP
  = sole state-changing effect/reconciliation authority

OCPv2
  = non-authoritative transport/control plane

RDC
  = emergency recovery only
```

Status after this document:

```text
DESIGN_STATUS = EDP_ALL_PASS_CANDIDATE
USER_APPROVAL = PENDING
IMPLEMENTATION_PLAN = NOT_YET_AUTHORIZED_BY_THIS_DOCUMENT
IMPLEMENTATION_EXECUTION = NOT_AUTHORIZED
RUNTIME_QUALIFICATION = NOT_STARTED
LIVE_ACTIVATION = NOT_AUTHORIZED
MAIN_BRANCH = UNCHANGED_BY_THIS_DESIGN_ARTIFACT
```

After explicit user approval of this v0.3 corrected design, the next artifact is a detailed implementation plan covering RJI-1 through RJI-7. Live activation remains a separate RJI-8 decision.