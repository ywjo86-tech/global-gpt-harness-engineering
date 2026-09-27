from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.p3_canary_validate_binding import create_p3_canary_validate_binding
from runtime.orchestrator.p3_canary_validate_evidence import issue_p3_canary_validate_evidence
from runtime.orchestrator.p3_canary_validate_registration import (
    P3CanaryValidateRegistrationError,
    register_p3_canary_validate,
)


class P3CanaryValidateRegistrationTests(unittest.TestCase):
    def _fixture(self, root: Path):
        (root / "plan.md").write_text("P3 validation plan\n", encoding="utf-8")
        (root / "spec.md").write_text("P3 validation spec\n", encoding="utf-8")
        for args in (
            ("init",),
            ("config", "user.email", "test@example.invalid"),
            ("config", "user.name", "Test"),
            ("add", "plan.md", "spec.md"),
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
            approved_plan_path="plan.md",
            approved_plan_sha256=digest(root / "plan.md"),
            approved_spec_path="spec.md",
            approved_spec_sha256=digest(root / "spec.md"),
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


if __name__ == "__main__":
    unittest.main()
