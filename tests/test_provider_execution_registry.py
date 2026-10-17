from __future__ import annotations

import inspect
import unittest

from runtime.orchestrator.provider_router import (
    ELIGIBILITY_SCHEMA_V1, GOVERNED_POLICY_V1, ROUTER_REQUEST_SCHEMA_V2,
    ProviderEligibilitySnapshotV1, RouterRequestV2, route_request,
)
from runtime.orchestrator.provider_execution_registry import (
    HOST_GATEWAY, MANUAL_ACTION_BACKEND, PROVIDER_ACTION_BACKEND, PROVIDER_READ_ONLY_BACKEND,
    ProviderExecutionRegistryError, ProviderRunnerRegistry,
    execution_backend_for_manual_action_route, execution_backend_for_route,
)


class ProviderExecutionRegistryTest(unittest.TestCase):
    def _decision(self, provider: str, *, stage: str, caps: tuple[str, ...], native: bool = False):
        snapshot = ProviderEligibilitySnapshotV1(
            ELIGIBILITY_SCHEMA_V1, f"snap-{provider}-{stage}", {provider: True},
            {provider: f"{provider}/model"}, ("evidence",),
            provider_capabilities={provider: caps + (("native_tool_action",) if native else ())},
        )
        request = RouterRequestV2(
            ROUTER_REQUEST_SCHEMA_V2, f"req-{provider}-{stage}", "P", "R", "T", "E", "d"*64,
            stage, caps, stage == "ACTION", GOVERNED_POLICY_V1, snapshot,
        )
        return request, route_request(request)

    def test_router_projects_provider_generation_profile_without_provider_name_rule(self):
        request, decision = self._decision("provider-x", stage="PREPARE", caps=("reasoning", "read_only"))
        self.assertEqual(decision.execution_profile, "PROVIDER_GENERATION")
        self.assertEqual(execution_backend_for_route(request, decision), PROVIDER_READ_ONLY_BACKEND)

    def test_native_tool_profile_maps_to_host_gateway(self):
        request, decision = self._decision("provider-y", stage="ACTION", caps=("filesystem_write", "patch_generation"), native=True)
        self.assertEqual(decision.execution_profile, "NATIVE_TOOL")
        self.assertEqual(execution_backend_for_route(request, decision), HOST_GATEWAY)

    def test_provider_generation_action_maps_to_provider_action_backend(self):
        request, decision = self._decision("provider-z", stage="ACTION", caps=("filesystem_write", "patch_generation"))
        self.assertEqual(execution_backend_for_route(request, decision), PROVIDER_ACTION_BACKEND)

    def test_manual_action_accepts_only_bound_action_provider_blocked_route(self):
        snapshot = ProviderEligibilitySnapshotV1(
            ELIGIBILITY_SCHEMA_V1, "snap-manual-action", {"nvidia": False},
            {"nvidia": "nvidia/model"}, ("owner-approved-manual-action",),
            provider_capabilities={"nvidia": ("filesystem_write", "patch_generation")},
        )
        request = RouterRequestV2(
            ROUTER_REQUEST_SCHEMA_V2, "req-manual-action", "P", "R", "T", "E", "d"*64,
            "ACTION", ("filesystem_write", "patch_generation"), True,
            GOVERNED_POLICY_V1, snapshot,
        )
        decision = route_request(request)
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.action_state, "ACTION_PROVIDER_BLOCKED")
        self.assertEqual(
            execution_backend_for_manual_action_route(request, decision),
            MANUAL_ACTION_BACKEND,
        )

        eligible_request, eligible_decision = self._decision(
            "provider-y", stage="ACTION",
            caps=("filesystem_write", "patch_generation"), native=True,
        )
        with self.assertRaises(ProviderExecutionRegistryError):
            execution_backend_for_manual_action_route(eligible_request, eligible_decision)

    def test_runner_registry_is_identity_agnostic_and_fail_closed(self):
        runner = lambda **kwargs: {"status": "completed", "model": kwargs.get("model", "")}
        registry = ProviderRunnerRegistry(read_runners={"provider-x": runner}, action_runners={"provider-x": runner})
        self.assertIs(registry.resolve_read("provider-x"), runner)
        self.assertIs(registry.resolve_action("provider-x"), runner)
        self.assertIsNone(registry.resolve_read("unknown"))
        self.assertIsNone(registry.resolve_action("unknown"))

    def test_production_worker_has_no_provider_name_backend_selection(self):
        from runtime.orchestrator import production_worker_executor
        source = inspect.getsource(production_worker_executor.execute_production_worker)
        self.assertNotIn('provider_ref != "codex"', source)
        self.assertNotIn('provider_ref == NVIDIA_PROVIDER', source)
        self.assertNotIn('provider_runner=run_nvidia_reasoning_task', source)


if __name__ == "__main__":
    unittest.main()
