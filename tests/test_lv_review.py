from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator.lv_execution_package import WORKER_RESULT_SCHEMA_VERSION, canonical_json_bytes
from runtime.orchestrator.lv_review import (
    REVIEW_REPORT_FIELDS,
    REVIEW_STATUS_FIELDS,
    LVReviewError,
    _results_root,
    _scan_owned_files,
    _safe_read_result,
    _sha256,
    _safe_run_id,
    _validate_interpreter,
    _verify_legacy_lineage,
    _preflight,
    _seal_preflight_evidence,
    _package_root,
    preflight_run,
    review_run,
)
from runtime.orchestrator.cli import main as cli_main


RUN_ID = "fixture-run-01"


class LVReviewTest(unittest.TestCase):
    def test_interpreter_accepts_standard_venv_symlink_chain_with_verified_probe(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "wallet"
            interpreter = root / ".venv" / "bin" / "python"
            interpreter.parent.mkdir(parents=True)
            (root / ".venv" / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
            system_root = base / "system-bin"
            system_root.mkdir()
            system_root.chmod(0o755)
            target = system_root / "python"
            target.write_bytes(Path(sys.executable).read_bytes())
            target.chmod(0o755)
            (interpreter.parent / "python").symlink_to("python3")
            (interpreter.parent / "python3").symlink_to(target)
            proc_root = base / "proc"
            (proc_root / "self").mkdir(parents=True)
            (proc_root / "sys" / "kernel").mkdir(parents=True)
            (proc_root / "self" / "uid_map").write_text("1000 0 1\n", encoding="ascii")
            (proc_root / "sys" / "kernel" / "overflowuid").write_text("65534\n", encoding="ascii")
            (proc_root / "self" / "mountinfo").write_text(
                f"1 0 0:1 / {system_root} ro - ext4 /dev/fixture ro\n", encoding="utf-8"
            )
            probe = json.dumps({
                "version": 3,
                "prefix": str((root / ".venv").resolve()),
                "base_prefix": "/usr",
                "executable": str(interpreter),
            }).encode()
            with patch("runtime.orchestrator.lv_review.subprocess.run", return_value=subprocess.CompletedProcess([], 0, probe, b"")):
                result = _validate_interpreter(root, interpreter, allowed_system_roots=(system_root,), proc_root=proc_root)
            self.assertTrue(result["python_venv_verified"])
            self.assertEqual(result["python_executable_sha256"], _sha256(target.read_bytes()))

    def test_interpreter_rejects_broken_symlink_and_external_target(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "wallet"
            interpreter = root / ".venv" / "bin" / "python"
            interpreter.parent.mkdir(parents=True)
            interpreter.symlink_to("missing-python")
            with self.assertRaisesRegex(LVReviewError, "symlink chain"):
                _validate_interpreter(root, interpreter, allowed_system_roots=(base / "system",))
            loop_root = base / "loop"
            loop = loop_root / ".venv" / "bin" / "python"
            loop.parent.mkdir(parents=True)
            loop.symlink_to("other")
            (loop.parent / "other").symlink_to("python")
            with self.assertRaisesRegex(LVReviewError, "symlink chain"):
                _validate_interpreter(loop_root, loop, allowed_system_roots=(base / "system",))

    def test_target_binding_owner_namespace_mount_and_file_boundaries(self) -> None:
        from runtime.orchestrator.lv_review import _validate_target_binding

        with TemporaryDirectory() as directory:
            base = Path(directory)
            allowed = base / "system"
            allowed.mkdir(mode=0o755)
            target = allowed / "python"
            target.write_bytes(b"ELF-fixture")
            target.chmod(0o755)
            real_stat = target.stat()
            regular = SimpleNamespace(st_mode=real_stat.st_mode, st_uid=os.getuid())
            with patch("runtime.orchestrator.lv_review._namespace_binding", return_value=("ns", 65534)), patch(
                "runtime.orchestrator.lv_review._mount_binding", return_value=("mount", True)
            ):
                self.assertEqual(_validate_target_binding(target, regular, (allowed,), proc_root=base / "proc")[0], "direct-owner")
                overflow = SimpleNamespace(st_mode=real_stat.st_mode, st_uid=65534)
                self.assertEqual(_validate_target_binding(target, overflow, (allowed,), proc_root=base / "proc")[0], "sandbox-overflow-readonly")
                for bad_uid in (65533,):
                    with self.assertRaisesRegex(LVReviewError, "ownership"):
                        _validate_target_binding(target, SimpleNamespace(st_mode=real_stat.st_mode, st_uid=bad_uid), (allowed,), proc_root=base / "proc")
                with patch("runtime.orchestrator.lv_review._mount_binding", return_value=("mount", False)):
                    with self.assertRaisesRegex(LVReviewError, "not read-only"):
                        _validate_target_binding(target, overflow, (allowed,), proc_root=base / "proc")
                with patch("runtime.orchestrator.lv_review._namespace_binding", side_effect=LVReviewError("mapping")):
                    with self.assertRaises(LVReviewError):
                        _validate_target_binding(target, overflow, (allowed,), proc_root=base / "proc")
                for mode, message in ((0o775, "permissions"), (0o644, "executable")):
                    target.chmod(mode)
                    with self.assertRaisesRegex(LVReviewError, message):
                        _validate_target_binding(target, SimpleNamespace(st_mode=target.stat().st_mode, st_uid=65534), (allowed,), proc_root=base / "proc")
                target.chmod(0o755)
                allowed.chmod(0o775)
                with self.assertRaisesRegex(LVReviewError, "ancestor"):
                    _validate_target_binding(target, overflow, (allowed,), proc_root=base / "proc")

    def test_namespace_and_mount_fingerprint_drift_is_not_accepted(self) -> None:
        from runtime.orchestrator.lv_review import _validate_target_binding

        with TemporaryDirectory() as directory:
            base = Path(directory)
            allowed = base / "system"
            allowed.mkdir(mode=0o755)
            target = allowed / "python"
            target.write_bytes(b"ELF-fixture")
            target.chmod(0o755)
            st = target.stat()
            with patch("runtime.orchestrator.lv_review._namespace_binding", return_value=("ns-before", 65534)), patch(
                "runtime.orchestrator.lv_review._mount_binding", return_value=("mount-before", True)
            ):
                before = _validate_target_binding(target, SimpleNamespace(st_mode=st.st_mode, st_uid=65534), (allowed,), proc_root=base / "proc")
            with patch("runtime.orchestrator.lv_review._namespace_binding", return_value=("ns-after", 65534)), patch(
                "runtime.orchestrator.lv_review._mount_binding", return_value=("mount-after", True)
            ):
                after = _validate_target_binding(target, SimpleNamespace(st_mode=st.st_mode, st_uid=65534), (allowed,), proc_root=base / "proc")
            self.assertNotEqual(before[1], after[1])
            self.assertNotEqual(before[2], after[2])
            target.write_bytes(b"ELF-drift")
            self.assertNotEqual(_sha256(target.read_bytes()), _sha256(b"ELF-fixture"))

    def _git_fixture(self, base: Path) -> tuple[Path, dict[str, object], Path]:
        root = base / "wallet"
        (root / "app").mkdir(parents=True)
        (root / "tests").mkdir()
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Fixture"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"], check=True)
        (root / "README.md").write_text("fixture\n", encoding="utf-8")
        (root / ".gitignore").write_text(".venv/\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "README.md", ".gitignore"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
        package = base / "package"
        package.mkdir()
        head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        tree = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD^{tree}"], text=True).strip()
        from runtime.orchestrator.lv_execution_package import _index_fingerprint, _tracked_content_fingerprint

        manifest = {
            "schema_version": "orchestration.lv_execution_package.v1",
            "run_id": RUN_ID,
            "package_status": "sealed",
            "project_id": "fixture-wallet",
            "gate_id": "GATE-1",
            "lv_id": "G1-LV3-1",
            "canonical_plan_path": "IMPLEMENTATION_PLAN.md",
            "canonical_plan_sha256": "plan",
            "approval_id": "approval",
            "approval_record_hash": "record",
            "checkpoint_commit": "checkpoint",
            "gate_ledger_commit": head,
            "gate_ledger_blob_oid": "blob",
            "gate_ledger_sha256": "ledger",
            "active_scope": ["G1-LV3-1"],
            "owned_files": ["app/config.py", "tests/test_config.py"],
            "execution_authorization_required": True,
            "runtime_sandbox_approval_state": {
                "source": "external_codex_runtime",
                "state": "not_requested",
                "business_approval_reused": False,
                "verified_by_harness": False,
            },
            "source_head": head,
            "source_tree": tree,
            "source_index_fingerprint": _index_fingerprint(root),
            "source_worktree_fingerprint": _tracked_content_fingerprint(root),
        }
        manifest_path = package / "package.manifest.json"
        manifest_path.write_bytes(canonical_json_bytes(manifest))
        return root, manifest, manifest_path

    def _context(self, base: Path, *, result_path: Path | None = None, results_root: Path | None = None) -> tuple[Path, dict[str, object], Path, dict[str, object]]:
        root, manifest, manifest_path = self._git_fixture(base)
        manifest["manifest_sha256"] = _sha256(manifest_path.read_bytes())
        venv_bin = root / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        (root / ".venv" / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
        system_root = base / "system-bin"
        system_root.mkdir()
        system_python = system_root / "python-fixture"
        system_python.write_bytes(Path(sys.executable).read_bytes())
        system_python.chmod(0o755)
        (venv_bin / "python").symlink_to("python3")
        (venv_bin / "python3").symlink_to(system_python)
        from runtime.orchestrator.lv_review import _capture_git_evidence

        interpreter = Path(__file__).resolve().parents[2] / "wallet-affiliate-collector" / ".venv" / "bin" / "python"

        context = {
            "run_id": RUN_ID,
            "manifest": manifest,
            "manifest_path": manifest_path,
            "source": {},
            "project_root": root,
            "package_root": manifest_path.parent,
            "result_path": result_path or base / "worker.result.json",
            "results_root": results_root or base / "results" / RUN_ID / "attempt-01",
            "interpreter": interpreter,
            "interpreter_allowed_system_roots": (system_root,),
            "preflight_root": base / "preflight" / RUN_ID,
            "git_before": _capture_git_evidence(root),
        }
        context["interpreter_fingerprint"] = {
            "python_version": "3.12.0",
            "python_executable_sha256": _sha256(system_python.read_bytes()),
            "python_prefix_fingerprint": _sha256(str((root / ".venv").resolve()).encode()),
            "python_base_prefix_fingerprint": _sha256(b"/usr"),
            "python_venv_verified": True,
            "python_owner_validation_mode": "direct-owner",
            "python_namespace_fingerprint": _sha256(b"fixture-namespace"),
            "python_mount_fingerprint": _sha256(b"fixture-mount"),
        }
        context["interpreter_probe_required"] = False
        sealed = _seal_preflight_evidence(context)
        context["preflight_evidence_sha256"] = sealed["preflight_evidence_sha256"]
        return root, manifest, manifest_path, context

    def _worker_result(self, manifest: dict[str, object], root: Path, *, changed: list[str] | None = None) -> dict[str, object]:
        head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        changed = changed or ["app/config.py", "tests/test_config.py"]
        return {
            "schema_version": WORKER_RESULT_SCHEMA_VERSION,
            "attempt": 1,
            "run_id": RUN_ID,
            "preflight_evidence_sha256": "pending-fixture-binding",
            "package_manifest_sha256": manifest["manifest_sha256"],
            "gate_id": "GATE-1",
            "lv_id": "G1-LV3-1",
            "status": "completed",
            "started_at": "2026-08-26T00:00:00+00:00",
            "completed_at": "2026-08-26T00:01:00+00:00",
            "source_head_before": head,
            "source_head_after": head,
            "source_tree_before": manifest["source_tree"],
            "source_tree_after": manifest["source_tree"],
            "source_index_before": manifest["source_index_fingerprint"],
            "source_index_after": manifest["source_index_fingerprint"],
            "source_worktree_before": manifest["source_worktree_fingerprint"],
            "source_worktree_after": manifest["source_worktree_fingerprint"],
            "changed_files": changed,
            "created_files": changed,
            "modified_files": [],
            "deleted_files": [],
            "owned_files": ["app/config.py", "tests/test_config.py"],
            "tests": ["pytest"],
            "commands_summary": [],
            "violations": [],
            "error": None,
            "worker_type": "manual",
            "runtime_sandbox_approval_state": {
                "source": "external_codex_runtime",
                "state": "user_approved",
                "business_approval_reused": False,
                "verified_by_harness": False,
            },
        }

    def _write_worker(self, path: Path, payload: dict[str, object]) -> bytes:
        if payload.get("preflight_evidence_sha256") == "pending-fixture-binding":
            preflight = path.parent / "preflight" / RUN_ID / "preflight.evidence.json"
            if preflight.is_file():
                payload["preflight_evidence_sha256"] = _sha256(preflight.read_bytes())
        data = canonical_json_bytes(payload)
        path.write_bytes(data)
        path.chmod(0o600)
        return data

    def test_preflight_evidence_ready_has_exact_three_bound_files(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            _, _, _, context = self._context(base)
            evidence_root = Path(context["preflight_root"])
            self.assertEqual({p.name for p in evidence_root.iterdir()}, {
                "preflight.evidence.json", "preflight.evidence.sha256", "preflight.status",
            })
            evidence = json.loads((evidence_root / "preflight.evidence.json").read_text())
            evidence_hash = hashlib.sha256((evidence_root / "preflight.evidence.json").read_bytes()).hexdigest()
            self.assertEqual((evidence_root / "preflight.evidence.sha256").read_text().strip(), evidence_hash)
            self.assertEqual(json.loads((evidence_root / "preflight.status").read_text())["status"], "READY")
            self.assertTrue(json.loads((evidence_root / "preflight.status").read_text())["hard_stop"])
            self.assertEqual(evidence["runtime_authorization"], "not_granted_by_preflight")
            self.assertFalse(evidence["business_approval_reused"])

    def test_preflight_evidence_duplicate_and_atomic_failure_blocked(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            _, _, _, context = self._context(base)
            with self.assertRaisesRegex(LVReviewError, "already exists"):
                _seal_preflight_evidence(context)
        with TemporaryDirectory() as directory:
            base = Path(directory)
            _, _, _, context = self._context(base)
            root = Path(context["preflight_root"])
            for child in root.iterdir():
                child.unlink()
            root.rmdir()
            with patch("runtime.orchestrator.lv_review.os.replace", side_effect=OSError("injected atomic failure")):
                with self.assertRaises(OSError):
                    _seal_preflight_evidence(context)
            self.assertFalse(root.exists())

    def test_preflight_blocks_existing_result_or_attempt(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / "worker.json"
            result.write_text("{}", encoding="utf-8")
            with patch("runtime.orchestrator.lv_review._assert_source_snapshot"), self.assertRaisesRegex(LVReviewError, "worker result already exists"):
                _preflight("wallet-g1-lv3-1-20260826-01", package_root=_package_root("wallet-g1-lv3-1-20260826-01"), result_path=result, results_root=root / "results")
            result.unlink()
            (root / "results").mkdir()
            with patch("runtime.orchestrator.lv_review._assert_source_snapshot"), self.assertRaisesRegex(LVReviewError, "attempt-01"):
                _preflight("wallet-g1-lv3-1-20260826-01", package_root=_package_root("wallet-g1-lv3-1-20260826-01"), result_path=result, results_root=root / "results")

    def test_preflight_stale_or_dirty_source_is_blocked(self) -> None:
        with patch("runtime.orchestrator.lv_review._assert_source_snapshot", side_effect=LVReviewError("source snapshot mismatch")):
            with self.assertRaises(LVReviewError):
                _preflight("wallet-g1-lv3-1-20260826-01", package_root=_package_root("wallet-g1-lv3-1-20260826-01"), result_path=Path("/tmp/nonexistent-h4-3b-result"), results_root=Path("/tmp/nonexistent-h4-3b-results"))

    def test_safe_result_rejects_symlink_permissions_and_size(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "result.json"
            target.write_text("{}", encoding="utf-8")
            link = root / "link.json"
            link.symlink_to(target)
            with self.assertRaises(LVReviewError):
                _safe_read_result(link)
            target.chmod(0o666)
            with self.assertRaises(LVReviewError):
                _safe_read_result(target)
            target.chmod(0o600)
            target.write_bytes(b"x" * (1024 * 1024 + 1))
            with self.assertRaises(LVReviewError):
                _safe_read_result(target)

    def test_safe_result_rejects_malformed_json(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text("not-json", encoding="utf-8")
            path.chmod(0o600)
            with self.assertRaisesRegex(LVReviewError, "malformed"):
                _safe_read_result(path)

    def test_review_passes_two_owned_untracked_files_and_seals_five_artifacts(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, manifest, manifest_path, context = self._context(base)
            (root / "app" / "config.py").write_text("VALUE = 'fixture'\n", encoding="utf-8")
            (root / "tests" / "test_config.py").write_text("def test_config():\n    assert True\n", encoding="utf-8")
            payload = self._worker_result(manifest, root)
            result_path = base / "worker.result.json"
            data = self._write_worker(result_path, payload)
            context["result_path"] = result_path
            results_root = base / "results" / RUN_ID / "attempt-01"
            context["results_root"] = results_root
            with patch("runtime.orchestrator.lv_review._preflight", return_value=context):
                outcome = review_run(RUN_ID, attempt=1, result_path=result_path, results_root=results_root, interpreter=Path(sys.executable))
            self.assertEqual(outcome["status"], "PASS")
            self.assertTrue(outcome["hard_stop"])
            self.assertEqual({p.name for p in results_root.iterdir()}, {
                "worker.result.json", "worker.result.sha256", "reviewer.report.json", "reviewer.report.sha256", "review.status",
            })
            self.assertEqual((results_root / "worker.result.json").read_bytes(), data)
            self.assertEqual((results_root / "worker.result.sha256").read_text().strip(), _sha256(data))
            report = json.loads((results_root / "reviewer.report.json").read_text())
            self.assertEqual(report["verdict"], "PASS")
            self.assertTrue(report["hard_stop"])
            self.assertEqual(report["actual_created_files"], ["app/config.py", "tests/test_config.py"])

    def test_review_blocks_duplicate_attempt_without_overwrite(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, manifest, _, context = self._context(base)
            (root / "app" / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tests" / "test_config.py").write_text("def test_config():\n    assert True\n", encoding="utf-8")
            result_path = base / "worker.result.json"
            self._write_worker(result_path, self._worker_result(manifest, root))
            results_root = base / "results" / RUN_ID / "attempt-01"
            results_root.mkdir(parents=True)
            sentinel = results_root / "sentinel"
            sentinel.write_text("keep", encoding="utf-8")
            context.update(result_path=result_path, results_root=results_root)
            with patch("runtime.orchestrator.lv_review._preflight", return_value=context):
                outcome = review_run(RUN_ID, attempt=1, result_path=result_path, results_root=results_root, interpreter=Path(sys.executable))
            self.assertEqual(outcome["status"], "BLOCKED")
            self.assertEqual(sentinel.read_text(), "keep")

    def test_review_fails_out_of_scope_and_worker_set_mismatch(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, manifest, _, context = self._context(base)
            (root / "app" / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tests" / "test_config.py").write_text("def test_config():\n    assert True\n", encoding="utf-8")
            (root / "unexpected.txt").write_text("bad\n", encoding="utf-8")
            result_path = base / "worker.result.json"
            payload = self._worker_result(manifest, root, changed=["app/config.py", "tests/test_config.py"])
            self._write_worker(result_path, payload)
            results_root = base / "results" / RUN_ID / "attempt-01"
            context.update(result_path=result_path, results_root=results_root)
            with patch("runtime.orchestrator.lv_review._preflight", return_value=context):
                outcome = review_run(RUN_ID, attempt=1, result_path=result_path, results_root=results_root, interpreter=Path(sys.executable))
            self.assertEqual(outcome["status"], "FAIL")
            report = json.loads((results_root / "reviewer.report.json").read_text())
            self.assertTrue(report["violations"])

    def test_review_blocks_result_identity_runtime_and_missing_test(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, manifest, _, context = self._context(base)
            result_path = base / "worker.result.json"
            payload = self._worker_result(manifest, root)
            payload["package_manifest_sha256"] = "wrong"
            self._write_worker(result_path, payload)
            results_root = base / "results" / RUN_ID / "attempt-01"
            context.update(result_path=result_path, results_root=results_root)
            with patch("runtime.orchestrator.lv_review._preflight", return_value=context):
                outcome = review_run(RUN_ID, attempt=1, result_path=result_path, results_root=results_root, interpreter=Path(sys.executable))
            self.assertEqual(outcome["status"], "BLOCKED")
            report = json.loads((results_root / "reviewer.report.json").read_text())
            self.assertEqual(report["verdict"], "BLOCKED")

    def test_review_missing_result_is_blocked_without_review_artifact(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, _, _, context = self._context(base)
            result_path = base / "missing-worker.result.json"
            results_root = base / "results" / RUN_ID / "attempt-01"
            context.update(result_path=result_path, results_root=results_root)
            with patch("runtime.orchestrator.lv_review._preflight", return_value=context):
                outcome = review_run(RUN_ID, attempt=1, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
            self.assertEqual(outcome["status"], "BLOCKED")

        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, manifest, _, context = self._context(base)
            sidecar = Path(context["preflight_root"]) / "preflight.evidence.sha256"
            sidecar.write_text("0" * 64 + "\n", encoding="ascii")
            result_path = base / "worker.result.json"
            self._write_worker(result_path, self._worker_result(manifest, root))
            results_root = base / "results" / RUN_ID / "attempt-01"
            context.update(result_path=result_path, results_root=results_root)
            with patch("runtime.orchestrator.lv_review._preflight", return_value=context):
                outcome = review_run(RUN_ID, attempt=1, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
            self.assertEqual(outcome["status"], "BLOCKED")
            self.assertFalse(results_root.exists())

    def test_review_requires_preflight_evidence_and_hash_binding(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, manifest, _, context = self._context(base)
            (root / "app" / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tests" / "test_config.py").write_text("def test_config():\n    assert True\n", encoding="utf-8")
            result_path = base / "worker.result.json"
            self._write_worker(result_path, self._worker_result(manifest, root))
            results_root = base / "results" / RUN_ID / "attempt-01"
            context.update(result_path=result_path, results_root=results_root)
            evidence_root = Path(context["preflight_root"])
            for child in evidence_root.iterdir():
                child.unlink()
            evidence_root.rmdir()
            with patch("runtime.orchestrator.lv_review._preflight", return_value=context):
                outcome = review_run(RUN_ID, attempt=1, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
            self.assertEqual(outcome["status"], "BLOCKED")
            self.assertFalse(results_root.exists())

        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, manifest, _, context = self._context(base)
            evidence_path = Path(context["preflight_root"]) / "preflight.evidence.json"
            evidence_path.write_bytes(b"not-json")
            (root / "app" / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tests" / "test_config.py").write_text("def test_config():\n    assert True\n", encoding="utf-8")
            result_path = base / "worker.result.json"
            self._write_worker(result_path, self._worker_result(manifest, root))
            results_root = base / "results" / RUN_ID / "attempt-01"
            context.update(result_path=result_path, results_root=results_root)
            with patch("runtime.orchestrator.lv_review._preflight", return_value=context):
                outcome = review_run(RUN_ID, attempt=1, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
            self.assertEqual(outcome["status"], "BLOCKED")

    def test_review_blocks_completed_with_invalid_runtime_state(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, manifest, _, context = self._context(base)
            result_path = base / "worker.result.json"
            payload = self._worker_result(manifest, root)
            payload["runtime_sandbox_approval_state"] = {
                "source": "external_codex_runtime",
                "state": "denied",
                "business_approval_reused": False,
                "verified_by_harness": False,
            }
            self._write_worker(result_path, payload)
            results_root = base / "results" / RUN_ID / "attempt-01"
            context.update(result_path=result_path, results_root=results_root)
            with patch("runtime.orchestrator.lv_review._preflight", return_value=context):
                outcome = review_run(RUN_ID, attempt=1, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
            self.assertEqual(outcome["status"], "BLOCKED")

    def test_review_fails_worker_violations_and_error(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, manifest, _, context = self._context(base)
            (root / "app" / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tests" / "test_config.py").write_text("def test_config():\n    assert True\n", encoding="utf-8")
            result_path = base / "worker.result.json"
            payload = self._worker_result(manifest, root)
            payload["status"] = "partial"
            payload["violations"] = ["worker used forbidden command"]
            payload["error"] = {"code": "reported"}
            self._write_worker(result_path, payload)
            results_root = base / "results" / RUN_ID / "attempt-01"
            context.update(result_path=result_path, results_root=results_root)
            with patch("runtime.orchestrator.lv_review._preflight", return_value=context):
                outcome = review_run(RUN_ID, attempt=1, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
            self.assertEqual(outcome["status"], "FAIL")

    def test_review_fails_staged_change_and_deletion(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, manifest, _, context = self._context(base)
            (root / "app" / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tests" / "test_config.py").write_text("def test_config():\n    assert True\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "app/config.py"], check=True)
            (root / "README.md").unlink()
            result_path = base / "worker.result.json"
            payload = self._worker_result(manifest, root, changed=["README.md", "app/config.py", "tests/test_config.py"])
            payload["created_files"] = ["app/config.py", "tests/test_config.py"]
            payload["deleted_files"] = ["README.md"]
            payload["changed_files"] = ["README.md", "app/config.py", "tests/test_config.py"]
            self._write_worker(result_path, payload)
            results_root = base / "results" / RUN_ID / "attempt-01"
            context.update(result_path=result_path, results_root=results_root)
            with patch("runtime.orchestrator.lv_review._preflight", return_value=context):
                outcome = review_run(RUN_ID, attempt=1, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
            self.assertEqual(outcome["status"], "FAIL")

    def test_review_fails_branch_local_config_remote_head_and_index_changes(self) -> None:
        for mutation in ("branch", "config", "remote", "head", "index", "submodule"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                base = Path(directory)
                root, manifest, _, context = self._context(base)
                (root / "app" / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
                (root / "tests" / "test_config.py").write_text("def test_config():\n    assert True\n", encoding="utf-8")
                if mutation == "branch":
                    subprocess.run(["git", "-C", str(root), "branch", "-m", "changed"], check=True)
                elif mutation == "config":
                    subprocess.run(["git", "-C", str(root), "config", "user.name", "Changed"], check=True)
                elif mutation == "remote":
                    subprocess.run(["git", "-C", str(root), "remote", "add", "origin", "https://example.invalid/repo.git"], check=True)
                elif mutation == "head":
                    (root / "head-change.txt").write_text("head\n", encoding="utf-8")
                    subprocess.run(["git", "-C", str(root), "add", "head-change.txt"], check=True)
                    subprocess.run(["git", "-C", str(root), "commit", "-qm", "head-change"], check=True)
                elif mutation == "index":
                    subprocess.run(["git", "-C", str(root), "add", "app/config.py"], check=True)
                elif mutation == "submodule":
                    context["git_before"]["submodule_fingerprint"] = "changed-submodule"
                result_path = base / "worker.result.json"
                payload = self._worker_result(manifest, root)
                if mutation == "head":
                    payload["source_head_before"] = manifest["source_head"]
                    payload["source_head_after"] = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
                self._write_worker(result_path, payload)
                results_root = base / "results" / RUN_ID / "attempt-01"
                context.update(result_path=result_path, results_root=results_root)
                with patch("runtime.orchestrator.lv_review._preflight", return_value=context):
                    outcome = review_run(RUN_ID, attempt=1, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
                self.assertEqual(outcome["status"], "FAIL")

    def test_review_rejects_owned_file_symlink_and_unsafe_result_without_artifacts(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, manifest, _, context = self._context(base)
            target = base / "outside.py"
            target.write_text("VALUE = 1\n", encoding="utf-8")
            (root / "app" / "config.py").symlink_to(target)
            (root / "tests" / "test_config.py").write_text("def test_config():\n    assert True\n", encoding="utf-8")
            result_path = base / "worker.result.json"
            self._write_worker(result_path, self._worker_result(manifest, root))
            results_root = base / "results" / RUN_ID / "attempt-01"
            context.update(result_path=result_path, results_root=results_root)
            with patch("runtime.orchestrator.lv_review._preflight", return_value=context):
                outcome = review_run(RUN_ID, attempt=1, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
            self.assertEqual(outcome["status"], "FAIL")

        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, manifest, _, context = self._context(base)
            (root / "app" / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tests" / "test_config.py").write_text("def test_config():\n    assert True\n", encoding="utf-8")
            real = base / "real-result.json"
            self._write_worker(real, self._worker_result(manifest, root))
            result_path = base / "worker.result.json"
            result_path.symlink_to(real)
            results_root = base / "results" / RUN_ID / "attempt-01"
            context.update(result_path=result_path, results_root=results_root)
            with patch("runtime.orchestrator.lv_review._preflight", return_value=context):
                outcome = review_run(RUN_ID, attempt=1, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
            self.assertEqual(outcome["status"], "BLOCKED")
            self.assertFalse(results_root.exists())

    def test_review_fails_test_failure_timeout_and_unexpected_test_file(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, manifest, _, context = self._context(base)
            (root / "app" / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tests" / "test_config.py").write_text("def test_config():\n    assert True\n", encoding="utf-8")
            result_path = base / "worker.result.json"
            self._write_worker(result_path, self._worker_result(manifest, root))
            results_root = base / "results" / RUN_ID / "attempt-01"
            context.update(result_path=result_path, results_root=results_root)
            with patch("runtime.orchestrator.lv_review._preflight", return_value=context), patch(
                "runtime.orchestrator.lv_review._run_tests", return_value=([{"exit_code": 1, "timeout": False}], "independent test command failed")
            ):
                outcome = review_run(RUN_ID, attempt=1, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
            self.assertEqual(outcome["status"], "FAIL")

        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, manifest, _, context = self._context(base)
            (root / "app" / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tests" / "test_config.py").write_text("def test_config():\n    assert True\n", encoding="utf-8")
            result_path = base / "worker.result.json"
            self._write_worker(result_path, self._worker_result(manifest, root))
            results_root = base / "results" / RUN_ID / "attempt-01"
            context.update(result_path=result_path, results_root=results_root)
            def create_unexpected(*args: object, **kwargs: object) -> tuple[list[dict[str, object]], str | None]:
                (root / "unexpected-after-test.txt").write_text("unexpected\n", encoding="utf-8")
                return ([{"exit_code": 0, "timeout": False}], None)
            with patch("runtime.orchestrator.lv_review._preflight", return_value=context), patch(
                "runtime.orchestrator.lv_review._run_tests", side_effect=create_unexpected
            ):
                outcome = review_run(RUN_ID, attempt=1, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
            self.assertEqual(outcome["status"], "FAIL")

    def test_review_atomic_seal_failure_does_not_expose_artifact(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, manifest, _, context = self._context(base)
            (root / "app" / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tests" / "test_config.py").write_text("def test_config():\n    assert True\n", encoding="utf-8")
            result_path = base / "worker.result.json"
            self._write_worker(result_path, self._worker_result(manifest, root))
            results_root = base / "results" / RUN_ID / "attempt-01"
            context.update(result_path=result_path, results_root=results_root)
            with patch("runtime.orchestrator.lv_review._preflight", return_value=context), patch(
                "runtime.orchestrator.lv_review._seal_review", side_effect=LVReviewError("injected atomic failure")
            ):
                outcome = review_run(RUN_ID, attempt=1, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
            self.assertEqual(outcome["status"], "BLOCKED")
            self.assertFalse(results_root.exists())

    def test_review_blocks_missing_required_test_without_creating_pass(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, manifest, _, context = self._context(base)
            (root / "app" / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
            result_path = base / "worker.result.json"
            self._write_worker(result_path, self._worker_result(manifest, root, changed=["app/config.py", "tests/test_config.py"]))
            results_root = base / "results" / RUN_ID / "attempt-01"
            context.update(result_path=result_path, results_root=results_root)
            with patch("runtime.orchestrator.lv_review._preflight", return_value=context):
                outcome = review_run(RUN_ID, attempt=1, result_path=result_path, results_root=results_root, interpreter=Path(sys.executable))
            self.assertEqual(outcome["status"], "BLOCKED")
            self.assertFalse(results_root.exists())

    def _legacy_contract(self, run_root: Path, worker_bytes: bytes) -> tuple[dict[str, str], dict[str, tuple[int, bytes]]]:
        run_root.mkdir(parents=True, exist_ok=True)
        content = {
            "reviewer.report.json": b'{"verdict":"PASS"}',
            "reviewer.report.sha256": b"legacy-report-sidecar\n",
            "review.status": b'{"verdict":"PASS"}',
            "worker.result.json": worker_bytes,
            "worker.result.sha256": (_sha256(worker_bytes) + "\n").encode("ascii"),
        }
        contract: dict[str, str] = {}
        preserved: dict[str, tuple[int, bytes]] = {}
        for name, data in content.items():
            path = run_root / name
            path.write_bytes(data)
            contract[name] = _sha256(data)
            preserved[name] = (path.stat().st_ino, data)
        return contract, preserved

    def _legacy_lineage(self, context: dict[str, object], contract: dict[str, str], worker_hash: str) -> dict[str, object]:
        run_id = str(context["run_id"])
        return {
            "prior_review_location_kind": "legacy_run_root",
            "prior_review_contract_status": "artifact_contract_failed",
            "artifacts": [
                {"path": f"_workspace/orchestration-results/{run_id}/{name}", "sha256": digest}
                for name, digest in contract.items()
            ],
            "prior_reviewer_report_sha256": contract["reviewer.report.json"],
            "package_manifest_sha256": _sha256(Path(context["manifest_path"]).read_bytes()),
            "preflight_evidence_sha256": context["preflight_evidence_sha256"],
            "worker_result_sha256": worker_hash,
        }

    def _attempt_two_contract(
        self,
        context: dict[str, object],
        legacy_lineage: dict[str, object],
        worker_bytes: bytes,
    ) -> tuple[dict[str, str], dict[str, tuple[int, bytes]]]:
        worker_hash = _sha256(worker_bytes)
        common = {
            "run_id": context["run_id"],
            "review_attempt": 2,
            "worker_attempt": 1,
            "verdict": "FAIL",
            "hard_stop": True,
            "package_manifest_sha256": _sha256(Path(context["manifest_path"]).read_bytes()),
            "preflight_evidence_sha256": context["preflight_evidence_sha256"],
            "worker_result_sha256": worker_hash,
            "review_only_reexecution": True,
            "reran_worker": False,
        }
        report = {field: None for field in REVIEW_REPORT_FIELDS}
        report.update(common)
        report.update({
            "schema_version": "orchestration.lv_reviewer.report.v1",
            "prior_review_lineage": legacy_lineage,
            "independent_checks": [{"check": "secret_like_value", "status": "FAIL", "summary": "redacted findings"}],
            "violations": ["independent check failed: secret_like_value"],
            "blockers": [],
            "reasons": [],
        })
        report_bytes = canonical_json_bytes(report)
        report_hash = _sha256(report_bytes)
        status = {field: None for field in REVIEW_STATUS_FIELDS}
        status.update(common)
        status.update({
            "schema_version": "orchestration.lv_reviewer.status.v1",
            "reviewer_report_sha256": report_hash,
        })
        content = {
            "reviewer.report.json": report_bytes,
            "reviewer.report.sha256": (report_hash + "\n").encode("ascii"),
            "review.status": canonical_json_bytes(status),
            "worker.result.json": worker_bytes,
            "worker.result.sha256": (worker_hash + "\n").encode("ascii"),
        }
        prior_root = Path(context["results_root"]).parent / "attempt-02"
        prior_root.mkdir()
        contract: dict[str, str] = {}
        preserved: dict[str, tuple[int, bytes]] = {}
        for name, data in content.items():
            path = prior_root / name
            path.write_bytes(data)
            contract[name] = _sha256(data)
            preserved[name] = (path.stat().st_ino, data)
        return contract, preserved

    def test_attempt_paths_are_canonical_and_run_root_is_never_the_output(self) -> None:
        with patch("runtime.orchestrator.lv_review._harness_root", return_value=Path("/fixture/harness")):
            self.assertEqual(_results_root(RUN_ID, 1), Path("/fixture/harness/_workspace/orchestration-results") / RUN_ID / "attempt-01")
            self.assertEqual(_results_root(RUN_ID, 2), Path("/fixture/harness/_workspace/orchestration-results") / RUN_ID / "attempt-02")
        for invalid in (None, 0, -1, "0", "-1", "01", "+1", "1x", True):
            with self.subTest(invalid=invalid):
                outcome = review_run(RUN_ID, attempt=invalid)
                self.assertEqual(outcome["status"], "BLOCKED")

    def test_attempt_two_review_only_lineage_is_sealed_without_mutating_legacy(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, manifest, _, context = self._context(base, results_root=base / "results" / RUN_ID / "attempt-02")
            (root / "app" / "config.py").write_text("VALUE = 'fixture'\n", encoding="utf-8")
            (root / "tests" / "test_config.py").write_text("def test_config():\n    assert True\n", encoding="utf-8")
            result_path = base / "worker.result.json"
            worker_bytes = self._write_worker(result_path, self._worker_result(manifest, root))
            context["result_path"] = result_path
            run_root = Path(context["results_root"]).parent
            contract, preserved = self._legacy_contract(run_root, worker_bytes)
            with patch("runtime.orchestrator.lv_review._preflight", return_value=context):
                outcome = review_run(RUN_ID, attempt=2, result_path=result_path, prior_review_contract=contract)
            self.assertEqual(outcome["status"], "PASS")
            report = json.loads((Path(context["results_root"]) / "reviewer.report.json").read_text())
            status = json.loads((Path(context["results_root"]) / "review.status").read_text())
            self.assertEqual(set(report), REVIEW_REPORT_FIELDS)
            self.assertEqual(set(status), REVIEW_STATUS_FIELDS)
            self.assertEqual((report["worker_attempt"], report["review_attempt"]), (1, 2))
            self.assertTrue(report["review_only_reexecution"])
            self.assertFalse(report["reran_worker"])
            self.assertEqual(report["preflight_evidence_sha256"], context["preflight_evidence_sha256"])
            self.assertEqual(status["preflight_evidence_sha256"], context["preflight_evidence_sha256"])
            self.assertEqual(report["prior_review_lineage"]["prior_review_location_kind"], "legacy_run_root")
            self.assertEqual(report["prior_review_lineage"]["prior_reviewer_report_sha256"], contract["reviewer.report.json"])
            required_interpreter = {
                "python_version", "python_executable_sha256", "python_owner_validation_mode",
                "python_namespace_fingerprint", "python_mount_fingerprint", "python_prefix_fingerprint",
                "python_base_prefix_fingerprint", "python_venv_verified",
            }
            self.assertTrue(required_interpreter <= set(report["interpreter_before"]))
            self.assertEqual(report["interpreter_before"], report["interpreter_after"])
            for name, (inode, data) in preserved.items():
                self.assertEqual((run_root / name).stat().st_ino, inode)
                self.assertEqual((run_root / name).read_bytes(), data)

    def test_attempt_two_blocks_missing_or_drifted_legacy_without_output(self) -> None:
        for mutation in ("missing", "drift"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                base = Path(directory)
                root, manifest, _, context = self._context(base, results_root=base / "results" / RUN_ID / "attempt-02")
                (root / "app" / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
                (root / "tests" / "test_config.py").write_text("def test_config():\n    assert True\n", encoding="utf-8")
                result_path = base / "worker.result.json"
                worker_bytes = self._write_worker(result_path, self._worker_result(manifest, root))
                context["result_path"] = result_path
                run_root = Path(context["results_root"]).parent
                contract, _ = self._legacy_contract(run_root, worker_bytes)
                target = run_root / "review.status"
                if mutation == "missing":
                    target.unlink()
                else:
                    target.write_bytes(b"drift")
                with patch("runtime.orchestrator.lv_review._preflight", return_value=context):
                    outcome = review_run(RUN_ID, attempt=2, prior_review_contract=contract)
                self.assertEqual(outcome["status"], "BLOCKED")
                self.assertFalse(Path(context["results_root"]).exists())

    def test_attempt_three_binds_immediate_attempt_two_and_legacy_lineage(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            _, manifest, _, context = self._context(base, results_root=base / "results" / RUN_ID / "attempt-03")
            worker_bytes = canonical_json_bytes(self._worker_result(manifest, Path(context["project_root"])))
            worker_hash = _sha256(worker_bytes)
            legacy_contract, _ = self._legacy_contract(Path(context["results_root"]).parent, worker_bytes)
            legacy_lineage = self._legacy_lineage(context, legacy_contract, worker_hash)
            prior_contract, preserved = self._attempt_two_contract(context, legacy_lineage, worker_bytes)
            context["review_attempt"] = 3
            lineage = _verify_legacy_lineage(
                context,
                worker_hash,
                contract=legacy_contract,
                prior_attempt_contract=prior_contract,
            )
            self.assertEqual(lineage["prior_review_location_kind"], "legacy_run_root")
            immediate = lineage["immediate_prior_review"]
            self.assertEqual((immediate["review_attempt"], immediate["verdict"], immediate["hard_stop"]), (2, "FAIL", True))
            self.assertEqual(immediate["violation_identifier"], "secret_like_value")
            self.assertEqual({item["sha256"] for item in immediate["artifacts"]}, set(prior_contract.values()))
            self.assertFalse(Path(context["results_root"]).exists())
            for name, (inode, data) in preserved.items():
                path = Path(context["results_root"]).parent / "attempt-02" / name
                self.assertEqual((path.stat().st_ino, path.read_bytes()), (inode, data))

    def test_attempt_three_lineage_contract_failures_block_before_output(self) -> None:
        mutations = (
            "missing", "hash_drift", "report_sidecar", "status_report_sha", "run_id", "review_attempt",
            "worker_attempt", "verdict", "hard_stop", "package_hash", "preflight_hash", "worker_hash",
            "missing_secret_violation",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                base = Path(directory)
                _, manifest, _, context = self._context(base, results_root=base / "results" / RUN_ID / "attempt-03")
                worker_bytes = canonical_json_bytes(self._worker_result(manifest, Path(context["project_root"])))
                worker_hash = _sha256(worker_bytes)
                legacy_contract, _ = self._legacy_contract(Path(context["results_root"]).parent, worker_bytes)
                prior_contract, _ = self._attempt_two_contract(
                    context, self._legacy_lineage(context, legacy_contract, worker_hash), worker_bytes
                )
                context["review_attempt"] = 3
                prior_root = Path(context["results_root"]).parent / "attempt-02"
                if mutation == "missing":
                    (prior_root / "review.status").unlink()
                elif mutation == "hash_drift":
                    (prior_root / "worker.result.sha256").write_bytes(b"drift\n")
                elif mutation == "report_sidecar":
                    (prior_root / "reviewer.report.sha256").write_bytes(b"0" * 64 + b"\n")
                    prior_contract["reviewer.report.sha256"] = _sha256((prior_root / "reviewer.report.sha256").read_bytes())
                else:
                    target = prior_root / ("review.status" if mutation == "status_report_sha" else "reviewer.report.json")
                    payload = json.loads(target.read_text())
                    field_values = {
                        "status_report_sha": ("reviewer_report_sha256", "0" * 64),
                        "run_id": ("run_id", "wrong-run"),
                        "review_attempt": ("review_attempt", 1),
                        "worker_attempt": ("worker_attempt", 2),
                        "verdict": ("verdict", "PASS"),
                        "hard_stop": ("hard_stop", False),
                        "package_hash": ("package_manifest_sha256", "0" * 64),
                        "preflight_hash": ("preflight_evidence_sha256", "0" * 64),
                        "worker_hash": ("worker_result_sha256", "0" * 64),
                    }
                    if mutation == "missing_secret_violation":
                        payload["violations"] = []
                    else:
                        field, value = field_values[mutation]
                        payload[field] = value
                    target.write_bytes(canonical_json_bytes(payload))
                    prior_contract[target.name] = _sha256(target.read_bytes())
                    if target.name == "reviewer.report.json":
                        report_hash = prior_contract[target.name]
                        (prior_root / "reviewer.report.sha256").write_text(report_hash + "\n", encoding="ascii")
                        prior_contract["reviewer.report.sha256"] = _sha256((prior_root / "reviewer.report.sha256").read_bytes())
                with self.assertRaises(LVReviewError):
                    _verify_legacy_lineage(
                        context, worker_hash, contract=legacy_contract, prior_attempt_contract=prior_contract
                    )
                self.assertFalse(Path(context["results_root"]).exists())

    def test_attempts_above_three_are_not_generalized(self) -> None:
        with self.assertRaisesRegex(LVReviewError, "above 3"):
            _verify_legacy_lineage({"review_attempt": 4}, "unused")

    def test_worker_attempt_and_preflight_hash_are_fail_closed(self) -> None:
        for mutation in ("missing_attempt", "wrong_attempt", "empty_preflight"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                base = Path(directory)
                root, manifest, _, context = self._context(base)
                (root / "app" / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
                (root / "tests" / "test_config.py").write_text("def test_config():\n    assert True\n", encoding="utf-8")
                payload = self._worker_result(manifest, root)
                if mutation == "missing_attempt":
                    del payload["attempt"]
                elif mutation == "wrong_attempt":
                    payload["attempt"] = 2
                result_path = base / "worker.result.json"
                self._write_worker(result_path, payload)
                context["result_path"] = result_path
                verify = patch("runtime.orchestrator.lv_review._verify_preflight_evidence", return_value=({}, "")) if mutation == "empty_preflight" else patch("runtime.orchestrator.lv_review._preflight", return_value=context)
                if mutation == "empty_preflight":
                    with patch("runtime.orchestrator.lv_review._preflight", return_value=context), verify:
                        outcome = review_run(RUN_ID, attempt=1)
                else:
                    with verify:
                        outcome = review_run(RUN_ID, attempt=1)
                self.assertEqual(outcome["status"], "BLOCKED")

    def test_review_records_interpreter_before_after_and_fails_drift(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, manifest, _, context = self._context(base)
            (root / "app" / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tests" / "test_config.py").write_text("def test_config():\n    assert True\n", encoding="utf-8")
            result_path = base / "worker.result.json"
            self._write_worker(result_path, self._worker_result(manifest, root))
            context["result_path"] = result_path
            context["interpreter_probe_required"] = True
            drifted = dict(context["interpreter_fingerprint"], python_namespace_fingerprint="drifted")
            with patch("runtime.orchestrator.lv_review._preflight", return_value=context), patch(
                "runtime.orchestrator.lv_review._validate_interpreter", return_value=drifted
            ):
                outcome = review_run(RUN_ID, attempt=1)
            self.assertEqual(outcome["status"], "FAIL")
            report = json.loads((Path(context["results_root"]) / "reviewer.report.json").read_text())
            self.assertEqual(report["interpreter_before"], context["interpreter_fingerprint"])
            self.assertEqual(report["interpreter_after"], drifted)
            self.assertIn("interpreter fingerprint changed during review", report["violations"])

    def test_static_checks_redact_secrets_and_do_not_flag_environment_name(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            safe = root / "safe.py"
            safe.write_text(
                '"""api_key documents configuration."""\n'
                "import os\n"
                "from dataclasses import dataclass\n"
                "@dataclass\n"
                "class Settings:\n    secret_name: str\n"
                "def loader(name: str) -> str:\n    return os.environ.get(name, '')\n"
                "def build(api_key: str) -> Settings:\n"
                "    # password is supplied by the environment\n"
                "    existing_identifier = loader('ADPICK_API_KEY')\n"
                "    api_token = loader('TOKEN')\n"
                "    password = os.getenv('PASSWORD', '')\n"
                "    secret = ''\n"
                "    placeholder_secret = '<empty>' if False else ''\n"
                "    return Settings(secret_name=existing_identifier)\n"
                "settings = build(api_key=loader('ADPICK_API_KEY'))\n",
                encoding="utf-8",
            )
            checks = {item["check"]: item for item in _scan_owned_files(root, ["safe.py"])}
            self.assertEqual(checks["secret_like_value"]["status"], "PASS")
            unsafe = root / "unsafe.py"
            secret_value = "unit-test-credential-value"
            unsafe.write_text("pass" + 'word = "' + secret_value + '"\n', encoding="utf-8")
            checks = {item["check"]: item for item in _scan_owned_files(root, ["unsafe.py"])}
            self.assertEqual(checks["secret_like_value"]["status"], "FAIL")
            self.assertNotIn(secret_value, checks["secret_like_value"]["summary"])
            self.assertNotIn(secret_value, json.dumps(checks["secret_like_value"]))
            self.assertEqual(
                set(checks["secret_like_value"]["findings"][0]),
                {"path", "line", "check", "kind", "fingerprint"},
            )
            credential_url = "https://fixture-" + "user:fixture-" + "pass@example.invalid/path"
            unsafe.write_text('url = "' + credential_url + '"\n', encoding="utf-8")
            checks = {item["check"]: item for item in _scan_owned_files(root, ["unsafe.py"])}
            self.assertEqual(checks["secret_like_value"]["status"], "FAIL")
            self.assertNotIn("fixture-pass", checks["secret_like_value"]["summary"])
            self.assertNotIn(credential_url, json.dumps(checks["secret_like_value"]))
            unsafe.write_bytes(b"value = \xff\n")
            checks = {item["check"]: item for item in _scan_owned_files(root, ["unsafe.py"])}
            self.assertEqual(checks["utf8_decode"]["status"], "FAIL")
            unsafe.write_bytes(b"\xef\xbb\xbfvalue = 1 \n<<<<<<< HEAD\n\0")
            checks = {item["check"]: item for item in _scan_owned_files(root, ["unsafe.py"])}
            for identifier in ("bom", "nul", "trailing_whitespace", "conflict_marker"):
                self.assertEqual(checks[identifier]["status"], "FAIL")

    def test_python_secret_scanner_literal_boundaries_and_parse_failure(self) -> None:
        cases = {
            "api_key": "direct-value",
            "token": "prefix-" + "suffix",
            "password": "nonempty",
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (name, value) in enumerate(cases.items()):
                path = root / f"unsafe_{index}.py"
                path.write_text(f"{name} = {value!r}\n", encoding="utf-8")
                check = {item["check"]: item for item in _scan_owned_files(root, [path.name])}["secret_like_value"]
                self.assertEqual(check["status"], "FAIL")
                self.assertNotIn(value, json.dumps(check))
            combined = root / "combined.py"
            combined.write_text("api_key = 'static-' + 'credential'\n", encoding="utf-8")
            check = {item["check"]: item for item in _scan_owned_files(root, [combined.name])}["secret_like_value"]
            self.assertEqual(check["status"], "FAIL")
            self.assertEqual(check["findings"][0]["kind"], "secret_named_literal")
            shaped = root / "shaped.py"
            shaped.write_text("value = 'sk-fixturetokenvalue123'\n", encoding="utf-8")
            check = {item["check"]: item for item in _scan_owned_files(root, [shaped.name])}["secret_like_value"]
            self.assertEqual(check["status"], "FAIL")
            self.assertEqual(check["findings"][0]["kind"], "known_token_literal")
            invalid = root / "invalid.py"
            invalid.write_text("def broken(:\n", encoding="utf-8")
            check = {item["check"]: item for item in _scan_owned_files(root, [invalid.name])}["secret_like_value"]
            self.assertEqual(check["status"], "FAIL")
            self.assertEqual(check["findings"][0]["kind"], "python_ast_parse_error")

    def test_safe_unapproved_reserved_url_fixture_is_not_a_credential_url(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "tests" / "test_config.py"
            path.parent.mkdir()
            path.write_text(
                "def test_rejects_unapproved_origin():\n"
                "    api_url = 'https://unapproved.example.invalid'\n"
                "    fixture_values = {'ADPICK_API_KEY': 'fixture-key-not-a-secret'}\n"
                "    secret_marker = 'fixture-sensitive-marker'\n"
                "    assert api_url and fixture_values and secret_marker\n",
                encoding="utf-8",
            )
            check = {item["check"]: item for item in _scan_owned_files(root, ["tests/test_config.py"])}["secret_like_value"]
            self.assertEqual(check["status"], "PASS")

    def test_cli_requires_attempt_and_distinguishes_exit_codes(self) -> None:
        for status, expected in (("PASS", 0), ("FAIL", 9), ("BLOCKED", 10)):
            with self.subTest(status=status), patch("runtime.orchestrator.cli.review_run", return_value={"status": status}):
                self.assertEqual(cli_main(["lv-review", "--run-id", RUN_ID, "--attempt", "2"]), expected)
        with self.assertRaises(SystemExit) as missing:
            cli_main(["lv-review", "--run-id", RUN_ID])
        self.assertEqual(missing.exception.code, 2)

    def test_cli_integration_uses_default_attempt_path_in_temporary_fixture(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, manifest, _, context = self._context(base)
            (root / "app" / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tests" / "test_config.py").write_text("def test_config():\n    assert True\n", encoding="utf-8")
            result_path = base / "worker.result.json"
            self._write_worker(result_path, self._worker_result(manifest, root))
            context["result_path"] = result_path
            expected = base / "_workspace" / "orchestration-results" / RUN_ID / "attempt-01"
            context["results_root"] = expected

            def fixture_preflight(*args: object, **kwargs: object) -> dict[str, object]:
                self.assertIsNone(kwargs.get("results_root"))
                self.assertEqual(kwargs.get("review_attempt"), 1)
                return context

            with patch("runtime.orchestrator.lv_review._harness_root", return_value=base), patch(
                "runtime.orchestrator.lv_review._preflight", side_effect=fixture_preflight
            ):
                self.assertEqual(cli_main(["lv-review", "--run-id", RUN_ID, "--attempt", "1"]), 0)
            self.assertTrue(expected.is_dir())
            self.assertFalse((expected.parent / "reviewer.report.json").exists())

    def test_hard_stop_is_true_for_pass_and_no_worker_execution_is_required(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root, manifest, _, context = self._context(base)
            (root / "app" / "config.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tests" / "test_config.py").write_text("def test_config():\n    assert True\n", encoding="utf-8")
            result_path = base / "worker.result.json"
            self._write_worker(result_path, self._worker_result(manifest, root))
            results_root = base / "results" / RUN_ID / "attempt-01"
            context.update(result_path=result_path, results_root=results_root)
            with patch("runtime.orchestrator.lv_review._preflight", return_value=context):
                outcome = review_run(RUN_ID, attempt=1, result_path=result_path, results_root=results_root, interpreter=Path(sys.executable))
            status = json.loads((results_root / "review.status").read_text())
            self.assertEqual(outcome["status"], "PASS")
            self.assertTrue(outcome["hard_stop"])
            self.assertTrue(status["hard_stop"])


if __name__ == "__main__":
    unittest.main()
