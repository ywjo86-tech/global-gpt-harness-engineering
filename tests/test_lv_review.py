from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from runtime.orchestrator.lv_execution_package import WORKER_RESULT_SCHEMA_VERSION, canonical_json_bytes
from runtime.orchestrator.lv_review import (
    LVReviewError,
    _safe_read_result,
    _sha256,
    _safe_run_id,
    _preflight,
    _seal_preflight_evidence,
    _package_root,
    preflight_run,
    review_run,
)


RUN_ID = "fixture-run-01"


class LVReviewTest(unittest.TestCase):
    def _git_fixture(self, base: Path) -> tuple[Path, dict[str, object], Path]:
        root = base / "wallet"
        (root / "app").mkdir(parents=True)
        (root / "tests").mkdir()
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Fixture"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"], check=True)
        (root / "README.md").write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
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
        from runtime.orchestrator.lv_review import _capture_git_evidence

        context = {
            "run_id": RUN_ID,
            "manifest": manifest,
            "manifest_path": manifest_path,
            "source": {},
            "project_root": root,
            "package_root": manifest_path.parent,
            "result_path": result_path or base / "worker.result.json",
            "results_root": results_root or base / "results" / RUN_ID / "attempt-01",
            "interpreter": Path(__file__).resolve().parents[2] / "wallet-affiliate-collector" / ".venv" / "bin" / "python",
            "preflight_root": base / "preflight" / RUN_ID,
            "git_before": _capture_git_evidence(root),
        }
        sealed = _seal_preflight_evidence(context)
        context["preflight_evidence_sha256"] = sealed["preflight_evidence_sha256"]
        return root, manifest, manifest_path, context

    def _worker_result(self, manifest: dict[str, object], root: Path, *, changed: list[str] | None = None) -> dict[str, object]:
        head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        changed = changed or ["app/config.py", "tests/test_config.py"]
        return {
            "schema_version": WORKER_RESULT_SCHEMA_VERSION,
            "run_id": RUN_ID,
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
            with self.assertRaisesRegex(LVReviewError, "worker result already exists"):
                _preflight("wallet-g1-lv3-1-20260826-01", package_root=_package_root("wallet-g1-lv3-1-20260826-01"), result_path=result, results_root=root / "results")
            result.unlink()
            (root / "results").mkdir()
            with self.assertRaisesRegex(LVReviewError, "attempt-01"):
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
                outcome = review_run(RUN_ID, result_path=result_path, results_root=results_root, interpreter=Path(sys.executable))
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
                outcome = review_run(RUN_ID, result_path=result_path, results_root=results_root, interpreter=Path(sys.executable))
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
                outcome = review_run(RUN_ID, result_path=result_path, results_root=results_root, interpreter=Path(sys.executable))
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
                outcome = review_run(RUN_ID, result_path=result_path, results_root=results_root, interpreter=Path(sys.executable))
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
                outcome = review_run(RUN_ID, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
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
                outcome = review_run(RUN_ID, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
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
                outcome = review_run(RUN_ID, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
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
                outcome = review_run(RUN_ID, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
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
                outcome = review_run(RUN_ID, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
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
                outcome = review_run(RUN_ID, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
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
                outcome = review_run(RUN_ID, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
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
                    outcome = review_run(RUN_ID, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
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
                outcome = review_run(RUN_ID, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
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
                outcome = review_run(RUN_ID, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
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
                outcome = review_run(RUN_ID, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
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
                outcome = review_run(RUN_ID, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
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
                outcome = review_run(RUN_ID, result_path=result_path, results_root=results_root, interpreter=context["interpreter"])
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
                outcome = review_run(RUN_ID, result_path=result_path, results_root=results_root, interpreter=Path(sys.executable))
            self.assertEqual(outcome["status"], "BLOCKED")
            self.assertFalse(results_root.exists())

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
                outcome = review_run(RUN_ID, result_path=result_path, results_root=results_root, interpreter=Path(sys.executable))
            status = json.loads((results_root / "review.status").read_text())
            self.assertEqual(outcome["status"], "PASS")
            self.assertTrue(outcome["hard_stop"])
            self.assertTrue(status["hard_stop"])


if __name__ == "__main__":
    unittest.main()
