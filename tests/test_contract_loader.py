from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest.mock import patch

from runtime.orchestrator.approval_hash import calculate_record_hash
from runtime.orchestrator.contract_adapter import (
    ContractMappingError,
    evaluate_canonical_state,
    load_project_mapping,
    select_canonical_source,
)
from runtime.orchestrator.cli import main
from runtime.orchestrator.contract_loader import ContractLoadError, load_contract
from runtime.orchestrator.contract_adapter import sha256_file

from tests.helpers import cloned_sample_project


class ContractLoaderTest(unittest.TestCase):
    @staticmethod
    def _event(
        approval_id: str,
        target_id: str,
        plan_hash: str,
        previous_hash: str | None,
        *,
        approval_version: int = 1,
        previous_approval_id: str | None = None,
    ) -> dict[str, object]:
        event: dict[str, object] = {
            "approval_id": approval_id,
            "target_type": "GATE",
            "target_id": target_id,
            "approval_type": "START_GATE",
            "approval_scope": {"lv3_ids": [f"G{approval_version - 1}-LV3-1"]},
            "approval_version": approval_version,
            "approval_hash_version": 1,
            "plan_version": "V20",
            "plan_sha256": plan_hash,
            "external_action": False,
            "action_parameters": {},
            "approved_hash": "a" * 64,
            "approved_by": "USER_OWNER",
            "approved_at": "2026-08-25T00:00:00Z",
            "expires_at": None,
            "source_reference": "test fixture",
            "approval_event_type": "APPROVED",
            "previous_approval_id": previous_approval_id,
            "revokes_approval_id": None,
            "previous_record_hash": previous_hash,
        }
        event["record_hash"] = calculate_record_hash(event)
        return event

    @staticmethod
    def _commit(root: Path, message: str = "checkpoint") -> str:
        if not (root / ".git").is_dir():
            subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Test User"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(root), "add", "--", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", message], check=True)
        return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()

    def _checkpoint_fixture(
        self,
        root: Path,
        mapping_dir: Path,
        *,
        transition_approval_id: str | None = None,
    ) -> tuple[object, dict[str, object]]:
        self._mapped_wallet_fixture(
            root,
            mapping_dir,
            gate_text="Gate closure: `CLOSED`\nG0-LV3-8: `PASS`\n",
            events=[],
            transition_approval_id=transition_approval_id,
        )
        with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir):
            mapping = load_project_mapping(root)
        gate_zero = self._event("gate-0", "GATE-0", mapping.approved_source_sha256, None)
        (root / "docs" / "APPROVAL.md").write_text(
            f"```json\n{json.dumps(gate_zero)}\n```\n", encoding="utf-8"
        )
        (root / "docs" / "GATE.md").write_text(
            "Gate closure: `CLOSED`\nG0-LV3-8: `PASS`\nGate 1: 시작하지 않음\n"
            f"approval event count: `1`\nlast `record_hash`: `{gate_zero['record_hash']}`\n",
            encoding="utf-8",
        )
        self._commit(root)
        return mapping, gate_zero

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

    def test_wallet_gate_one_approval_without_mapping_fails_closed(self) -> None:
        wallet = Path(__file__).resolve().parents[2] / "wallet-affiliate-collector"
        with self.assertRaisesRegex(ContractMappingError, "mapping is not configured"):
            load_contract(wallet)

    def test_closed_gate_without_head_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "mapped-project"
            mapping_dir = base / "mappings"
            self._mapped_wallet_fixture(
                root,
                mapping_dir,
                gate_text="Gate closure: `CLOSED`\nG0-LV3-8: `PASS`\nGate 1: 시작하지 않음\n",
                events=[self._event("gate-0", "GATE-0", sha256_file(root / "V20.md") if root.exists() else "0" * 64, None)],
            )
            with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir):
                mapping = load_project_mapping(root)
                event = self._event("gate-0", "GATE-0", mapping.approved_source_sha256, None)
                (root / "docs" / "APPROVAL.md").write_text(
                    f"```json\n{json.dumps(event)}\n```\n", encoding="utf-8"
                )
                (root / "docs" / "GATE.md").write_text(
                    "Gate closure: `CLOSED`\nG0-LV3-8: `PASS`\n"
                    f"approval event count: `1`\nlast `record_hash`: `{event['record_hash']}`\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ContractMappingError, "CHECKPOINT_DECLARED_BUT_UNCOMMITTED.*Git HEAD does not exist"):
                    select_canonical_source(mapping)

    def test_complete_checkpoint_and_gate_one_approval_select_implementation_plan(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "mapped-project"
            mapping_dir = base / "mappings"
            head = "a" * 64
            gate_text = (
                "Gate closure: `CLOSED`\nG0-LV3-8: `PASS`\n"
                "approval event count: `1`\nlast `record_hash`: `" + head + "`\n"
            )
            events: list[dict[str, object]] = []
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
                gate_zero = self._event("gate-0", "GATE-0", mapping.approved_source_sha256, None)
                head = str(gate_zero["record_hash"])
                (root / "docs" / "GATE.md").write_text(
                    "Gate closure: `CLOSED`\nG0-LV3-8: `PASS`\n"
                    f"approval event count: `1`\nlast `record_hash`: `{head}`\n",
                    encoding="utf-8",
                )
                (root / "docs" / "APPROVAL.md").write_text(
                    f"```json\n{json.dumps(gate_zero)}\n```\n", encoding="utf-8"
                )
                self._commit(root)
                checkpoint_commit = subprocess.check_output(
                    ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
                ).strip()
                gate_one = self._event(
                    "gate-1", "GATE-1", mapping.canonical_sha256, head
                )
                approval_blocks = "\n".join(
                    f"```json\n{json.dumps(event)}\n```" for event in [gate_zero, gate_one]
                )
                (root / "docs" / "APPROVAL.md").write_text(approval_blocks, encoding="utf-8")
                self._commit(root, "gate one approval")
                state = evaluate_canonical_state(mapping)
                self.assertEqual(state["selected_source"], root / "IMPLEMENTATION_PLAN.md")
                self.assertEqual(state["checkpoint_commit"], checkpoint_commit)

    def test_complete_checkpoint_without_gate_one_approval_keeps_v20(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "mapped-project"
            mapping, _ = self._checkpoint_fixture(root, base / "mappings")
            state = evaluate_canonical_state(mapping)
            self.assertEqual(state["state"], "GATE0_CLOSED_WAITING_GATE1_APPROVAL")
            self.assertEqual(state["selected_source"], root / "V20.md")
            self.assertEqual(state["checkpoint_commit"], subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
            ).strip())

    def test_checkpoint_followed_by_unrelated_commit_keeps_v20(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "mapped-project"
            mapping, _ = self._checkpoint_fixture(root, base / "mappings")
            checkpoint_commit = subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
            ).strip()
            (root / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")
            self._commit(root, "unrelated")
            state = evaluate_canonical_state(mapping)
            self.assertEqual(state["state"], "GATE0_CLOSED_WAITING_GATE1_APPROVAL")
            self.assertEqual(state["selected_source"], root / "V20.md")
            self.assertEqual(state["checkpoint_commit"], checkpoint_commit)

    def test_uncommitted_gate_one_approval_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "mapped-project"
            mapping, gate_zero = self._checkpoint_fixture(
                root, base / "mappings", transition_approval_id="gate-1"
            )
            gate_one = self._event(
                "gate-1",
                "GATE-1",
                mapping.canonical_sha256,
                str(gate_zero["record_hash"]),
            )
            (root / "docs" / "APPROVAL.md").write_text(
                "\n".join(
                    f"```json\n{json.dumps(event)}\n```" for event in [gate_zero, gate_one]
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ContractMappingError, "working approval log differs"):
                select_canonical_source(mapping)

    def test_working_only_closed_gate_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "mapped-project"
            mapping, _ = self._checkpoint_fixture(root, base / "mappings")
            (root / "docs" / "GATE.md").write_text(
                (root / "docs" / "GATE.md").read_text(encoding="utf-8") + "working-only change\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ContractMappingError, "CHECKPOINT_DECLARED_BUT_UNCOMMITTED.*differs from the committed HEAD snapshot"):
                select_canonical_source(mapping)

    def test_committed_checkpoint_count_head_mismatch_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "mapped-project"
            mapping, _ = self._checkpoint_fixture(root, base / "mappings")
            gate = (root / "docs" / "GATE.md").read_text(encoding="utf-8").replace(
                "approval event count: `1`", "approval event count: `2`"
            )
            (root / "docs" / "GATE.md").write_text(gate, encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "--", "docs/GATE.md"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "bad metadata"], check=True)
            with self.assertRaisesRegex(ContractMappingError, "checkpoint metadata differs"):
                select_canonical_source(mapping)

    def test_committed_approval_payload_tamper_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "mapped-project"
            mapping, _ = self._checkpoint_fixture(root, base / "mappings")
            approval = (root / "docs" / "APPROVAL.md").read_text(encoding="utf-8").replace("GATE-0", "TAMPERED")
            (root / "docs" / "APPROVAL.md").write_text(approval, encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "--", "docs/APPROVAL.md"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "tamper"], check=True)
            with self.assertRaisesRegex(ContractMappingError, "approval log validation failed"):
                select_canonical_source(mapping)

    def test_gate_one_transition_evidence_must_be_complete_and_consistent(self) -> None:
        cases = ("missing_id", "duplicate", "plan_hash", "chain")
        for case in cases:
            with self.subTest(case=case), TemporaryDirectory() as directory:
                base = Path(directory)
                root = base / "mapped-project"
                mapping, gate_zero = self._checkpoint_fixture(
                    root,
                    base / "mappings",
                    transition_approval_id="gate-1",
                )
                plan_hash = mapping.approved_source_sha256 if case == "plan_hash" else mapping.canonical_sha256
                previous_hash = "f" * 64 if case == "chain" else str(gate_zero["record_hash"])
                gate_one = self._event(
                    "gate-1", "GATE-1", plan_hash, previous_hash
                )
                if case == "missing_id":
                    gate_one.pop("approval_id")
                    gate_one["record_hash"] = calculate_record_hash(gate_one)
                events = [gate_zero, gate_one]
                if case == "duplicate":
                    duplicate = self._event(
                        "gate-1",
                        "GATE-1",
                        mapping.canonical_sha256,
                        str(gate_one["record_hash"]),
                        approval_version=2,
                        previous_approval_id="gate-1",
                    )
                    events.append(duplicate)
                (root / "docs" / "APPROVAL.md").write_text(
                    "\n".join(f"```json\n{json.dumps(event)}\n```" for event in events),
                    encoding="utf-8",
                )
                self._commit(root, f"invalid gate one {case}")
                expected = {
                    "missing_id": "missing or duplicated",
                    "duplicate": "missing or duplicated",
                    "plan_hash": "not bound",
                    "chain": "does not link",
                }[case]
                with self.assertRaisesRegex(ContractMappingError, expected):
                    select_canonical_source(mapping)

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
