# Multi-Provider ACTION Independent Review Input

## Authority / goal
- Canonical plan SHA256: f3cfae7deb67d6c464932f8fe97f1736263a6c1640874db44c66a9401fa4344d (unchanged).
- Full Plan owns lifecycle/task sequencing and fan-in.
- Provider Router alone selects provider/model.
- MPRF supplies provider/runtime eligibility facts and must not select.
- Provider may generate a bounded change proposal; provider must not own filesystem/state effects.
- Execution Backend / ProductionToolTransport / SingleToolBroker own approved effects and effect evidence.
- Manual Action is emergency-only, not the normal ACTION path.

## Remediation behavior
1. Governed ACTION is no longer bound to Codex. Router translates effect capabilities (filesystem_write/shell/git/activation) out of model-generation requirements and requires patch_generation for ACTION.
2. Current provider capability profiles are projected into the immutable eligibility snapshot and therefore its digest.
3. Legacy non-governed HYBRID state-changing routing fails closed and requires governed RouterRequest.v2.
4. Non-Codex ACTION in durable production uses PROVIDER_ACTION: model generates exact JSON proposal, then ProductionToolTransport executes approved owned-file writes through SingleToolBroker.
5. NVIDIA non-ACTION remains read-only. Codex can continue existing governed HOST_GATEWAY tool path.
6. Provider ACTION canonical authority requires MUTATION_REQUIRED but does not fabricate Codex readiness.
7. Proposal identity binds project/run/gate/LV/plan/source-head and owned-file IDs. Duplicate/out-of-scope/unsafe writes fail closed.
8. Complete provider proposal is secret-scanned before private persistence; rejected raw proposal is neither persisted nor applied.
9. Deterministic Harness validation and checkpoint commit remain after effects.

## Negative-space observations
- Search found no governed ACTION -> CODEX_PROVIDER hard binding or governed_action_to_codex in runtime/orchestrator.
- runtime/mprf contains no route_request/route_provider invocation (router_client only defines build_reroute_request).
- provider_action_execution has no product-file write_text/write_bytes/subprocess/git call; its direct os.open is only private proposal evidence. Product effects call ProductionToolTransport.handle.
- git diff for runtime/mprf and runtime/full_mcp is empty.
- docs/DEVELOPMENT_PLAN.txt SHA remains canonical.

## Regression evidence
- Full repository: 1574 tests PASS, 12 opt-in/environment skips, RC=0.
- git diff --check PASS.
- compileall runtime/orchestrator + tests PASS.
- Focused provider action tests include invalid owned identity, source-head mismatch, history/runtime context exclusion, and secret-rejected proposal no-persistence/no-effect.

## Source SHA256
- runtime/orchestrator/provider_router.py: bd9804162092faabf209beeab1d3938e72b776229b2206fe86a8fc3538588ae3
- runtime/orchestrator/provider_action_execution.py: e7af27f3f1bc037b0a1a3935539a444375d3837d77087ce791c40ee504c8abaf
- runtime/orchestrator/provider_runtime_policy.py: 1493a9cb891aef3afcfcd947c5df49bf871b42da848a33692269af737be6dbc2
- runtime/orchestrator/provider_runtime_binding.py: dc2e5428fc0c31e75437d900e8fa7011de520856a090c803f4d16e2c27bfbc01
- runtime/orchestrator/production_worker_executor.py: 288c72d0d664e555ae382f4bdab905e0193581f1177fd92446da1d276e3a6839
- runtime/orchestrator/gate_orchestrator.py: a9b3de4e47ddb0fc8351e44c41dcde700e640cda85766605f052c018d4bfabac
- runtime/orchestrator/production_canonical_authority.py: 01a6d8bd94a6fa96ed670cbe580f7bd877358c719f2781463c66ca90aefef697
- runtime/orchestrator/production_tool_transport.py: ce7dd9c3e2579f7793fbffb2a35bd12d30324ac4d17a2db2f2da07fd6d2c1b89

## Selected governed Router/runtime diff excerpt
```diff
diff --git a/runtime/orchestrator/execution_modes.py b/runtime/orchestrator/execution_modes.py
index 1831416..f1ebb14 100644
--- a/runtime/orchestrator/execution_modes.py
+++ b/runtime/orchestrator/execution_modes.py
@@ -56,7 +56,7 @@ def mode_info(mode: str | None) -> ExecutionModeInfo:
     if normalized == HYBRID:
         return ExecutionModeInfo(
             mode=normalized,
-            description="Rule-based provider routing across NVIDIA reasoning and Codex state-changing execution.",
+            description="Capability-based governed provider routing; state effects remain in the Execution Backend.",
             codex_cli_eligible=True,
             manual_fallback=True,
         )
diff --git a/runtime/orchestrator/provider_executor.py b/runtime/orchestrator/provider_executor.py
index 435fb53..853a956 100644
--- a/runtime/orchestrator/provider_executor.py
+++ b/runtime/orchestrator/provider_executor.py
@@ -47,6 +47,21 @@ def _execute_governed(
             "next_step": "GPT_OPERATOR_REVIEW_REQUIRED",
         }

+    if decision.stage == "ACTION" and decision.provider_ref != CODEX_PROVIDER:
+        # The legacy provider executor has no Broker/tool-authorization context.
+        # Never mistake proposal generation for an applied state change. Durable
+        # Full Plan uses production_worker_executor.PROVIDER_ACTION instead.
+        return {
+            "status": "action_provider_blocked", "mode": "hybrid",
+            "provider": decision.provider_ref, "model": decision.model_ref,
+            "route_reason": "production_action_backend_required",
+            "router_decision_digest": decision.decision_digest,
+            "runtime_stage": decision.stage, "action_state": "ACTION_BACKEND_REQUIRED",
+            "required_capabilities": list(decision.required_capabilities),
+            "errors": ["production_action_backend_required"],
+            "next_step": "DURABLE_FULL_PLAN_ACTION_BACKEND_REQUIRED",
+        }
+
     if decision.provider_ref == NVIDIA_PROVIDER:
         payload = run_nvidia_reasoning_task(
             prompt=task.input,
diff --git a/runtime/orchestrator/provider_router.py b/runtime/orchestrator/provider_router.py
index f98d39b..dab00ce 100644
--- a/runtime/orchestrator/provider_router.py
+++ b/runtime/orchestrator/provider_router.py
@@ -55,7 +55,9 @@ def route_provider(mode: str | None, required_capabilities: Iterable[str] | None
     if normalized_mode == HYBRID:
         if read_only:
             return ProviderRouteDecision(NVIDIA_PROVIDER, normalized_mode, "hybrid_read_only_to_nvidia", capabilities, True)
-        return ProviderRouteDecision(CODEX_PROVIDER, normalized_mode, "hybrid_state_changing_to_codex", capabilities, True)
+        return ProviderRouteDecision(
+            MANUAL_PROVIDER, normalized_mode, "hybrid_state_change_requires_governed_router", capabilities, False
+        )
     raise ValueError(f"Unsupported execution mode: {mode}")


@@ -110,6 +112,7 @@ class ProviderEligibilitySnapshotV1:
     evidence_refs: tuple[str, ...] = ()
     failure_classes: Mapping[str, str] | None = None
     model_fallback_refs: Mapping[str, tuple[str, ...]] | None = None
+    provider_capabilities: Mapping[str, tuple[str, ...]] | None = None

     def __post_init__(self) -> None:
         if self.schema_version != ELIGIBILITY_SCHEMA_V1 or not self.snapshot_id:
@@ -119,6 +122,13 @@ class ProviderEligibilitySnapshotV1:
         if any(provider not in {NVIDIA_PROVIDER, CODEX_PROVIDER} for provider in self.model_refs):
             raise ProviderRouterContractError("unapproved provider model binding")
         fallbacks = self.model_fallback_refs or {}
+        provider_caps = self.provider_capabilities or {}
+        if any(provider not in {NVIDIA_PROVIDER, CODEX_PROVIDER} for provider in provider_caps):
+            raise ProviderRouterContractError("unapproved provider capability binding")
+        for provider, refs in provider_caps.items():
+            normalized_caps = tuple(sorted({str(ref).strip() for ref in refs if str(ref).strip()}))
+            if not normalized_caps or len(normalized_caps) != len(tuple(refs)):
+                raise ProviderRouterContractError("invalid provider capability binding")
         if any(provider not in {NVIDIA_PROVIDER, CODEX_PROVIDER} for provider in fallbacks):
             raise ProviderRouterContractError("unapproved provider fallback binding")
         for provider, refs in fallbacks.items():
@@ -142,6 +152,10 @@ class ProviderEligibilitySnapshotV1:
             payload["model_fallback_refs"] = {
                 provider: list(refs) for provider, refs in self.model_fallback_refs.items() if refs
             }
+        if self.provider_capabilities:
+            payload["provider_capabilities"] = {
+                provider: list(refs) for provider, refs in self.provider_capabilities.items() if refs
+            }
         return payload

     @property
@@ -315,6 +329,9 @@ def eligibility_snapshot_from_mapping(value: Mapping[str, Any]) -> ProviderEligi
             str(provider): tuple(refs)
             for provider, refs in raw_fallbacks.items()
         } or None,
+        provider_capabilities={
+            str(provider): tuple(refs) for provider, refs in dict(value.get("provider_capabilities", {})).items()
+        } or None,
     )


@@ -356,6 +373,70 @@ def validate_router_envelope(value: Mapping[str, Any]) -> tuple[RouterRequestV2,
     return request, decision


+EFFECT_ONLY_CAPABILITIES = frozenset({"filesystem_write", "shell", "git", "activation"})
+ACTION_GENERATION_ALIASES = {
+    "implementation_apply": "implementation_generation",
+    "test_execution": "test_design",
+}
+ACTION_PROPOSAL_CAPABILITY = "patch_generation"
+
+
+def provider_generation_requirements(request: RouterRequestV2) -> tuple[str, ...]:
+    """Translate task/effect requirements into model-generation capabilities.
+
+    Effect authority (write/shell/git/activation) belongs to Execution Backend,
+    never to the selected model. ACTION providers only need to generate a
+    bounded proposal for those effects.
+    """
+    required: set[str] = set()
+    for capability in request.required_capabilities:
+        if capability in EFFECT_ONLY_CAPABILITIES:
+            continue
+        required.add(ACTION_GENERATION_ALIASES.get(capability, capability))
+    if request.stage == "ACTION":
+        required.add(ACTION_PROPOSAL_CAPABILITY)
+    return tuple(sorted(required))
+
+
+def _legacy_provider_cap
```
