from __future__ import annotations

import unittest

from runtime.orchestrator.provider_router import (
    ELIGIBILITY_SCHEMA_V1, GOVERNED_POLICY_V1, LEGACY_REQUEST_SOURCE_V1,
    ROUTER_REQUEST_SCHEMA_V2, ProviderEligibilitySnapshotV1, ProviderRouterContractError,
    RouterRequestV2, normalize_legacy_hybrid_request, route_provider, route_request,
)


class ProviderRouterTest(unittest.TestCase):
    def test_explicit_codex_cli_routes_to_codex_for_read_only_and_state_changing(self) -> None:
        for capabilities in (["read_only", "reasoning"], ["implementation"], ["test", "git"]):
            with self.subTest(capabilities=capabilities):
                decision = route_provider("codex-cli", capabilities)
                self.assertEqual(decision.provider, "codex")
                self.assertEqual(decision.reason_code, "mode_codex_cli")
                self.assertTrue(decision.eligible)

    def test_manual_and_mock_modes_do_not_auto_route_to_codex(self) -> None:
        manual = route_provider("manual", ["implementation"])
        mock = route_provider("mock", ["implementation"])

        self.assertEqual(manual.provider, "manual")
        self.assertEqual(manual.reason_code, "mode_manual")
        self.assertTrue(manual.eligible)
        self.assertEqual(mock.provider, "local")
        self.assertEqual(mock.reason_code, "mode_mock_local")
        self.assertTrue(mock.eligible)

    def test_hybrid_routes_read_only_to_nvidia(self) -> None:
        decision = route_provider("hybrid", ["reasoning", "read_only"])
        self.assertEqual(decision.provider, "nvidia")
        self.assertEqual(decision.reason_code, "hybrid_read_only_to_nvidia")

    def test_hybrid_routes_state_changing_to_codex(self) -> None:
        for capability in ["filesystem_write", "shell", "test", "git", "implementation", "integration"]:
            with self.subTest(capability=capability):
                decision = route_provider("hybrid", ["reasoning", capability])
                self.assertEqual(decision.provider, "codex")
                self.assertEqual(decision.reason_code, "hybrid_state_changing_to_codex")

    def test_nvidia_rejects_state_changing(self) -> None:
        for capability in ["filesystem_write", "shell", "test", "git", "implementation", "integration"]:
            with self.subTest(capability=capability):
                decision = route_provider("nvidia", ["reasoning", capability])
                self.assertEqual(decision.provider, "manual")
                self.assertFalse(decision.eligible)

    def test_read_only_plus_integration_is_state_changing(self) -> None:
        hybrid = route_provider("hybrid", ["reasoning", "read_only", "integration"])
        nvidia = route_provider("nvidia", ["reasoning", "read_only", "integration"])

        self.assertEqual(hybrid.provider, "codex")
        self.assertEqual(hybrid.reason_code, "hybrid_state_changing_to_codex")
        self.assertEqual(nvidia.provider, "manual")
        self.assertFalse(nvidia.eligible)

    def test_capabilities_are_deduplicated_and_sorted_in_decision(self) -> None:
        decision = route_provider("hybrid", ["test", "read_only", "test", " reasoning ", ""])

        self.assertEqual(decision.provider, "codex")
        self.assertEqual(decision.required_capabilities, ("read_only", "reasoning", "test"))


class ProviderRouterV2Test(unittest.TestCase):
    def _request(self, *, stage="PREPARE", state_change=False, caps=("reasoning", "read_only"), codex=True, nvidia=True):
        snapshot = ProviderEligibilitySnapshotV1(
            schema_version=ELIGIBILITY_SCHEMA_V1, snapshot_id="S1",
            provider_eligible={"nvidia": nvidia, "codex": codex},
            model_refs={"nvidia": "nvidia/model-a", "codex": "openai/model-b"}, evidence_refs=("E1",),
        )
        return RouterRequestV2(
            schema_version=ROUTER_REQUEST_SCHEMA_V2, request_id="REQ1", project_id="P1", run_id="R1",
            task_id="T1", task_execution_id="E1", directive_digest="d" * 64, stage=stage,
            required_capabilities=tuple(caps), state_change_required=state_change,
            policy_profile=GOVERNED_POLICY_V1, eligibility_snapshot=snapshot,
        )

    def test_prepare_selects_nvidia_with_router_bound_model(self):
        decision = route_request(self._request())
        self.assertTrue(decision.eligible)
        self.assertEqual(decision.provider_ref, "nvidia")
        self.assertEqual(decision.model_ref, "nvidia/model-a")
        self.assertEqual(len(decision.decision_digest), 64)

    def test_action_selects_codex_only_when_eligible(self):
        request = self._request(stage="ACTION", state_change=True, caps=("reasoning", "filesystem_write"))
        decision = route_request(request)
        self.assertTrue(decision.eligible)
        self.assertEqual(decision.provider_ref, "codex")
        self.assertEqual(decision.model_ref, "openai/model-b")

    def test_action_unavailable_blocks_without_manual_provider_selection(self):
        request = self._request(stage="ACTION", state_change=True, caps=("filesystem_write",), codex=False)
        decision = route_request(request)
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.provider_ref, "")
        self.assertEqual(decision.model_ref, "")
        self.assertEqual(decision.action_state, "ACTION_PROVIDER_BLOCKED")

    def test_nvidia_failure_never_selects_codex_for_same_read_stage(self):
        request = self._request(stage="PREPARE", nvidia=False, codex=True)
        decision = route_request(request)
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.provider_ref, "")
        self.assertEqual(decision.reason_code, "read_provider_unavailable")


class ProviderRouterV2ContractQualificationTest(unittest.TestCase):
    def _snapshot(self, *, nvidia=True, codex=True):
        return ProviderEligibilitySnapshotV1(
            schema_version=ELIGIBILITY_SCHEMA_V1, snapshot_id="QUAL-S1",
            provider_eligible={"nvidia": nvidia, "codex": codex},
            model_refs={"nvidia": "nvidia/qualified", "codex": "codex/qualified"},
            evidence_refs=("eligibility-evidence",),
        )

    def _request(self, **changes):
        values = dict(
            schema_version=ROUTER_REQUEST_SCHEMA_V2, request_id="QUAL-REQ", project_id="P1", run_id="R1",
            task_id="T1", task_execution_id="E1", directive_digest="d" * 64, stage="PREPARE",
            required_capabilities=("reasoning", "read_only"), state_change_required=False,
            policy_profile=GOVERNED_POLICY_V1, eligibility_snapshot=self._snapshot(),
        )
        values.update(changes)
        return RouterRequestV2(**values)

    def test_snapshot_ref_and_digest_are_bound_and_mismatch_fails_closed(self):
        request = self._request()
        self.assertEqual(request.eligibility_snapshot_ref, request.eligibility_snapshot.snapshot_id)
        self.assertEqual(request.eligibility_snapshot_digest, request.eligibility_snapshot.snapshot_digest)
        tampered = self._request(eligibility_snapshot_digest="0" * 64)
        decision = route_request(tampered)
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.reason_code, "eligibility_snapshot_binding_mismatch")
        self.assertEqual(decision.provider_ref, "")
        self.assertEqual(decision.model_ref, "")

    def test_failure_class_is_closed_and_reroute_stays_fail_closed_pre_mprf(self):
        with self.assertRaises(ProviderRouterContractError):
            self._request(failure_class="NOT_A_FAILURE_CLASS")
        prohibited = route_request(self._request(
            failure_class="POLICY_REJECTION", failover_request_ref="REROUTE-1"
        ))
        self.assertFalse(prohibited.eligible)
        self.assertEqual(prohibited.reason_code, "reroute_failure_class_prohibited")
        eligible_but_not_activated = route_request(self._request(
            failure_class="PROVIDER_FAILURE", failover_request_ref="REROUTE-2"
        ))
        self.assertFalse(eligible_but_not_activated.eligible)
        self.assertEqual(eligible_but_not_activated.reason_code, "reroute_policy_not_activated_pre_mprf")
        self.assertEqual(eligible_but_not_activated.provider_ref, "")

    def test_legacy_hybrid_contract_normalizes_to_v2_without_failure_context(self):
        snapshot = self._snapshot()
        read_request = normalize_legacy_hybrid_request(
            required_capabilities=("reasoning", "read_only"), eligibility_snapshot=snapshot,
            request_id="LEGACY-R", project_id="P1", run_id="R1", task_id="T1",
            task_execution_id="E1", directive_digest="a" * 64,
        )
        self.assertEqual(read_request.request_source, LEGACY_REQUEST_SOURCE_V1)
        self.assertEqual(read_request.stage, "PREPARE")
        self.assertFalse(read_request.state_change_required)
        self.assertEqual(read_request.failure_class, "")
        self.assertEqual(route_request(read_request).provider_ref, "nvidia")

        action_request = normalize_legacy_hybrid_request(
            required_capabilities=("reasoning", "test", "implementation"), eligibility_snapshot=snapshot,
            request_id="LEGACY-A", project_id="P1", run_id="R1", task_id="T2",
            task_execution_id="E2", directive_digest="b" * 64,
        )
        self.assertEqual(action_request.stage, "ACTION")
        self.assertTrue(action_request.state_change_required)
        self.assertEqual(
            action_request.required_capabilities,
            ("implementation_apply", "reasoning", "test_execution"),
        )
        self.assertEqual(route_request(action_request).provider_ref, "codex")

    def test_router_decision_evidence_is_deterministic(self):
        request1 = self._request()
        request2 = self._request()
        decision1 = route_request(request1)
        decision2 = route_request(request2)
        self.assertEqual(request1.request_digest, request2.request_digest)
        self.assertEqual(decision1.decision_digest, decision2.decision_digest)
        self.assertIn("eligibility-evidence", decision1.eligibility_evidence_refs)



if __name__ == "__main__":
    unittest.main()
