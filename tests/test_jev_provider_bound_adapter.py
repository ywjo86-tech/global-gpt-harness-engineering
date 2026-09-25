from __future__ import annotations

from dataclasses import replace
import inspect
import unittest

from runtime.orchestrator.external_advisory_contract import (
    REQUEST_SCHEMA_V1,
    ExternalCapabilityRequestV1,
)
from runtime.orchestrator.provider_execution_registry import ProviderRunnerRegistry
from runtime.orchestrator.provider_router import (
    ELIGIBILITY_SCHEMA_V1,
    GOVERNED_POLICY_V1,
    ROUTER_REQUEST_SCHEMA_V2,
    ProviderEligibilitySnapshotV1,
    RouterRequestV2,
    route_request,
)
from runtime.orchestrator.jev_provider_bound_adapter import (
    JEV_CAPABILITY_ID,
    JEV_CAPABILITY_VERSION,
    JevProviderBoundAdapter,
    JevProviderBoundAdapterError,
    JevRateLimitError,
    JevTransportResponseV1,
    build_jev_read_runner,
    jev_route_ref,
)


class JevProviderBoundAdapterTest(unittest.TestCase):
    def routed(
        self,
        *,
        stage: str = "PREPARE",
        eligible: bool = True,
        provider_id: str = "jev",
        model_ref: str = "typesafe/system-one",
    ):
        caps = (
            ("filesystem_write", "patch_generation")
            if stage == "ACTION"
            else ("read_only", "reasoning")
        )
        snapshot = ProviderEligibilitySnapshotV1(
            schema_version=ELIGIBILITY_SCHEMA_V1,
            snapshot_id=f"snap-{stage.lower()}",
            provider_eligible={provider_id: eligible},
            model_refs={provider_id: model_ref},
            evidence_refs=("evidence:jev-runtime",),
            provider_capabilities={
                provider_id: (
                    "filesystem_write", "patch_generation", "read_only", "reasoning"
                )
            },
        )
        request = RouterRequestV2(
            schema_version=ROUTER_REQUEST_SCHEMA_V2,
            request_id=f"router-{stage.lower()}",
            project_id="PROJECT-1",
            run_id="RUN-1",
            task_id="TASK-1",
            task_execution_id="EXEC-1",
            directive_digest="d" * 64,
            stage=stage,
            required_capabilities=caps,
            state_change_required=stage == "ACTION",
            policy_profile=GOVERNED_POLICY_V1,
            eligibility_snapshot=snapshot,
        )
        return request, route_request(request)

    def capability_request(self, router_request, router_decision, **overrides):
        values = {
            "schema_version": REQUEST_SCHEMA_V1,
            "project_id": router_request.project_id,
            "project_run_id": router_request.run_id,
            "task_id": router_request.task_id,
            "task_execution_id": router_request.task_execution_id,
            "correlation_id": "CORR-1",
            "operation_request_id": "OP-JEV-1",
            "capability_id": JEV_CAPABILITY_ID,
            "capability_version": JEV_CAPABILITY_VERSION,
            "schema_digest": "sha256:" + "a" * 64,
            "input_set_digest": "sha256:" + "b" * 64,
            "source_snapshot_digest": "sha256:" + "c" * 64,
            "capability_admission_ref": "admission:jev-v1",
            "policy_ref": "policy:jev-advisory-only",
            "egress_policy_ref": "egress:typesafe-api-only",
            "budget_ref": "budget:jev-single-attempt",
            "deadline_ms": 2500,
            "attempt": 1,
            "payload_digest": "sha256:" + "e" * 64,
            "provider_decision_ref": router_decision.decision_digest,
            "provider_id": router_decision.provider_ref,
            "model_id": router_decision.model_ref,
            "route_ref": jev_route_ref(router_decision),
        }
        values.update(overrides)
        return ExternalCapabilityRequestV1(**values)

    def response(self, capability_request, **overrides):
        values = {
            "result": {"choice": "ALLOW_REVIEW", "score": 0.91},
            "actual_provider_ref": capability_request.provider_id,
            "actual_model_ref": capability_request.model_id,
            "actual_route_ref": capability_request.route_ref,
            "confidence": 0.91,
            "usage": {"requests": 1},
            "latency_ms": 14,
        }
        values.update(overrides)
        return JevTransportResponseV1(**values)

    def assert_code(self, code: str, callable_):
        with self.assertRaises(JevProviderBoundAdapterError) as caught:
            callable_()
        self.assertEqual(caught.exception.code, code)

    def test_prepare_verify_and_review_use_exact_router_binding_once(self) -> None:
        for stage in ("PREPARE", "VERIFY", "REVIEW"):
            with self.subTest(stage=stage):
                router_request, decision = self.routed(stage=stage)
                capability_request = self.capability_request(router_request, decision)
                calls = []

                def transport(request, timeout_ms):
                    calls.append((request, timeout_ms))
                    return self.response(request)

                result = JevProviderBoundAdapter(transport).execute(
                    router_request,
                    decision,
                    capability_request,
                    evidence_ref=f"evidence:jev:{stage.lower()}",
                )
                self.assertEqual(calls, [(capability_request, capability_request.deadline_ms)])
                self.assertTrue(result.non_authoritative)
                self.assertEqual(result.actual_provider_id, decision.provider_ref)
                self.assertEqual(result.actual_model_id, decision.model_ref)
                self.assertEqual(result.actual_route_ref, capability_request.route_ref)
                self.assertIsNone(result.error)

    def test_action_decision_is_rejected_before_transport(self) -> None:
        router_request, decision = self.routed(stage="ACTION")
        capability_request = self.capability_request(router_request, decision)
        calls = []
        adapter = JevProviderBoundAdapter(lambda request, timeout_ms: calls.append(request))
        self.assert_code(
            "CAPABILITY_SIDE_EFFECT_DENIED",
            lambda: adapter.execute(router_request, decision, capability_request, evidence_ref="evidence:1"),
        )
        self.assertEqual(calls, [])

    def test_ineligible_decision_is_rejected_before_transport(self) -> None:
        router_request, decision = self.routed(eligible=False)
        self.assertFalse(decision.eligible)
        # A blocked Router decision cannot itself populate provider bindings.
        capability_request = ExternalCapabilityRequestV1(
            schema_version=REQUEST_SCHEMA_V1,
            project_id=router_request.project_id,
            project_run_id=router_request.run_id,
            task_id=router_request.task_id,
            task_execution_id=router_request.task_execution_id,
            correlation_id="CORR-1",
            operation_request_id="OP-JEV-BLOCKED",
            capability_id=JEV_CAPABILITY_ID,
            capability_version=JEV_CAPABILITY_VERSION,
            schema_digest="sha256:" + "a" * 64,
            input_set_digest="sha256:" + "b" * 64,
            source_snapshot_digest="sha256:" + "c" * 64,
            capability_admission_ref="admission:jev-v1",
            policy_ref="policy:jev-advisory-only",
            egress_policy_ref="egress:typesafe-api-only",
            budget_ref="budget:jev-single-attempt",
            deadline_ms=2500,
            attempt=1,
            payload_digest="sha256:" + "e" * 64,
        )
        calls = []
        adapter = JevProviderBoundAdapter(lambda request, timeout_ms: calls.append(request))
        self.assert_code(
            "CAPABILITY_PROVIDER_BINDING_MISMATCH",
            lambda: adapter.execute(router_request, decision, capability_request, evidence_ref="evidence:1"),
        )
        self.assertEqual(calls, [])

    def test_router_request_digest_mismatch_is_rejected_before_transport(self) -> None:
        router_request, decision = self.routed()
        bad_decision = replace(decision, request_digest="0" * 64)
        capability_request = self.capability_request(router_request, decision)
        calls = []
        adapter = JevProviderBoundAdapter(lambda request, timeout_ms: calls.append(request))
        self.assert_code(
            "CAPABILITY_PROVIDER_BINDING_MISMATCH",
            lambda: adapter.execute(router_request, bad_decision, capability_request, evidence_ref="evidence:1"),
        )
        self.assertEqual(calls, [])

    def test_capability_provider_model_decision_and_route_bindings_are_exact(self) -> None:
        router_request, decision = self.routed()
        cases = (
            {"provider_decision_ref": "f" * 64},
            {"provider_id": "other-provider"},
            {"model_id": "other/model"},
            {"route_ref": "route:other"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                capability_request = self.capability_request(router_request, decision, **overrides)
                calls = []
                adapter = JevProviderBoundAdapter(lambda request, timeout_ms: calls.append(request))
                self.assert_code(
                    "CAPABILITY_PROVIDER_BINDING_MISMATCH",
                    lambda: adapter.execute(
                        router_request, decision, capability_request, evidence_ref="evidence:1"
                    ),
                )
                self.assertEqual(calls, [])

    def test_transport_identity_mismatch_fails_closed_without_retry(self) -> None:
        router_request, decision = self.routed()
        capability_request = self.capability_request(router_request, decision)
        for field, bad_value in (
            ("actual_provider_ref", "other-provider"),
            ("actual_model_ref", "other/model"),
            ("actual_route_ref", "route:other"),
        ):
            with self.subTest(field=field):
                calls = []

                def transport(request, timeout_ms):
                    calls.append((request, timeout_ms))
                    return self.response(request, **{field: bad_value})

                adapter = JevProviderBoundAdapter(transport)
                self.assert_code(
                    "CAPABILITY_PROVIDER_BINDING_MISMATCH",
                    lambda: adapter.execute(
                        router_request, decision, capability_request, evidence_ref="evidence:mismatch"
                    ),
                )
                self.assertEqual(len(calls), 1)

    def test_timeout_and_rate_limit_are_normalized_without_fallback(self) -> None:
        router_request, decision = self.routed()
        capability_request = self.capability_request(router_request, decision)
        for error, expected_code in (
            (TimeoutError("slow"), "CAPABILITY_TIMEOUT"),
            (JevRateLimitError("limited"), "CAPABILITY_RATE_LIMITED"),
        ):
            with self.subTest(expected_code=expected_code):
                calls = []

                def transport(request, timeout_ms):
                    calls.append((request, timeout_ms))
                    raise error

                result = JevProviderBoundAdapter(transport).execute(
                    router_request,
                    decision,
                    capability_request,
                    evidence_ref=f"evidence:{expected_code.lower()}",
                )
                self.assertEqual(len(calls), 1)
                self.assertTrue(result.non_authoritative)
                self.assertIsNotNone(result.error)
                self.assertEqual(result.error.code, expected_code)
                self.assertFalse(result.error.retryable)

    def test_read_runner_factory_uses_existing_read_registry_seam(self) -> None:
        router_request, decision = self.routed()
        capability_request = self.capability_request(router_request, decision)
        calls = []

        def transport(request, timeout_ms):
            calls.append((request, timeout_ms))
            return self.response(request)

        runner = build_jev_read_runner(transport)
        registry = ProviderRunnerRegistry(read_runners={decision.provider_ref: runner})
        resolved = registry.resolve_read(decision.provider_ref)
        self.assertIs(resolved, runner)
        result = resolved(
            router_request=router_request,
            router_decision=decision,
            capability_request=capability_request,
            evidence_ref="evidence:registry",
        )
        self.assertEqual(len(calls), 1)
        self.assertTrue(result.non_authoritative)

    def test_adapter_source_has_no_routing_action_fallback_or_effect_authority(self) -> None:
        from runtime.orchestrator import jev_provider_bound_adapter

        source = inspect.getsource(jev_provider_bound_adapter)
        forbidden = (
            "route_request(",
            "resolve_action(",
            "model_fallback_refs",
            "ProductionExecutionGateway",
            "production_execution_gateway",
            "operator_control_plane",
            "ocpv2",
            "full_mcp",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
