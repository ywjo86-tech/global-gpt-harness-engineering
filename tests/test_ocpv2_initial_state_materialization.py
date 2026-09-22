from __future__ import annotations

import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime.orchestrator.production_full_plan_entry as full_plan_entry
from runtime.orchestrator.production_full_plan_entry import (
    FullPlanJobError,
    load_job,
    load_registered_job,
    register_job,
)
from runtime.orchestrator.production_full_plan_runner import DurableFullPlanSupervisor


class OCPv2InitialStateMaterializationTests(unittest.TestCase):
    def _job_path(self, root: Path) -> Path:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        payload = {
            "schema_version": "orchestration.production-full-plan-job.v1",
            "project_root": str(root),
            "harness_root": str(root),
            "project_id": "proj",
            "run_id": "gate-e-materialization",
            "required_executables": ["git"],
            "gates": [{
                "gate_id": "G1",
                "approval_evidence": str(root / "approval.json"),
                "requirements_sha256": "a" * 64,
                "branch": "main",
                "head": "b" * 40,
                "full_plan_opt_in": True,
                "project_final_validation": True,
            }],
            "policy": {
                "retry_budget": 0,
                "gate_timeout_seconds": 1,
                "heartbeat_seconds": 0.03,
                "lease_seconds": 0.08,
                "min_disk_free_bytes": 0,
                "min_inode_free": 0,
                "min_memory_available_bytes": 0,
            },
        }
        path = root / "job.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    @staticmethod
    def _supervisor(root: Path, job: dict) -> DurableFullPlanSupervisor:
        return DurableFullPlanSupervisor(
            root,
            project_id=job["project_id"],
            run_id=job["run_id"],
            gates=[item["gate_id"] for item in job["gates"]],
            authority_core_sha256=job["authority_core_sha256"],
            **job["policy"],
        )

    def test_register_job_materializes_stable_initial_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registered = register_job(load_job(self._job_path(root)))
            job = load_registered_job(registered)
            supervisor = self._supervisor(root, job)

            self.assertTrue(
                supervisor.state_path.is_file(),
                "registered jobs must publish a durable initial Full Plan state",
            )
            first, recovered_first = supervisor.load()
            time.sleep(1.05)
            second, recovered_second = supervisor.load()

            self.assertFalse(recovered_first)
            self.assertFalse(recovered_second)
            self.assertEqual(first["state"], "READY")
            self.assertEqual(first["current_gate"], "G1")
            self.assertEqual(first["state_sha256"], second["state_sha256"])
            self.assertEqual(first["progress_sequence"], 0)
            self.assertFalse((supervisor.base / "artifacts").exists())

    def test_job_publish_happens_after_initial_state_is_durable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = load_job(self._job_path(root))
            state_path = (
                root
                / "_workspace"
                / "production-full-plan"
                / "proj"
                / "gate-e-materialization"
                / "state.json"
            )
            observed_state_at_publish: list[bool] = []
            real_atomic_write_json = full_plan_entry.atomic_write_json

            def observe_publish(path, payload):
                target = Path(path)
                if "production-full-plan-jobs" in target.parts:
                    observed_state_at_publish.append(state_path.is_file())
                return real_atomic_write_json(path, payload)

            with patch.object(full_plan_entry, "atomic_write_json", side_effect=observe_publish):
                register_job(job)

            self.assertEqual(
                observed_state_at_publish,
                [True],
                "canonical job discovery must only become visible after initial state persistence",
            )

    def test_existing_registered_job_without_durable_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = load_job(self._job_path(root))
            registered = register_job(source)
            job = load_registered_job(registered)
            supervisor = self._supervisor(root, job)
            self.assertTrue(supervisor.state_path.is_file())

            supervisor.state_path.unlink()
            previous = supervisor.state_path.with_suffix(".json.prev")
            if previous.exists() or previous.is_symlink():
                previous.unlink()

            with self.assertRaisesRegex(
                FullPlanJobError,
                "durable Full Plan state is unavailable",
            ):
                register_job(source)

            self.assertFalse(supervisor.state_path.exists())

    def test_identical_reregistration_keeps_same_state_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = load_job(self._job_path(root))
            registered = register_job(source)
            job = load_registered_job(registered)
            supervisor = self._supervisor(root, job)
            first, _ = supervisor.load()
            events_before = supervisor.events_path.read_text(encoding="utf-8")

            time.sleep(1.05)
            self.assertEqual(register_job(source), registered)
            second, _ = supervisor.load()

            self.assertEqual(first["state_sha256"], second["state_sha256"])
            self.assertEqual(events_before, supervisor.events_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
