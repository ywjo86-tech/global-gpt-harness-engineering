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


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        environment={
            "OCP_LIFECYCLE_V2_P3_PROMOTION_ENABLED": "1",
            "OCP_LIFECYCLE_V2_P3_PROMOTION_POLICY_REF": POLICY_REF,
            "OCP_LIFECYCLE_V2_P3_PROMOTION_POLICY_DIGEST": POLICY_DIGEST,
        },
        state_root=Path("/unused/ocp-state"),
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
        config = _config()
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

    def test_admission_ready_seals_durable_handoff_for_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _config()
            config.state_root = Path(tmp) / "ocp-state"
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
            self.assertEqual(handoff["candidate_run_id"], request.candidate_run_id)
            self.assertEqual(handoff["admission_request_digest"], request.request_digest)
            self.assertEqual(handoff["admission_evidence_digest"], evidence.evidence_digest)
            self.assertEqual(handoff["admission_digest"], expected.admission_digest)
            self.assertIs(handoff["authorization_required"], True)

            path = (
                config.state_root
                / "p3-lifecycle-handoffs"
                / f"{expected.admission_digest}.waiting.json"
            )
            self.assertTrue(path.is_file())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), handoff)

    def _collect_with_state(self, workspace: Path, harness_state: Path):
        entry = {
            "alias": _request().project_alias,
            "project_root": str(workspace),
            "project_id": "HARNESS-LIFECYCLE-V2-SUCCESSOR-20260925",
        }
        registry = SimpleNamespace(entries=lambda: [entry])
        with patch.object(runtime, "_mapping_root", return_value=workspace), patch.object(
            runtime, "OnboardingRegistry", return_value=registry
        ), patch.object(
            runtime,
            "_readonly_git",
            side_effect=[_request().expected_branch, _request().expected_head],
        ), patch.object(
            runtime, "resolve_harness_state_root", return_value=harness_state
        ), patch.object(
            runtime, "_matching_staged_receipt", return_value={"status": "STAGED"}
        ), patch.object(
            runtime._ReadOnlyPredecessorServiceStateProbe, "serving", return_value=True
        ), patch.object(
            runtime, "_serving_preservation_is_current", return_value=True
        ):
            return runtime._collect_p3_promotion_evidence(_config(), _request())

    def test_missing_harness_state_cannot_be_interpreted_as_absent_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "successor"
            workspace.mkdir()
            missing_state = Path(tmp) / "missing-state"
            with self.assertRaisesRegex(
                runtime.SuccessorStageRuntimeError,
                "P3_PROMOTION_HARNESS_STATE_UNAVAILABLE",
            ):
                self._collect_with_state(workspace, missing_state)

    def test_durable_prev_candidate_receipt_is_not_interpreted_as_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "successor"
            workspace.mkdir()
            harness_state = Path(tmp) / "harness-state"
            candidate = (
                harness_state
                / "_workspace"
                / "production-full-plan-jobs"
                / "HARNESS-LIFECYCLE-V2-SUCCESSOR-20260925"
                / f"{_request().candidate_run_id}.job.json"
            )
            candidate.parent.mkdir(parents=True)
            candidate.with_suffix(candidate.suffix + ".prev").write_text("{}", encoding="utf-8")
            evidence = self._collect_with_state(workspace, harness_state)
            self.assertEqual(evidence.candidate_run_registration_state, "REGISTERED")


if __name__ == "__main__":
    unittest.main()
