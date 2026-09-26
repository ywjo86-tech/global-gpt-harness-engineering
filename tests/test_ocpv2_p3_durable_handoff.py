from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator import ocpv2_successor_stage_runtime as runtime
from runtime.orchestrator.lifecycle_v2_p3_promotion_admission import (
    LifecycleV2P3PromotionAdmissionEvidence,
    LifecycleV2P3PromotionAdmissionRequest,
    evaluate_p3_promotion_admission,
)


POLICY_REF = "LIFECYCLE-V2-P3-CANARY"
POLICY_DIGEST = "d" * 64
PROJECT = "harness-lifecycle-v2-successor-20260925"
BRANCH = "p2/harness-lifecycle-v2-successor-20260925"
HEAD = "a" * 40
CANDIDATE = "p3-canary-handoff-001"


def _request() -> LifecycleV2P3PromotionAdmissionRequest:
    return LifecycleV2P3PromotionAdmissionRequest.from_mapping(
        {
            "schema_version": "orchestration.lifecycle-v2-p3-promotion-admission-request.v1",
            "request_id": "p3-admission-handoff-001",
            "project_alias": PROJECT,
            "expected_branch": BRANCH,
            "expected_head": HEAD,
            "successor_profile": "lifecycle-v2-p2",
            "current_phase": "P2_SIDE_BY_SIDE",
            "requested_phase": "P3_CANARY",
            "candidate_run_id": CANDIDATE,
            "candidate_run_origin": "FRESH_ACTIVATION",
            "approval_policy_ref": POLICY_REF,
            "approval_policy_digest": POLICY_DIGEST,
            "mode": "DRY_RUN",
            "predecessor_serving_required": True,
            "predecessor_quiesce_requested": False,
            "runtime_current_switch_requested": False,
            "existing_run_migration_requested": False,
            "canary_scope": [CANDIDATE],
        }
    )


def _evidence() -> LifecycleV2P3PromotionAdmissionEvidence:
    return LifecycleV2P3PromotionAdmissionEvidence.from_mapping(
        {
            "schema_version": "orchestration.lifecycle-v2-p3-promotion-admission-evidence.v1",
            "project_alias": PROJECT,
            "observed_branch": BRANCH,
            "observed_head": HEAD,
            "observed_successor_profile": "lifecycle-v2-p2",
            "candidate_run_id": CANDIDATE,
            "candidate_run_registration_state": "ABSENT",
            "predecessor_serving": True,
            "runtime_current_points_to_predecessor": True,
            "approved_policy_ref": POLICY_REF,
            "approved_policy_digest": POLICY_DIGEST,
        }
    )


class OCPv2P3DurableHandoffTests(unittest.TestCase):
    def test_admission_ready_seals_waiting_handoff_with_explicit_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "ocp-state"
            config = SimpleNamespace(
                environment={
                    "OCP_LIFECYCLE_V2_P3_PROMOTION_ENABLED": "1",
                    "OCP_LIFECYCLE_V2_P3_PROMOTION_POLICY_REF": POLICY_REF,
                    "OCP_LIFECYCLE_V2_P3_PROMOTION_POLICY_DIGEST": POLICY_DIGEST,
                },
                state_root=state_root,
            )
            service = SimpleNamespace(
                lifecycle_v2_p3_promotion_enabled=False,
                lifecycle_v2_p3_promotion_policy_ref="",
                admit_p3_promotion_authorized=None,
            )
            request = _request()
            evidence = _evidence()
            expected = evaluate_p3_promotion_admission(request, evidence)
            envelope = SimpleNamespace(message_id="P3-HANDOFF-MSG-1", payload=request)

            with patch.object(runtime, "_collect_p3_promotion_evidence", return_value=evidence):
                composed = runtime._wire_p3_promotion(config, service)
                projection = composed.admit_p3_promotion_authorized(envelope)

            self.assertIn("handoff", projection)
            handoff = projection["handoff"]
            self.assertEqual(handoff["state"], "WAITING_FOR_AUTHORIZED_ACTIVATION")
            self.assertEqual(handoff["last_completed_step"], "P3_PROMOTION_ADMISSION")
            self.assertEqual(
                handoff["next_required_request_kind"],
                "LIFECYCLE_V2_P3_CANARY_ACTIVATION",
            )
            self.assertEqual(handoff["candidate_run_id"], CANDIDATE)
            self.assertEqual(handoff["admission_request_digest"], request.request_digest)
            self.assertEqual(handoff["admission_evidence_digest"], evidence.evidence_digest)
            self.assertEqual(handoff["admission_digest"], expected.admission_digest)
            self.assertIs(handoff["authorization_required"], True)

            handoff_path = (
                state_root
                / "p3-lifecycle-handoffs"
                / f"{expected.admission_digest}.waiting.json"
            )
            self.assertTrue(handoff_path.is_file())
            self.assertEqual(
                json.loads(handoff_path.read_text(encoding="utf-8")),
                handoff,
            )


if __name__ == "__main__":
    unittest.main()
