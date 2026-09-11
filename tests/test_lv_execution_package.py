from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from runtime.orchestrator.lv_execution_package import (
    LVExecutionPackageError,
    MANIFEST_SCHEMA_VERSION,
    WORKER_RESULT_SCHEMA_VERSION,
    _worker_prompt,
    create_lv_execution_package,
    validate_worker_result,
)
from runtime.orchestrator.lv_preview import preview_lv_read_only
from tests.test_lv_preview import LVPreviewTest


class LVExecutionPackageTest(unittest.TestCase):
    def _fixture(self, base: Path) -> tuple[Path, Path]:
        base.mkdir(parents=True, exist_ok=True)
        root, mapping_dir = LVPreviewTest._fixture(base)
        return root, mapping_dir

    def _create(self, base: Path, run_id: str = "run-lv3-1") -> tuple[Path, Path, dict[str, object]]:
        root, mapping_dir = self._fixture(base)
        output = base / "harness-workspace"
        with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir):
            package = create_lv_execution_package(root, "GATE-1", "G1-LV3-1", run_id, output_root=output)
        return root, output, package

    def test_atomic_package_has_exact_files_and_bound_hashes(self) -> None:
        with TemporaryDirectory() as directory:
            _, output, package = self._create(Path(directory))
            package_root = Path(package["package_root"])
            self.assertEqual(
                {path.name for path in package_root.iterdir()},
                {"package.manifest.json", "package.manifest.sha256", "package.input.json", "worker_prompt.md", "source_snapshot.json", "package.status"},
            )
            manifest = json.loads((package_root / "package.manifest.json").read_text(encoding="utf-8"))
            manifest_bytes = (package_root / "package.manifest.json").read_bytes()
            self.assertEqual(package["manifest_sha256"], __import__("hashlib").sha256(manifest_bytes).hexdigest())
            self.assertEqual((package_root / "package.manifest.sha256").read_text(encoding="ascii").strip(), package["manifest_sha256"])
            self.assertEqual(json.loads((package_root / "package.status").read_text()), {"manifest_sha256": package["manifest_sha256"], "package_status": "sealed"})
            self.assertEqual(manifest["execution_mode"], "manual")
            self.assertNotIn("execution_authorized", manifest)
            self.assertTrue(manifest["execution_authorization_required"])
            self.assertEqual(manifest["runtime_sandbox_approval_state"], {
                "source": "external_codex_runtime",
                "state": "not_requested",
                "business_approval_reused": False,
                "verified_by_harness": False,
            })
            self.assertEqual(manifest["active_scope"], ["G1-LV3-1"])
            self.assertEqual(manifest["owned_files"], ["app/config.py", "tests/test_config.py"])
            projection = manifest["tool_authorization_projection"]
            self.assertEqual(projection["decision_ref"], "DEC-007")
            self.assertEqual(projection["worker_task_id"], "TASK-4A-08")
            self.assertEqual(projection["active_contract_count"], 3)
            self.assertEqual(set(projection["operation_class_ids"]), {
                "PROJECT_OWNED_FILE_LIST", "PROJECT_OWNED_FILE_READ", "PROJECT_OWNED_FILE_WRITE",
            })
            self.assertEqual(len(manifest["active_tool_authorization_contracts"]), 3)
            self.assertTrue(all(item["contract_status"] == "ACTIVE"
                                for item in manifest["active_tool_authorization_contracts"]))
            self.assertTrue(all(item["authorization_decision_ref"] == "DEC-007"
                                for item in manifest["active_tool_authorization_contracts"]))
            for field, filename in (("package_input_sha256", "package.input.json"), ("source_snapshot_sha256", "source_snapshot.json"), ("worker_prompt_sha256", "worker_prompt.md")):
                data = (package_root / filename).read_bytes()
                self.assertEqual(manifest[field], __import__("hashlib").sha256(data).hexdigest())
            self.assertTrue((output / "run-lv3-1").is_dir())

    def test_prompt_contains_contract_controls_without_implementation_instruction(self) -> None:
        with TemporaryDirectory() as directory:
            _, _, package = self._create(Path(directory))
            prompt = (Path(package["package_root"]) / "worker_prompt.md").read_text(encoding="utf-8")
            for text in (
                "manifest SHA-256",
                "does not grant runtime or sandbox permission",
                "separately authorized external Codex runtime session",
                "Business/Gate approval must not be reused",
                "Do not modify the package manifest to change approval state",
                "Record the runtime state observed at execution time",
                "Worker reporting is not Harness final approval or verification",
                "Do not run git add",
                "Do not use network or API access",
                "Do not guess external API schemas",
                ".venv/bin/python -m pytest -q tests/test_config.py",
                ".venv/bin/python -m pytest -q",
                "After producing the worker result, stop",
                "Review is a separate hard stop",
                "do not automatically start another LV",
            ):
                self.assertIn(text, prompt)
            self.assertNotIn("execution_authorized=false", prompt)
            self.assertNotIn("Implement G1-LV3-1", prompt)

    @staticmethod
    def _prompt_manifest() -> dict[str, object]:
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "package_status": "sealed",
            "run_id": "candidate-stage-01",
            "project_id": "fixture-project",
            "gate_id": "GATE-1",
            "lv_id": "G1-LV3-2",
            "task": {"purpose": "Internal standard candidate model", "execution": "parallel-eligible"},
            "dependencies": ["Gate 0"],
            "completion_checks": ["standard fields and validation", "dedicated model tests"],
            "owned_files": ["app/models/product.py", "tests/test_product.py"],
            "execution_mode": "manual",
            "business_scope_mutation_policy": "owned_files_only",
            "execution_authorization_required": True,
            "worker_result_schema_version": WORKER_RESULT_SCHEMA_VERSION,
        }

    def test_prompt_is_dynamic_deterministic_and_binds_current_stage_meaning(self) -> None:
        manifest = self._prompt_manifest()
        first = _worker_prompt(manifest)
        second = _worker_prompt(dict(manifest))
        self.assertEqual(first, second)
        for text in (
            "Stage goal: Internal standard candidate model",
            "app/models/product.py",
            "tests/test_product.py",
            "Every path not listed in editable scope is out of scope",
            "Do not guess external API schemas",
            ".venv/bin/python -m pytest -q tests/test_product.py",
            "Full regression: `.venv/bin/python -m pytest -q`",
            "After producing the worker result, stop",
            "Do not run review yourself",
            "do not automatically start another LV",
            "advance the Gate",
        ):
            self.assertIn(text, first)

    def test_prompt_missing_stage_or_malformed_owned_files_fail_closed(self) -> None:
        missing_stage = self._prompt_manifest()
        del missing_stage["task"]
        with self.assertRaisesRegex(LVExecutionPackageError, "Stage contract"):
            _worker_prompt(missing_stage)
        for owned_files in (
            [],
            ["app/models/product.py", "app/models/product.py"],
            ["../app/models/product.py", "tests/test_product.py"],
            ["app/models/product.py"],
        ):
            with self.subTest(owned_files=owned_files):
                malformed = self._prompt_manifest()
                malformed["owned_files"] = owned_files
                with self.assertRaises(LVExecutionPackageError):
                    _worker_prompt(malformed)

    def test_run_id_collision_and_invalid_ids_fail_closed(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, mapping_dir = self._fixture(base)
            output = base / "harness-workspace"
            with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir):
                self.assertTrue(create_lv_execution_package(root, "GATE-1", "G1-LV3-1", "collision", output_root=output))
            with self.assertRaisesRegex(LVExecutionPackageError, "already exists"):
                with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir):
                    create_lv_execution_package(root, "GATE-1", "G1-LV3-1", "collision", output_root=output)
            for index, run_id in enumerate(("", "../escape", "a/b", "a\\b", "/absolute")):
                with self.assertRaises(LVExecutionPackageError):
                    self._create(base / f"invalid-{index}", run_id)

    def test_dirty_staged_untracked_and_identity_mismatch_fail_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root, mapping_dir = self._fixture(Path(directory))
            (root / "docs" / "GATE_STATE.md").write_text("dirty\n", encoding="utf-8")
            with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir), self.assertRaisesRegex(LVExecutionPackageError, "clean"):
                create_lv_execution_package(root, "GATE-1", "G1-LV3-1", "dirty", output_root=Path(directory) / "out")
        with TemporaryDirectory() as directory:
            root, mapping_dir = self._fixture(Path(directory))
            (root / "unexpected.txt").write_text("untracked\n", encoding="utf-8")
            with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir), self.assertRaisesRegex(LVExecutionPackageError, "clean"):
                create_lv_execution_package(root, "GATE-1", "G1-LV3-1", "untracked", output_root=Path(directory) / "out")
        with TemporaryDirectory() as directory:
            root, mapping_dir = self._fixture(Path(directory))
            (root / "docs" / "GATE_STATE.md").write_text("staged\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "--", "docs/GATE_STATE.md"], check=True)
            with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir), self.assertRaisesRegex(LVExecutionPackageError, "clean"):
                create_lv_execution_package(root, "GATE-1", "G1-LV3-1", "staged", output_root=Path(directory) / "out")

    def test_worker_result_validator_is_strict_and_does_not_use_normalizer(self) -> None:
        with TemporaryDirectory() as directory:
            _, _, package = self._create(Path(directory))
            manifest = dict(package["manifest"])
            base = {
                "schema_version": WORKER_RESULT_SCHEMA_VERSION,
                "run_id": manifest["run_id"],
                "package_manifest_sha256": package["manifest_sha256"],
                "gate_id": "GATE-1",
                "lv_id": "G1-LV3-1",
                "status": "completed",
                "started_at": "2026-01-01T00:00:00+00:00",
                "completed_at": "2026-01-01T00:01:00+00:00",
                "source_head_before": "a", "source_head_after": "a",
                "source_tree_before": "b", "source_tree_after": "b",
                "source_index_before": "c", "source_index_after": "c",
                "source_worktree_before": "clean", "source_worktree_after": "clean",
                "changed_files": [], "created_files": [], "modified_files": [], "deleted_files": [],
                "tests": [], "commands_summary": [], "violations": [], "error": None,
                "worker_type": "manual", "runtime_sandbox_approval_state": {
                    "source": "external_codex_runtime",
                    "state": "allowed_by_active_policy",
                    "business_approval_reused": False,
                    "verified_by_harness": False,
                },
            }
            self.assertEqual(validate_worker_result(base, manifest)["status"], "completed")
            missing = dict(base)
            del missing["tests"]
            with self.assertRaisesRegex(LVExecutionPackageError, "missing fields"):
                validate_worker_result(missing, manifest)
            malformed = dict(base, status="blocked", error=None)
            with self.assertRaisesRegex(LVExecutionPackageError, "structured error"):
                validate_worker_result(malformed, manifest)

    def test_worker_result_runtime_state_matrix(self) -> None:
        with TemporaryDirectory() as directory:
            _, _, package = self._create(Path(directory))
            manifest = dict(package["manifest"])
            base = self._valid_result(manifest, package["manifest_sha256"])
            for state in ("allowed_by_active_policy", "user_approved"):
                result = dict(base, runtime_sandbox_approval_state=self._runtime_state(state))
                self.assertEqual(validate_worker_result(result, manifest)["status"], "completed")
            for state in ("not_requested", "denied"):
                result = dict(base, runtime_sandbox_approval_state=self._runtime_state(state))
                with self.assertRaises(LVExecutionPackageError):
                    validate_worker_result(result, manifest)
            for state in ("denied", "unknown", "not_requested"):
                result = dict(base, status="blocked", error={"code": "blocked"}, runtime_sandbox_approval_state=self._runtime_state(state))
                self.assertEqual(validate_worker_result(result, manifest)["status"], "blocked")

    def test_worker_result_runtime_state_rejects_malformed_objects(self) -> None:
        with TemporaryDirectory() as directory:
            _, _, package = self._create(Path(directory))
            manifest = dict(package["manifest"])
            base = self._valid_result(manifest, package["manifest_sha256"])
            cases = (
                "not_requested",
                dict(self._runtime_state("user_approved"), source="business_gate"),
                dict(self._runtime_state("user_approved"), business_approval_reused=True),
                dict(self._runtime_state("user_approved"), verified_by_harness=True),
                {"source": "external_codex_runtime", "state": "user_approved", "business_approval_reused": False},
                self._runtime_state("invalid"),
            )
            for runtime_state in cases:
                with self.assertRaises(LVExecutionPackageError):
                    validate_worker_result(dict(base, runtime_sandbox_approval_state=runtime_state), manifest)

    @staticmethod
    def _runtime_state(state: str) -> dict[str, object]:
        return {
            "source": "external_codex_runtime",
            "state": state,
            "business_approval_reused": False,
            "verified_by_harness": False,
        }

    @classmethod
    def _valid_result(cls, manifest: dict[str, object], manifest_hash: str) -> dict[str, object]:
        return {
            "schema_version": WORKER_RESULT_SCHEMA_VERSION,
            "run_id": manifest["run_id"], "package_manifest_sha256": manifest_hash,
            "gate_id": "GATE-1", "lv_id": "G1-LV3-1", "status": "completed",
            "started_at": "2026-01-01T00:00:00+00:00", "completed_at": "2026-01-01T00:01:00+00:00",
            "source_head_before": "a", "source_head_after": "a", "source_tree_before": "b", "source_tree_after": "b",
            "source_index_before": "c", "source_index_after": "c", "source_worktree_before": "clean", "source_worktree_after": "clean",
            "changed_files": [], "created_files": [], "modified_files": [], "deleted_files": [], "tests": [],
            "commands_summary": [], "violations": [], "error": None, "worker_type": "manual",
            "runtime_sandbox_approval_state": cls._runtime_state("allowed_by_active_policy"),
        }

    def test_preview_does_not_create_package(self) -> None:
        with TemporaryDirectory() as directory:
            root, mapping_dir = self._fixture(Path(directory))
            output = Path(directory) / "harness-workspace"
            with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir):
                preview_lv_read_only(root, "GATE-1", "G1-LV3-1")
            self.assertFalse(output.exists())

    def test_mappingless_cli_fails_without_artifact(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "mappingless-project"
            root.mkdir()
            (root / "README.md").write_text("mappingless\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "fixture"], check=True)
            result = subprocess.run(
                ["python3", "-m", "runtime.orchestrator.cli", "lv-package", "--project-root", str(root), "--gate-id", "GATE-1", "--lv-id", "G1-LV3-1", "--run-id", "mappingless"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 6)
            self.assertIn("mapping is required", result.stdout)

    def test_atomic_failure_leaves_no_sealed_directory(self) -> None:
        with TemporaryDirectory() as directory:
            root, mapping_dir = self._fixture(Path(directory))
            output = Path(directory) / "harness-workspace"
            with (
                patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir),
                patch(
                    "runtime.orchestrator.lv_execution_package._write_canonical_json",
                    side_effect=LVExecutionPackageError("injected sealing failure"),
                ),
                self.assertRaisesRegex(LVExecutionPackageError, "injected sealing failure"),
            ):
                create_lv_execution_package(root, "GATE-1", "G1-LV3-1", "atomic-failure", output_root=output)
            self.assertFalse((output / "atomic-failure").exists())


if __name__ == "__main__":
    unittest.main()
