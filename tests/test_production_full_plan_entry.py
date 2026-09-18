from __future__ import annotations

import json
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.production_full_plan_entry import (
    FullPlanJobError,
    build_gate_executor,
    load_job,
    preflight_job,
    run_job,
    transient_systemd_command,
)


class ProductionFullPlanEntryTests(unittest.TestCase):
    def make_job(self, root: Path, gates=("G1", "G2", "G3")) -> Path:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        common = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-common-dir"],
                                check=True, capture_output=True, text=True).stdout.strip()
        common_path = (root / common).resolve() if not Path(common).is_absolute() else Path(common).resolve()
        payload = {
            "schema_version": "orchestration.production-full-plan-job.v1",
            "project_root": str(root), "harness_root": str(root),
            "project_id": "proj", "run_id": "run",
            "git_common_dir": str(common_path), "required_executables": ["git"],
            "gates": [
                {"gate_id": gate, "approval_evidence": str(root / f"{gate}.approval.json"),
                 "requirements_sha256": "a" * 64, "branch": "main", "head": "b" * 40,
                 "full_plan_opt_in": True, "project_final_validation": True}
                for gate in gates
            ],
            "policy": {"retry_budget": 0, "gate_timeout_seconds": 1,
                       "heartbeat_seconds": 0.03, "lease_seconds": 0.08,
                       "min_disk_free_bytes": 0, "min_inode_free": 0},
        }
        path = root / "job.json"; path.write_text(json.dumps(payload)); return path

    def test_load_job_rejects_duplicate_gate(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); path = self.make_job(root, ("G1", "G1"))
            with self.assertRaises(FullPlanJobError): load_job(path)


    def test_load_job_rejects_missing_full_plan_opt_in(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); path = self.make_job(root, ("G1",))
            payload = json.loads(path.read_text())
            payload["gates"][0]["full_plan_opt_in"] = False
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(FullPlanJobError, "explicit FULL_PLAN opt-in"):
                load_job(path)

    def test_preflight_binds_git_common_dir_not_directory_basename(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); job = load_job(self.make_job(root))
            result = preflight_job(job)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(Path(result["git_common_dir"]).resolve(), Path(job["git_common_dir"]).resolve())

    def test_preflight_blocks_wrong_git_identity(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); job = load_job(self.make_job(root)); job["git_common_dir"] = str(root / "other")
            self.assertEqual(preflight_job(job)["reason"], "GIT_COMMON_DIR_MISMATCH")

    def test_bound_executor_invokes_execute_gate_in_full_plan_mode(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); job = load_job(self.make_job(root, ("G1",)))
            executor = build_gate_executor(job)
            with patch("runtime.orchestrator.gate_orchestrator.execute_gate", return_value={"status": "GATE_EXIT"}) as call:
                out = executor("G1", "run--g1", False)
            self.assertEqual(out["status"], "GATE_EXIT")
            self.assertEqual(call.call_args.kwargs["mode"], "FULL_PLAN")
            self.assertFalse(call.call_args.kwargs["resume"])
            self.assertTrue(call.call_args.kwargs["full_plan_opt_in"])
            self.assertTrue(call.call_args.kwargs["project_final_validation"])


    def test_bound_executor_loads_task_scoped_requirement_contracts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); path = self.make_job(root, ("G1",))
            payload = json.loads(path.read_text())
            req = root / "task-1.requirements.json"
            req.write_text(json.dumps({
                "schema_version": "orchestration.project-requirement-contract.v1",
                "requirements": {"REQ-001": {"status": "PENDING"}},
            }))
            payload["gates"][0]["requirement_evidence_paths_by_lv"] = {"TASK-001": str(req)}
            path.write_text(json.dumps(payload))
            job = load_job(path)
            executor = build_gate_executor(job)
            with patch("runtime.orchestrator.gate_orchestrator.execute_gate", return_value={"status": "GATE_EXIT"}) as call:
                executor("G1", "run--g1", False)
            nested = call.call_args.kwargs["project_requirement_evidence_by_lv"]
            self.assertEqual(nested, {"TASK-001": {"REQ-001": {"status": "PENDING"}}})

    def test_run_job_drives_three_gate_bound_production_path(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); path = self.make_job(root)
            def fake_execute(*args, **kwargs):
                return {"status": "GATE_EXIT", "next": {"action": "SYSTEM_TRANSITION", "automatic": True}}
            with patch("runtime.orchestrator.gate_orchestrator.execute_gate", side_effect=fake_execute):
                out = run_job(path)
            self.assertEqual(out["status"], "COMPLETED")
            self.assertEqual(out["state"]["completed_gates"], ["G1", "G2", "G3"])

    def test_preflight_preserves_virtualenv_symlink_executable(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); path = self.make_job(root, ("G1",))
            link = root / "venv-python"; link.symlink_to(Path(sys.executable))
            payload = json.loads(path.read_text())
            payload["python_executable"] = str(link)
            payload["required_python_modules"] = ["json"]
            path.write_text(json.dumps(payload))
            result = preflight_job(load_job(path))
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["python"], str(link))

    def test_preflight_blocks_missing_required_python_module(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); job = load_job(self.make_job(root, ("G1",)))
            job["required_python_modules"] = ["module_that_must_not_exist_fpce"]
            result = preflight_job(job)
            self.assertEqual(result["status"], "BLOCK")
            self.assertEqual(result["reason"], "MISSING_PYTHON_MODULE:module_that_must_not_exist_fpce")


    def test_mapping_root_is_durably_bound_and_process_local(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); path = self.make_job(root, ("G1",))
            mapping_root = root / "mappings"; mapping_root.mkdir()
            payload = json.loads(path.read_text())
            payload["mapping_root"] = str(mapping_root.resolve())
            path.write_text(json.dumps(payload))
            seen = []
            class Result:
                def to_dict(self):
                    return {"status": "COMPLETED"}
            def fake_run(_self, *args, **kwargs):
                seen.append(__import__("os").environ.get("HARNESS_CONTRACT_MAPPING_ROOT"))
                return Result()
            before = __import__("os").environ.get("HARNESS_CONTRACT_MAPPING_ROOT")
            with patch("runtime.orchestrator.production_full_plan_entry.DurableFullPlanSupervisor.run", new=fake_run):
                out = run_job(path)
            self.assertEqual(out["status"], "COMPLETED")
            self.assertEqual(seen, [str(mapping_root.resolve())])
            self.assertEqual(__import__("os").environ.get("HARNESS_CONTRACT_MAPPING_ROOT"), before)

    def test_preflight_rejects_invalid_mapping_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); path = self.make_job(root, ("G1",))
            payload = json.loads(path.read_text()); payload["mapping_root"] = str(root / "missing")
            path.write_text(json.dumps(payload))
            self.assertEqual(preflight_job(load_job(path))["reason"], "MAPPING_ROOT_INVALID")

    def test_transient_supervisor_restarts_crashes_not_explicit_waits(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); path = self.make_job(root)
            command = transient_systemd_command(path)
            joined = " ".join(command)
            self.assertIn("XDG_RUNTIME_DIR=/run/user/", joined)
            self.assertIn("DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/", joined)
            self.assertIn("Restart=on-failure", joined)
            self.assertIn("RestartPreventExitStatus=2 3", joined)
            self.assertIn("KillMode=control-group", joined)
            self.assertIn("SendSIGKILL=yes", joined)
            self.assertIn("TimeoutStopSec=15s", joined)
            self.assertIn("--working-directory=", joined)
            self.assertIn("production_full_plan_entry", joined)


if __name__ == "__main__":
    unittest.main()
