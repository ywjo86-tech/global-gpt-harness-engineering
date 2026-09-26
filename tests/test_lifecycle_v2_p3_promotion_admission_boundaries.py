from __future__ import annotations

import unittest

from runtime.orchestrator.lifecycle_v2_p3_promotion_admission import (
    LifecycleV2P3PromotionAdmissionError,
    LifecycleV2P3PromotionAdmissionRequest,
)
from runtime.orchestrator.remote_operator_service import ControlMode, RemoteOperatorService
from tests.test_lifecycle_v2_p3_promotion_admission import (
    FakeTransport,
    POLICY_DIGEST,
    POLICY_REF,
    _validated_envelope,
)


def _bounded_request(**changes) -> dict:
    value = {
        "schema_version": "orchestration.lifecycle-v2-p3-promotion-admission-request.v1",
        "request_id": "p3-admission-scope-001",
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
    value.update(changes)
    return value


class LifecycleV2P3PromotionAdmissionBoundaryTests(unittest.TestCase):
    def test_exact_single_fresh_candidate_canary_scope_is_accepted(self):
        request = LifecycleV2P3PromotionAdmissionRequest.from_mapping(_bounded_request())
        self.assertEqual(request.canary_scope, ("fresh-canary-run-001",))
        self.assertFalse(request.predecessor_quiesce_requested)

    def test_missing_canary_scope_fails_closed(self):
        raw = _bounded_request()
        raw.pop("canary_scope")
        with self.assertRaisesRegex(LifecycleV2P3PromotionAdmissionError, "canary scope"):
            LifecycleV2P3PromotionAdmissionRequest.from_mapping(raw)

    def test_empty_or_oversized_canary_scope_fails_closed(self):
        bad_scopes = (
            [],
            ["fresh-canary-run-001", "other-run"],
        )
        for canary_scope in bad_scopes:
            with self.subTest(canary_scope=canary_scope):
                with self.assertRaisesRegex(
                    LifecycleV2P3PromotionAdmissionError,
                    "canary scope",
                ):
                    LifecycleV2P3PromotionAdmissionRequest.from_mapping(
                        _bounded_request(canary_scope=canary_scope)
                    )

    def test_canary_scope_must_equal_candidate_run(self):
        with self.assertRaisesRegex(LifecycleV2P3PromotionAdmissionError, "canary scope"):
            LifecycleV2P3PromotionAdmissionRequest.from_mapping(
                _bounded_request(canary_scope=["other-run"])
            )

    def test_predecessor_quiesce_request_fails_closed(self):
        with self.assertRaisesRegex(LifecycleV2P3PromotionAdmissionError, "quiesce"):
            LifecycleV2P3PromotionAdmissionRequest.from_mapping(
                _bounded_request(predecessor_quiesce_requested=True)
            )

    def test_missing_admission_callback_fails_closed_even_when_gate_enabled(self):
        envelope = _validated_envelope(self)
        transport = FakeTransport()
        service = RemoteOperatorService(
            transport=transport,
            decode_envelope=lambda raw: envelope,
            ingress=lambda env: (_ for _ in ()).throw(
                AssertionError("legacy ingress must not handle P3 admission")
            ),
            execute_authorized=lambda env, directive: (_ for _ in ()).throw(
                AssertionError("generic mutation executor must not handle P3 admission")
            ),
            lifecycle_v2_p3_promotion_enabled=True,
            lifecycle_v2_p3_promotion_policy_ref=POLICY_REF,
        )
        result = service.poll_once(mode=ControlMode.CONTROL_READ_ONLY)
        self.assertEqual(result.p3_promotion_admitted, 0)
        self.assertEqual(result.blocked, 1)
        self.assertEqual(
            transport.projections[0]["result_class"],
            "P3_PROMOTION_ADMISSION_DISABLED",
        )


if __name__ == "__main__":
    unittest.main()
