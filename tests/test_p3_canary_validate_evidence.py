from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.p3_canary_validate_evidence import (
    P3CanaryValidateEvidenceError,
    issue_p3_canary_validate_evidence,
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


if __name__ == "__main__":
    unittest.main()
