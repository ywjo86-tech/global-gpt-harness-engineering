from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from runtime.orchestrator.approval_hash import calculate_record_hash
from runtime.orchestrator.contract_adapter import ContractMappingError, load_project_mapping, select_canonical_source
from runtime.orchestrator.cli import main
from runtime.orchestrator.contract_loader import ContractLoadError, load_contract
from runtime.orchestrator.contract_adapter import sha256_file

from tests.helpers import cloned_sample_project


class ContractLoaderTest(unittest.TestCase):
    @staticmethod
    def _mapped_wallet_fixture(
        root: Path,
        mapping_dir: Path,
        *,
        gate_text: str,
        events: list[dict[str, object]],
        implementation_hash: str = "actual",
        transition_approval_id: str | None = None,
    ) -> None:
        root.mkdir()
        (root / "IMPLEMENTATION_PLAN.md").write_text("implementation plan\n", encoding="utf-8")
        (root / "V20.md").write_text("v20 plan\n", encoding="utf-8")
        (root / "docs").mkdir()
        (root / "docs" / "GATE.md").write_text(gate_text, encoding="utf-8")
        approval_blocks = "\n".join(f"```json\n{json.dumps(event)}\n```" for event in events)
        (root / "docs" / "APPROVAL.md").write_text(approval_blocks, encoding="utf-8")
        from runtime.orchestrator.contract_adapter import sha256_file

        actual_implementation_hash = sha256_file(root / "IMPLEMENTATION_PLAN.md")
        actual_v20_hash = sha256_file(root / "V20.md")
        mapping = {
            "project_id": root.name,
            "contract_paths": {"development_plan": "IMPLEMENTATION_PLAN.md"},
            "required_contract_keys": ["development_plan"],
            "canonical_implementation_source": {
                "path": "IMPLEMENTATION_PLAN.md",
                "sha256": implementation_hash if implementation_hash != "actual" else actual_implementation_hash,
            },
            "approved_source_reference": {"path": "V20.md", "sha256": actual_v20_hash},
            "static_validation": {"business_lv_approval": "docs/APPROVAL.md", "gate_state": "docs/GATE.md"},
            "canonical_transition": {"gate_1_approval_id": transition_approval_id},
        }
        mapping_dir.mkdir()
        (mapping_dir / f"{root.name}.json").write_text(json.dumps(mapping), encoding="utf-8")

    def test_loads_required_project_contract_files(self) -> None:
        with cloned_sample_project() as project:
            contract = load_contract(project)
            self.assertEqual(contract.current_phase, "runtime orchestration smoke test")
            self.assertEqual(contract.missing_files, [])
            self.assertIn("Documentation Stabilization", contract.development_plan_text)

    def test_unmapped_project_keeps_legacy_strict_fail_closed_behavior(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaises(ContractLoadError):
                load_contract(directory)

    def test_mapping_rejects_project_path_escape(self) -> None:
        with TemporaryDirectory() as project_dir, TemporaryDirectory() as mapping_dir:
            root = Path(project_dir) / "mapped-project"
            root.mkdir()
            mapping = {
                "project_id": "mapped-project",
                "contract_paths": {"development_plan": "../outside.md"},
                "required_contract_keys": ["development_plan"],
                "canonical_implementation_source": {"path": "../outside.md", "sha256": "0" * 64},
                "approved_source_reference": {"path": "source.md", "sha256": "0" * 64},
                "static_validation": {"business_lv_approval": "approval.md", "gate_state": "gate.md"},
            }
            (Path(mapping_dir) / "mapped-project.json").write_text(json.dumps(mapping), encoding="utf-8")
            with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", Path(mapping_dir)):
                with self.assertRaises(ContractMappingError):
                    load_project_mapping(root)

    def test_mapping_rejects_absolute_project_path(self) -> None:
        with TemporaryDirectory() as project_dir, TemporaryDirectory() as mapping_dir:
            root = Path(project_dir) / "mapped-project"
            root.mkdir()
            mapping = {
                "project_id": "mapped-project",
                "contract_paths": {"development_plan": "/tmp/outside.md"},
                "required_contract_keys": ["development_plan"],
                "canonical_implementation_source": {"path": "/tmp/outside.md", "sha256": "0" * 64},
                "approved_source_reference": {"path": "source.md", "sha256": "0" * 64},
                "static_validation": {"business_lv_approval": "approval.md", "gate_state": "gate.md"},
            }
            (Path(mapping_dir) / "mapped-project.json").write_text(json.dumps(mapping), encoding="utf-8")
            with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", Path(mapping_dir)):
                with self.assertRaises(ContractMappingError):
                    load_project_mapping(root)

    def test_gate_zero_open_selects_v20_canonical_source(self) -> None:
        wallet = Path(__file__).resolve().parents[2] / "wallet-affiliate-collector"
        contract = load_contract(wallet)
        self.assertEqual(Path(contract.paths.development_plan).name, "WALLET_AFFILIATE_IMPLEMENTATION_PLAN_V20.md")
        self.assertEqual(
            contract.contract_mapping["selected_canonical_source"]["path"],
            "WALLET_AFFILIATE_IMPLEMENTATION_PLAN_V20.md",
        )

    def test_missing_checkpoint_keeps_v20_canonical_source(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "mapped-project"
            mapping_dir = base / "mappings"
            self._mapped_wallet_fixture(
                root,
                mapping_dir,
                gate_text="Gate closure: `CLOSED`\nG0-LV3-8: `PASS`\nGate 1: 시작하지 않음\n",
                events=[],
            )
            with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir):
                mapping = load_project_mapping(root)
                self.assertEqual(select_canonical_source(mapping), root / "V20.md")

    def test_complete_checkpoint_and_gate_one_approval_select_implementation_plan(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "mapped-project"
            mapping_dir = base / "mappings"
            head = "a" * 64
            transition = "b" * 64
            gate_text = (
                "Gate closure: `CLOSED`\nG0-LV3-8: `PASS`\n"
                "local checkpoint commit: `" + "c" * 40 + "`\n"
                "approval event count: `1`\nlast `record_hash`: `" + head + "`\n"
            )
            events = [
                {"approval_id": "gate-0", "record_hash": head, "previous_record_hash": None},
                {
                    "approval_id": "gate-1",
                    "record_hash": transition,
                    "previous_record_hash": head,
                    "target_type": "GATE",
                    "approval_type": "START_GATE",
                    "approval_event_type": "APPROVED",
                },
            ]
            self._mapped_wallet_fixture(
                root,
                mapping_dir,
                gate_text=gate_text,
                events=events,
                implementation_hash="actual",
                transition_approval_id="gate-1",
            )
            with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir):
                mapping = load_project_mapping(root)
                events[1]["plan_sha256"] = mapping.canonical_sha256
                approval_blocks = "\n".join(f"```json\n{json.dumps(event)}\n```" for event in events)
                (root / "docs" / "APPROVAL.md").write_text(approval_blocks, encoding="utf-8")
                self.assertEqual(select_canonical_source(mapping), root / "IMPLEMENTATION_PLAN.md")

    def test_conflicting_transition_evidence_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "mapped-project"
            mapping_dir = base / "mappings"
            self._mapped_wallet_fixture(
                root,
                mapping_dir,
                gate_text="Gate closure: `CLOSED`\nG0-LV3-8: `FAIL`\n",
                events=[],
                implementation_hash="actual",
            )
            event: dict[str, object] = {
                "approval_id": "APR-GATE0-1",
                "target_type": "GATE",
                "target_id": "GATE-0-1",
                "approval_type": "START_GATE",
                "approval_scope": {"lv3_ids": ["G0-LV3-8"]},
                "approval_version": 1,
                "approval_hash_version": 1,
                "plan_version": "V20",
                "plan_sha256": sha256_file(root / "V20.md"),
                "external_action": False,
                "action_parameters": {},
                "approved_hash": "a" * 64,
                "approved_by": "USER_OWNER",
                "approved_at": "2026-08-25T00:00:00Z",
                "expires_at": None,
                "source_reference": "test fixture",
                "approval_event_type": "APPROVED",
                "previous_approval_id": None,
                "revokes_approval_id": None,
                "previous_record_hash": None,
            }
            event["record_hash"] = calculate_record_hash(event)
            (root / "docs" / "APPROVAL.md").write_text(
                f"```json\n{json.dumps(event)}\n```\n",
                encoding="utf-8",
            )
            (root / "docs" / "GATE.md").write_text(
                "Gate closure: `CLOSED`\n"
                "G0-LV3-8: `FAIL`\n"
                f"local checkpoint commit: `{'c' * 40}`\n"
                "approval event count: `1`\n"
                f"last `record_hash`: `{event['record_hash']}`\n",
                encoding="utf-8",
            )
            with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir):
                mapping = load_project_mapping(root)
                with self.assertRaisesRegex(ContractMappingError, "Gate 0 transition evidence is conflicting"):
                    select_canonical_source(mapping)
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = main(["inspect", "--read-only", "--project", str(root)])
                self.assertEqual(exit_code, 4)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(payload["error_type"], "contract_mapping_error")
                self.assertIn("Gate 0 transition evidence is conflicting", payload["error"])

    def test_source_hash_mismatch_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "mapped-project"
            mapping_dir = base / "mappings"
            self._mapped_wallet_fixture(
                root,
                mapping_dir,
                gate_text="Gate closure: `OPEN`\nG0-LV3-8: `FAIL`\nGate 1: 시작하지 않음\n",
                events=[],
                implementation_hash="1" * 64,
            )
            with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir):
                mapping = load_project_mapping(root)
                with self.assertRaises(ContractMappingError):
                    select_canonical_source(mapping)


if __name__ == "__main__":
    unittest.main()
