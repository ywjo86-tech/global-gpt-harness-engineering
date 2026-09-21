from __future__ import annotations
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.provider_router import (
    ELIGIBILITY_SCHEMA_V1, ProviderEligibilitySnapshotV1,
    normalize_legacy_hybrid_request, route_request,
)


class WaitRecoveryTests(unittest.TestCase):
    def api(self):
        from runtime.orchestrator.wait_recovery import (
            classify_wait_recovery, WaitRecoveryError,
            build_provider_wait_recovery_evidence,
            evaluate_provider_wait_recovery,
            evaluate_resource_wait_recovery,
            record_provider_wait_recovery_evidence,
            load_active_provider_wait_recovery_evidence,
        )
        return (classify_wait_recovery, WaitRecoveryError,
                build_provider_wait_recovery_evidence,
                evaluate_provider_wait_recovery,
                evaluate_resource_wait_recovery,
                record_provider_wait_recovery_evidence,
                load_active_provider_wait_recovery_evidence)

    def test_each_wait_reason_has_exact_owner(self):
        classify,*_=self.api()
        expected={"OPERATOR_TASK_RECEIPT_PENDING":"DCC_OR_OPERATOR","CONTINUATION_RECOVERY_PENDING":"DCC_RECONCILER",
                  "LOW_RESOURCE_BACKPRESSURE":"RESOURCE_RECOVERY","RUNTIME_MIGRATION_QUIESCED":"RUNTIME_MIGRATION",
                  "PROVIDER_UNAVAILABLE":"PROVIDER_RECOVERY","PROVIDER_RECOVERY_PENDING":"PROVIDER_RECOVERY"}
        for reason,owner in expected.items():
            state="WAITING_PROVIDER" if reason.startswith("PROVIDER_") else "WAITING_RESOURCE"
            self.assertEqual(classify({"state":state,"wait_reason":reason,"last_error":"detail"}).owner,owner)

    def test_unknown_or_incompatible_wait_fails_closed(self):
        classify,Error,*_=self.api()
        with self.assertRaises(Error): classify({"state":"WAITING_RESOURCE","last_error":"UNKNOWN"})
        with self.assertRaises(Error): classify({"state":"WAITING_PROVIDER","wait_reason":"LOW_RESOURCE_BACKPRESSURE"})
        result=classify({"state":"WAITING_APPROVAL","last_error":"USER_DECISION_REQUIRED"})
        self.assertEqual(result.owner,"USER_DECISION")
        self.assertFalse(result.auto_recoverable)

    @staticmethod
    def snapshots():
        unavailable=ProviderEligibilitySnapshotV1(
            ELIGIBILITY_SCHEMA_V1,"wait-snapshot",{"nvidia":False,"codex":False},
            {"codex":"openai/test-model"},("wait-evidence",),provider_capabilities={
                "codex":("read_only","reasoning","documentation")})
        recovered=ProviderEligibilitySnapshotV1(
            ELIGIBILITY_SCHEMA_V1,"fresh-snapshot",{"nvidia":False,"codex":True},
            {"codex":"openai/test-model"},("fresh-mprf-health",),provider_capabilities={
                "codex":("read_only","reasoning","documentation")})
        return unavailable,recovered

    def test_provider_recovery_reuses_sealed_request_contract(self):
        _,_,build,evaluate,*_=self.api()
        unavailable,recovered=self.snapshots()
        request=normalize_legacy_hybrid_request(
            required_capabilities=("read_only","reasoning"), eligibility_snapshot=unavailable,
            request_id="req",project_id="P",run_id="G-RUN",task_id="LV1",
            task_execution_id="G-RUN-LV1-worker",directive_digest="d"*64)
        blocked=route_request(request); self.assertFalse(blocked.eligible)
        evidence=build(
            project_id="P",gate_run_id="G-RUN",gate_id="G1",lv_id="LV1",
            lv_run_id="G-RUN",project_root="/tmp/project",source_head="1"*40,
            router_request=request.to_dict(),router_decision=blocked.to_dict(),
            output_contract={"purpose":"read"},validation_contract={"tests":["T1"]},
            risk_contract={"state_change_required":False})
        decision=evaluate(evidence,fresh_snapshot=recovered,current_head="1"*40)
        self.assertTrue(decision.resume_allowed)
        self.assertEqual(decision.router_request_sha256,request.request_digest)
        self.assertEqual(decision.router_decision["provider_ref"],"codex")
        self.assertEqual(decision.output_contract_sha256,evidence["output_contract_sha256"])

    def test_provider_recovery_rejects_source_drift(self):
        _,_,build,evaluate,*_=self.api(); unavailable,recovered=self.snapshots()
        request=normalize_legacy_hybrid_request(
            required_capabilities=("read_only",),eligibility_snapshot=unavailable,
            request_id="req",project_id="P",run_id="R",task_id="LV",task_execution_id="R-LV-worker",directive_digest="d"*64)
        evidence=build(project_id="P",gate_run_id="R",gate_id="G",lv_id="LV",lv_run_id="R",
            project_root="/tmp/p",source_head="1"*40,router_request=request.to_dict(),router_decision=route_request(request).to_dict(),
            output_contract={"purpose":"x"},validation_contract={"tests":["T"]},risk_contract={"state_change_required":False})
        decision=evaluate(evidence,fresh_snapshot=recovered,current_head="2"*40)
        self.assertFalse(decision.resume_allowed)
        self.assertEqual(decision.reason,"SOURCE_HEAD_DRIFT")

    def test_resource_recovery_requires_matching_state_sha_and_epoch(self):
        *_,evaluate_resource,_,_=self.api()
        state={"state":"WAITING_RESOURCE","wait_reason":"LOW_RESOURCE_BACKPRESSURE",
               "state_sha256":"a"*64,"epoch":7}
        ok=evaluate_resource(state,resources_ok=True,expected_state_sha256="a"*64,expected_epoch=7)
        self.assertTrue(ok.resume_allowed)
        stale=evaluate_resource(state,resources_ok=True,expected_state_sha256="b"*64,expected_epoch=7)
        self.assertFalse(stale.resume_allowed); self.assertEqual(stale.reason,"STATE_CAS_MISMATCH")

    def test_provider_wait_evidence_round_trip_uses_active_pointer(self):
        *_,record,load=self.api(); unavailable,_=self.snapshots()
        request=normalize_legacy_hybrid_request(
            required_capabilities=("read_only",),eligibility_snapshot=unavailable,
            request_id="req",project_id="P",run_id="GR",task_id="LV",task_execution_id="GR-LV-worker",directive_digest="d"*64)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            evidence=record(root,project_id="P",gate_run_id="GR",gate_id="G",lv_id="LV",lv_run_id="GR",
                project_root="/tmp/project",source_head="1"*40,router_request=request.to_dict(),
                router_decision=route_request(request).to_dict(),output_contract={"purpose":"x"},
                validation_contract={"tests":["T"]},risk_contract={"state_change_required":False})
            loaded=load(root,project_id="P",gate_run_id="GR")
            self.assertEqual(loaded["evidence_sha256"],evidence["evidence_sha256"])
            self.assertEqual(loaded["lv_id"],"LV")

if __name__=="__main__": unittest.main()
