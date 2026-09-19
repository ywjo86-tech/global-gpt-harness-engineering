from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.production_full_plan_boot import (
    discover_jobs,
    reconcile_all,
    reconcile_job,
    systemd_user_unit,
    install_user_unit,
)
from runtime.orchestrator.production_full_plan_entry import load_job, register_job
from runtime.orchestrator.production_full_plan_runner import DurableFullPlanSupervisor


class ProductionFullPlanBootTests(unittest.TestCase):
    def job(self, root: Path, run_id: str = "run") -> Path:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        payload = {
            "schema_version": "orchestration.production-full-plan-job.v1",
            "project_root": str(root), "harness_root": str(root), "project_id": "proj", "run_id": run_id,
            "required_executables": ["git"],
            "gates": [{"gate_id": "G1", "approval_evidence": str(root / "approval.json"),
                       "requirements_sha256": "a"*64, "branch": "main", "head": "b"*40,
                       "full_plan_opt_in": True, "project_final_validation": True}],
            "policy": {"retry_budget": 0, "gate_timeout_seconds": 1, "heartbeat_seconds": .03,
                       "lease_seconds": .08, "min_disk_free_bytes": 0, "min_inode_free": 0,
                       "min_memory_available_bytes": 0},
        }
        path = root / f"{run_id}.json"; path.write_text(json.dumps(payload)); return path

    def registered(self, root: Path, run_id: str = "run") -> Path:
        job = load_job(self.job(root, run_id)); return register_job(job)

    def test_register_and_discover_authorized_job(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); registered = self.registered(root)
            self.assertEqual(discover_jobs(root), [registered])

    def test_ready_job_would_resume_on_boot(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); registered = self.registered(root)
            with patch("runtime.orchestrator.production_full_plan_boot._unit_active", return_value=False):
                result = reconcile_job(registered, launch=False)
            self.assertEqual(result["action"], "WOULD_RESUME"); self.assertEqual(result["state"], "READY")

    def test_waiting_approval_is_never_auto_resumed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); registered = self.registered(root); job = load_job(registered)
            sup = DurableFullPlanSupervisor(root, project_id="proj", run_id="run", gates=["G1"],
                                            authority_core_sha256=job["authority_core_sha256"],
                                            retry_budget=0, gate_timeout_seconds=1, heartbeat_seconds=.03,
                                            lease_seconds=.08, min_disk_free_bytes=0, min_inode_free=0,
                                            min_memory_available_bytes=0)
            state, _ = sup.load(); state["state"] = "WAITING_APPROVAL"; sup._persist(state, {"event":"WAIT"})
            with patch("runtime.orchestrator.production_full_plan_boot._unit_active", return_value=False):
                result = reconcile_job(registered, launch=False)
            self.assertEqual(result["action"], "PRESERVE_WAIT")

    def test_completed_run_is_not_relaunched(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); registered = self.registered(root); job = load_job(registered)
            sup = DurableFullPlanSupervisor(root, project_id="proj", run_id="run", gates=["G1"],
                                            authority_core_sha256=job["authority_core_sha256"],
                                            retry_budget=0, gate_timeout_seconds=1, heartbeat_seconds=.03,
                                            lease_seconds=.08, min_disk_free_bytes=0, min_inode_free=0,
                                            min_memory_available_bytes=0)
            state, _ = sup.load(); state["queue"][0]["status"]="COMPLETED"; state["completed_gates"]=["G1"]
            state["state"]="COMPLETED"; sup._persist(state,{"event":"DONE"})
            with patch("runtime.orchestrator.production_full_plan_boot._unit_active", return_value=False):
                result = reconcile_job(registered, launch=False)
            self.assertEqual(result["action"], "SKIP_TERMINAL")

    def test_already_active_unit_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); registered = self.registered(root)
            with patch("runtime.orchestrator.production_full_plan_boot._unit_active", return_value=True):
                result = reconcile_job(registered, launch=False)
            self.assertEqual(result["action"], "ALREADY_ACTIVE")

    def test_reconcile_all_reports_only_active_resume_candidates(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); self.registered(root, "r1"); self.registered(root, "r2")
            with patch("runtime.orchestrator.production_full_plan_boot._unit_active", return_value=False):
                result = reconcile_all(root, launch=False)
            self.assertEqual(result["jobs_found"], 2)
            self.assertEqual([x["action"] for x in result["results"]], ["WOULD_RESUME", "WOULD_RESUME"])

    def test_systemd_boot_unit_is_oneshot_not_daemon(self):
        with tempfile.TemporaryDirectory() as d:
            text = systemd_user_unit(harness_root=d)
            self.assertIn("Type=oneshot", text)
            self.assertIn("WantedBy=default.target", text)
            self.assertNotIn("Restart=always", text)

    def test_install_unit_binds_calling_python_interpreter(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fake_home = root / "home"; fake_home.mkdir()
            python = root / "venv-python"; python.write_text("#!/bin/sh\nexit 0\n"); python.chmod(0o755)
            with patch("pathlib.Path.home", return_value=fake_home), \
                 patch("runtime.orchestrator.production_full_plan_boot.subprocess.run") as run:
                from runtime.orchestrator.production_full_plan_boot import install_user_unit
                target = install_user_unit(harness_root=root, python_executable=str(python))
            content = target.read_text()
            self.assertIn(f"ExecStart={python.resolve()} -m runtime.orchestrator.production_full_plan_boot", content)
            self.assertEqual(run.call_count, 2)

    def test_install_unit_can_bind_stable_runtime_link_instead_of_worktree(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            harness = root / "worktree"; harness.mkdir()
            fake_home = root / "home"; fake_home.mkdir()
            python = root / "venv-python"; python.write_text("#!/bin/sh\nexit 0\n"); python.chmod(0o755)
            runtime_link = fake_home / ".local/share/global-gpt-harness/runtime-current"
            with patch("pathlib.Path.home", return_value=fake_home), \
                 patch("runtime.orchestrator.production_full_plan_boot.subprocess.run"):
                target = install_user_unit(
                    harness_root=harness, python_executable=str(python), runtime_link=runtime_link)
            self.assertTrue(runtime_link.is_symlink())
            self.assertEqual(runtime_link.resolve(), harness.resolve())
            content = target.read_text()
            self.assertIn(f"WorkingDirectory={runtime_link.absolute()}", content)
            self.assertNotIn(f"WorkingDirectory={harness.resolve()}", content)


if __name__ == "__main__": unittest.main()
