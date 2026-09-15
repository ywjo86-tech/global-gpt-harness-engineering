from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from runtime.orchestrator.approval_hash import calculate_record_hash
from runtime.orchestrator.contract_adapter import (
    ContractMappingError,
    evaluate_canonical_state,
    load_project_mapping,
)


class FirstGateActiveCanonicalStateTests(unittest.TestCase):
    @staticmethod
    def _commit(root: Path, message: str) -> str:
        subprocess.run(["git", "-C", str(root), "add", "--", "."], check=True)
        subprocess.run(
            ["git", "-C", str(root), "-c", "user.name=Test User", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", message],
            check=True,
        )
        return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()

    def _fixture(self, base: Path):
        root = base / "family-like"; root.mkdir()
        (root / "docs" / "harness").mkdir(parents=True)
        plan = root / "docs" / "DEVELOPMENT_PLAN.txt"
        plan.write_text("approved family-like plan\n", encoding="utf-8")
        plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
        (root / "docs" / "APPROVAL_LOG.md").write_text("# Approval Log\n", encoding="utf-8")
        (root / "docs" / "GATE_STATE.md").write_text("# Gate State\n\nStatus: FIRST_GATE_WAITING_APPROVAL\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
        baseline = self._commit(root, "baseline")

        gate_id = "GATE-001"
        approval_id = "APR-FIRST-GATE"
        sealed_hash = "a" * 64
        lv_order = ["TASK-001", "TASK-002"]
        owned_files = ["android-app/"]
        event = {
            "approval_id": approval_id, "target_type": "GATE", "target_id": gate_id,
            "approval_type": "START_GATE", "approval_scope": {"lv3_ids": lv_order, "owned_files": owned_files},
            "approval_version": 1, "approval_hash_version": 1, "plan_version": "GENERIC",
            "plan_sha256": plan_sha, "external_action": False, "action_parameters": {},
            "approved_hash": sealed_hash, "approved_by": "USER", "approved_at": "2026-09-15T00:00:00Z",
            "expires_at": "2026-09-16T00:00:00Z", "source_reference": "BOOTSTRAP_GENESIS",
            "approval_event_type": "APPROVED", "previous_approval_id": None, "revokes_approval_id": None,
            "previous_record_hash": None,
        }
        event["record_hash"] = calculate_record_hash(event)
        (root / "docs" / "APPROVAL_LOG.md").write_text(
            "# Approval Log\n\n```json\n" + json.dumps(event, sort_keys=True, indent=2) + "\n```\n", encoding="utf-8"
        )
        ledger = {
            "schema_version": 1, "project_id": root.name, "gate_id": gate_id, "gate_state": "GATE1_ACTIVE",
            "canonical_plan": "docs/DEVELOPMENT_PLAN.txt", "plan_sha256": plan_sha,
            "approval_id": approval_id, "approval_record_hash": event["record_hash"],
            "active_scope": lv_order, "owned_files": owned_files,
        }
        (root / "docs" / "GATE_STATE.md").write_text(
            "# Gate State Ledger\n\nStatus: FIRST_GATE_ACTIVE\n\n```json\n" + json.dumps(ledger, sort_keys=True, indent=2) + "\n```\n",
            encoding="utf-8",
        )
        activation = {
            "schema_version": "orchestration.first-gate.activation.v1", "project_id": root.name,
            "gate_id": gate_id, "plan_sha256": plan_sha, "approval_id": approval_id,
            "approval_record_hash": sealed_hash, "branch": "main", "head": baseline,
            "lv_order": lv_order, "owned_files": owned_files, "state": "ACTIVE", "system_transition": True,
        }
        activation_path = root / "docs" / "harness" / "first-gate.activation.json"
        activation_path.write_text(json.dumps(activation, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        activation_commit = self._commit(root, "activate first gate")

        mapping_dir = base / "mappings"; mapping_dir.mkdir()
        mapping = {
            "project_id": root.name,
            "contract_paths": {"development_plan": "docs/DEVELOPMENT_PLAN.txt"},
            "required_contract_keys": ["development_plan"],
            "canonical_implementation_source": {"path": "docs/DEVELOPMENT_PLAN.txt", "sha256": plan_sha},
            "approved_source_reference": {"path": "docs/DEVELOPMENT_PLAN.txt", "sha256": plan_sha},
            "static_validation": {
                "business_lv_approval": "docs/APPROVAL_LOG.md", "gate_state": "docs/GATE_STATE.md",
                "gate_state_ledger": "docs/GATE_STATE.md",
            },
            "canonical_transition": {"gate_1_approval_id": None, "gate_approval_ids": {}},
        }
        (mapping_dir / f"{root.name}.json").write_text(json.dumps(mapping), encoding="utf-8")
        with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir):
            loaded = load_project_mapping(root)
        return root, mapping_dir, loaded, activation_path, activation, baseline, activation_commit

    def test_first_gate_active_uses_project_root_and_consumes_committed_activation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _, mapping, _, _, baseline, activation_commit = self._fixture(Path(directory))
            state = evaluate_canonical_state(mapping)
            self.assertEqual(state["state"], "GATE1_ACTIVE")
            self.assertTrue(state["transition_authorized"])
            self.assertEqual(state["canonical_plan"], "docs/DEVELOPMENT_PLAN.txt")
            self.assertEqual(state["checkpoint_commit"], baseline)
            self.assertEqual(state["activation_commit"], activation_commit)
            self.assertEqual(state["active_scope"], ["TASK-001", "TASK-002"])
            self.assertEqual(subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout, "")

    def test_uncommitted_activation_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, mapping, activation_path, activation, _, _ = self._fixture(Path(directory))
            activation["approval_id"] = "APR-TAMPERED"
            activation_path.write_text(json.dumps(activation, sort_keys=True, separators=(",", ":")), encoding="utf-8")
            with self.assertRaisesRegex(ContractMappingError, "not committed"):
                evaluate_canonical_state(mapping)

    def test_activation_baseline_must_be_parent_of_activation_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _, mapping, activation_path, activation, _, _ = self._fixture(Path(directory))
            activation["head"] = "b" * 40
            activation_path.write_text(json.dumps(activation, sort_keys=True, separators=(",", ":")), encoding="utf-8")
            self._commit(root, "tampered activation lineage")
            with self.assertRaisesRegex(ContractMappingError, "baseline parent mismatch"):
                evaluate_canonical_state(mapping)


if __name__ == "__main__":
    unittest.main()
