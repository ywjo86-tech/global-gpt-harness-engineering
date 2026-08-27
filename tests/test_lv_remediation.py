from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.cli import main as cli_main
from runtime.orchestrator.lv_remediation import (
    LVRemediationError,
    PACKAGE_SCHEMA,
    WORKER_SCHEMA,
    create_remediation_package,
    create_remediation_preflight,
    remediation_worker_result_path,
    review_remediation, _run_checks,
)


def canon(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class LVRemediationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.harness = base / "harness"
        self.project = base / "managed-project"
        self.harness.mkdir(); self.project.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=self.project, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=self.project, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=self.project, check=True)
        (self.project / "README.md").write_text("baseline\n")
        subprocess.run(["git", "add", "README.md"], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "baseline"], cwd=self.project, check=True, stdout=subprocess.DEVNULL)
        (self.project / "app").mkdir(); (self.project / "tests").mkdir()
        (self.project / "app/model.py").write_text("VALUE = 1\n\n")
        (self.project / "tests/test_model.py").write_text("def test_value():\n    assert 1 == 1\n")
        self.owned = ["app/model.py", "tests/test_model.py"]
        self.before = self.snapshot()
        self.parent = "parent-run"
        self.run = "remediation-run"
        self.make_parent()
        self.patches = [
            patch("runtime.orchestrator.lv_remediation._harness_root", return_value=self.harness),
            patch("runtime.orchestrator.lv_remediation._project_root_for", return_value=self.project),
            patch("runtime.orchestrator.lv_remediation._validate_parent_lineage", return_value=({
                "project_id": self.project.name, "gate_id": "GATE-1", "lv_id": "LV-2",
                "canonical_plan_path": "PLAN.md", "canonical_plan_sha256": "d" * 64,
                "approval_id": "approval-1", "approval_record_hash": "a" * 64,
                "gate_ledger_commit": "b" * 40, "gate_ledger_sha256": "c" * 64,
            }, "e" * 64)),
        ]
        for item in self.patches: item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches): item.stop()
        result = remediation_worker_result_path(self.run)
        if result.exists(): result.unlink()
        self.temp.cleanup()

    def snapshot(self) -> list[dict[str, object]]:
        result = []
        for relative in self.owned:
            data = (self.project / relative).read_bytes()
            result.append({"path": relative, "sha256": sha(data), "size": len(data)})
        return result

    def write_json(self, path: Path, value: object) -> str:
        data = canon(value); path.write_bytes(data); return sha(data)

    def make_parent(self) -> None:
        package = self.harness / "_workspace/orchestration-runs" / self.parent
        preflight = self.harness / "_workspace/orchestration-preflights" / self.parent
        review = self.harness / "_workspace/orchestration-results" / self.parent / "attempt-02"
        package.mkdir(parents=True); preflight.mkdir(parents=True); review.mkdir(parents=True)
        package_hash = self.write_json(package / "package.manifest.json", {
            "project_id": self.project.name, "gate_id": "GATE-1", "lv_id": "LV-2",
            "canonical_plan_path": "PLAN.md", "canonical_plan_sha256": "d" * 64,
            "approval_id": "approval-1", "approval_record_hash": "a" * 64,
            "gate_ledger_commit": "b" * 40, "gate_ledger_sha256": "c" * 64,
        })
        (package / "package.manifest.sha256").write_text(package_hash + "\n")
        self.write_json(preflight / "preflight.evidence.json", {"status": "READY"})
        (preflight / "preflight.evidence.sha256").write_text("placeholder\n")
        worker = canon({"attempt": 1})
        (review / "worker.result.json").write_bytes(worker)
        (review / "worker.result.sha256").write_text(sha(worker) + "\n")
        report = {
            "run_id": self.parent, "project": self.project.name, "gate": "GATE-1", "lv": "LV-2",
            "review_attempt": 2, "verdict": "PASS", "hard_stop": True,
            "canonical_plan": {"path": "PLAN.md", "sha256": "d" * 64},
            "owned_files": self.owned,
            "owned_content_evidence": {"before": self.before, "after": self.before, "final": self.before, "stable": True},
        }
        report_hash = self.write_json(review / "reviewer.report.json", report)
        (review / "reviewer.report.sha256").write_text(report_hash + "\n")
        self.write_json(review / "review.status", {
            "run_id": self.parent, "worker_attempt": 1, "verdict": "PASS", "hard_stop": True,
            "reviewer_report_sha256": report_hash,
        })

    def package_preflight(self) -> dict[str, object]:
        package = create_remediation_package(self.parent, self.run, "POST_REVIEW_VALIDATION", "cached diff failure")
        self.assertEqual(package["status"], "SEALED")
        preflight = create_remediation_preflight(self.run)
        self.assertEqual(preflight["status"], "READY")
        return preflight

    def worker(self, preflight: dict[str, object], *, stale: bool = False) -> None:
        manifest_path = self.harness / "_workspace/orchestration-remediations" / self.run / "package/remediation.manifest.json"
        manifest = json.loads(manifest_path.read_text())
        result = {
            "schema_version": WORKER_SCHEMA, "run_id": self.run, "parent_run_id": self.parent,
            "manifest_sha256": sha(manifest_path.read_bytes()),
            "preflight_evidence_sha256": "0" * 64 if stale else preflight["preflight_evidence_sha256"],
            "worker_attempt": 1, "status": "completed", "started_at": "start", "completed_at": "end",
            "before_owned_content": manifest["before_owned_content"], "after_owned_content": self.snapshot(),
            "owned_files": self.owned, "changed_files": ["app/model.py"],
            "dirty_owned_files": self.owned, "remediated_files": ["app/model.py"],
            "tests": ["focused", "full"],
            "commands_summary": ["validated"], "violations": [], "error": None, "worker_type": "manual",
            "runtime_sandbox_approval_state": {"source": "external_codex_runtime", "state": "user_approved", "business_approval_reused": False, "verified_by_harness": False},
        }
        remediation_worker_result_path(self.run).write_bytes(canon(result))

    def test_package_preflight_review_pass_and_hard_stop(self) -> None:
        preflight = self.package_preflight()
        (self.project / "app/model.py").write_text("VALUE = 1\n")
        self.worker(preflight)
        with patch("runtime.orchestrator.lv_remediation._run_checks", return_value=([{"check": "fixture", "status": "PASS"}], True)):
            outcome = review_remediation(self.run)
        self.assertEqual(outcome["status"], "PASS")
        self.assertTrue(outcome["hard_stop"])
        review = self.harness / "_workspace/orchestration-remediations" / self.run / "review"
        self.assertEqual((review / "worker.result.json").read_bytes(), remediation_worker_result_path(self.run).read_bytes())
        report = json.loads((review / "reviewer.report.json").read_text())
        self.assertFalse(report["transition_authorized"])
        self.assertTrue(report["owned_content_evidence"]["stable"])

    def test_parent_artifact_drift_blocks_preflight(self) -> None:
        self.package_preflight()
        parent = self.harness / "_workspace/orchestration-results" / self.parent / "attempt-02/review.status"
        parent.write_text("{}")
        self.assertEqual(create_remediation_preflight("another-run")["status"], "BLOCKED")

    def test_non_owned_change_blocks_package(self) -> None:
        (self.project / "other.txt").write_text("drift")
        with self.assertRaisesRegex(LVRemediationError, "non-owned"):
            create_remediation_package(self.parent, self.run, "POST_REVIEW_VALIDATION", "reason")

    def test_staged_change_blocks_package(self) -> None:
        subprocess.run(["git", "add", "app/model.py"], cwd=self.project, check=True)
        with self.assertRaisesRegex(LVRemediationError, "staged"):
            create_remediation_package(self.parent, self.run, "POST_REVIEW_VALIDATION", "reason")

    def test_stale_worker_result_is_blocked(self) -> None:
        preflight = self.package_preflight()
        (self.project / "app/model.py").write_text("VALUE = 1\n")
        self.worker(preflight, stale=True)
        self.assertEqual(review_remediation(self.run)["status"], "BLOCKED")

    def test_no_change_is_blocked(self) -> None:
        preflight = self.package_preflight()
        self.worker(preflight)
        self.assertEqual(review_remediation(self.run)["status"], "BLOCKED")

    def test_run_overwrite_is_blocked(self) -> None:
        self.package_preflight()
        with self.assertRaisesRegex(LVRemediationError, "already exists"):
            create_remediation_package(self.parent, self.run, "POST_REVIEW_VALIDATION", "reason")

    def test_parent_snapshot_accepts_review_file_metadata(self) -> None:
        review = self.harness / "_workspace/orchestration-results" / self.parent / "attempt-02"
        path = review / "reviewer.report.json"
        payload = json.loads(path.read_text())
        enriched = [dict(item, regular_file=True, not_symlink=True) for item in self.before]
        payload["owned_content_evidence"] = {"before": enriched, "after": enriched, "final": enriched, "stable": True}
        data = canon(payload); path.write_bytes(data)
        report_hash = sha(data); (review / "reviewer.report.sha256").write_text(report_hash + "\n")
        status = json.loads((review / "review.status").read_text()); status["reviewer_report_sha256"] = report_hash
        (review / "review.status").write_bytes(canon(status))
        outcome = create_remediation_package(self.parent, self.run, "POST_REVIEW_VALIDATION", "reason")
        self.assertEqual(outcome["status"], "SEALED")

    def test_parent_review_binding_tamper_blocks_package(self) -> None:
        review = self.harness / "_workspace/orchestration-results" / self.parent / "attempt-02"
        path = review / "reviewer.report.json"
        payload = json.loads(path.read_text()); payload["lv"] = "OTHER-LV"
        data = canon(payload); path.write_bytes(data)
        report_hash = sha(data); (review / "reviewer.report.sha256").write_text(report_hash + "\n")
        status = json.loads((review / "review.status").read_text()); status["reviewer_report_sha256"] = report_hash
        (review / "review.status").write_bytes(canon(status))
        with self.assertRaisesRegex(LVRemediationError, "binding mismatch"):
            create_remediation_package(self.parent, self.run, "POST_REVIEW_VALIDATION", "reason")

    def test_head_drift_blocks_preflight(self) -> None:
        self.package_preflight()
        (self.project / "README.md").write_text("next\n")
        subprocess.run(["git", "add", "README.md"], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "drift"], cwd=self.project, check=True, stdout=subprocess.DEVNULL)
        self.assertEqual(create_remediation_preflight(self.run)["status"], "BLOCKED")

    def test_failed_independent_review_remains_hard_stop(self) -> None:
        preflight = self.package_preflight()
        (self.project / "app/model.py").write_text("VALUE = 1\n")
        self.worker(preflight)
        with patch("runtime.orchestrator.lv_remediation._run_checks", return_value=([{"check": "fixture", "status": "FAIL"}], False)):
            outcome = review_remediation(self.run)
        self.assertEqual(outcome["status"], "FAIL")
        self.assertTrue(outcome["hard_stop"])

    def test_worker_content_binding_tamper_is_blocked(self) -> None:
        preflight = self.package_preflight()
        (self.project / "app/model.py").write_text("VALUE = 1\n")
        self.worker(preflight)
        payload = json.loads(remediation_worker_result_path(self.run).read_text())
        payload["after_owned_content"][0]["size"] += 1
        remediation_worker_result_path(self.run).write_bytes(canon(payload))
        self.assertEqual(review_remediation(self.run)["status"], "BLOCKED")

    def test_clean_untracked_owned_bytes_diff_check_passes(self) -> None:
        (self.project / "app/model.py").write_text("VALUE = 1\n")
        with patch("runtime.orchestrator.lv_remediation._scan_owned_files", return_value=[]), \
             patch("runtime.orchestrator.lv_remediation._validate_remediation_interpreter", return_value={}), \
             patch("runtime.orchestrator.lv_remediation._run_tests", return_value=([], None)):
            checks, passed = _run_checks(self.project, self.owned)
        item = next(value for value in checks if value["check"] == "owned_bytes_diff_check")
        self.assertEqual(item["status"], "PASS")
        self.assertTrue(passed)

    def test_untracked_blank_eof_fails_owned_bytes_diff_check(self) -> None:
        with patch("runtime.orchestrator.lv_remediation._scan_owned_files", return_value=[]), \
             patch("runtime.orchestrator.lv_remediation._validate_remediation_interpreter", return_value={}), \
             patch("runtime.orchestrator.lv_remediation._run_tests", return_value=([], None)):
            checks, passed = _run_checks(self.project, self.owned)
        item = next(value for value in checks if value["check"] == "owned_bytes_diff_check")
        self.assertEqual(item["status"], "FAIL")
        self.assertFalse(passed)

    def test_cli_invalid_reason_returns_bounded_error(self) -> None:
        self.assertEqual(cli_main(["lv-remediation-package", "--parent-run-id", self.parent, "--run-id", self.run, "--reason-code", "bad", "--reason", "reason"]), 11)

    def test_package_status_tamper_blocks_preflight(self) -> None:
        self.package_preflight()
        status = self.harness / "_workspace/orchestration-remediations" / self.run / "package/package.status"
        status.write_text("{}")
        self.assertEqual(create_remediation_preflight(self.run)["status"], "BLOCKED")

    def test_preflight_status_tamper_blocks_review(self) -> None:
        preflight = self.package_preflight()
        (self.project / "app/model.py").write_text("VALUE = 1\n")
        self.worker(preflight)
        status = self.harness / "_workspace/orchestration-remediations" / self.run / "preflight/preflight.status"
        status.write_text("{}")
        self.assertEqual(review_remediation(self.run)["status"], "BLOCKED")

    def test_unchanged_owned_file_is_not_reported_as_remediated(self) -> None:
        preflight = self.package_preflight()
        (self.project / "app/model.py").write_text("VALUE = 1\n")
        self.worker(preflight)
        with patch("runtime.orchestrator.lv_remediation._run_checks", return_value=([{"check": "fixture", "status": "PASS"}], True)):
            outcome = review_remediation(self.run)
        self.assertEqual(outcome["status"], "PASS")
        report = json.loads((self.harness / "_workspace/orchestration-remediations" / self.run / "review/reviewer.report.json").read_text())
        self.assertEqual(report["changed_files"], ["app/model.py"])
        self.assertEqual(report["dirty_owned_files"], self.owned)

    def test_invalid_reason_and_same_run_are_blocked(self) -> None:
        with self.assertRaises(LVRemediationError):
            create_remediation_package(self.parent, self.run, "bad", "reason")
        with self.assertRaises(LVRemediationError):
            create_remediation_package(self.parent, self.parent, "POST_REVIEW_VALIDATION", "reason")


if __name__ == "__main__":
    unittest.main()
