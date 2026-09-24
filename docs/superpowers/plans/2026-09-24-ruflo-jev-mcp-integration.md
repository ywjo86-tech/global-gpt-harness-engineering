# Ruflo / Jev MCP Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Ruflo read-only advisory tools and TypeSafe/Jev typed judgments as optional, fail-closed, non-authoritative capabilities while preserving Provider Router, MPRF, Tool Authorization, Full MCP, OCPv2, and Completion Authority boundaries.

**Architecture:** Reuse the current provider-neutral execution and tool-authorization seams instead of introducing another registry or control plane. Jev runs only through the existing `ProviderRunnerRegistry` read side after an immutable `RouterDecisionV2`; Ruflo is filtered to zero tools by default and any admitted tool must become a read-only operation behind the existing closed registry / `SingleToolBroker`. Both normalize into immutable advisory evidence that cannot mutate canonical decisions.

**Tech Stack:** Python 3.12, `dataclasses`, `unittest`, existing Harness Router/MPRF/SingleToolBroker contracts, urllib-compatible injectable Jev transport, existing GitHub Actions full regression.

**Spec:** `docs/superpowers/specs/2026-09-24-ruflo-jev-mcp-integration-v0.4-approved.md`

## Global Constraints

- Provider Router remains sole provider/model initial-selection and cross-provider-reselection authority.
- MPRF owns provider runtime lifecycle/health/quota/failure/recovery-eligibility facts only; it never selects a replacement provider.
- Jev consumes an eligible immutable `RouterDecisionV2`; no provider selection, substitution, cross-provider fallback, hidden retry, or action-runner path.
- Ruflo starts with zero exposed tools; no spawn/swarm/daemon/hooks/model call/provider call/fs write/shell/Git/memory/canonical-state mutation.
- Ruflo package identity is pinned to `ruvnet/ruflo@0a96fb8857dabd343d71d76c3ca703100a2923bc` / `3.44.0` for this qualification slice; `latest` is forbidden.
- TypeSafe/Jev official API contract observed 2026-09-24 uses `POST /v1/systemone`, `GET /v1/models`, Bearer credential transport; secrets never enter Git/log/report/tool arguments.
- Private source/business/user payloads remain denied until account/privacy/retention/region/security qualification is explicitly complete.
- `non_authoritative=true` is forced by Harness-owned code and cannot be overridden by external responses.
- External delegation depth is `0`; egress is deny-by-default except explicitly qualified endpoint transport.
- Capability disable restores pre-integration behavior without stable-core rollback or canonical-state migration.
- Existing OCPv2 remains transport/input only. RDC is emergency recovery only.
- All production-code behavior changes follow RED -> observed failing test -> minimal GREEN -> focused tests -> full regression.
- No new third-party Python dependency is introduced for this slice.

## Review Focus

1. External response attempts to inject control fields (`provider_ref`, `approval`, `authorization`, `completion`, `action`, `lifecycle`) must fail closed rather than influence Harness state.
2. Jev transport returns a provider/model/route identity different from the bound Router decision; result must be `CAPABILITY_PROVIDER_BINDING_MISMATCH` and no retry/fallback occurs.
3. Ruflo exposes a mutating, delegating, provider-calling, daemon/background, or unpinned tool; qualification must reject it and zero-tool baseline must remain intact.
4. Source/input/schema/version drift after advisory creation must mark the evidence stale/quarantined and prevent reuse.
5. Capability flags, credentials, endpoint qualification, or runtime EDP evidence are missing at activation; activation must fail closed and unrelated Harness behavior must remain unchanged.

---

### Task 1: RJI-1/RJI-2 Common Advisory Contract and Provenance

**Files:**
- Create: `runtime/orchestrator/external_advisory_contract.py`
- Create: `tests/test_external_advisory_contract.py`
- Modify: `runtime/orchestrator/__init__.py` only if a public export is required by existing import conventions.

**Interfaces:**
- Consumes: canonical Router/provider ids and plain immutable metadata; it does not call Router, MPRF, Full MCP, network, filesystem, or OCP.
- Produces: `ExternalCapabilityDescriptorV1`, `ExternalCapabilityRequestV1`, `ExternalCapabilityResultV1`, `ExternalCapabilityError`, `ExternalCapabilityContractError`, `canonical_external_digest(value)`, and `validate_advisory_freshness(request, result)`.

- [ ] **Step 1: Write failing contract tests**

Create `tests/test_external_advisory_contract.py` with focused `unittest.TestCase` cases proving:

```python
from runtime.orchestrator.external_advisory_contract import (
    DESCRIPTOR_SCHEMA_V1, REQUEST_SCHEMA_V1, RESULT_SCHEMA_V1,
    ExternalCapabilityContractError, ExternalCapabilityDescriptorV1,
    ExternalCapabilityRequestV1, ExternalCapabilityResultV1,
    canonical_external_digest, validate_advisory_freshness,
)

class ExternalAdvisoryContractTest(unittest.TestCase):
    def descriptor(self, *, capability_id="external.jev.typed_judgment.v1", model_backed=True):
        return ExternalCapabilityDescriptorV1(
            schema_version=DESCRIPTOR_SCHEMA_V1,
            capability_id=capability_id,
            capability_kind="TYPED_JUDGMENT" if model_backed else "READ_ONLY_TOOL",
            authority_class="NONE",
            effect_class="READ_ONLY_EVIDENCE",
            trust_class="EXTERNAL_UNTRUSTED",
            lifecycle_state="QUALIFIED",
            capability_version="3.44.0" if not model_backed else "typesafe-api-0.2.0",
            package_or_endpoint_digest="sha256:" + "a" * 64,
            schema_digest="sha256:" + "b" * 64,
            model_backed=model_backed,
            provider_binding_required=model_backed,
            egress_policy_ref="egress:test",
            budget_ref="budget:test",
            retry_policy="NONE",
            max_delegation_depth=0,
            source_binding_required=True,
        )
```

Add tests that assert:
- descriptor rejects `authority_class != NONE`, non-read-only effect, retry policy other than `NONE`, delegation depth > 0, missing digests, and inconsistent model/provider binding;
- request requires exact project/run/task/task_execution/correlation/operation/capability/input/source/policy/egress/budget/deadline/attempt bindings and requires Router decision/provider/model fields iff model-backed;
- result always serializes `non_authoritative=True` even if raw external payload contains a false/override value;
- raw result keys from the forbidden control set cause `ExternalCapabilityContractError`;
- canonical digest is stable under mapping key order;
- a changed input/source/schema/capability/provider-decision binding causes `validate_advisory_freshness(...) == False`.

- [ ] **Step 2: Run tests and observe RED**

Run: `python3 -m unittest -v tests.test_external_advisory_contract`

Expected: import failure for missing `runtime.orchestrator.external_advisory_contract`.

- [ ] **Step 3: Implement minimal immutable contract**

Implement frozen/slot dataclasses and validation only. Required constants:

```python
DESCRIPTOR_SCHEMA_V1 = "external-capability.descriptor.v1"
REQUEST_SCHEMA_V1 = "external-capability.request.v1"
RESULT_SCHEMA_V1 = "external-capability.result.v1"
ALLOWED_LIFECYCLE_STATES = frozenset({
    "DISCOVERED", "QUALIFIED", "SHADOW", "CANARY",
    "READY_FOR_ACTIVATION", "ACTIVE", "QUARANTINED", "DISABLED",
})
FORBIDDEN_EXTERNAL_CONTROL_FIELDS = frozenset({
    "provider_ref", "model_ref", "provider_id", "model_id", "route",
    "approval", "approval_state", "authorization", "authorization_ref",
    "action", "action_state", "lifecycle_state", "completion", "completion_proof",
    "merge", "ship", "patch_apply", "execution_authority",
})
```

`ExternalCapabilityResultV1.from_external_payload(...)` must inspect the external payload before normalization and reject any forbidden control key. Harness-supplied provider/model identity lives in dedicated trusted arguments, never copied from arbitrary external prose.

- [ ] **Step 4: Run focused tests and observe GREEN**

Run: `python3 -m unittest -v tests.test_external_advisory_contract`

Expected: PASS.

- [ ] **Step 5: Run existing Router/MPRF boundary tests**

Run: `python3 -m unittest -v tests.test_provider_execution_registry tests.mprf.test_contracts`

Expected: PASS; no Router/MPRF behavior change.

- [ ] **Step 6: Commit**

```bash
git add runtime/orchestrator/external_advisory_contract.py tests/test_external_advisory_contract.py
git commit -m "feat: add external advisory contracts"
```

---

### Task 2: RJI-3 Ruflo Zero-Tool Filtering Proxy

**Files:**
- Create: `runtime/orchestrator/ruflo_filtering_proxy.py`
- Create: `tests/test_ruflo_filtering_proxy.py`
- Modify: `runtime/orchestrator/production_tool_transport.py`
- Test: `tests/test_production_tool_transport.py`

**Interfaces:**
- Consumes: `ExternalCapabilityDescriptorV1`, existing `RegisteredOperation`, `ClosedOperationRegistry`, `ToolAuthorizationContract`, and `SingleToolBroker`.
- Produces: `RufloQualifiedToolV1`, `RufloFilteringProxy`, `ruflo_registered_operation(tool)`, and an additive `ProductionToolTransport` read-only extension hook that cannot register write/effect operations.

- [ ] **Step 1: Write failing zero-tool and rejection tests**

Create tests asserting:

```python
proxy = RufloFilteringProxy(
    runtime_version="3.44.0",
    runtime_commit="0a96fb8857dabd343d71d76c3ca703100a2923bc",
    runtime_invoker=lambda tool_id, args: {"ok": True},
)
self.assertEqual(proxy.qualified_tool_ids, ())
self.assertEqual(proxy.registered_operations(), ())
```

Add one-case-per-rule rejection tests for:
- unpinned runtime version/commit;
- `READ_ONLY` false or any mutation flag true;
- agent/worker/swarm/daemon/hook/background/delegation flag true;
- provider/model-call flag true;
- memory/canonical-state access true;
- unapproved egress;
- missing/changed tool schema digest;
- delegation depth > 0.

Add a qualified synthetic read-only tool fixture and assert `ruflo_registered_operation()` has `intent="READ"` and `effect_class="READ_ONLY"`.

- [ ] **Step 2: Run Ruflo test and observe RED**

Run: `python3 -m unittest -v tests.test_ruflo_filtering_proxy`

Expected: import failure for missing proxy module.

- [ ] **Step 3: Implement filtering proxy and immutable tool descriptor**

`RufloQualifiedToolV1` fields must include exact runtime version/commit, tool id, operation class id, input/output schemas, schema digest, effect class, all forbidden-behavior booleans, egress policy, and max delegation depth. Constructor validation is fail-closed.

`RufloFilteringProxy.invoke(tool_id, arguments)`:
- resolves only a qualified tool id;
- validates JSON-like mapping input;
- invokes exactly once through injected `runtime_invoker`;
- rejects external control fields by normalizing through Task 1 contract;
- has no retry and no alternate tool/provider path.

- [ ] **Step 4: Add read-only external operation hook to existing tool transport**

Extend `ProductionToolTransport.__init__` with optional keyword-only arguments:

```python
external_read_only_operations: tuple[RegisteredOperation, ...] = ()
external_read_only_launchers: Mapping[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]] | None = None
```

Before constructing `ClosedOperationRegistry`, validate every extra operation:
- `intent == "READ"`;
- `effect_class == "READ_ONLY"`;
- unique registration id and operation class id versus built-ins;
- launcher exists for each extra operation;
- no extra launcher without an operation.

Then build the same existing `SingleToolBroker` using built-ins plus qualified read-only operations. Do not modify write/effect journal semantics.

- [ ] **Step 5: Run focused Ruflo and broker tests**

Run: `python3 -m unittest -v tests.test_ruflo_filtering_proxy tests.test_production_tool_transport`

Expected: PASS, including a negative test proving an external `WRITE` operation is rejected before broker construction.

- [ ] **Step 6: Run Full MCP boundary lint**

Run: `python3 scripts/full_mcp_lint.py runtime/full_mcp runtime/orchestrator/production_execution_gateway.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add runtime/orchestrator/ruflo_filtering_proxy.py runtime/orchestrator/production_tool_transport.py tests/test_ruflo_filtering_proxy.py tests/test_production_tool_transport.py
git commit -m "feat: add zero-tool Ruflo advisory proxy"
```

---

### Task 3: RJI-4 Jev Provider-Bound Read Adapter

**Files:**
- Create: `runtime/orchestrator/jev_provider_bound_adapter.py`
- Create: `tests/test_jev_provider_bound_adapter.py`
- Modify: `runtime/orchestrator/provider_execution_registry.py` only for a small helper if needed; do not change selection semantics.

**Interfaces:**
- Consumes: `RouterRequestV2`, `RouterDecisionV2`, `ProviderRunnerRegistry.resolve_read()`, `ExternalCapabilityRequestV1`, and an injected `JevTransport` callable.
- Produces: `JevProviderBoundAdapter`, `JevTransportResponseV1`, `build_jev_read_runner(transport)`, normalized `ExternalCapabilityResultV1`.

- [ ] **Step 1: Write failing provider-binding tests**

Build a real `RouterRequestV2` + `route_request(request)` in tests; do not mock the Router decision shape. Assert:
- eligible PREPARE/VERIFY/REVIEW decision with matching request digest may invoke transport exactly once;
- ACTION decision is rejected;
- ineligible decision is rejected;
- Router request digest mismatch is rejected before transport;
- capability request provider/model/decision digest mismatch is rejected before transport;
- transport returning different actual provider/model/route identity returns/raises `CAPABILITY_PROVIDER_BINDING_MISMATCH` and call count stays one;
- transport timeout and rate-limit are normalized without fallback;
- no list of fallback models is consumed by the adapter;
- result is `non_authoritative=True`.

- [ ] **Step 2: Run Jev tests and observe RED**

Run: `python3 -m unittest -v tests.test_jev_provider_bound_adapter`

Expected: import failure for missing adapter module.

- [ ] **Step 3: Implement thin provider-bound adapter**

Define:

```python
@dataclass(frozen=True, slots=True)
class JevTransportResponseV1:
    result: Mapping[str, Any]
    actual_provider_ref: str
    actual_model_ref: str
    actual_route_ref: str
    confidence: float | None
    usage: Mapping[str, Any] | None
    latency_ms: int

JevTransport = Callable[[ExternalCapabilityRequestV1, int], JevTransportResponseV1]
```

`JevProviderBoundAdapter.execute(router_request, router_decision, capability_request)` validates all trusted bindings and calls transport once. It never calls `route_request`, MPRF reroute, `resolve_action`, fallback refs, Full MCP, or OCP.

- [ ] **Step 4: Expose an explicit read-runner factory**

`build_jev_read_runner(transport)` returns a callable compatible with the existing read-runner registry. It receives the already-selected request/decision/capability request as keyword arguments and delegates only to `JevProviderBoundAdapter.execute`.

No provider id is hard-coded into `ProviderRunnerRegistry`; registration is performed by caller/configuration with the Router-selected identity.

- [ ] **Step 5: Run Jev + provider-registry tests**

Run: `python3 -m unittest -v tests.test_jev_provider_bound_adapter tests.test_provider_execution_registry`

Expected: PASS.

- [ ] **Step 6: Static authority negative-space assertion**

In `tests/test_jev_provider_bound_adapter.py`, use `inspect.getsource` and assert the adapter source does not contain calls to `route_request(`, `resolve_action(`, `model_fallback_refs`, `ProductionExecutionGateway`, or OCP transport modules.

Run the test again; expected PASS.

- [ ] **Step 7: Commit**

```bash
git add runtime/orchestrator/jev_provider_bound_adapter.py tests/test_jev_provider_bound_adapter.py runtime/orchestrator/provider_execution_registry.py
git commit -m "feat: add provider-bound Jev advisory adapter"
```

---

### Task 4: RJI-5 SHADOW Evidence Recorder and Freshness Enforcement

**Files:**
- Create: `runtime/orchestrator/external_advisory_shadow.py`
- Create: `tests/test_external_advisory_shadow.py`
- Modify: `runtime/orchestrator/observability_source_adapters.py` only if its existing projection contract can accept an additive external-advisory projection without source-of-truth duplication.

**Interfaces:**
- Consumes: canonical baseline decision digest + `ExternalCapabilityRequestV1` + `ExternalCapabilityResultV1`.
- Produces: `AdvisoryShadowRecordV1` and `record_shadow_advisory(...)` with no decision mutation API.

- [ ] **Step 1: Write failing SHADOW tests**

Tests must prove:
- record contains baseline canonical decision digest and advisory result digest;
- no field named `selected_provider`, `override`, `approval`, `action`, or `completion` is present;
- canonical decision object supplied to recorder is unchanged before/after;
- stale result is rejected with `CAPABILITY_EVIDENCE_STALE`;
- unavailable optional advisory can be recorded without changing canonical decision;
- private payload body is not stored; only bindings/digests/metadata are recorded.

- [ ] **Step 2: Observe RED**

Run: `python3 -m unittest -v tests.test_external_advisory_shadow`

Expected: import failure.

- [ ] **Step 3: Implement immutable SHADOW record**

`AdvisoryShadowRecordV1` must contain only identity/digest/status/latency/confidence/usage/error metadata and `canonical_decision_delta=0`. Do not accept a mutable callback for changing decisions.

- [ ] **Step 4: Run focused tests**

Run: `python3 -m unittest -v tests.test_external_advisory_shadow tests.test_external_advisory_contract`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/external_advisory_shadow.py tests/test_external_advisory_shadow.py runtime/orchestrator/observability_source_adapters.py
git commit -m "feat: add shadow advisory evidence recording"
```

---

### Task 5: RJI-6 Bounded CANARY, Kill Switch, and Disable-to-Baseline

**Files:**
- Create: `runtime/orchestrator/external_advisory_runtime.py`
- Create: `tests/test_external_advisory_runtime.py`
- Modify: `runtime/orchestrator/provider_runtime_policy.py` only if needed for existing feature-policy conventions; do not add provider selection logic.

**Interfaces:**
- Consumes: approved descriptor, lifecycle state, explicit environment/config flags, qualification evidence refs.
- Produces: `ExternalAdvisoryRuntimePolicyV1`, `capability_enabled(...)`, `assert_activation_ready(...)`; no network or provider execution.

- [ ] **Step 1: Write failing runtime-policy tests**

Prove:
- both capabilities disabled by default;
- `QUALIFIED` or `SHADOW` cannot be treated as ACTIVE;
- CANARY requires explicit per-capability enable flag plus qualification evidence;
- ACTIVE requires `READY_FOR_ACTIVATION`, RJI-7 pass receipt, user safety approval receipt, exact pinned identity, and capability-specific enable flag;
- kill switch immediately returns false without mutating Router/MPRF configuration;
- missing Jev credential reference, endpoint qualification, or Ruflo tool qualification fails closed;
- disabling both capabilities produces exactly the pre-integration path decision supplied by the caller.

- [ ] **Step 2: Observe RED**

Run: `python3 -m unittest -v tests.test_external_advisory_runtime`

Expected: import failure.

- [ ] **Step 3: Implement policy-only runtime guard**

Use configuration values, not hard-coded provider choices. Never read or log secret values; accept only booleans/credential reference names and evidence identifiers. Default all activation flags to false.

- [ ] **Step 4: Run focused tests**

Run: `python3 -m unittest -v tests.test_external_advisory_runtime tests.test_provider_execution_registry tests.test_ai_office_authority_negative_space`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/orchestrator/external_advisory_runtime.py tests/test_external_advisory_runtime.py runtime/orchestrator/provider_runtime_policy.py
git commit -m "feat: add bounded external advisory runtime policy"
```

---

### Task 6: RJI-7 Runtime EDP Qualification and Regression Gate

**Files:**
- Create: `tests/test_ruflo_jev_authority_negative_space.py`
- Create: `scripts/rji_runtime_edp.py`
- Modify: `.github/workflows/ocpv2-r2-ci.yml`
- Create: `docs/history/upgrades/20260924-v00/RUFLO_JEV_RUNTIME_EDP_REPORT.md` only after test evidence exists.

**Interfaces:**
- Consumes: all Task 1-5 tests and repository full-regression runner.
- Produces: deterministic JSON/console qualification summary and a human-readable EDP evidence record; does not activate capabilities.

- [ ] **Step 1: Write negative-space tests before qualification script implementation**

Test these end-to-end invariants through public APIs:
- external advisory cannot create Router decisions;
- Jev adapter cannot resolve action runner or invoke fallback;
- Ruflo extra operation cannot be WRITE or mutable;
- OCP modules do not import/call Ruflo/Jev adapters directly;
- advisory evidence cannot satisfy approval/completion contracts;
- disabled external capability leaves existing provider/tool execution path unchanged;
- stale/schema-drift/version-drift/provider-identity mismatch all fail closed;
- missing secret/egress/privacy qualification blocks ACTIVE.

- [ ] **Step 2: Run negative-space tests**

Run: `python3 -m unittest -v tests.test_ruflo_jev_authority_negative_space`

Expected: initially FAIL for missing qualification helper/script-facing API; failures must be about missing intended behavior, not syntax/fixture errors.

- [ ] **Step 3: Implement `scripts/rji_runtime_edp.py`**

The script runs these exact groups with `subprocess.run` and fails non-zero if any group fails:

```text
contract
ruflo_proxy
jev_adapter
shadow
runtime_policy
authority_negative_space
provider_registry
production_tool_transport
ai_office_authority_negative_space
full_repository_regression
compileall
git_diff_check
```

It prints one final machine-readable line:

```text
RJI_RUNTIME_EDP status=PASS blocker=0 unresolved_major=0 current_only_regressions=0
```

Only print PASS after every required command returns zero.

- [ ] **Step 4: Add PR-CI qualification job/path coverage**

Update `.github/workflows/ocpv2-r2-ci.yml` pull-request path filters to include:

```yaml
- "runtime/mprf/**"
- "runtime/full_mcp/**"
- "scripts/rji_runtime_edp.py"
```

Add a focused step `python3 scripts/rji_runtime_edp.py --focused` if the script supports it; keep the existing full-regression job unchanged so the same repository-wide baseline remains authoritative.

- [ ] **Step 5: Run focused qualification**

Run: `python3 scripts/rji_runtime_edp.py --focused`

Expected: PASS and zero open blocker/major.

- [ ] **Step 6: Run full repository regression**

Run: `python3 scripts/ocpv2_full_regression.py`

Expected: no current-only regressions. If baseline has pre-existing failures, record exact baseline/current failure identity and require current-only delta = 0.

- [ ] **Step 7: Run compile/lint/diff checks**

Run:

```bash
python3 scripts/full_mcp_lint.py runtime/full_mcp runtime/orchestrator/production_execution_gateway.py
python3 -m compileall -q runtime tests

git diff --check
```

Expected: all zero.

- [ ] **Step 8: Write runtime EDP report from observed evidence**

Create `docs/history/upgrades/20260924-v00/RUFLO_JEV_RUNTIME_EDP_REPORT.md` with exact commands, commit SHA, test counts, failure identities, authority-negative-space results, rollback proof, qualification pins, and final status. Never write `ALL PASS` unless all required evidence above is green.

- [ ] **Step 9: Commit**

```bash
git add tests/test_ruflo_jev_authority_negative_space.py scripts/rji_runtime_edp.py .github/workflows/ocpv2-r2-ci.yml docs/history/upgrades/20260924-v00/RUFLO_JEV_RUNTIME_EDP_REPORT.md
git commit -m "test: qualify Ruflo Jev runtime boundaries"
```

---

### Task 7: RJI-8 Activation Preparation and Qualified Slice Activation

**Files:**
- Create: `runtime/orchestrator/external_advisory_activation.py`
- Create: `tests/test_external_advisory_activation.py`
- Create: `docs/history/upgrades/20260924-v00/RUFLO_JEV_ACTIVATION_RECEIPT.md`
- Modify: deployment/runtime configuration only through the existing OCP-controlled path after readiness proof; do not add an RDC dependency.

**Interfaces:**
- Consumes: RJI-7 PASS receipt, user dangerous-work approval receipt, exact capability descriptors, endpoint/tool qualification evidence, feature flags, non-secret credential-reference metadata.
- Produces: `ActivationDecisionV1` with one of `READY`, `ACTIVE`, `BLOCKED`, `QUARANTINED`, plus rollback/disable instructions. It never exposes credential values.

- [ ] **Step 1: Write activation fail-closed tests**

Test:
- missing RJI-7 receipt -> BLOCKED;
- missing safety-approval receipt -> BLOCKED;
- Ruflo pin drift -> QUARANTINED;
- Ruflo zero qualified tools may be ACTIVE only as a zero-tool/no-op capability, never as proof that a tool is usable;
- Jev missing credential reference or endpoint/account/privacy qualification -> BLOCKED;
- Jev with private-data scope before privacy qualification -> BLOCKED;
- qualified synthetic/non-sensitive Jev CANARY may be ACTIVE only with exact endpoint/model binding evidence;
- rollback returns both feature flags disabled and contains no stable-core rollback instruction.

- [ ] **Step 2: Observe RED**

Run: `python3 -m unittest -v tests.test_external_advisory_activation`

Expected: import failure.

- [ ] **Step 3: Implement activation decision logic**

`ActivationDecisionV1` is pure policy/evidence evaluation. It does not install packages, open network sockets, or read secret values. The actual deployment action remains OCP-controlled and occurs only after the decision is `READY`.

- [ ] **Step 4: Run activation tests and Runtime EDP again**

Run:

```bash
python3 -m unittest -v tests.test_external_advisory_activation
python3 scripts/rji_runtime_edp.py --focused
python3 scripts/ocpv2_full_regression.py
```

Expected: all qualification checks green / no current-only regressions.

- [ ] **Step 5: Execute only technically qualified activation slice**

Activation order:

```text
1. Ruflo zero-tool profile -> ACTIVE only if exact package/runtime identity is available through OCP and zero-tool/no-egress invariants are provable.
2. Individually qualified Ruflo read-only tool -> CANARY/ACTIVE only after its tool-specific proof.
3. Jev -> synthetic/non-sensitive CANARY first; ACTIVE only if credential reference, endpoint/account/privacy/retention/security and actual provider/model identity verification are all present.
4. Private/business/user payload scope remains disabled until its separate privacy qualification passes.
```

If the current execution environment lacks the OCP deployment channel or required credential/endpoint evidence, record `BLOCKED_EXTERNAL_RUNTIME_EVIDENCE_MISSING`; do not substitute RDC, hard-coded secrets, manual hidden configuration, or an unqualified direct network call.

- [ ] **Step 6: Record activation/rollback evidence**

`RUFLO_JEV_ACTIVATION_RECEIPT.md` must state exact capability slice, lifecycle state, pin/digest, OCP deployment evidence, feature flags, canary input class, rollback command/path, and any blocked slices. Do not call a blocked slice ACTIVE.

- [ ] **Step 7: Commit activation policy/evidence**

```bash
git add runtime/orchestrator/external_advisory_activation.py tests/test_external_advisory_activation.py docs/history/upgrades/20260924-v00/RUFLO_JEV_ACTIVATION_RECEIPT.md
git commit -m "feat: gate Ruflo Jev live activation"
```

---

### Task 8: Whole-Branch Verification, EDP Closure, and Handoff

**Files:**
- Modify: `docs/DEVELOPMENT_PLAN.txt`
- Modify: `docs/APPROVAL_LOG.md`
- Create: `docs/history/upgrades/20260924-v00/RUFLO_JEV_IMPLEMENTATION_CLOSURE.md`

**Interfaces:**
- Consumes: Task 1-7 commits, CI evidence, Runtime EDP report, Activation receipt.
- Produces: implementation closure state that distinguishes `IMPLEMENTED`, `RUNTIME_EDP_PASS`, `ACTIVE`, and any `BLOCKED` sub-slices.

- [ ] **Step 1: Run complete verification from clean branch state**

Run:

```bash
python3 scripts/rji_runtime_edp.py
python3 scripts/full_mcp_lint.py runtime/full_mcp runtime/orchestrator/production_execution_gateway.py
python3 -m compileall -q runtime tests

git diff --check
```

Expected: zero current-only regression and all mandatory gates green.

- [ ] **Step 2: Verify disable-to-baseline**

Run the explicit runtime-policy test with both external capabilities disabled and compare the projected Router/tool behavior with a pre-integration fixture. Expected: exact semantic baseline match for unrelated routing/effect paths.

- [ ] **Step 3: Review whole branch against spec**

Review `git diff <implementation-base>...HEAD` for:
- authority drift;
- duplicated registry/control-plane logic;
- secret leakage;
- direct OCP/RDC external invocation;
- hidden retry/fallback;
- unbounded Ruflo surface;
- unsupported activation claims.

Any Critical/Important finding gets one TDD fix pass before closure.

- [ ] **Step 4: Update canonical documentation**

Record exact implementation state in `docs/DEVELOPMENT_PLAN.txt` and `docs/APPROVAL_LOG.md`. If Jev or Ruflo live slice is blocked by missing runtime/credential evidence, document it as BLOCKED rather than lowering the gate.

- [ ] **Step 5: Write closure report**

`RUFLO_JEV_IMPLEMENTATION_CLOSURE.md` must include:
- implementation commit range;
- RJI-0..RJI-8 status matrix;
- focused/full test evidence;
- current-only regression count;
- authority-negative-space summary;
- active vs blocked capability slices;
- rollback/disable evidence;
- residual risks and next allowed action.

- [ ] **Step 6: Commit documentation closure**

```bash
git add docs/DEVELOPMENT_PLAN.txt docs/APPROVAL_LOG.md docs/history/upgrades/20260924-v00/RUFLO_JEV_IMPLEMENTATION_CLOSURE.md
git commit -m "docs: close Ruflo Jev integration qualification"
```

## Self-Review Result

- Spec coverage: RJI-1 through RJI-8, all 37 v0.4 obligations, stable-core rollback, and authority negative space are mapped to explicit tasks/tests.
- Placeholder scan: no implementation TBD is permitted; missing external runtime evidence has an explicit fail-closed disposition.
- Type consistency: Jev consumes existing `RouterRequestV2` / `RouterDecisionV2`; read execution uses existing `ProviderRunnerRegistry`; Ruflo uses existing `RegisteredOperation` / `SingleToolBroker` path.
- Review Focus: each of the five high-risk input/failure classes is explicitly covered by Task 1, 2, 3, 5/6, and 7 tests.
- Architecture correction: no new Provider Router, MPRF, Full MCP, OCP, or provider-registry authority is introduced.
