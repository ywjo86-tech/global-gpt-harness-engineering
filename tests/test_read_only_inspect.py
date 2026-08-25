from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from runtime.orchestrator.approval_hash import calculate_record_hash, canonical_record_payload
from runtime.orchestrator.cli import main
from runtime.orchestrator.contract_adapter import sha256_file
from runtime.orchestrator.read_only_inspector import _validate_approval_state

REPO_ROOT = Path(__file__).resolve().parents[1]


class ReadOnlyInspectTest(unittest.TestCase):
    @staticmethod
    def _event(version: int, plan_hash: str, previous_hash: str | None, approval_id: str | None = None) -> dict[str, object]:
        event: dict[str, object] = {
            "approval_id": approval_id or f"APR-{version}",
            "target_type": "GATE",
            "target_id": f"GATE-{version}",
            "approval_type": "START_GATE",
            "approval_scope": {"lv3_ids": [f"G{version}-LV3-1"]},
            "approval_version": version,
            "approval_hash_version": 1,
            "plan_version": "V20",
            "plan_sha256": plan_hash,
            "external_action": False,
            "action_parameters": {},
            "approved_hash": "c" * 64,
            "approved_by": "USER_OWNER",
            "approved_at": "2026-08-25T00:00:00Z",
            "expires_at": None,
            "source_reference": "test fixture",
            "approval_event_type": "APPROVED",
            "previous_approval_id": None,
            "revokes_approval_id": None,
            "previous_record_hash": previous_hash,
        }
        event["record_hash"] = calculate_record_hash(event)
        return event

    @staticmethod
    def _approval_text(events: list[dict[str, object]]) -> str:
        return "\n".join(f"```json\n{json.dumps(event, ensure_ascii=False)}\n```" for event in events)

    def _cli_fixture(self, root: Path, mapping_dir: Path, event: dict[str, object]) -> None:
        root.mkdir()
        (root / "V20.md").write_text("- 현재 상태: Phase 1 / Gate 0 진행 중\n", encoding="utf-8")
        (root / "IMPLEMENTATION_PLAN.md").write_text("implementation\n", encoding="utf-8")
        (root / "docs").mkdir()
        (root / "docs" / "GATE.md").write_text(
            "Gate closure: `OPEN`\nG0-LV3-8: `FAIL`\nGate 1: 시작하지 않음\n",
            encoding="utf-8",
        )
        (root / "docs" / "APPROVAL.md").write_text(self._approval_text([event]), encoding="utf-8")
        mapping_dir.mkdir()
        mapping = {
            "project_id": root.name,
            "contract_paths": {"development_plan": "IMPLEMENTATION_PLAN.md"},
            "required_contract_keys": ["development_plan"],
            "canonical_implementation_source": {
                "path": "IMPLEMENTATION_PLAN.md",
                "sha256": sha256_file(root / "IMPLEMENTATION_PLAN.md"),
            },
            "approved_source_reference": {"path": "V20.md", "sha256": sha256_file(root / "V20.md")},
            "static_validation": {"business_lv_approval": "docs/APPROVAL.md", "gate_state": "docs/GATE.md"},
            "canonical_transition": {"gate_1_approval_id": None},
        }
        (mapping_dir / f"{root.name}.json").write_text(json.dumps(mapping), encoding="utf-8")

    @staticmethod
    def _tree_signature(root: Path) -> dict[str, tuple[str, int]]:
        return {
            path.relative_to(root).as_posix(): ("dir" if path.is_dir() else "file", path.stat().st_mtime_ns)
            for path in root.rglob("*")
        }

    def test_wallet_mapping_inspect_is_no_write_and_separates_approval_namespaces(self) -> None:
        wallet = REPO_ROOT.parent / "wallet-affiliate-collector"
        if not wallet.is_dir():
            self.skipTest("read-only reference project is not available")
        before = self._tree_signature(wallet)
        harness_paths = [REPO_ROOT / "runtime" / "orchestrator_state.json", REPO_ROOT / "logs" / "app.log"]
        harness_before = {str(path): (path.exists(), path.stat().st_mtime_ns if path.exists() else None) for path in harness_paths}
        result = subprocess.run(
            [sys.executable, "-m", "runtime.orchestrator.cli", "inspect", "--read-only", "--project", str(wallet)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["inspection_mode"], "read_only_no_write")
        self.assertFalse(payload["write_operations_performed"])
        self.assertTrue(payload["contract_mapping"]["valid"])
        self.assertEqual(
            payload["contract_mapping"]["selected_canonical_source"]["path"],
            "WALLET_AFFILIATE_IMPLEMENTATION_PLAN_V20.md",
        )
        self.assertEqual(payload["contract_mapping"]["canonical_state"], "PRE_CHECKPOINT")
        self.assertIsNone(payload["contract_mapping"]["checkpoint_commit"])
        self.assertIn("Gate 0", payload["project_static_inspect"]["current_phase"])
        self.assertEqual(payload["business_gate_state"]["gate_closure"], "OPEN")
        self.assertEqual(payload["business_gate_state"]["g0_lv3_8"], "FAIL")
        self.assertFalse(payload["business_gate_state"]["gate_1_started"])
        self.assertFalse(payload["codex_runtime_sandbox_approval_state"]["business_approval_reused"])
        self.assertTrue(payload["business_lv_approval_state"]["record_hashes_valid"])
        after = self._tree_signature(wallet)
        self.assertEqual(before, after)
        harness_after = {str(path): (path.exists(), path.stat().st_mtime_ns if path.exists() else None) for path in harness_paths}
        self.assertEqual(harness_before, harness_after)

    def test_wallet_stored_event_matches_canonical_record_hash(self) -> None:
        wallet = REPO_ROOT.parent / "wallet-affiliate-collector"
        text = (wallet / "docs" / "APPROVAL_LOG.md").read_text(encoding="utf-8")
        report = _validate_approval_state(text, {sha256_file(wallet / "WALLET_AFFILIATE_IMPLEMENTATION_PLAN_V20.md")})
        self.assertTrue(report["schema_valid"], report["errors"])
        self.assertTrue(report["record_hashes_valid"])

    def test_two_event_chain_recomputes_every_record_hash(self) -> None:
        plan_hash = "a" * 64
        first = self._event(1, plan_hash, None)
        second = self._event(2, plan_hash, str(first["record_hash"]))
        report = _validate_approval_state(self._approval_text([first, second]), {plan_hash})
        self.assertTrue(report["schema_valid"], report["errors"])
        self.assertTrue(report["chain_links_valid"])
        self.assertTrue(report["record_hashes_valid"])

    def test_payload_tampering_cases_fail_closed_with_cli_exit_five(self) -> None:
        cases = {
            "ordinary_field": lambda event: event.__setitem__("target_id", "TAMPERED"),
            "plan_sha256": lambda event: event.__setitem__("plan_sha256", "d" * 64),
            "previous_record_hash": lambda event: event.__setitem__("previous_record_hash", "e" * 64),
            "record_hash": lambda event: event.__setitem__("record_hash", "f" * 64),
        }
        for name, tamper in cases.items():
            with self.subTest(name=name), TemporaryDirectory() as directory:
                base = Path(directory)
                root = base / "mapped-project"
                mapping_dir = base / "mappings"
                (base / "seed-v20").write_text("- 현재 상태: Phase 1 / Gate 0 진행 중\n", encoding="utf-8")
                plan_hash = sha256_file(base / "seed-v20")
                event = self._event(1, plan_hash, None)
                tamper(event)
                self._cli_fixture(root, mapping_dir, event)
                if name != "plan_sha256":
                    event["plan_sha256"] = sha256_file(root / "V20.md")
                    (root / "docs" / "APPROVAL.md").write_text(self._approval_text([event]), encoding="utf-8")
                stdout = StringIO()
                with (
                    patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir),
                    patch("runtime.orchestrator.read_only_inspector.evaluate_canonical_state") as inspect_select,
                    patch("runtime.orchestrator.contract_loader.select_canonical_source") as loader_select,
                    redirect_stdout(stdout),
                ):
                    exit_code = main(["inspect", "--read-only", "--project", str(root)])
                inspect_select.assert_not_called()
                loader_select.assert_not_called()
                payload = json.loads(stdout.getvalue())
                self.assertEqual(exit_code, 5)
                self.assertEqual(payload["error_type"], "read_only_validation_error")
                errors = payload["validation"]["business_lv_approval_state"]["errors"]
                if name == "plan_sha256":
                    self.assertTrue(any("mapped source" in error for error in errors))
                self.assertTrue(any("payload mismatch" in error for error in errors))

    def test_middle_event_payload_tamper_is_detected_before_chain_tail(self) -> None:
        plan_hash = "a" * 64
        first = self._event(1, plan_hash, None)
        second = self._event(2, plan_hash, str(first["record_hash"]))
        third = self._event(3, plan_hash, str(second["record_hash"]))
        second["target_id"] = "TAMPERED"
        report = _validate_approval_state(self._approval_text([first, second, third]), {plan_hash})
        self.assertFalse(report["schema_valid"])
        self.assertFalse(report["record_hashes_valid"])
        self.assertTrue(any("event 2" in error and "payload mismatch" in error for error in report["errors"]))

    def test_null_and_missing_are_distinct_and_missing_required_field_is_rejected(self) -> None:
        plan_hash = "a" * 64
        event = self._event(1, plan_hash, None)
        missing = dict(event)
        missing.pop("expires_at")
        self.assertNotEqual(canonical_record_payload(event), canonical_record_payload(missing))
        report = _validate_approval_state(self._approval_text([missing]), {plan_hash})
        self.assertFalse(report["schema_valid"])
        self.assertTrue(any("expires_at" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
