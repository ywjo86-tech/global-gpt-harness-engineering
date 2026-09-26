from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator import ocpv2_successor_stage_runtime as runtime
from runtime.orchestrator.lifecycle_v2_p3_promotion_admission import (
    LifecycleV2P3PromotionAdmissionEvidence,
    LifecycleV2P3PromotionAdmissionRequest,
)


POLICY_REF = "LIFECYCLE-V2-P3-CANARY"
POLICY_DIGEST = "d" * 64


def _request() -> LifecycleV2P3PromotionAdmissionRequest:
    return LifecycleV2P3PromotionAdmissionRequest.from_mapping(
        {
            "schema_version": "orchestration.lifecycle-v2-p3-promotion-admission-request.v1",
            "request_id": "p3-runtime-wiring-001",
            "project_alias": "harness-lifecycle-v2-successor-20260925",
            "expected_branch": "p2/harness-lifecycle-v2-successor-20260925",
            "expected_head": "a" * 40,
            "successor_profile": "lifecycle-v2-p2",
            "current_phase": "P2_SIDE_BY_SIDE",
            "requested_phase": "P3_CANARY",
            "candidate_run_id": "fresh-canary-run-001",
            "candidate_run_origin": "FRESH_ACTIVATION",
            "approval_policy_ref": POLICY_REF,
            "approval_policy_digest": POLICY_DIGEST,
            "mode": "DRY_RUN",
            "predecessor_serving_required": True,
            "predecessor_quiesce_requested": False,
            "runtime_current_switch_requested": False,
            "existing_run_migration_requested": False,
            "canary_scope": ["fresh-canary-run-001"],
        }
    )


def _evidence() -> LifecycleV2P3PromotionAdmissionEvidence:
    return LifecycleV2P3PromotionAdmissionEvidence.from_mapping(
        {
            "schema_version": "orchestration.lifecycle-v2-p3-promotion-admission-evidence.v1",
            "project_alias": "harness-lifecycle-v2-successor-20260925",
            "observed_branch": "p2/harness-lifecycle-v2-successor-20260925",
            "observed_head": "a" * 40,
            "observed_successor_profile": "lifecycle-v2-p2",
            "candidate_run_id": "fresh-canary-run-001",
            "candidate_run_registration_state": "ABSENT",
            "predecessor_serving": True,
            "runtime_current_points_to_predecessor": True,
            "approved_policy_ref": POLICY_REF,
            "approved_policy_digest": POLICY_DIGEST,
        }
    )


class OCPv2SuccessorStageRuntimeP3WiringTests(unittest.TestCase):
    def test_p3_gate_defaults_disabled_when_runtime_profile_does_not_enable_it(self):
        service = SimpleNamespace(
            lifecycle_v2_p3_promotion_enabled=False,
            lifecycle_v2_p3_promotion_policy_ref="",
            admit_p3_promotion_authorized=None,
        )
        config = SimpleNamespace(environment={})
        with patch.object(runtime.base, "_compose_service", return_value=service):
            composed = runtime.compose_service(config)
        self.assertFalse(composed.lifecycle_v2_p3_promotion_enabled)
        self.assertIsNone(composed.admit_p3_promotion_authorized)

    def test_enabled_runtime_profile_requires_sealed_policy_digest(self):
        service = SimpleNamespace(
            lifecycle_v2_p3_promotion_enabled=False,
            lifecycle_v2_p3_promotion_policy_ref="",
            admit_p3_promotion_authorized=None,
        )
        config = SimpleNamespace(
            environment={
                "OCP_LIFECYCLE_V2_P3_PROMOTION_ENABLED": "1",
                "OCP_LIFECYCLE_V2_P3_PROMOTION_POLICY_REF": POLICY_REF,
            }
        )
        with patch.object(runtime.base, "_compose_service", return_value=service):
            with self.assertRaisesRegex(runtime.SuccessorStageRuntimeError, "P3_PROMOTION_POLICY_DIGEST_REQUIRED"):
                runtime.compose_service(config)

    def test_enabled_runtime_profile_wires_existing_p3_admission_evaluator(self):
        service = SimpleNamespace(
            lifecycle_v2_p3_promotion_enabled=False,
            lifecycle_v2_p3_promotion_policy_ref="",
            admit_p3_promotion_authorized=None,
        )
        config = SimpleNamespace(
            environment={
                "OCP_LIFECYCLE_V2_P3_PROMOTION_ENABLED": "1",
                "OCP_LIFECYCLE_V2_P3_PROMOTION_POLICY_REF": POLICY_REF,
                "OCP_LIFECYCLE_V2_P3_PROMOTION_POLICY_DIGEST": POLICY_DIGEST,
            }
        )
        envelope = SimpleNamespace(message_id="P3-MSG-1", payload=_request())
        with patch.object(runtime.base, "_compose_service", return_value=service), patch.object(
            runtime, "_collect_p3_promotion_evidence", return_value=_evidence()
        ) as collect:
            composed = runtime.compose_service(config)
            self.assertTrue(composed.lifecycle_v2_p3_promotion_enabled)
            self.assertEqual(composed.lifecycle_v2_p3_promotion_policy_ref, POLICY_REF)
            self.assertTrue(callable(composed.admit_p3_promotion_authorized))
            projection = composed.admit_p3_promotion_authorized(envelope)

        collect.assert_called_once_with(config, envelope.payload)
        self.assertEqual(projection["result_class"], "P3_CANARY_ADMISSION_READY")
        self.assertEqual(projection["request_id"], "p3-runtime-wiring-001")
        self.assertEqual(projection["mode"], "DRY_RUN")
        self.assertFalse(projection["result"]["mutation_authorized"])
        self.assertFalse(projection["result"]["runtime_current_switch_authorized"])
        self.assertFalse(projection["result"]["existing_run_migration_authorized"])
        self.assertFalse(projection["result"]["predecessor_shutdown_authorized"])


if __name__ == "__main__":
    unittest.main()
