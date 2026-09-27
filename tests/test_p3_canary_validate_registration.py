from __future__ import annotations

import hashlib
import subprocess
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
from runtime.orchestrator.p3_canary_validate_binding import create_p3_canary_validate_binding
from runtime.orchestrator.p3_canary_validate_evidence import issue_p3_canary_validate_evidence
from runtime.orchestrator.p3_canary_validate_registration import (
    P3CanaryValidateRegistrationError,
    register_p3_canary_validate,
)
from runtime.orchestrator.p3_canary_validate_registration_request import (
    P3CanaryValidateRegistrationRequest,
)


class P3CanaryValidateRegistrationTests(unittest.TestCase):
    def _fixture(self, root: Path):
        plan = root / "docs/harness/P3_CANARY_VALIDATE_FULL_PLAN.md"
        spec = root / "docs/harness/P3_CANARY_VALIDATE_SPEC.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("P3 validation plan\n", encoding="utf-8")
        spec.write_text("P3 validation spec\n", encoding="utf-8")
        for args in (
            ("init",),
            ("config", "user.email", "test@example.invalid"),
            ("config", "user.name", "Test"),
            ("add", "docs/harness/P3_CANARY_VALIDATE_FULL_PLAN.md", "docs/harness/P3_CANARY_VALIDATE_SPEC.md"),
            ("commit", "-m", "P3 validation plan"),
            ("branch", "-M", "p3/test"),
        ):
            subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        state = root / "state"
        state.mkdir()
        evidence = issue_p3_canary_validate_evidence(
            state_root=state,
            project_alias="harness-lifecycle-v2-successor-20260925",
            candidate_run_id="P3-TEST-CANDIDATE",
            admission_request_id="P3-TEST-ADMISSION",
            admission_request_digest="a" * 64,
            admission_evidence_digest="b" * 64,
            admission_digest="c" * 64,
            approval_ref="P3_CANARY_VALIDATE",
        ).to_dict()
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        binding = create_p3_canary_validate_binding(
            project_alias=evidence["project_alias"],
            candidate_run_id=evidence["candidate_run_id"],
            admission_request_id=evidence["admission_request_id"],
            admission_request_digest=evidence["admission_request_digest"],
            admission_evidence_digest=evidence["admission_evidence_digest"],
            admission_digest=evidence["admission_digest"],
            expected_branch="p3/test",
            expected_head=head,
            approved_plan_path="docs/harness/P3_CANARY_VALIDATE_FULL_PLAN.md",
            approved_plan_sha256=digest(plan),
            approved_spec_path="docs/harness/P3_CANARY_VALIDATE_SPEC.md",
            approved_spec_sha256=digest(spec),
            approval_ref=evidence["approval_ref"],
            p3_canary_validate_evidence_digest=evidence["evidence_digest"],
        )
        return state, binding, evidence

    def test_registers_only_validation_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state, binding, evidence = self._fixture(root)
            receipt = register_p3_canary_validate(
                state_root=state,
                project_root=root,
                binding=binding,
                evidence=evidence,
            )

            self.assertEqual(receipt.status, "P3_CANARY_VALIDATE_REGISTERED")
            self.assertFalse(receipt.runtime_current_switch_authorized)
            self.assertFalse(receipt.predecessor_shutdown_authorized)
            self.assertFalse(receipt.existing_run_migration_authorized)
            self.assertFalse(receipt.successor_polling_authorized)
            self.assertFalse(receipt.execution_authorized)
            self.assertFalse((state / "_workspace" / "production-full-plan-jobs").exists())
            self.assertEqual(
                receipt,
                register_p3_canary_validate(
                    state_root=state,
                    project_root=root,
                    binding=binding,
                    evidence=evidence,
                ),
            )

    def test_rejects_conflicting_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state, binding, evidence = self._fixture(root)
            register_p3_canary_validate(
                state_root=state,
                project_root=root,
                binding=binding,
                evidence=evidence,
            )
            changed = dict(evidence)
            changed["candidate_run_id"] = "P3-OTHER-CANDIDATE"
            with self.assertRaisesRegex(P3CanaryValidateRegistrationError, "binding rejected"):
                register_p3_canary_validate(
                    state_root=state,
                    project_root=root,
                    binding=binding,
                    evidence=changed,
                )

    def test_runtime_registration_uses_committed_p3_source_without_generic_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = root / "docs/harness/P3_CANARY_VALIDATE_FULL_PLAN.md"
            spec = root / "docs/harness/P3_CANARY_VALIDATE_SPEC.md"
            plan.parent.mkdir(parents=True)
            plan.write_text("P3 validation plan\n", encoding="utf-8")
            spec.write_text("P3 validation spec\n", encoding="utf-8")
            for args in (
                ("init", "-b", "p3/test"),
                ("config", "user.email", "test@example.invalid"),
                ("config", "user.name", "Test"),
                ("add", "docs/harness/P3_CANARY_VALIDATE_FULL_PLAN.md", "docs/harness/P3_CANARY_VALIDATE_SPEC.md"),
                ("commit", "-m", "P3 authority"),
            ):
                subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)
            head = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            admission_request = LifecycleV2P3PromotionAdmissionRequest.from_mapping({
                "schema_version": "orchestration.lifecycle-v2-p3-promotion-admission-request.v1",
                "request_id": "p3-admission-001",
                "project_alias": "harness-lifecycle-v2-successor-20260925",
                "expected_branch": "p3/test",
                "expected_head": head,
                "successor_profile": "lifecycle-v2-p2",
                "current_phase": "P2_SIDE_BY_SIDE",
                "requested_phase": "P3_CANARY",
                "candidate_run_id": "p3-fresh-candidate",
                "candidate_run_origin": "FRESH_ACTIVATION",
                "approval_policy_ref": "P3_CANARY_VALIDATE",
                "approval_policy_digest": "d" * 64,
                "mode": "DRY_RUN",
                "predecessor_serving_required": True,
                "predecessor_quiesce_requested": False,
                "runtime_current_switch_requested": False,
                "existing_run_migration_requested": False,
                "canary_scope": ["p3-fresh-candidate"],
            })
            observed = LifecycleV2P3PromotionAdmissionEvidence.from_mapping({
                "schema_version": "orchestration.lifecycle-v2-p3-promotion-admission-evidence.v1",
                "project_alias": admission_request.project_alias,
                "observed_branch": "p3/test",
                "observed_head": head,
                "observed_successor_profile": "lifecycle-v2-p2",
                "candidate_run_id": admission_request.candidate_run_id,
                "candidate_run_registration_state": "ABSENT",
                "predecessor_serving": True,
                "runtime_current_points_to_predecessor": True,
                "approved_policy_ref": "P3_CANARY_VALIDATE",
                "approved_policy_digest": "d" * 64,
            })
            admission = evaluate_p3_promotion_admission(admission_request, observed)
            state = root / "state"
            state.mkdir()
            evidence = issue_p3_canary_validate_evidence(
                state_root=state,
                project_alias=admission_request.project_alias,
                candidate_run_id=admission_request.candidate_run_id,
                admission_request_id=admission_request.request_id,
                admission_request_digest=admission.request_digest,
                admission_evidence_digest=admission.evidence_digest,
                admission_digest=admission.admission_digest,
                approval_ref="P3_CANARY_VALIDATE",
            )
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            binding = create_p3_canary_validate_binding(
                project_alias=admission_request.project_alias,
                candidate_run_id=admission_request.candidate_run_id,
                admission_request_id=admission_request.request_id,
                admission_request_digest=admission.request_digest,
                admission_evidence_digest=admission.evidence_digest,
                admission_digest=admission.admission_digest,
                expected_branch="p3/test",
                expected_head=head,
                approved_plan_path=plan.relative_to(root).as_posix(),
                approved_plan_sha256=digest(plan),
                approved_spec_path=spec.relative_to(root).as_posix(),
                approved_spec_sha256=digest(spec),
                approval_ref="P3_CANARY_VALIDATE",
                p3_canary_validate_evidence_digest=evidence.evidence_digest,
            )
            request = P3CanaryValidateRegistrationRequest.from_mapping({
                "schema_version": "orchestration.lifecycle-v2-p3-canary-validate-registration-request.v1",
                "request_id": "p3-register-001",
                "admission_request": admission_request.to_dict(),
                "admission_request_digest": admission.request_digest,
                "admission_evidence_digest": admission.evidence_digest,
                "admission_digest": admission.admission_digest,
                "admission_status": admission.status,
                "binding": binding.to_dict(),
                "evidence": evidence.to_dict(),
            })
            config = SimpleNamespace(
                environment={
                    "OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_ENABLED": "1",
                    "OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_POLICY_REF": "P3_CANARY_VALIDATE",
                    "OCP_LIFECYCLE_V2_P3_CANARY_VALIDATE_POLICY_DIGEST": "e" * 64,
                },
                state_root=state,
            )
            service = SimpleNamespace()
            envelope = SimpleNamespace(message_id="p3-register-msg", payload=request)

            with patch.object(runtime, "_collect_p3_promotion_evidence", return_value=observed), patch.object(
                runtime, "_load_p3_waiting_handoff", return_value={"state": "WAITING_FOR_AUTHORIZED_ACTIVATION"}
            ), patch.object(Path, "cwd", return_value=root):
                composed = runtime._wire_p3_canary_validate_registration(config, service)
                projection = composed.register_p3_canary_validate_authorized(envelope)

            self.assertEqual(projection["result_class"], "P3_CANARY_VALIDATE_REGISTERED")
            self.assertFalse(projection["registration"]["execution_authorized"])
            self.assertFalse(projection["registration"]["successor_polling_authorized"])


if __name__ == "__main__":
    unittest.main()
