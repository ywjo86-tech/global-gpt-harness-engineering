from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.p3_canary_validate_evidence import (
    P3CanaryValidateEvidenceError,
    issue_p3_canary_validate_evidence,
)
from runtime.orchestrator.p3_canary_validate_binding import (
    P3CanaryValidateBindingError,
    create_p3_canary_validate_binding,
    validate_p3_canary_validate_binding,
)


class P3CanaryValidateEvidenceTests(unittest.TestCase):
    def _kwargs(self, root: Path) -> dict[str, object]:
        return {
            "state_root": root,
            "project_alias": "harness-lifecycle-v2-successor-20260925",
            "candidate_run_id": "P3-BAB2-FRESH-CANARY-20260927T0316Z",
            "admission_request_id": "P3-BAB2-ADMISSION-20260927T0316Z",
            "admission_request_digest": "a" * 64,
            "admission_evidence_digest": "b" * 64,
            "admission_digest": "c" * 64,
            "approval_ref": "P3_CANARY_VALIDATE",
        }

    def test_issues_exactly_one_stable_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = issue_p3_canary_validate_evidence(**self._kwargs(root))
            second = issue_p3_canary_validate_evidence(**self._kwargs(root))

            self.assertEqual(first, second)
            path = root / "p3-canary-validate-evidence" / ("c" * 64 + ".json")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), first.to_dict())
            self.assertEqual(first.scope, "P3_CANARY_VALIDATE")

    def test_rejects_conflicting_reissue_for_same_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            issue_p3_canary_validate_evidence(**self._kwargs(root))
            changed = self._kwargs(root)
            changed["candidate_run_id"] = "P3-OTHER-CANDIDATE"
            with self.assertRaisesRegex(P3CanaryValidateEvidenceError, "evidence conflict"):
                issue_p3_canary_validate_evidence(**changed)

    def test_rejects_symlinked_state_root(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            real_root = base / "real-state"
            real_root.mkdir()
            linked_root = base / "linked-state"
            linked_root.symlink_to(real_root, target_is_directory=True)
            with self.assertRaisesRegex(P3CanaryValidateEvidenceError, "unsafe state root"):
                issue_p3_canary_validate_evidence(**self._kwargs(linked_root))

    def test_rejects_invalid_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            kwargs = self._kwargs(Path(directory))
            kwargs["admission_digest"] = "not-a-digest"
            with self.assertRaisesRegex(P3CanaryValidateEvidenceError, "invalid admission digest"):
                issue_p3_canary_validate_evidence(**kwargs)

    def test_binding_requires_committed_artifacts_and_exact_evidence_lineage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plan.md").write_text("P3 validation plan\n", encoding="utf-8")
            (root / "spec.md").write_text("P3 validation spec\n", encoding="utf-8")
            import subprocess
            for args in (("init",), ("config", "user.email", "test@example.invalid"), ("config", "user.name", "Test"), ("add", "plan.md", "spec.md"), ("commit", "-m", "P3 plan"), ("branch", "-M", "p3/test")):
                subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)
            head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
            evidence = issue_p3_canary_validate_evidence(**self._kwargs(root)).to_dict()
            sha = lambda path: __import__("hashlib").sha256(path.read_bytes()).hexdigest()
            binding = create_p3_canary_validate_binding(
                project_alias=evidence["project_alias"], candidate_run_id=evidence["candidate_run_id"],
                admission_request_id=evidence["admission_request_id"], admission_request_digest=evidence["admission_request_digest"],
                admission_evidence_digest=evidence["admission_evidence_digest"], admission_digest=evidence["admission_digest"],
                expected_branch="p3/test", expected_head=head, approved_plan_path="plan.md", approved_plan_sha256=sha(root / "plan.md"),
                approved_spec_path="spec.md", approved_spec_sha256=sha(root / "spec.md"), approval_ref=evidence["approval_ref"],
                p3_canary_validate_evidence_digest=evidence["evidence_digest"],
            )
            self.assertEqual(validate_p3_canary_validate_binding(binding=binding, project_root=root, evidence=evidence), binding)
            altered = dict(evidence)
            altered["candidate_run_id"] = "P3-OTHER"
            with self.assertRaises(P3CanaryValidateBindingError):
                validate_p3_canary_validate_binding(binding=binding, project_root=root, evidence=altered)


if __name__ == "__main__":
    unittest.main()
