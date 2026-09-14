from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from poc.graphify import entry_gate

BASELINE_REF = "958d335c2d85dfbbe4ed5a45bf6d78f14bdc9c37"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _fixture_manifest(root: Path) -> Path:
    completion = root / "evidence" / "completion.md"
    source = root / "evidence" / "source.json"
    approval = root / "evidence" / "approval.json"
    completion.parent.mkdir(parents=True, exist_ok=True)
    completion.write_text("complete\n", encoding="utf-8")
    _write_json(source, {"state": "pass"})
    _write_json(approval, {
        "baseline_id": "FULL_PLAN_STABLE_BASELINE",
        "normalized_decision": "APPROVED",
        "baseline_commit_sha": BASELINE_REF,
        "origin_main_sha": BASELINE_REF,
        "completion_status": "VERIFIED_COMPLETE",
        "blocking_defects_found": 0,
    })
    manifest = root / "manifest.json"
    _write_json(manifest, {
        "baseline_id": "FULL_PLAN_STABLE_BASELINE",
        "baseline_commit_sha": BASELINE_REF,
        "origin_main_sha": BASELINE_REF,
        "synchronized": True,
        "completion_status": "VERIFIED_COMPLETE",
        "final_baseline_approval_status": "APPROVED_SEALED",
        "blocking_defects_found": 0,
        "documents": [{"path": "evidence/completion.md", "sha256": _sha(completion)}],
        "source_evidence": [{"path": "evidence/source.json", "sha256": _sha(source)}],
        "approval_record": {"path": "evidence/approval.json", "sha256": _sha(approval)},
    })
    return manifest


class GraphifyEntryGateTests(unittest.TestCase):
    def test_task_013_verifies_real_predecessor_baseline(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "predecessor_baseline_verification.json"
            record = entry_gate.verify_predecessor_baseline(
                root,
                BASELINE_REF,
                output_path=output,
            )
            self.assertEqual(record["verification_status"], "VERIFIED")
            self.assertTrue(record["predecessor_entry_eligible"])
            self.assertEqual(record["reasons"], [])
            self.assertTrue(output.is_file())

    def test_task_013_missing_evidence_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = _fixture_manifest(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["documents"][0]["path"] = "evidence/missing.md"
            _write_json(manifest, payload)
            with patch.object(entry_gate, "_git_commit_exists", return_value=True):
                record = entry_gate.verify_predecessor_baseline(
                    root, BASELINE_REF, manifest_path="manifest.json"
                )
            self.assertEqual(record["verification_status"], "FAILED")
            self.assertFalse(record["predecessor_entry_eligible"])
            self.assertTrue(any(
                reason.startswith("evidence_missing:") for reason in record["reasons"]
            ))

    def test_task_013_ambiguous_evidence_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = _fixture_manifest(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["source_evidence"].append(dict(payload["documents"][0]))
            _write_json(manifest, payload)
            with patch.object(entry_gate, "_git_commit_exists", return_value=True):
                record = entry_gate.verify_predecessor_baseline(
                    root, BASELINE_REF, manifest_path="manifest.json"
                )
            self.assertEqual(record["verification_status"], "FAILED")
            self.assertFalse(record["predecessor_entry_eligible"])
            self.assertIn("evidence_reference_missing_or_ambiguous", record["reasons"])

    def test_task_013_baseline_ref_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _fixture_manifest(root)
            wrong_ref = "1" * 40
            with patch.object(entry_gate, "_git_commit_exists", return_value=True):
                record = entry_gate.verify_predecessor_baseline(
                    root, wrong_ref, manifest_path="manifest.json"
                )
            self.assertEqual(record["verification_status"], "FAILED")
            self.assertFalse(record["predecessor_entry_eligible"])
            self.assertIn("manifest_baseline_commit_sha_mismatch", record["reasons"])


    def _gate_records(self):
        predecessor = {"verification_status": "VERIFIED", "predecessor_entry_eligible": True, "baseline_ref": BASELINE_REF}
        source = {"current_source_baseline": "REVERIFIED", "test_002_status": "PASS", "unresolved_what_impact_drift": False, "source_drift_detected": False, "baseline_ref": BASELINE_REF}
        version = {
            "qualification_status": "QUALIFIED_PINNED_FOR_INSTALLATION_REQUEST",
            "package_name": "graphifyy", "version": "0.9.58", "exact_requirement": "graphifyy[mcp]==0.9.58",
            "installation_ready_subject_to_gate": True,
            "installer_policy": {"package_installation_performed": False, "automatic_upgrade_allowed": False},
            "transport_policy": {"shared_http_allowed": False, "external_semantic_backend_allowed": False},
        }
        guard = {"guard_status": "CLEAR", "verification_status": "VERIFIED", "entry_eligible": True, "controlled_change_required": False, "baseline_ref": BASELINE_REF}
        approval = {"normalized_decision": "APPROVED", "approval_scope": "GRAPHIFY_PACKAGE_INSTALLATION", "approval_statement_verbatim": "위험 확인 후 승인"}
        return predecessor, source, version, guard, approval

    def test_task_004_opens_only_when_all_prerequisites_pass(self) -> None:
        record = entry_gate.evaluate_poc_entry_gate(*self._gate_records())
        self.assertEqual(record["gate_status"], "OPEN")
        self.assertTrue(record["package_installation_authorized"])
        self.assertEqual(record["next_step"], "TASK-005")

    def test_task_004_wrong_dangerous_phrase_fails_closed(self) -> None:
        records = list(self._gate_records())
        records[4] = dict(records[4], approval_statement_verbatim="승인")
        record = entry_gate.evaluate_poc_entry_gate(*records)
        self.assertEqual(record["gate_status"], "CLOSED")
        self.assertIn("prerequisite_failed:dangerous_install_approval", record["reasons"])

    def test_task_004_each_missing_prerequisite_fails_closed(self) -> None:
        mutations = [(0, "predecessor_entry_eligible", False), (1, "current_source_baseline", "STALE"), (2, "installation_ready_subject_to_gate", False), (3, "guard_status", "CONTROLLED_CHANGE_REQUIRED")]
        for index, key, value in mutations:
            with self.subTest(index=index, key=key):
                records = [json.loads(json.dumps(item)) for item in self._gate_records()]
                records[index][key] = value
                self.assertEqual(entry_gate.evaluate_poc_entry_gate(*records)["gate_status"], "CLOSED")

    def test_task_004_baseline_ref_mismatch_fails_closed(self) -> None:
        records = list(self._gate_records())
        records[1] = dict(records[1], baseline_ref="2" * 40)
        record = entry_gate.evaluate_poc_entry_gate(*records)
        self.assertEqual(record["gate_status"], "CLOSED")
        self.assertIn("prerequisite_failed:baseline_refs_consistent", record["reasons"])


if __name__ == "__main__":
    unittest.main()
