from __future__ import annotations

from copy import deepcopy
import unittest

from runtime.orchestrator.external_advisory_contract import (
    DESCRIPTOR_SCHEMA_V1,
    ExternalCapabilityDescriptorV1,
)
from runtime.orchestrator.external_advisory_runtime import (
    ExternalAdvisoryRuntimeError,
    ExternalAdvisoryRuntimePolicyV1,
    ExternalCapabilityRuntimeEvidenceV1,
    assert_activation_ready,
    baseline_path_when_disabled,
    capability_enabled,
)
from runtime.orchestrator.jev_provider_bound_adapter import JEV_CAPABILITY_ID, JEV_CAPABILITY_VERSION
from runtime.orchestrator.ruflo_filtering_proxy import (
    RUFLO_CAPABILITY_ID,
    RUFLO_PINNED_VERSION,
)


class ExternalAdvisoryRuntimePolicyTest(unittest.TestCase):
    def descriptor(self, capability_id: str, *, lifecycle: str, digest_char: str = "a"):
        is_jev = capability_id == JEV_CAPABILITY_ID
        return ExternalCapabilityDescriptorV1(
            schema_version=DESCRIPTOR_SCHEMA_V1,
            capability_id=capability_id,
            capability_kind="TYPED_JUDGMENT" if is_jev else "READ_ONLY_TOOL",
            authority_class="NONE",
            effect_class="READ_ONLY_EVIDENCE" if is_jev else "READ_ONLY",
            trust_class="EXTERNAL_UNTRUSTED",
            lifecycle_state=lifecycle,
            capability_version=JEV_CAPABILITY_VERSION if is_jev else RUFLO_PINNED_VERSION,
            package_or_endpoint_digest="sha256:" + digest_char * 64,
            schema_digest="sha256:" + "b" * 64,
            model_backed=is_jev,
            provider_binding_required=is_jev,
            egress_policy_ref="egress:typesafe-api-only" if is_jev else "egress:deny-all",
            budget_ref="budget:bounded",
            retry_policy="NONE",
            max_delegation_depth=0,
            source_binding_required=True,
        )

    def evidence(self, descriptor, **overrides):
        is_jev = descriptor.capability_id == JEV_CAPABILITY_ID
        values = {
            "capability_id": descriptor.capability_id,
            "lifecycle_state": descriptor.lifecycle_state,
            "approved_identity_digest": descriptor.package_or_endpoint_digest,
            "qualification_evidence_refs": ("qualification:contract-lab",),
            "credential_ref": "credential-ref:jev" if is_jev else "",
            "endpoint_qualified": is_jev,
            "privacy_qualified": False,
            "private_data_scope": False,
            "zero_tool_only": not is_jev,
            "tool_qualification_refs": (),
        }
        values.update(overrides)
        return ExternalCapabilityRuntimeEvidenceV1(**values)

    def test_both_capabilities_are_disabled_by_default(self) -> None:
        policy = ExternalAdvisoryRuntimePolicyV1()
        ruflo = self.descriptor(RUFLO_CAPABILITY_ID, lifecycle="CANARY")
        jev = self.descriptor(JEV_CAPABILITY_ID, lifecycle="CANARY")
        self.assertFalse(capability_enabled(policy, ruflo, self.evidence(ruflo), target_state="CANARY"))
        self.assertFalse(capability_enabled(policy, jev, self.evidence(jev), target_state="CANARY"))

    def test_qualified_or_shadow_lifecycle_cannot_be_active(self) -> None:
        policy = ExternalAdvisoryRuntimePolicyV1(
            ruflo_enabled=True,
            rji7_pass_receipt="rji7:pass",
            safety_approval_receipt="user:rji8-approved",
        )
        for lifecycle in ("QUALIFIED", "SHADOW"):
            with self.subTest(lifecycle=lifecycle):
                descriptor = self.descriptor(RUFLO_CAPABILITY_ID, lifecycle=lifecycle)
                with self.assertRaises(ExternalAdvisoryRuntimeError):
                    assert_activation_ready(
                        policy, descriptor, self.evidence(descriptor), target_state="ACTIVE"
                    )

    def test_canary_requires_explicit_flag_and_qualification_evidence(self) -> None:
        descriptor = self.descriptor(JEV_CAPABILITY_ID, lifecycle="CANARY")
        policy = ExternalAdvisoryRuntimePolicyV1(jev_enabled=True)
        self.assertTrue(capability_enabled(policy, descriptor, self.evidence(descriptor), target_state="CANARY"))
        missing = self.evidence(descriptor, qualification_evidence_refs=())
        self.assertFalse(capability_enabled(policy, descriptor, missing, target_state="CANARY"))
        disabled = ExternalAdvisoryRuntimePolicyV1(jev_enabled=False)
        self.assertFalse(capability_enabled(disabled, descriptor, self.evidence(descriptor), target_state="CANARY"))

    def test_active_requires_ready_state_rji7_safety_approval_pin_and_flag(self) -> None:
        descriptor = self.descriptor(JEV_CAPABILITY_ID, lifecycle="READY_FOR_ACTIVATION")
        evidence = self.evidence(descriptor)
        ready = ExternalAdvisoryRuntimePolicyV1(
            jev_enabled=True,
            rji7_pass_receipt="rji7:pass:commit",
            safety_approval_receipt="user:rji8-approved:2026-09-24",
        )
        self.assertTrue(capability_enabled(ready, descriptor, evidence, target_state="ACTIVE"))

        cases = (
            ExternalAdvisoryRuntimePolicyV1(
                jev_enabled=False, rji7_pass_receipt=ready.rji7_pass_receipt,
                safety_approval_receipt=ready.safety_approval_receipt,
            ),
            ExternalAdvisoryRuntimePolicyV1(
                jev_enabled=True, rji7_pass_receipt="",
                safety_approval_receipt=ready.safety_approval_receipt,
            ),
            ExternalAdvisoryRuntimePolicyV1(
                jev_enabled=True, rji7_pass_receipt=ready.rji7_pass_receipt,
                safety_approval_receipt="",
            ),
        )
        for bad_policy in cases:
            with self.subTest(policy=bad_policy):
                self.assertFalse(capability_enabled(bad_policy, descriptor, evidence, target_state="ACTIVE"))

        drifted = self.evidence(descriptor, approved_identity_digest="sha256:" + "f" * 64)
        self.assertFalse(capability_enabled(ready, descriptor, drifted, target_state="ACTIVE"))

    def test_kill_switch_immediately_disables_without_mutating_router_or_mprf_config(self) -> None:
        policy = ExternalAdvisoryRuntimePolicyV1(
            kill_switch=True,
            jev_enabled=True,
            rji7_pass_receipt="rji7:pass",
            safety_approval_receipt="user:approved",
        )
        descriptor = self.descriptor(JEV_CAPABILITY_ID, lifecycle="READY_FOR_ACTIVATION")
        evidence = self.evidence(descriptor)
        canonical_runtime_config = {
            "router": {"policy": "UNCHANGED"},
            "mprf": {"lifecycle": "UNCHANGED"},
        }
        before = deepcopy(canonical_runtime_config)
        self.assertFalse(capability_enabled(policy, descriptor, evidence, target_state="ACTIVE"))
        self.assertEqual(canonical_runtime_config, before)

    def test_jev_missing_credential_endpoint_or_private_data_qualification_fails_closed(self) -> None:
        descriptor = self.descriptor(JEV_CAPABILITY_ID, lifecycle="CANARY")
        policy = ExternalAdvisoryRuntimePolicyV1(jev_enabled=True)
        cases = (
            self.evidence(descriptor, credential_ref=""),
            self.evidence(descriptor, endpoint_qualified=False),
            self.evidence(
                descriptor,
                private_data_scope=True,
                privacy_qualified=False,
            ),
        )
        for bad_evidence in cases:
            with self.subTest(evidence=bad_evidence):
                self.assertFalse(
                    capability_enabled(policy, descriptor, bad_evidence, target_state="CANARY")
                )

        private_ready = self.evidence(
            descriptor,
            private_data_scope=True,
            privacy_qualified=True,
        )
        self.assertTrue(capability_enabled(policy, descriptor, private_ready, target_state="CANARY"))

    def test_ruflo_tool_surface_requires_tool_specific_qualification(self) -> None:
        descriptor = self.descriptor(RUFLO_CAPABILITY_ID, lifecycle="CANARY")
        policy = ExternalAdvisoryRuntimePolicyV1(ruflo_enabled=True)
        zero_tool = self.evidence(descriptor, zero_tool_only=True, tool_qualification_refs=())
        self.assertTrue(capability_enabled(policy, descriptor, zero_tool, target_state="CANARY"))
        tool_surface_missing = self.evidence(
            descriptor,
            zero_tool_only=False,
            tool_qualification_refs=(),
        )
        self.assertFalse(
            capability_enabled(policy, descriptor, tool_surface_missing, target_state="CANARY")
        )
        tool_surface_ready = self.evidence(
            descriptor,
            zero_tool_only=False,
            tool_qualification_refs=("qualification:ruflo-tool-1",),
        )
        self.assertTrue(
            capability_enabled(policy, descriptor, tool_surface_ready, target_state="CANARY")
        )

    def test_disabling_both_capabilities_returns_exact_preintegration_baseline_object(self) -> None:
        policy = ExternalAdvisoryRuntimePolicyV1()
        baseline = {
            "provider_route": "existing-router-result",
            "tool_path": "existing-single-tool-broker",
        }
        returned = baseline_path_when_disabled(policy, baseline)
        self.assertIs(returned, baseline)
        self.assertEqual(returned, baseline)

    def test_unknown_capability_is_fail_closed(self) -> None:
        descriptor = self.descriptor("external.unknown.v1", lifecycle="CANARY")
        evidence = self.evidence(descriptor)
        policy = ExternalAdvisoryRuntimePolicyV1(ruflo_enabled=True, jev_enabled=True)
        self.assertFalse(capability_enabled(policy, descriptor, evidence, target_state="CANARY"))


if __name__ == "__main__":
    unittest.main()
