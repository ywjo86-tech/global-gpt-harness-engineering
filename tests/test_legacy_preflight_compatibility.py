from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from runtime.orchestrator.lv_execution_package import canonical_json_bytes
from runtime.orchestrator.lv_review import (
    _sha256,
    classify_derived_preflight_status,
    resolve_derived_preflight_publication,
)


class LegacyPreflightCompatibilityTests(unittest.TestCase):
    def _fixture(self, base: Path) -> dict[str, object]:
        run_id = "fixture-compat-run"
        package = base / "runs" / "gate" / "lv" / "package"
        source = package / "preflight"
        publication_parent = base / "publications"
        package.mkdir(parents=True)
        source.mkdir()
        publication_parent.mkdir()
        transition = {
            "predecessor_completion_digest": "9" * 64,
        }
        manifest = {
            "run_id": run_id, "project_id": "second-project", "gate_id": "GATE-X", "lv_id": "GX-LV1",
            "source_head": "a" * 40, "source_tree": "b" * 40,
            "source_index_fingerprint": "c" * 64, "source_worktree_fingerprint": "d" * 64,
            "canonical_plan_sha256": "e" * 64, "gate_ledger_commit": "f" * 40,
            "gate_ledger_blob_oid": "1" * 40, "gate_ledger_sha256": "2" * 64,
            "owned_files": ["src/example.py"], "approval_id": "approval-fixture",
            "approval_record_hash": "3" * 64, "production_transition": transition,
        }
        manifest_path = package / "package.manifest.json"
        manifest_path.write_bytes(canonical_json_bytes(manifest))
        (package / "package.manifest.sha256").write_text(_sha256(manifest_path.read_bytes()), encoding="ascii")
        source_evidence = {
            "schema_version": "orchestration.gate.preflight.v1", "run_id": run_id,
            "project_id": manifest["project_id"], "gate_id": manifest["gate_id"], "lv_id": manifest["lv_id"],
            "package_manifest_sha256": _sha256(manifest_path.read_bytes()),
        }
        source_bytes = canonical_json_bytes(source_evidence)
        (source / "preflight.evidence.json").write_bytes(source_bytes)
        (source / "preflight.evidence.sha256").write_text(_sha256(source_bytes), encoding="ascii")
        (source / "preflight.status").write_bytes(canonical_json_bytes({
            "status": "READY", "hard_stop": True, "evidence_sha256": _sha256(source_bytes),
        }))
        worker = package / "worker.result.json"
        worker.write_bytes(canonical_json_bytes({
            "status": "completed", "tests": ["fixture"], "run_id": run_id,
            "project_id": manifest["project_id"], "gate_id": manifest["gate_id"], "lv_id": manifest["lv_id"],
        }))
        (package / "worker.request.json").write_bytes(canonical_json_bytes({
            "project_root": str(base / "second-project"), "task": {}, "state_snapshot": {},
            "contract_summary": {"project_id": manifest["project_id"], "gate_id": manifest["gate_id"],
                                 "lv_id": manifest["lv_id"], "canonical_plan_sha256": manifest["canonical_plan_sha256"]},
            "extra_context": {"run_id": run_id, "package_manifest_sha256": _sha256(manifest_path.read_bytes())},
        }))
        request = {
            "schema_version": "orchestration.production.review-request.v1", "run_id": run_id,
            "project_id": manifest["project_id"], "gate_id": manifest["gate_id"], "lv_id": manifest["lv_id"],
            "review_attempt": 1, "package_manifest_sha256": _sha256(manifest_path.read_bytes()),
            "worker_result_sha256": _sha256(worker.read_bytes()),
            "canonical_plan_sha256": manifest["canonical_plan_sha256"], "approval_id": manifest["approval_id"],
            "approval_record_hash": manifest["approval_record_hash"],
            "production_transition_sha256": _sha256(canonical_json_bytes(transition)),
            "predecessor_completion_digest": transition["predecessor_completion_digest"],
        }
        request_path = package / "production.review-request-01.json"
        request_path.write_bytes(canonical_json_bytes(request))
        legacy = publication_parent / f"{run_id}-v2legacy"
        legacy.mkdir()
        legacy_evidence = {
            "schema_version": "orchestration.lv_preflight.evidence.v1", "run_id": run_id,
            "project_id": manifest["project_id"], "gate_id": manifest["gate_id"], "lv_id": manifest["lv_id"],
            "package_manifest_sha256": request["package_manifest_sha256"],
            "canonical_plan_sha256": manifest["canonical_plan_sha256"],
        }
        legacy_bytes = canonical_json_bytes(legacy_evidence)
        legacy_sha = _sha256(legacy_bytes)
        (legacy / "preflight.evidence.json").write_bytes(legacy_bytes)
        (legacy / "preflight.evidence.sha256").write_text(legacy_sha, encoding="ascii")
        (legacy / "preflight.status").write_bytes(canonical_json_bytes({
            "status": "READY", "hard_stop": True, "evidence_sha256": legacy_sha,
        }))
        context = {
            "git_before": {"branch": "main", "local_config_fingerprint": "4" * 64,
                           "remote_fingerprint": "5" * 64, "submodule_fingerprint": "6" * 64},
            "interpreter_fingerprint": {"python_version": "3", "python_executable_sha256": "7" * 64,
                "python_prefix_fingerprint": "8" * 64, "python_base_prefix_fingerprint": "a" * 64,
                "python_venv_verified": True, "python_owner_validation_mode": "direct-owner",
                "python_namespace_fingerprint": "b" * 64, "python_mount_fingerprint": "c" * 64},
        }
        return locals()

    def test_valid_legacy_is_upgraded_append_only_and_replayed(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            legacy = fixture["legacy"]
            originals = {item.name: item.read_bytes() for item in legacy.iterdir()}
            with patch("runtime.orchestrator.lv_review._preflight_root", return_value=fixture["publication_parent"] / fixture["run_id"]), \
                 patch("runtime.orchestrator.lv_review._preflight", return_value=fixture["context"]), \
                 patch("runtime.orchestrator.lv_review._project_root_for", return_value=Path(directory)), \
                 patch("runtime.orchestrator.lv_review._assert_canonical_binding"):
                first = resolve_derived_preflight_publication(
                    fixture["run_id"], package_root=fixture["package"], source_root=fixture["source"],
                    result_path=fixture["worker"], review_request_path=fixture["request_path"])
                replay = resolve_derived_preflight_publication(
                    fixture["run_id"], package_root=fixture["package"], source_root=fixture["source"],
                    result_path=fixture["worker"], review_request_path=fixture["request_path"])
            self.assertEqual(first["status"], "READY")
            self.assertEqual(first["classification"], "LEGACY_STATUS_UPGRADABLE")
            self.assertEqual(replay["classification"], "CURRENT_STATUS_VALID")
            self.assertTrue(replay["idempotent"])
            self.assertEqual(originals, {item.name: item.read_bytes() for item in legacy.iterdir()})
            successor = next(fixture["publication_parent"].glob(f"{fixture['run_id']}-v2c-*"))
            evidence = json.loads((successor / "preflight.evidence.json").read_bytes())
            lineage = evidence["publication"]["successor"]
            self.assertEqual(lineage["predecessor_artifact_sha256"], fixture["legacy_sha"])
            self.assertFalse(lineage["legacy_completion_eligible"])

    def test_invalid_legacy_and_trusted_binding_tamper_fail_closed(self) -> None:
        mutations = {
            "evidence": lambda f: (f["legacy"] / "preflight.evidence.json").write_bytes(b"{}"),
            "sidecar": lambda f: (f["legacy"] / "preflight.evidence.sha256").write_text("0" * 64),
            "status": lambda f: (f["legacy"] / "preflight.status").write_bytes(b"{"),
            "source": lambda f: (f["source"] / "preflight.evidence.sha256").write_text("0" * 64),
            "worker": lambda f: f["worker"].write_bytes(b"{}"),
            "request": lambda f: f["request_path"].write_bytes(b"{}"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), TemporaryDirectory() as directory:
                fixture = self._fixture(Path(directory)); mutate(fixture)
                with patch("runtime.orchestrator.lv_review._preflight_root", return_value=fixture["publication_parent"] / fixture["run_id"]), \
                     patch("runtime.orchestrator.lv_review._project_root_for", return_value=Path(directory)), \
                     patch("runtime.orchestrator.lv_review._assert_canonical_binding"):
                    result = resolve_derived_preflight_publication(
                        fixture["run_id"], package_root=fixture["package"], source_root=fixture["source"],
                        result_path=fixture["worker"], review_request_path=fixture["request_path"])
                self.assertEqual(result["status"], "REJECTED")

    def test_ambiguous_legacy_and_unsafe_files_are_blocked(self) -> None:
        with TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            duplicate = fixture["legacy"].with_name(f"{fixture['run_id']}-v2legacy-other")
            duplicate.mkdir()
            for item in fixture["legacy"].iterdir():
                (duplicate / item.name).write_bytes(item.read_bytes())
            with patch("runtime.orchestrator.lv_review._preflight_root", return_value=fixture["publication_parent"] / fixture["run_id"]), \
                 patch("runtime.orchestrator.lv_review._project_root_for", return_value=Path(directory)), \
                 patch("runtime.orchestrator.lv_review._assert_canonical_binding"):
                result = resolve_derived_preflight_publication(
                    fixture["run_id"], package_root=fixture["package"], source_root=fixture["source"],
                    result_path=fixture["worker"], review_request_path=fixture["request_path"])
            self.assertEqual(result["classification"], "LEGACY_STATUS_AMBIGUOUS")
            self.assertEqual(result["status"], "REJECTED")

        for kind in ("symlink", "hardlink"):
            with self.subTest(kind=kind), TemporaryDirectory() as directory:
                fixture = self._fixture(Path(directory)); status = fixture["legacy"] / "preflight.status"
                status.unlink()
                if kind == "symlink": status.symlink_to(fixture["legacy"] / "preflight.evidence.json")
                else: os.link(fixture["legacy"] / "preflight.evidence.json", status)
                classified = classify_derived_preflight_status(fixture["legacy"], fixture["manifest"])
                self.assertEqual(classified["classification"], "LEGACY_STATUS_INVALID")


if __name__ == "__main__":
    unittest.main()
