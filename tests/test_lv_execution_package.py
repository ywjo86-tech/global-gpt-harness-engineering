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
from tests.support.lv_preview_fixture import build_lv_preview_fixture


class LVExecutionPackageTest(unittest.TestCase):
    def _fixture(self, base: Path) -> tuple[Path, Path]:
        base.mkdir(parents=True, exist_ok=True)
        root, mapping_dir = build_lv_preview_fixture(base)
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
            self.assertEqual(projection["worker_task_id"], "G1-LV3-1")
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
                "Full regression: `.venv/bin/python -m pytest -q`",
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

    def test_prompt_accepts_safe_directory_scopes_for_project_native_validation(self) -> None:
        manifest = self._prompt_manifest()
        manifest["owned_files"] = ["backend/", "tests/test_product.py"]
        manifest["validation_toolchain"] = {
            "profile_ids": ["NODE_NPM"],
            "focused": [["npm", "--prefix", "backend", "test"]],
            "full": [["npm", "--prefix", "backend", "test"]],
            "compile": [["npm", "--prefix", "backend", "run", "build"]],
            "deferred": False,
        }
        prompt = _worker_prompt(manifest)
        self.assertIn("backend/", prompt)
        self.assertIn("npm --prefix backend test", prompt)

    def test_package_is_immutable_after_sealing(self) -> None:
        with TemporaryDirectory() as directory:
            _, _, package = self._create(Path(directory))
            package_root = Path(package["package_root"])
            with self.assertRaises(LVExecutionPackageError):
                create_lv_execution_package(package_root.parent.parent.parent, "GATE-1", "G1-LV3-1", "run-lv3-1", output_root=package_root.parent.parent)

    def test_worker_result_validation_enforces_scope_and_identity(self) -> None:
        with TemporaryDirectory() as directory:
            _, _, package = self._create(Path(directory))
            manifest = package["manifest"]
            result = {
                "schema_version": WORKER_RESULT_SCHEMA_VERSION,
                "run_id": manifest["run_id"],
                "project_id": manifest["project_id"],
                "gate_id": manifest["gate_id"],
                "lv_id": manifest["lv_id"],
                "package_manifest_sha256": manifest["manifest_sha256"],
                "source_head_before": manifest["source_head"],
                "source_head_after": manifest["source_head"],
                "source_tree_before": manifest["source_tree"],
                "source_tree_after": manifest["source_tree"],
                "changed_files": ["app/config.py"],
                "created_files": [],
                "deleted_files": [],
                "tests": [{"name": "focused", "status": "PASS"}],
                "commands": [],
                "violations": [],
                "status": "PASS",
                "error": None,
            }
            validated = validate_worker_result(result, manifest)
            self.assertEqual(validated["status"], "PASS")
            bad = dict(result)
            bad["changed_files"] = ["outside.py"]
            with self.assertRaises(LVExecutionPackageError):
                validate_worker_result(bad, manifest)

    def test_preview_rejects_unknown_gate_before_package_creation(self) -> None:
        with TemporaryDirectory() as directory:
            root, mapping_dir = self._fixture(Path(directory))
            with patch("runtime.orchestrator.contract_adapter.MAPPING_DIR", mapping_dir):
                with self.assertRaises(Exception):
                    preview_lv_read_only(root, "GATE-X", "G1-LV3-1")


if __name__ == "__main__":
    unittest.main()
