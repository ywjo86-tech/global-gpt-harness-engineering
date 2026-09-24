from __future__ import annotations

import unittest

from runtime.orchestrator.external_advisory_activation import (
    ACTIVATION_STATUS_ACTIVE,
    ACTIVATION_STATUS_BLOCKED,
    ACTIVATION_STATUS_QUARANTINED,
    ACTIVATION_STATUS_READY,
    ActivationEvidenceV1,
    activation_decision,
    rollback_to_disabled,
)
from runtime.orchestrator.external_advisory_contract import (
    DESCRIPTOR_SCHEMA_V1,
    ExternalCapabilityDescriptorV1,
)
from runtime.orchestrator.external_advisory_runtime import (
    ExternalAdvisoryRuntimePolicyV1,
    ExternalCapabilityRuntimeEvidenceV1,
)
from runtime.orchestrator.jev_provider_bound_adapter import (
    JEV_CAPABILITY_ID,
    JEV_CAPABILITY_VERSION,
)
from runtime.orchestrator.ruflo_filtering_proxy import (
    RUFLO_CAPABILITY_ID,
    RUFLO_PINNED_VERSION,
)


class ExternalAdvisoryActivationTest(unittest.TestCase):
    def descriptor(
        self,
        capability_id: str,
        *,
        lifecycle: str = "READY_FOR_ACTIVATION",
        digest_char: str = "a",
        version: str | None = None,
    ) -> ExternalCapabilityDescriptorV1:
        is_jev = capability_id == JEV_CAPABILITY_ID
        return ExternalCapabilityDescriptorV1(
            schema_version=DESCRIPTOR_SCHEMA_V1,
            capability_id=capability_id,
            capability_kind="TYPED_JUDGMENT" if is_jev else "READ_ONLY_TOOL",
            authority_class="NONE",
            effect_class="READ_ONLY_EVIDENCE" if is_jev else "READ_ONLY",
            trust_class="EXTERNAL_UNTRUSTED",
            lifecycle_state=lifecycle,
            capability_version=version or (JEV_CAPABILITY_VERSION if is_jev else RUFLO_PINNED_VERSION),
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

    def runtime_evidence(self, descriptor, **overrides) -> ExternalCapabilityRuntimeEvidenceV1:
        is_jev = descriptor.capability_id == JEV_CAPABILITY_ID
        values = {
            "capability_id": descriptor.capability_id,
            "lifecycle_state": descriptor.lifecycle_state,
            "approved_identity_digest": descriptor.package_or_endpoint_digest,
            "qualification_evidence_refs": ("qualification:rji7",),
            "credential_ref": "credential-ref:jev" if is_jev else "",
            "endpoint_qualified": is_jev,
            "privacy_qualified": False,
            "private_data_scope": False,
            "zero_tool_only": not is_jev,
            "tool_qualification_refs": (),
        }
        values.update(overrides)
        return ExternalCapabilityRuntimeEvidenceV1(**values)

    def activation_evidence(self, descriptor, **overrides) -> ActivationEvidenceV1:
        is_jev = descriptor.capability_id == JEV_CAPABILITY_ID
        values = {
            "rji7_receipt_ref": "rji7:f2d80f74",
            "safety_approval_receipt_ref": "user:rji8-approved",
            "ocp_deployment_evidence_ref": "ocp:qualified-runtime",
            "endpoint_account_qualified": is_jev,
            "retention_qualified": is_jev,
            "security_qualified": is_jev,
            "actual_provider_ref": "jev" if is_jev else "",
            "actual_model_ref": "typesafe/system-one" if is_jev else "",
            "expected_provider_ref": "jev" if is_jev else "",
            "expected_model_ref": "typesafe/system-one" if is_jev else "",
            "canary_input_class": "SYNTHETIC_NON_SENSITIVE" if is_jev else "ZERO_TOOL_NOOP",
        }
        values.update(overrides)
        return ActivationEvidenceV1(**values)

    def active_policy(self, capability_id: str, **overrides) -> ExternalAdvisoryRuntimePolicyV1:
        values = {
            "ruflo_enabled": capability_id == RUFLO_CAPABILITY_ID,
            "jev_enabled": capability_id == JEV_CAPABILITY_ID,
            "rji7_pass_receipt": "rji7:f2d80f74",
            "safety_approval_receipt": "user:rji8-approved",
        }
        values.update(overrides)
        return ExternalAdvisoryRuntimePolicyV1(**values)

    def test_missing_rji7_receipt_is_blocked(self) -> None:
        descriptor = self.descriptor(RUFLO_CAPABILITY_ID)
        runtime = self.runtime_evidence(descriptor)
        decision = activation_decision(
            policy=self.active_policy(RUFLO_CAPABILITY_ID, rji7_pass_receipt=""),
            descriptor=descriptor,
            runtime_evidence=runtime,
            activation_evidence=self.activation_evidence(descriptor, rji7_receipt_ref=""),
            target_state="ACTIVE",
        )
        self.assertEqual(decision.status, ACTIVATION_STATUS_BLOCKED)
        self.assertEqual(decision.reason_code, "RJI7_RECEIPT_MISSING")

    def test_missing_safety_approval_is_blocked(self) -> None:
        descriptor = self.descriptor(RUFLO_CAPABILITY_ID)
        decision = activation_decision(
            policy=self.active_policy(RUFLO_CAPABILITY_ID, safety_approval_receipt=""),
            descriptor=descriptor,
            runtime_evidence=self.runtime_evidence(descriptor),
            activation_evidence=self.activation_evidence(
                descriptor, safety_approval_receipt_ref=""
            ),
            target_state="ACTIVE",
        )
        self.assertEqual(decision.status, ACTIVATION_STATUS_BLOCKED)
        self.assertEqual(decision.reason_code, "SAFETY_APPROVAL_MISSING")

    def test_receipt_identity_mismatch_is_quarantined(self) -> None:
        descriptor = self.descriptor(RUFLO_CAPABILITY_ID)
        for overrides in (
            {"rji7_receipt_ref": "rji7:other"},
            {"safety_approval_receipt_ref": "user:other"},
        ):
            with self.subTest(overrides=overrides):
                decision = activation_decision(
                    policy=self.active_policy(RUFLO_CAPABILITY_ID),
                    descriptor=descriptor,
                    runtime_evidence=self.runtime_evidence(descriptor),
                    activation_evidence=self.activation_evidence(descriptor, **overrides),
                    target_state="ACTIVE",
                )
                self.assertEqual(decision.status, ACTIVATION_STATUS_QUARANTINED)
                self.assertEqual(decision.reason_code, "ACTIVATION_RECEIPT_MISMATCH")

    def test_ready_decision_precedes_ocp_deployment(self) -> None:
        descriptor = self.descriptor(RUFLO_CAPABILITY_ID)
        decision = activation_decision(
            policy=self.active_policy(RUFLO_CAPABILITY_ID),
            descriptor=descriptor,
            runtime_evidence=self.runtime_evidence(descriptor),
            activation_evidence=self.activation_evidence(
                descriptor, ocp_deployment_evidence_ref=""
            ),
            target_state="READY",
        )
        self.assertEqual(decision.status, ACTIVATION_STATUS_READY)
        self.assertEqual(decision.reason_code, "QUALIFIED_FOR_OCP_DEPLOYMENT")

    def test_missing_ocp_deployment_evidence_is_blocked_without_rdc_fallback(self) -> None:
        descriptor = self.descriptor(RUFLO_CAPABILITY_ID)
        decision = activation_decision(
            policy=self.active_policy(RUFLO_CAPABILITY_ID),
            descriptor=descriptor,
            runtime_evidence=self.runtime_evidence(descriptor),
            activation_evidence=self.activation_evidence(
                descriptor, ocp_deployment_evidence_ref=""
            ),
            target_state="ACTIVE",
        )
        self.assertEqual(decision.status, ACTIVATION_STATUS_BLOCKED)
        self.assertEqual(decision.reason_code, "BLOCKED_EXTERNAL_RUNTIME_EVIDENCE_MISSING")
        self.assertNotIn("RDC", " ".join(decision.rollback_instructions).upper())

    def test_ruflo_pin_drift_is_quarantined(self) -> None:
        descriptor = self.descriptor(RUFLO_CAPABILITY_ID)
        runtime = self.runtime_evidence(
            descriptor, approved_identity_digest="sha256:" + "f" * 64
        )
        decision = activation_decision(
            policy=self.active_policy(RUFLO_CAPABILITY_ID),
            descriptor=descriptor,
            runtime_evidence=runtime,
            activation_evidence=self.activation_evidence(descriptor),
            target_state="ACTIVE",
        )
        self.assertEqual(decision.status, ACTIVATION_STATUS_QUARANTINED)
        self.assertEqual(decision.reason_code, "RUFLO_PIN_DRIFT")

    def test_ruflo_zero_tool_can_only_activate_as_noop_slice(self) -> None:
        descriptor = self.descriptor(RUFLO_CAPABILITY_ID)
        decision = activation_decision(
            policy=self.active_policy(RUFLO_CAPABILITY_ID),
            descriptor=descriptor,
            runtime_evidence=self.runtime_evidence(
                descriptor, zero_tool_only=True, tool_qualification_refs=()
            ),
            activation_evidence=self.activation_evidence(descriptor),
            target_state="ACTIVE",
        )
        self.assertEqual(decision.status, ACTIVATION_STATUS_ACTIVE)
        self.assertEqual(decision.active_slice, "RUFLO_ZERO_TOOL_NOOP")
        self.assertEqual(decision.usable_tool_ids, ())

    def test_ruflo_nonzero_tool_requires_specific_qualification(self) -> None:
        descriptor = self.descriptor(RUFLO_CAPABILITY_ID)
        decision = activation_decision(
            policy=self.active_policy(RUFLO_CAPABILITY_ID),
            descriptor=descriptor,
            runtime_evidence=self.runtime_evidence(
                descriptor, zero_tool_only=False, tool_qualification_refs=()
            ),
            activation_evidence=self.activation_evidence(
                descriptor, canary_input_class="READ_ONLY_TOOL"
            ),
            target_state="ACTIVE",
        )
        self.assertEqual(decision.status, ACTIVATION_STATUS_BLOCKED)
        self.assertEqual(decision.reason_code, "RUFLO_TOOL_QUALIFICATION_MISSING")

    def test_jev_missing_credential_or_endpoint_account_privacy_evidence_is_blocked(self) -> None:
        descriptor = self.descriptor(JEV_CAPABILITY_ID)
        policy = self.active_policy(JEV_CAPABILITY_ID)
        cases = (
            (
                self.runtime_evidence(descriptor, credential_ref=""),
                self.activation_evidence(descriptor),
            ),
            (
                self.runtime_evidence(descriptor, endpoint_qualified=False),
                self.activation_evidence(descriptor),
            ),
            (
                self.runtime_evidence(
                    descriptor, private_data_scope=True, privacy_qualified=False
                ),
                self.activation_evidence(descriptor),
            ),
            (
                self.runtime_evidence(descriptor),
                self.activation_evidence(descriptor, endpoint_account_qualified=False),
            ),
            (
                self.runtime_evidence(descriptor),
                self.activation_evidence(descriptor, retention_qualified=False),
            ),
            (
                self.runtime_evidence(descriptor),
                self.activation_evidence(descriptor, security_qualified=False),
            ),
        )
        for runtime, activation in cases:
            with self.subTest(runtime=runtime, activation=activation):
                decision = activation_decision(
                    policy=policy,
                    descriptor=descriptor,
                    runtime_evidence=runtime,
                    activation_evidence=activation,
                    target_state="ACTIVE",
                )
                self.assertEqual(decision.status, ACTIVATION_STATUS_BLOCKED)

    def test_jev_private_scope_remains_blocked_before_privacy_qualification(self) -> None:
        descriptor = self.descriptor(JEV_CAPABILITY_ID, lifecycle="CANARY")
        decision = activation_decision(
            policy=ExternalAdvisoryRuntimePolicyV1(jev_enabled=True),
            descriptor=descriptor,
            runtime_evidence=self.runtime_evidence(
                descriptor, private_data_scope=True, privacy_qualified=False
            ),
            activation_evidence=self.activation_evidence(descriptor),
            target_state="CANARY",
        )
        self.assertEqual(decision.status, ACTIVATION_STATUS_BLOCKED)
        self.assertEqual(decision.reason_code, "JEV_PRIVATE_SCOPE_UNQUALIFIED")

    def test_synthetic_jev_canary_requires_exact_provider_model_binding(self) -> None:
        descriptor = self.descriptor(JEV_CAPABILITY_ID, lifecycle="CANARY")
        policy = ExternalAdvisoryRuntimePolicyV1(jev_enabled=True)
        ready = activation_decision(
            policy=policy,
            descriptor=descriptor,
            runtime_evidence=self.runtime_evidence(descriptor),
            activation_evidence=self.activation_evidence(descriptor),
            target_state="CANARY",
        )
        self.assertEqual(ready.status, ACTIVATION_STATUS_ACTIVE)
        self.assertEqual(ready.active_slice, "JEV_SYNTHETIC_NON_SENSITIVE_CANARY")

        mismatch = activation_decision(
            policy=policy,
            descriptor=descriptor,
            runtime_evidence=self.runtime_evidence(descriptor),
            activation_evidence=self.activation_evidence(
                descriptor, actual_model_ref="typesafe/other-model"
            ),
            target_state="CANARY",
        )
        self.assertEqual(mismatch.status, ACTIVATION_STATUS_QUARANTINED)
        self.assertEqual(mismatch.reason_code, "JEV_PROVIDER_MODEL_BINDING_MISMATCH")

    def test_rollback_disables_both_flags_without_stable_core_rollback(self) -> None:
        rollback = rollback_to_disabled()
        self.assertFalse(rollback.policy.ruflo_enabled)
        self.assertFalse(rollback.policy.jev_enabled)
        joined = " ".join(rollback.instructions).lower()
        self.assertNotIn("router rollback", joined)
        self.assertNotIn("mprf rollback", joined)
        self.assertNotIn("full mcp rollback", joined)
        self.assertIn("disable", joined)


if __name__ == "__main__":
    unittest.main()
