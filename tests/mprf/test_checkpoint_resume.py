from __future__ import annotations

import inspect
import unittest
from dataclasses import replace

import runtime.mprf.checkpoint as checkpoint_module
import runtime.mprf.execution_client as execution_module
from runtime.mprf.checkpoint import RECOVERY_REQUIRED as CHECKPOINT_RECOVERY_REQUIRED, seal_checkpoint, validate_checkpoint
from runtime.mprf.execution_client import (
    EFFECT_AMBIGUOUS, EFFECT_CONFIRMED, RECOVERY_REQUIRED, RESUMED, RECOVERY_STAGES_V1,
    execute_recovery_sequence,
)
from runtime.mprf.failure import FailureClassV1
from runtime.orchestrator.provider_router import ROUTER_DECISION_SCHEMA_V2, RouterDecisionV2


class MPRFCheckpointResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.checkpoint = seal_checkpoint(
            project_id="P", run_id="R", task_id="T", task_execution_id="E", stage="PREPARE",
            provider_runtime_state_version=3, artifact_digest_refs=("artifact://a#1",),
            router_decision_refs=("router://d#1",), effect_reconciliation_refs=("effect://e#1",),
            authorization_ref="auth://a#1", parent_checkpoint_ref="checkpoint://parent#1",
        )
        self.original = RouterDecisionV2(
            ROUTER_DECISION_SCHEMA_V2, "original", "a" * 64, "PREPARE", "nvidia", "n/model",
            "governed_read_stage_to_nvidia", ("read_only", "reasoning"), True,
            ("eligibility://1",), "NVIDIA_PRIMARY_CODEX_SECONDARY_V1", "PREPARE_PENDING",
        )

    def kwargs(self):
        return dict(
            checkpoint=self.checkpoint, project_id="P", run_id="R", task_id="T", task_execution_id="E",
            expected_parent_checkpoint_ref="checkpoint://parent#1", artifact_integrity_ref="artifact-integrity://ok",
            artifact_valid=True, effect_reconciliation_ref="effect-reconcile://confirmed", effect_status=EFFECT_CONFIRMED,
            authorization_validation_ref="auth-validation://ok", authorization_valid=True,
            policy_validation_ref="policy-validation://ok", policy_valid=True,
            failure=FailureClassV1.MODEL_FAILURE, original_router_decision=self.original,
            reroute_request_id="rr-1", router_exchange=self.router_ok, resume_exchange=lambda _: True,
        )

    def router_ok(self, reroute):
        return RouterDecisionV2(
            ROUTER_DECISION_SCHEMA_V2, "rerouted", "b" * 64, reroute.original_stage,
            "nvidia", "n/model-2", "rerouted", reroute.requested_capabilities, True,
            (reroute.router_reference,), "NVIDIA_PRIMARY_CODEX_SECONDARY_V1", "PREPARE_PENDING",
        )

    def test_025_digest_corruption_blocks_and_requires_recovery(self):
        bad = replace(self.checkpoint, integrity_digest="0" * 64)
        result = validate_checkpoint(bad, project_id="P", run_id="R", task_id="T", task_execution_id="E",
                                     expected_parent_checkpoint_ref="checkpoint://parent#1")
        self.assertEqual(result.status, CHECKPOINT_RECOVERY_REQUIRED)
        self.assertEqual(result.reason_code, "CHECKPOINT_INTEGRITY_CORRUPT")

    def test_025_lineage_corruption_blocks_before_any_resume_stage(self):
        calls = []
        args = self.kwargs(); args["expected_parent_checkpoint_ref"] = "checkpoint://wrong#1"
        args["router_exchange"] = lambda value: calls.append("ROUTER")
        args["resume_exchange"] = lambda value: calls.append("RESUME")
        result = execute_recovery_sequence(**args)
        self.assertEqual(result.status, RECOVERY_REQUIRED)
        self.assertEqual(result.blocked_stage, "CHECKPOINT")
        self.assertEqual(calls, [])

    def test_026_exact_valid_order_reaches_external_router_then_resume(self):
        calls = []
        def router(reroute):
            calls.append("ROUTER")
            return self.router_ok(reroute)
        def resume(ref):
            calls.append("RESUME")
            return True
        args = self.kwargs(); args["router_exchange"] = router; args["resume_exchange"] = resume
        result = execute_recovery_sequence(**args)
        self.assertEqual(result.status, RESUMED)
        self.assertEqual(result.completed_stages, RECOVERY_STAGES_V1)
        self.assertEqual(calls, ["ROUTER", "RESUME"])

    def test_026_artifact_failure_stops_before_effect_auth_policy_router(self):
        calls = []
        args = self.kwargs(); args["artifact_valid"] = False; args["router_exchange"] = lambda x: calls.append("ROUTER")
        result = execute_recovery_sequence(**args)
        self.assertEqual(result.blocked_stage, "ARTIFACT")
        self.assertEqual(result.completed_stages, ("CHECKPOINT",))
        self.assertEqual(calls, [])

    def test_026_ambiguous_effect_stops_before_authorization_and_router(self):
        calls = []
        args = self.kwargs(); args["effect_status"] = EFFECT_AMBIGUOUS; args["router_exchange"] = lambda x: calls.append("ROUTER")
        result = execute_recovery_sequence(**args)
        self.assertEqual(result.blocked_stage, "EFFECT_RECONCILIATION")
        self.assertEqual(result.reason_code, "ACTION_SIDE_EFFECT_AMBIGUOUS")
        self.assertEqual(result.completed_stages, ("CHECKPOINT", "ARTIFACT"))
        self.assertEqual(calls, [])

    def test_026_invalid_authorization_stops_before_policy_and_router(self):
        calls = []
        args = self.kwargs(); args["authorization_valid"] = False; args["router_exchange"] = lambda x: calls.append("ROUTER")
        result = execute_recovery_sequence(**args)
        self.assertEqual(result.blocked_stage, "AUTHORIZATION")
        self.assertEqual(result.completed_stages, ("CHECKPOINT", "ARTIFACT", "EFFECT_RECONCILIATION"))
        self.assertEqual(calls, [])

    def test_026_prohibited_failover_stops_before_router(self):
        calls = []
        args = self.kwargs(); args["failure"] = FailureClassV1.POLICY_REJECTION; args["router_exchange"] = lambda x: calls.append("ROUTER")
        result = execute_recovery_sequence(**args)
        self.assertEqual(result.blocked_stage, "FAILOVER_POLICY")
        self.assertEqual(calls, [])

    def test_no_selection_authority_or_full_mcp_truth_duplication(self):
        source = inspect.getsource(execution_module) + inspect.getsource(checkpoint_module)
        self.assertNotIn("route_request(", source)
        for forbidden in ("raw_action_receipt", "effect_journal", "remote_canonical_state"):
            self.assertNotIn(forbidden, source)
        fields = set(self.checkpoint.__dataclass_fields__)
        self.assertTrue({"effect_reconciliation_refs", "artifact_digest_refs", "router_decision_refs"}.issubset(fields))
        self.assertFalse({"provider_ref", "model_ref", "action_receipt", "effect_journal"}.intersection(fields))


if __name__ == "__main__":
    unittest.main()
