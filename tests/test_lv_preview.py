from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from runtime.orchestrator.cli import main
from runtime.orchestrator.approval_hash import calculate_record_hash
from runtime.orchestrator.contract_adapter import sha256_file
from runtime.orchestrator.lv_preview import LVPreviewValidationError, parse_lv_definition, preview_lv_read_only
from runtime.orchestrator.read_only_inspector import ReadOnlyValidationError
from tests import test_read_only_inspect as read_only_fixtures


REPO_ROOT = read_only_fixtures.REPO_ROOT


class LVPreviewTest(unittest.TestCase):
    @staticmethod
    def _fixture(base: Path) -> tuple[Path, Path]:
        helper = read_only_fixtures.ReadOnlyInspectTest("runTest")
        root, mapping_dir, _ = helper._wallet_lifecycle_fixture(base, active=True)
        plan = root / "IMPLEMENTATION_PLAN.md"
        plan.write_text(
            "\n".join(
                [
                    "### Gate 1 — Core Model",
                    "",
                    "| ID | 작업 | 대상 | 완료조건 |",
                    "|---|---|---|---|",
                    "| G1-LV3-1 | 설정·수집 프로필 로더 | `app/config.py` | 환경변수 검증, COACH 프로필 단일 관리 및 secret 미출력 |",
                    "| G1-LV3-2 | Product 모델 | `app/models/product.py` | 표준 필드와 검증 구현 |",
                    "",
                    "| ID | depends_on | execution | owned_files | input → output / exit_check |",
                    "|---|---|---|---|---|",
                    "| G1-LV3-1 | Gate 0 | parallel-eligible | `app/config.py`, 관련 테스트 | 환경변수·수집 프로필 계약 → 설정·프로필 로더 / 단일 프로필 테스트 |",
                    "| G1-LV3-2 | Gate 0 | parallel-eligible | `app/models/product.py`, 관련 테스트 | 표준 상품 필드 → Product 모델 / 모델 테스트 |",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        plan_hash = sha256_file(plan)
        approval_path = root / "docs" / "APPROVAL.md"
        events = helper._approval_text
        approval_blocks = approval_path.read_text(encoding="utf-8")
        parsed_events = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", approval_blocks, flags=re.DOTALL)]
        parsed_events[-1]["plan_sha256"] = plan_hash
        parsed_events[-1]["record_hash"] = calculate_record_hash(parsed_events[-1])
        approval_path.write_text(events(parsed_events), encoding="utf-8")
        ledger_path = root / "docs" / "GATE_STATE.md"
        ledger_text = ledger_path.read_text(encoding="utf-8")
        ledger = json.loads(ledger_text.split("```json\n", 1)[1].split("\n```", 1)[0])
        ledger["plan_sha256"] = plan_hash
        ledger["approval_record_hash"] = parsed_events[-1]["record_hash"]
        ledger_path.write_text("# Gate State Ledger\n\n```json\n" + json.dumps(ledger, indent=2) + "\n```\n", encoding="utf-8")
        mapping_path = mapping_dir / f"{root.name}.json"
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        mapping["canonical_implementation_source"]["sha256"] = plan_hash
        mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "--", "IMPLEMENTATION_PLAN.md", "docs/APPROVAL.md", "docs/GATE_STATE.md"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "bind LV preview plan"], check=True)
        return root, mapping_dir

    @staticmethod
    def _preview(root: Path, mapping_dir: Path, lv_id: str = "G1-LV3-1") -> dict[str, object]:
        with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir):
            return preview_lv_read_only(root, "GATE-1", lv_id)

    def test_exact_selection_preview_is_read_only(self) -> None:
        with TemporaryDirectory() as directory:
            root, mapping_dir = self._fixture(Path(directory))
            before = read_only_fixtures.ReadOnlyInspectTest._tree_signature(root)
            preview = self._preview(root, mapping_dir)
            self.assertEqual(preview["selected_lv"]["lv_id"], "G1-LV3-1")
            self.assertEqual(preview["approved_owned_files"], ["app/config.py", "tests/test_config.py"])
            self.assertEqual(preview["execution_mode"], "read-only-preview")
            self.assertFalse(preview["mutation_permitted"])
            self.assertFalse(preview["codex_runtime_sandbox_approval_state"]["business_approval_reused"])
            self.assertEqual(before, read_only_fixtures.ReadOnlyInspectTest._tree_signature(root))

    def test_other_lv_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root, mapping_dir = self._fixture(Path(directory))
            with self.assertRaisesRegex(LVPreviewValidationError, "single active scope"):
                self._preview(root, mapping_dir, "G1-LV3-2")

    def test_inactive_gate_and_active_scope_mismatch_fail_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root, mapping_dir = self._fixture(Path(directory))
            with (
                patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir),
                patch("runtime.orchestrator.lv_preview.evaluate_canonical_state", return_value={"state": "TRANSITION_READY"}),
                self.assertRaisesRegex(LVPreviewValidationError, "requires an active canonical Gate state"),
            ):
                preview_lv_read_only(root, "GATE-1", "G1-LV3-1")
            with (
                patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir),
                patch(
                    "runtime.orchestrator.lv_preview.evaluate_canonical_state",
                    return_value={"state": "GATE1_ACTIVE", "gate_id": "GATE-1", "active_scope": ["G1-LV3-2"]},
                ),
                self.assertRaisesRegex(LVPreviewValidationError, "single active scope"),
            ):
                preview_lv_read_only(root, "GATE-1", "G1-LV3-1")

    def test_common_selector_uses_mapping_and_ledger_identifiers(self) -> None:
        with TemporaryDirectory() as directory:
            root, mapping_dir = self._fixture(Path(directory))
            original_plan = root / "IMPLEMENTATION_PLAN.md"
            canonical_plan = root / "DELIVERY_PLAN.md"
            canonical_plan.write_text(
                original_plan.read_text(encoding="utf-8")
                .replace("Gate 1", "Gate 2")
                .replace("G1-LV3-", "G2-LV3-"),
                encoding="utf-8",
            )
            plan_hash = sha256_file(canonical_plan)
            mapping_path = mapping_dir / f"{root.name}.json"
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            mapping["contract_paths"]["development_plan"] = "DELIVERY_PLAN.md"
            mapping["canonical_implementation_source"] = {
                "path": "DELIVERY_PLAN.md",
                "sha256": plan_hash,
            }
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            canonical_state = {
                "state": "GATE2_ACTIVE",
                "gate_id": "GATE-2",
                "active_scope": ["G2-LV3-1"],
                "selected_source": canonical_plan,
                "canonical_plan": "DELIVERY_PLAN.md",
                "plan_sha256": plan_hash,
                "owned_files": ["app/config.py", "tests/test_config.py"],
            }
            inspection = {
                "business_gate_state": {"state": "GATE2_ACTIVE"},
                "business_lv_approval_state": {"active_scope": ["G2-LV3-1"]},
                "codex_runtime_sandbox_approval_state": {"business_approval_reused": False},
            }
            with (
                patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir),
                patch("runtime.orchestrator.lv_preview.evaluate_canonical_state", return_value=canonical_state),
                patch("runtime.orchestrator.lv_preview.inspect_read_only", return_value=inspection),
            ):
                preview = preview_lv_read_only(root, "GATE-2", "G2-LV3-1")
            self.assertEqual(preview["selected_canonical_plan"]["path"], "DELIVERY_PLAN.md")
            self.assertEqual(preview["selected_lv"]["gate_id"], "GATE-2")
            self.assertEqual(preview["selected_lv"]["lv_id"], "G2-LV3-1")
            self.assertFalse(preview["mutation_permitted"])

    def test_lv_omission_fails_at_cli_boundary(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
            main(["lv-plan", "--project-root", "/tmp/unused", "--gate-id", "GATE-1", "--read-only"])
        self.assertEqual(raised.exception.code, 2)
        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = main(
                [
                    "lv-plan",
                    "--project-root",
                    "/tmp/unused",
                    "--gate-id",
                    "GATE-1",
                    "--lv-id",
                    "G1-LV3-1",
                ]
            )
        self.assertEqual(exit_code, 6)
        self.assertEqual(json.loads(stdout.getvalue())["error_type"], "lv_preview_validation_error")

    def test_duplicate_definition_owned_mismatch_and_path_escape_fail(self) -> None:
        plan = "\n".join(
            [
                "### Gate 1 — Core Model",
                "| ID | 작업 | 대상 | 완료조건 |",
                "|---|---|---|---|",
                "| G1-LV3-1 | config | `app/config.py` | validate |",
                "",
                "| ID | depends_on | execution | owned_files | input / exit_check |",
                "|---|---|---|---|---|",
                "| G1-LV3-1 | Gate 0 | sequential | `app/config.py`, 관련 테스트 | test |",
            ]
        )
        duplicate = plan.replace(
            "| G1-LV3-1 | config | `app/config.py` | validate |",
            "| G1-LV3-1 | config | `app/config.py` | validate |\n| G1-LV3-1 | duplicate | `app/config.py` | validate |",
        )
        approved = ["app/config.py", "tests/test_config.py"]
        with self.assertRaisesRegex(LVPreviewValidationError, "exactly once"):
            parse_lv_definition(duplicate, "GATE-1", "G1-LV3-1", approved)
        with self.assertRaisesRegex(LVPreviewValidationError, "do not match"):
            parse_lv_definition(plan, "GATE-1", "G1-LV3-1", ["app/config.py", "tests/test_wrong.py"])
        with self.assertRaisesRegex(LVPreviewValidationError, "escapes"):
            parse_lv_definition(plan, "GATE-1", "G1-LV3-1", ["../app/config.py", "tests/test_config.py"])
        with self.assertRaisesRegex(LVPreviewValidationError, "project-relative"):
            parse_lv_definition(plan, "GATE-1", "G1-LV3-1", ["/app/config.py", "tests/test_config.py"])

    def test_canonical_plan_hash_mismatch_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root, mapping_dir = self._fixture(Path(directory))
            mapping_path = mapping_dir / f"{root.name}.json"
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            mapping["canonical_implementation_source"]["sha256"] = "0" * 64
            mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
            with self.assertRaises(ReadOnlyValidationError):
                self._preview(root, mapping_dir)

    def test_actual_wallet_cli_preview_is_no_write(self) -> None:
        wallet = REPO_ROOT.parent / "wallet-affiliate-collector"
        if not wallet.is_dir():
            self.skipTest("read-only Wallet preview skipped: project checkout is not available")
        before = read_only_fixtures.ReadOnlyInspectTest._tree_signature(wallet)
        harness_artifacts = [
            REPO_ROOT / "runtime" / "orchestrator_state.json",
            REPO_ROOT / "runtime" / "orchestrator_runs",
            REPO_ROOT / "docs" / "harness" / "orchestration-state.md",
        ]
        harness_before = {
            str(path): (path.exists(), path.stat().st_mtime_ns if path.exists() else None)
            for path in harness_artifacts
        }
        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = main(
                [
                    "lv-plan",
                    "--project-root",
                    str(wallet),
                    "--gate-id",
                    "GATE-1",
                    "--lv-id",
                    "G1-LV3-2",
                    "--read-only",
                ]
            )
        payload = json.loads(stdout.getvalue())
        ledger_text = (wallet / "docs" / "GATE_STATE.md").read_text(encoding="utf-8")
        ledger = json.loads(ledger_text.split("```json\n", 1)[1].split("\n```", 1)[0])
        if ledger.get("gate_status") == "READY_FOR_APPROVAL":
            self.assertEqual(exit_code, 6)
            self.assertEqual(payload["error_type"], "lv_preview_validation_error")
        else:
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["selected_canonical_plan"]["path"], "IMPLEMENTATION_PLAN.md")
            self.assertEqual(payload["selected_lv"]["lv_id"], "G1-LV3-2")
            self.assertIn("app/models/product.py", payload["approved_owned_files"])
            self.assertFalse(payload["mutation_permitted"])
        self.assertEqual(before, read_only_fixtures.ReadOnlyInspectTest._tree_signature(wallet))
        harness_after = {
            str(path): (path.exists(), path.stat().st_mtime_ns if path.exists() else None)
            for path in harness_artifacts
        }
        self.assertEqual(harness_before, harness_after)


if __name__ == "__main__":
    unittest.main()
