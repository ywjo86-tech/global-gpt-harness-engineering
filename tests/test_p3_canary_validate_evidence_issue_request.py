from __future__ import annotations

import unittest

from runtime.orchestrator.p3_canary_validate_evidence_issue_request import P3CanaryValidateEvidenceIssueRequest, P3CanaryValidateEvidenceIssueRequestError


class EvidenceIssueRequestTests(unittest.TestCase):
    def payload(self):
        admission = {"schema_version":"orchestration.lifecycle-v2-p3-promotion-admission-request.v1","request_id":"p3-admission","project_alias":"p3-project","expected_branch":"p3/test","expected_head":"a" * 40,"successor_profile":"lifecycle-v2-p2","current_phase":"P2_SIDE_BY_SIDE","requested_phase":"P3_CANARY","candidate_run_id":"p3-candidate","candidate_run_origin":"FRESH_ACTIVATION","approval_policy_ref":"P3-PROMOTION","approval_policy_digest":"b" * 64,"mode":"DRY_RUN","predecessor_serving_required":True,"predecessor_quiesce_requested":False,"runtime_current_switch_requested":False,"existing_run_migration_requested":False,"canary_scope":["p3-candidate"]}
        from runtime.orchestrator.lifecycle_v2_p3_promotion_admission import LifecycleV2P3PromotionAdmissionRequest
        parsed = LifecycleV2P3PromotionAdmissionRequest.from_mapping(admission)
        return {"schema_version":"orchestration.lifecycle-v2-p3-canary-validate-evidence-issue-request.v1","request_id":"p3-evidence-issue","admission_request":admission,"admission_request_digest":parsed.request_digest,"admission_evidence_digest":"c" * 64,"admission_digest":"d" * 64,"admission_status":"P3_CANARY_ADMISSION_READY","approval_ref":"P3_CANARY_VALIDATE"}

    def test_requires_exact_admission_lineage(self):
        value = self.payload()
        self.assertEqual(P3CanaryValidateEvidenceIssueRequest.from_mapping(value).approval_ref, "P3_CANARY_VALIDATE")
        value["admission_digest"] = "bad"
        with self.assertRaises(P3CanaryValidateEvidenceIssueRequestError):
            P3CanaryValidateEvidenceIssueRequest.from_mapping(value)
