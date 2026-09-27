from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.lifecycle_v2_p3_promotion_admission import LifecycleV2P3PromotionAdmissionRequest
from runtime.orchestrator.p3_canary_validate_binding import create_p3_canary_validate_binding
from runtime.orchestrator.p3_canary_validate_evidence import issue_p3_canary_validate_evidence
from runtime.orchestrator.p3_canary_validate_registration_request import (
    P3CanaryValidateRegistrationRequest,
    P3CanaryValidateRegistrationRequestError,
)


class P3CanaryValidateRegistrationRequestTests(unittest.TestCase):
    def _request(self, root: Path) -> dict:
        (root / "plan.md").write_text("plan\n", encoding="utf-8")
        (root / "spec.md").write_text("spec\n", encoding="utf-8")
        for args in (("init",), ("config", "user.email", "test@example.invalid"), ("config", "user.name", "Test"), ("add", "plan.md", "spec.md"), ("commit", "-m", "P3 validation"), ("branch", "-M", "p3/test")):
            subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        state = root / "state"; state.mkdir()
        admission = LifecycleV2P3PromotionAdmissionRequest.from_mapping({
            "schema_version": "orchestration.lifecycle-v2-p3-promotion-admission-request.v1", "request_id": "p3-admission-001",
            "project_alias": "p3-project", "expected_branch": "p3/test", "expected_head": head,
            "successor_profile": "lifecycle-v2-p2", "current_phase": "P2_SIDE_BY_SIDE", "requested_phase": "P3_CANARY",
            "candidate_run_id": "p3-fresh-candidate", "candidate_run_origin": "FRESH_ACTIVATION", "approval_policy_ref": "P3-CANARY",
            "approval_policy_digest": "a" * 64, "mode": "DRY_RUN", "predecessor_serving_required": True,
            "predecessor_quiesce_requested": False, "runtime_current_switch_requested": False,
            "existing_run_migration_requested": False, "canary_scope": ["p3-fresh-candidate"],
        })
        evidence = issue_p3_canary_validate_evidence(state_root=state, project_alias="p3-project", candidate_run_id="p3-fresh-candidate", admission_request_id="p3-admission-001", admission_request_digest=admission.request_digest, admission_evidence_digest="b" * 64, admission_digest="c" * 64, approval_ref="P3_CANARY_VALIDATE").to_dict()
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        binding = create_p3_canary_validate_binding(project_alias="p3-project", candidate_run_id="p3-fresh-candidate", admission_request_id="p3-admission-001", admission_request_digest=admission.request_digest, admission_evidence_digest="b" * 64, admission_digest="c" * 64, expected_branch="p3/test", expected_head=head, approved_plan_path="plan.md", approved_plan_sha256=digest(root / "plan.md"), approved_spec_path="spec.md", approved_spec_sha256=digest(root / "spec.md"), approval_ref="P3_CANARY_VALIDATE", p3_canary_validate_evidence_digest=evidence["evidence_digest"])
        return {"schema_version": "orchestration.lifecycle-v2-p3-canary-validate-registration-request.v1", "request_id": "p3-validate-001", "admission_request": admission.to_dict(), "admission_request_digest": admission.request_digest, "admission_evidence_digest": "b" * 64, "admission_digest": "c" * 64, "admission_status": "P3_CANARY_ADMISSION_READY", "binding": binding.to_dict(), "evidence": evidence}

    def test_accepts_only_exact_validation_lineage(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self._request(Path(directory))
            sealed = P3CanaryValidateRegistrationRequest.from_mapping(request)
            self.assertEqual(sealed.evidence.scope, "P3_CANARY_VALIDATE")
            self.assertEqual(sealed.binding.candidate_run_id, "p3-fresh-candidate")

    def test_rejects_binding_or_evidence_lineage_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self._request(Path(directory))
            changed = dict(request)
            changed["admission_digest"] = "d" * 64
            with self.assertRaisesRegex(P3CanaryValidateRegistrationRequestError, "lineage mismatch"):
                P3CanaryValidateRegistrationRequest.from_mapping(changed)


if __name__ == "__main__":
    unittest.main()
