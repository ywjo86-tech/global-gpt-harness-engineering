from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator.production_full_plan_entry import load_registered_job, register_job
from runtime.orchestrator.production_full_plan_operator_resume import (
    FullPlanOperatorResumeError,
    _operator_resume_lock,
    bind_manual_action_and_resume,
)


class _Supervisor:
    def __init__(self, base: Path, state: dict):
        self.base = base
        self._state = state
        self.resume_calls: list[str] = []

    def load(self):
        return dict(self._state), False

    def resume_wait(self, expected: str):
        self.resume_calls.append(expected)
        return {**self._state, "state": "RECOVERING"}


class ProductionFullPlanOperatorResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.files_temp = tempfile.TemporaryDirectory()
        self.files_root = Path(self.files_temp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Test"], check=True)
        (self.root / "seed.txt").write_text("seed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "seed.txt"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "seed"], check=True)
        subprocess.run(["git", "-C", str(self.root), "checkout", "-qb", "diagnosis/test"], check=True)
        (self.root / ".git" / "info" / "exclude").write_text("_workspace/\nrun/\n", encoding="utf-8")
        self.head = self.git("rev-parse", "HEAD")
        self.plan_sha = "a" * 64
        self.job = self.make_job()
        self.job_path = register_job(self.job)

    def tearDown(self):
        self.files_temp.cleanup()
        self.temp.cleanup()

    def git(self, *args: str) -> str:
        return subprocess.check_output(["git", "-C", str(self.root), *args], text=True).strip()

    def make_job(self) -> dict:
        return {
            "schema_version": "orchestration.production-full-plan-job.v1",
            "project_root": str(self.root),
            "harness_root": str(self.root),
            "project_id": "P1",
            "run_id": "RUN1",
            "expected_branch": "diagnosis/test",
            "gates": [{
                "gate_id": "GATE-005",
                "approval_evidence": str(self.root / "approval.json"),
                "requirements_sha256": "b" * 64,
                "branch": "diagnosis/test",
                "head": self.head,
                "full_plan_opt_in": True,
                "project_final_validation": True,
            }],
        }

    def plan(self):
        return SimpleNamespace(
            project_id="P1",
            canonical_plan_sha256=self.plan_sha,
            lvs=[
                SimpleNamespace(lv_id="TASK-015", owned_files=["a.py"], tests=["TEST-026", "TEST-027"]),
                SimpleNamespace(lv_id="TASK-016", owned_files=["b.py"], tests=["TEST-028"]),
            ],
        )

    def state(self, status="WAITING_PROVIDER"):
        return {
            "state": status,
            "current_gate": "GATE-005",
            "queue": [{
                "gate_id": "GATE-005",
                "gate_run_id": "RUN1--gate-005",
                "status": "READY",
            }],
        }

    def action(self, *, lv_id="TASK-015", run_id="RUN1--gate-005", source_head=None):
        return {
            "project_id": "P1",
            "gate_id": "GATE-005",
            "lv_id": lv_id,
            "run_id": run_id,
            "plan_sha256": self.plan_sha,
            "validation_ids": ["TEST-026", "TEST-027"] if lv_id == "TASK-015" else ["TEST-028"],
            "source_head": source_head or self.head,
        }

    def write_json(self, name: str, value: dict) -> Path:
        path = self.files_root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def invoke(self, *, state=None, action=None, lv_id="TASK-015"):
        supervisor = _Supervisor(self.root / "run", state or self.state())
        action_path = self.write_json("action.json", action or self.action(lv_id=lv_id))
        auth_path = self.write_json("authorization.json", {"operator": "GPT_OPERATOR"})
        with patch(
            "runtime.orchestrator.production_full_plan_operator_resume.DurableFullPlanSupervisor",
            return_value=supervisor,
        ), patch(
            "runtime.orchestrator.gate_orchestrator.load_gate_plan",
            return_value=self.plan(),
        ), patch(
            "runtime.orchestrator.production_full_plan_operator_resume.validate_action_package",
            return_value=(object(), object()),
        ):
            result = bind_manual_action_and_resume(
                job_path=self.job_path,
                gate_id="GATE-005",
                lv_id=lv_id,
                action_path=action_path,
                authorization_path=auth_path,
                launch=False,
            )
        return result, supervisor, action_path, auth_path

    def test_waiting_provider_manual_action_is_bound_and_resumed(self):
        result, supervisor, action_path, auth_path = self.invoke()
        self.assertEqual(result["from_state"], "WAITING_PROVIDER")
        self.assertEqual(result["to_state"], "RECOVERING")
        self.assertEqual(supervisor.resume_calls, ["WAITING_PROVIDER"])
        registered = load_registered_job(self.job_path)
        spec = registered["gates"][0]
        self.assertEqual(spec["manual_action_package_paths_by_lv"]["TASK-015"], str(action_path.resolve()))
        self.assertEqual(spec["manual_action_authorization_paths_by_lv"]["TASK-015"], str(auth_path.resolve()))
        self.assertTrue(Path(result["receipt_path"]).is_file())
        self.assertEqual(len(result["receipt_sha256"]), 64)

    def test_non_waiting_state_is_rejected_without_job_mutation(self):
        before = self.job_path.read_bytes()
        with self.assertRaisesRegex(FullPlanOperatorResumeError, "not waiting for provider"):
            self.invoke(state=self.state("READY"))
        self.assertEqual(self.job_path.read_bytes(), before)

    def test_wrong_lv_run_identity_is_rejected(self):
        bad = self.action(run_id="WRONG")
        before = self.job_path.read_bytes()
        with self.assertRaisesRegex(FullPlanOperatorResumeError, "run ID"):
            self.invoke(action=bad)
        self.assertEqual(self.job_path.read_bytes(), before)

    def test_stale_source_head_is_rejected(self):
        bad = self.action(source_head="f" * 40)
        before = self.job_path.read_bytes()
        with self.assertRaisesRegex(FullPlanOperatorResumeError, "source HEAD"):
            self.invoke(action=bad)
        self.assertEqual(self.job_path.read_bytes(), before)

    def test_operator_resume_lock_serializes_concurrent_bindings(self):
        base = self.root / "lock-test"
        acquired = threading.Event()
        def contender():
            with _operator_resume_lock(base):
                acquired.set()
        with _operator_resume_lock(base):
            thread = threading.Thread(target=contender)
            thread.start()
            time.sleep(0.05)
            self.assertFalse(acquired.is_set())
        thread.join(timeout=1.0)
        self.assertTrue(acquired.is_set())


    def test_same_prebound_manual_action_is_idempotent_after_bind_before_resume_crash(self):
        supervisor = _Supervisor(self.root / "run", self.state())
        action_path = self.write_json("action-prebound.json", self.action())
        auth_path = self.write_json("authorization-prebound.json", {"operator": "GPT_OPERATOR"})
        registered = json.loads(self.job_path.read_text(encoding="utf-8"))
        registered["gates"][0]["manual_action_package_paths_by_lv"] = {"TASK-015": str(action_path.resolve())}
        registered["gates"][0]["manual_action_authorization_paths_by_lv"] = {"TASK-015": str(auth_path.resolve())}
        self.job_path.write_text(json.dumps(registered), encoding="utf-8")
        with patch("runtime.orchestrator.production_full_plan_operator_resume.DurableFullPlanSupervisor", return_value=supervisor), \
             patch("runtime.orchestrator.gate_orchestrator.load_gate_plan", return_value=self.plan()), \
             patch("runtime.orchestrator.production_full_plan_operator_resume.validate_action_package", return_value=(object(), object())):
            result = bind_manual_action_and_resume(job_path=self.job_path, gate_id="GATE-005", lv_id="TASK-015",
                                                   action_path=action_path, authorization_path=auth_path)
        self.assertEqual(result["to_state"], "RECOVERING")
        self.assertEqual(supervisor.resume_calls, ["WAITING_PROVIDER"])


    def test_existing_different_manual_action_binding_is_rejected(self):
        registered = json.loads(self.job_path.read_text(encoding="utf-8"))
        registered["gates"][0]["manual_action_package_paths_by_lv"] = {"TASK-015": "/tmp/other-action.json"}
        registered["gates"][0]["manual_action_authorization_paths_by_lv"] = {"TASK-015": "/tmp/other-auth.json"}
        self.job_path.write_text(json.dumps(registered), encoding="utf-8")
        with self.assertRaisesRegex(FullPlanOperatorResumeError, "conflicting Manual Action"):
            self.invoke()

    def test_second_lv_requires_derived_durable_run_identity(self):
        action = self.action(lv_id="TASK-016", run_id="RUN1--gate-005-task-016")
        result, supervisor, _, _ = self.invoke(action=action, lv_id="TASK-016")
        self.assertEqual(result["lv_run_id"], "RUN1--gate-005-task-016")
        self.assertEqual(supervisor.resume_calls, ["WAITING_PROVIDER"])

    def test_manual_action_contract_failure_is_fail_closed(self):
        supervisor = _Supervisor(self.root / "run", self.state())
        action_path = self.write_json("action-invalid.json", self.action())
        auth_path = self.write_json("authorization-invalid.json", {"operator": "GPT_OPERATOR"})
        with patch("runtime.orchestrator.production_full_plan_operator_resume.DurableFullPlanSupervisor", return_value=supervisor), \
             patch("runtime.orchestrator.gate_orchestrator.load_gate_plan", return_value=self.plan()), \
             patch("runtime.orchestrator.production_full_plan_operator_resume.validate_action_package", side_effect=ValueError("bad contract")):
            with self.assertRaisesRegex(FullPlanOperatorResumeError, "manual action validation failed"):
                bind_manual_action_and_resume(job_path=self.job_path, gate_id="GATE-005", lv_id="TASK-015",
                                              action_path=action_path, authorization_path=auth_path)
        self.assertEqual(supervisor.resume_calls, [])


if __name__ == "__main__":
    unittest.main()
