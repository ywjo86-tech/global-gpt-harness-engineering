from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.canonical_transition import CanonicalTransitionError, validate_canonical_gate_state, validate_governance_descendant


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


class CanonicalTransitionTests(unittest.TestCase):
    def project(self, base: Path, name: str = "project") -> tuple[Path, str]:
        root = base / name; root.mkdir(); git(root, "init", "-b", "main")
        git(root, "config", "user.email", "fixture@example.invalid"); git(root, "config", "user.name", "Fixture")
        (root / "app").mkdir(); (root / "app" / "main.py").write_text("x=1\n")
        git(root, "add", "."); git(root, "commit", "-m", "baseline")
        return root, git(root, "rev-parse", "HEAD")

    def test_governance_only_descendant_is_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            root, baseline = self.project(Path(temp)); (root / "docs").mkdir(); (root / "docs" / "gate.md").write_text("closed\n")
            git(root, "add", "."); git(root, "commit", "-m", "governance")
            self.assertTrue(validate_governance_descendant(root, baseline)["governance_only"])

    def test_product_code_descendant_is_stale(self):
        with tempfile.TemporaryDirectory() as temp:
            root, baseline = self.project(Path(temp)); (root / "app" / "main.py").write_text("x=2\n")
            git(root, "add", "."); git(root, "commit", "-m", "product")
            with self.assertRaisesRegex(CanonicalTransitionError, "stale"):
                validate_governance_descendant(root, baseline)

    def test_stale_non_ancestor_head_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _ = self.project(Path(temp))
            with self.assertRaisesRegex(CanonicalTransitionError, "descendant|ancestor"):
                validate_governance_descendant(root, "f" * 40)

    def test_plan_state_mismatch_and_missing_gate_closure_are_blocked(self):
        state = {"schema_version": "orchestration.canonical-gate-state.v2", "project_id": "project", "gate_id": "GATE-1",
                 "phase": "PHASE-1", "plan_sha256": "a"*64, "gate_status": "READY_FOR_TRANSITION",
                 "closure_status": "CLOSED", "approval_record_hash": "b"*64}
        self.assertEqual(validate_canonical_gate_state(state, project_id="project", gate_id="GATE-1", phase="PHASE-1", plan_sha256="a"*64, approval_record_hash="b"*64)["closure_status"], "CLOSED")
        with self.assertRaisesRegex(CanonicalTransitionError, "plan_sha256 mismatch"):
            validate_canonical_gate_state(state, project_id="project", gate_id="GATE-1", phase="PHASE-1", plan_sha256="c"*64, approval_record_hash="b"*64)
        state["closure_status"] = "OPEN"
        with self.assertRaisesRegex(CanonicalTransitionError, "closure"):
            validate_canonical_gate_state(state, project_id="project", gate_id="GATE-1", phase="PHASE-1", plan_sha256="a"*64, approval_record_hash="b"*64)

    def test_preapproval_state_is_explicit_and_has_no_legacy_approval_binding(self):
        state = {"schema_version": "orchestration.canonical-gate-state.v2", "project_id": "project", "gate_id": "GATE-1",
                 "phase": "PHASE-1", "plan_sha256": "a"*64, "gate_status": "READY_FOR_APPROVAL",
                 "closure_status": "PREDECESSOR_CLOSED", "approval_record_hash": None}
        self.assertEqual(validate_canonical_gate_state(state, project_id="project", gate_id="GATE-1", phase="PHASE-1", plan_sha256="a"*64, approval_record_hash=None)["gate_status"], "READY_FOR_APPROVAL")
        state["approval_record_hash"] = "b" * 64
        with self.assertRaisesRegex(CanonicalTransitionError, "pre-approval"):
            validate_canonical_gate_state(state, project_id="project", gate_id="GATE-1", phase="PHASE-1", plan_sha256="a"*64, approval_record_hash="b"*64)


if __name__ == "__main__": unittest.main()
