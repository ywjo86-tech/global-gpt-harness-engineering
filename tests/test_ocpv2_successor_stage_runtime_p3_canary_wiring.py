from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator import ocpv2_successor_stage_runtime as runtime
from runtime.orchestrator.lifecycle_v2_p3_canary_activation import (
    LifecycleV2P3CanaryActivationRequest,
)
from runtime.orchestrator.lifecycle_v2_p3_promotion_admission import (
    LifecycleV2P3PromotionAdmissionEvidence,
    LifecycleV2P3PromotionAdmissionRequest,
    evaluate_p3_promotion_admission,
)
from runtime.orchestrator.remote_control_envelope import APPROVED_FULL_PLAN_ACTIVATION_KIND


POLICY_REF = "LIFECYCLE-V2-P3-CANARY"
POLICY_DIGEST = "d" * 64
CANDIDATE = "p3-canary-20260926-01"
PROJECT = "harness-lifecycle-v2-successor-20260925"
BRANCH = "p2/harness-lifecycle-v2-successor-20260925"
HEAD = "a" * 40


def _admission_request() -> LifecycleV2P3PromotionAdmissionRequest:
    return LifecycleV2P3PromotionAdmissionRequest.from_mapping(
        {
            "schema_version": "orchestration.lifecycle-v2-p3-promotion-admission-request.v1",
            "request_id": "p3-admission-wiring-001",
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


def _activation_request() -> LifecycleV2P3CanaryActivationRequest:
    admission = _admission_request()
    result = evaluate_p3_promotion_admission(admission, _evidence())
    return LifecycleV2P3CanaryActivationRequest.from_mapping(
        {
            "schema_version": "orchestration.lifecycle-v2-p3-canary-activation-request.v1",
            "request_id": "p3-canary-activation-wiring-001",
            "admission_request": admission.to_dict(),
            "admission_request_digest": admission.request_digest,
            "admission_evidence_digest": result.evidence_digest,
            "admission_digest": result.admission_digest,
            "admission_status": "P3_CANARY_ADMISSION_READY",
            "full_plan_activation": {
                "schema_version": "orchestration.approved-full-plan-activation-request.v1",
                "activation_request_id": CANDIDATE,
                "project_alias": PROJECT,
                "approved_plan": {"path": "APPROVED_PLAN.md", "sha256": "1" * 64},
                "approved_spec": {"path": "APPROVED_SPEC.md", "sha256": "2" * 64},
                "expected_branch": BRANCH,
                "expected_head": HEAD,
                "runtime_release_digest": "3" * 64,
                "approval_ref": "APR-P3-CANARY-001",
                "gate_bindings": [
                    {
                        "gate_id": "GATE-001",
                        "approval_evidence": {"path": "approval.json", "sha256": "4" * 64},
                        "engine_requirement_evidence": None,
                        "project_requirement_evidence_by_lv": [],
                    }
                ],
            },
        }
    )


def _config(**env_changes) -> SimpleNamespace:
    environment = {
        "OCP_LIFECYCLE_V2_P3_CANARY_ACTIVATION_ENABLED": "1",
        "OCP_LIFECYCLE_V2_P3_CANARY_ACTIVATION_POLICY_REF": POLICY_REF,
        "OCP_LIFECYCLE_V2_P3_CANARY_ACTIVATION_POLICY_DIGEST": POLICY_DIGEST,
    }
    environment.update(env_changes)
    return SimpleNamespace(
        environment=environment,
        state_root=Path("/unused/ocp-state"),
        full_plan_activation_enabled=True,
    )


class OCPv2SuccessorStageRuntimeP3CanaryWiringTests(unittest.TestCase):
    def test_p3_canary_activation_defaults_disabled(self):
        service = SimpleNamespace(
            activate_full_plan_authorized=lambda envelope: (_ for _ in ()).throw(
                AssertionError("canonical Full Plan activation must not be called")
            ),
            activate_p3_canary_authorized=None,
            lifecycle_v2_p3_canary_activation_enabled=False,
            lifecycle_v2_p3_canary_activation_policy_ref="",
        )
        composed = runtime._wire_p3_canary_activation(SimpleNamespace(environment={}), service)
        self.assertFalse(composed.lifecycle_v2_p3_canary_activation_enabled)
        self.assertIsNone(composed.activate_p3_canary_authorized)

    def test_enabled_p3_canary_requires_its_own_sealed_policy_digest(self):
        service = SimpleNamespace(activate_full_plan_authorized=lambda envelope: {})
        config = _config(OCP_LIFECYCLE_V2_P3_CANARY_ACTIVATION_POLICY_DIGEST="")
        with self.assertRaisesRegex(
            runtime.SuccessorStageRuntimeError,
            "P3_CANARY_ACTIVATION_POLICY_DIGEST_REQUIRED",
        ):
            runtime._wire_p3_canary_activation(config, service)

    def test_enabled_p3_canary_requires_full_plan_activation_prerequisite(self):
        service = SimpleNamespace(activate_full_plan_authorized=lambda envelope: {})
        config = _config()
        config.full_plan_activation_enabled = False
        with self.assertRaisesRegex(
            runtime.SuccessorStageRuntimeError,
            "P3_CANARY_ACTIVATION_FULL_PLAN_REQUIRED",
        ):
            runtime._wire_p3_canary_activation(config, service)

    def test_activation_policy_must_match_admitted_policy(self):
        service = SimpleNamespace(activate_full_plan_authorized=lambda envelope: {})
        config = _config(OCP_LIFECYCLE_V2_P3_CANARY_ACTIVATION_POLICY_REF="OTHER-POLICY")
        composed = runtime._wire_p3_canary_activation(config, service)
        envelope = SimpleNamespace(
            schema_version="orchestration.remote-control-envelope.v1",
            request_kind="LIFECYCLE_V2_P3_CANARY_ACTIVATION",
            message_id="P3-CANARY-MSG-1",
            sequence=1,
            issued_at="2026-09-26T12:00:00+00:00",
            expires_at="2026-09-26T13:00:00+00:00",
            actor="GPT_OPERATOR",
            transport=SimpleNamespace(
                adapter_id="TEST", channel_id="CTRL", source_actor_id="1", source_message_id="1"
            ),
            payload=_activation_request(),
            payload_digest=_activation_request().request_digest,
            authorization=None,
            envelope_sha256="f" * 64,
        )
        with self.assertRaisesRegex(runtime.SuccessorStageRuntimeError, "P3_CANARY_ACTIVATION_POLICY_MISMATCH"):
            composed.activate_p3_canary_authorized(envelope)

    def test_wiring_rechecks_admission_then_delegates_only_inner_full_plan_activation(self):
        delegated: list[object] = []
        enqueue_projection_flags: list[bool] = []

        def canonical_full_plan(envelope, *, enqueue_projection=True):
            delegated.append(envelope)
            enqueue_projection_flags.append(bool(enqueue_projection))
            self.assertEqual(envelope.request_kind, APPROVED_FULL_PLAN_ACTIVATION_KIND)
            self.assertEqual(envelope.payload.activation_request_id, CANDIDATE)
            return {
                "schema_version": "orchestration.remote-full-plan-activation-projection.v1",
                "message_id": envelope.message_id,
                "activation_request_id": CANDIDATE,
                "activation_profile": "AUTO_RECONCILE_FULL_PLAN",
                "binding_digest": "5" * 64,
                "executable_authority_bundle_digest": "6" * 64,
                "result_status": "FULL_PLAN_REGISTERED",
                "canonical_job_path": "/state/job.json",
                "run_id": CANDIDATE,
                "authority_digest": "7" * 64,
                "activation_digest": "8" * 64,
            }

        service = SimpleNamespace(
            activate_full_plan_authorized=canonical_full_plan,
            activate_p3_canary_authorized=None,
            lifecycle_v2_p3_canary_activation_enabled=False,
            lifecycle_v2_p3_canary_activation_policy_ref="",
        )
        config = _config()
        request = _activation_request()
        envelope = SimpleNamespace(
            schema_version="orchestration.remote-control-envelope.v1",
            request_kind="LIFECYCLE_V2_P3_CANARY_ACTIVATION",
            message_id="P3-CANARY-MSG-2",
            sequence=2,
            issued_at="2026-09-26T12:00:00+00:00",
            expires_at="2026-09-26T13:00:00+00:00",
            actor="GPT_OPERATOR",
            transport=SimpleNamespace(
                adapter_id="TEST", channel_id="CTRL", source_actor_id="1", source_message_id="2"
            ),
            payload=request,
            payload_digest=request.request_digest,
            authorization=None,
            envelope_sha256="f" * 64,
        )
        with patch.object(runtime, "_collect_p3_promotion_evidence", return_value=_evidence()) as collect:
            composed = runtime._wire_p3_canary_activation(config, service)
            projection = composed.activate_p3_canary_authorized(envelope)

        collect.assert_called_once_with(config, request.admission_request)
        self.assertEqual(len(delegated), 1)
        self.assertEqual(enqueue_projection_flags, [False])
        self.assertEqual(projection["result_class"], "P3_CANARY_ACTIVATED")
        self.assertEqual(projection["candidate_run_id"], CANDIDATE)
        self.assertEqual(projection["full_plan_result_status"], "FULL_PLAN_REGISTERED")
        self.assertTrue(projection["authorization"]["candidate_run_registration_authorized"])
        self.assertFalse(projection["authorization"]["runtime_current_switch_authorized"])
        self.assertFalse(projection["authorization"]["existing_run_migration_authorized"])
        self.assertFalse(projection["authorization"]["predecessor_shutdown_authorized"])
        self.assertFalse(projection["authorization"]["generic_mutation_authorized"])


if __name__ == "__main__":
    unittest.main()
