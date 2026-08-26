from __future__ import annotations

import json
import subprocess
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from runtime.orchestrator.approval_hash import calculate_record_hash
from runtime.orchestrator.cli import main
from runtime.orchestrator.contract_adapter import (
    ContractMappingError,
    evaluate_canonical_state,
    load_project_mapping,
    sha256_file,
)


class GateStateLedgerTest(unittest.TestCase):
    approval_id = "APR-GATE1-V1-20260826T015632Z"

    @staticmethod
    def _commit(root: Path, message: str) -> str:
        subprocess.run(["git", "-C", str(root), "add", "--", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", message], check=True)
        return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()

    @staticmethod
    def _event(approval_id: str, target_id: str, plan_hash: str, previous_hash: str | None) -> dict[str, object]:
        event: dict[str, object] = {
            "approval_id": approval_id,
            "target_type": "GATE",
            "target_id": target_id,
            "approval_type": "START_GATE",
            "approval_scope": {"lv3_ids": ["G1-LV3-1"]} if target_id == "GATE-1" else {"lv3_ids": ["G0-LV3-1"]},
            "approval_version": 1,
            "approval_hash_version": 1,
            "plan_version": "V20",
            "plan_sha256": plan_hash,
            "external_action": False,
            "action_parameters": {},
            "approved_hash": "a" * 64,
            "approved_by": "USER_OWNER",
            "approved_at": "2026-08-26T01:56:32Z",
            "expires_at": None,
            "source_reference": "test",
            "approval_event_type": "APPROVED",
            "previous_approval_id": None,
            "revokes_approval_id": None,
            "previous_record_hash": previous_hash,
        }
        if target_id == "GATE-1":
            event["approval_scope"] = {"lv3_ids": ["G1-LV3-1"], "owned_files": ["app/config.py", "tests/test_config.py"]}
        event["record_hash"] = calculate_record_hash(event)
        return event

    def _fixture(self, base: Path, *, transition: bool = True) -> tuple[Path, Path, dict[str, object]]:
        root = base / "wallet"
        mapping_dir = base / "mappings"
        root.mkdir()
        (root / "IMPLEMENTATION_PLAN.md").write_text("implementation plan\n", encoding="utf-8")
        (root / "V20.md").write_text("v20 plan\n", encoding="utf-8")
        (root / "docs").mkdir()
        (root / "docs" / "GATE.md").write_text(
            "Gate closure: `CLOSED`\nG0-LV3-8: `PASS`\nGate 1: 시작하지 않음\n"
            "approval event count: `1`\n",
            encoding="utf-8",
        )
        plan_hash = sha256_file(root / "IMPLEMENTATION_PLAN.md")
        v20_hash = sha256_file(root / "V20.md")
        gate0 = self._event("APR-GATE0", "GATE-0", v20_hash, None)
        (root / "docs" / "APPROVAL.md").write_text(
            "```json\n" + json.dumps(gate0) + "\n```\n", encoding="utf-8"
        )
        (root / "docs" / "GATE.md").write_text(
            "Gate closure: `CLOSED`\nG0-LV3-8: `PASS`\nGate 1: 시작하지 않음\n"
            f"approval event count: `1`\nlast `record_hash`: `{gate0['record_hash']}`\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Test User"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
        self._commit(root, "gate 0 checkpoint")
        gate1 = self._event(self.approval_id, "GATE-1", plan_hash, str(gate0["record_hash"]))
        (root / "docs" / "APPROVAL.md").write_text(
            "\n".join("```json\n" + json.dumps(event) + "\n```" for event in (gate0, gate1)) + "\n",
            encoding="utf-8",
        )
        self._commit(root, "gate 1 approval")
        mapping_dir.mkdir()
        mapping = {
            "project_id": root.name,
            "contract_paths": {"development_plan": "IMPLEMENTATION_PLAN.md"},
            "required_contract_keys": ["development_plan"],
            "canonical_implementation_source": {"path": "IMPLEMENTATION_PLAN.md", "sha256": plan_hash},
            "approved_source_reference": {"path": "V20.md", "sha256": v20_hash},
            "static_validation": {
                "business_lv_approval": "docs/APPROVAL.md",
                "gate_state": "docs/GATE.md",
                "gate_state_ledger": "docs/GATE_STATE.md",
            },
            "canonical_transition": {"gate_1_approval_id": self.approval_id if transition else None},
        }
        (mapping_dir / f"{root.name}.json").write_text(json.dumps(mapping), encoding="utf-8")
        return root, mapping_dir, gate1

    def test_transition_ready_without_ledger(self) -> None:
        with TemporaryDirectory() as directory:
            root, mapping_dir, _ = self._fixture(Path(directory))
            with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir):
                state = evaluate_canonical_state(load_project_mapping(root))
            self.assertEqual(state["state"], "TRANSITION_READY")
            self.assertTrue(state["transition_authorized"])
            self.assertFalse(state["gate_1_started"])

    def test_active_ledger_reports_first_parent_activation(self) -> None:
        with TemporaryDirectory() as directory:
            root, mapping_dir, gate1 = self._fixture(Path(directory))
            ledger = {
                "schema_version": 1,
                "project_id": root.name,
                "gate_id": "GATE-1",
                "gate_state": "GATE1_ACTIVE",
                "canonical_plan": "IMPLEMENTATION_PLAN.md",
                "plan_sha256": sha256_file(root / "IMPLEMENTATION_PLAN.md"),
                "approval_id": self.approval_id,
                "approval_record_hash": gate1["record_hash"],
                "active_scope": ["G1-LV3-1"],
                "owned_files": ["app/config.py", "tests/test_config.py"],
            }
            (root / "docs" / "GATE_STATE.md").write_text(
                "# Gate State Ledger\n\n```json\n" + json.dumps(ledger, indent=2) + "\n```\n", encoding="utf-8"
            )
            activation = self._commit(root, "activate gate 1")
            with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir):
                state = evaluate_canonical_state(load_project_mapping(root))
            self.assertEqual(state["state"], "GATE1_ACTIVE")
            self.assertTrue(state["transition_authorized"])
            self.assertTrue(state["gate_1_started"])
            self.assertEqual(state["activation_commit"], activation)
            self.assertTrue(state["activation_committed_at"])

    def test_active_inspect_reports_separate_business_and_runtime_namespaces(self) -> None:
        with TemporaryDirectory() as directory:
            root, mapping_dir, gate1 = self._fixture(Path(directory))
            (root / "docs" / "GATE_STATE.md").write_text(self._ledger_text(root, gate1["record_hash"]), encoding="utf-8")
            self._commit(root, "activate gate 1")
            output = StringIO()
            with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir), redirect_stdout(output):
                exit_code = main(["inspect", "--read-only", "--project", str(root)])
            report = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(report["contract_mapping"]["canonical_state"], "GATE1_ACTIVE")
            self.assertTrue(report["business_gate_state"]["transition_authorized"])
            self.assertTrue(report["business_gate_state"]["gate_1_started"])
            self.assertFalse(report["codex_runtime_sandbox_approval_state"]["business_approval_reused"])
            self.assertIn("activation_commit", report["business_gate_state"])

    def test_duplicate_and_unknown_ledger_keys_fail_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root, mapping_dir, gate1 = self._fixture(Path(directory))
            payload = self._ledger_text(root, gate1["record_hash"])
            duplicate = payload.replace('"schema_version": 1,', '"schema_version": 1,\n  "schema_version": 1,')
            for invalid in (duplicate, payload.replace('"owned_files":', '"unexpected": 1,\n  "owned_files":')):
                with self.subTest(invalid=invalid):
                    (root / "docs" / "GATE_STATE.md").write_text(invalid, encoding="utf-8")
                    self._commit(root, "invalid ledger")
                    with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir):
                        with self.assertRaises(ContractMappingError):
                            evaluate_canonical_state(load_project_mapping(root))

    def test_scope_and_owned_file_traversal_fail_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root, mapping_dir, gate1 = self._fixture(Path(directory))
            for field, value in (("active_scope", ["../G1-LV3-1"]), ("owned_files", ["../app/config.py", "tests/test_config.py"])):
                with self.subTest(field=field):
                    (root / "docs" / "GATE_STATE.md").write_text(
                        self._ledger_text(root, gate1["record_hash"], **{field: value}), encoding="utf-8"
                    )
                    self._commit(root, f"invalid {field}")
                    with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir):
                        with self.assertRaises(ContractMappingError):
                            evaluate_canonical_state(load_project_mapping(root))

    def test_uncommitted_ledger_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root, mapping_dir, gate1 = self._fixture(Path(directory))
            (root / "docs" / "GATE_STATE.md").write_text(
                self._ledger_text(root, gate1["record_hash"]), encoding="utf-8"
            )
            with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir):
                with self.assertRaisesRegex(ContractMappingError, "not committed"):
                    evaluate_canonical_state(load_project_mapping(root))

    @staticmethod
    def _ledger_text(root: Path, record_hash: object, **overrides: object) -> str:
        payload: dict[str, object] = {
            "schema_version": 1,
            "project_id": root.name,
            "gate_id": "GATE-1",
            "gate_state": "GATE1_ACTIVE",
            "canonical_plan": "IMPLEMENTATION_PLAN.md",
            "plan_sha256": sha256_file(root / "IMPLEMENTATION_PLAN.md"),
            "approval_id": GateStateLedgerTest.approval_id,
            "approval_record_hash": record_hash,
            "active_scope": ["G1-LV3-1"],
            "owned_files": ["app/config.py", "tests/test_config.py"],
        }
        payload.update(overrides)
        return "# Gate State Ledger\n\n```json\n" + json.dumps(payload) + "\n```\n"


if __name__ == "__main__":
    unittest.main()
