from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.ocpv2_canonical_resume import (
    CanonicalRemoteResumeError,
    execute_registered_full_plan_continuation,
)
from runtime.orchestrator.production_full_plan_boot import reconcile_job
from runtime.orchestrator.production_full_plan_entry import (
    FullPlanJobError,
    load_job,
    register_job,
    run_job,
)
from runtime.orchestrator.production_full_plan_runner import DurableFullPlanSupervisor
from runtime.orchestrator.production_run_authority import (
    AUTO_RECONCILE_OWNER,
    OCPV2_OWNER,
    RunAuthorityError,
    resolve_execution_owner,
)


class OCPv2SingleExecutionOwnerTests(unittest.TestCase):
    def _job(self, root: Path, *, run_id: str = "run", owner: str | None = None) -> dict:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        payload = {
            "schema_version": "orchestration.production-full-plan-job.v1",
            "project_root": str(root),
            "harness_root": str(root),
            "project_id": "P",
            "run_id": run_id,
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
        if owner is not None:
            payload["execution_owner"] = owner
        return payload

    def test_ownerless_job_resolves_auto_without_mutation(self):
        job = {"schema_version": "orchestration.production-full-plan-job.v1"}
        before = dict(job)
        self.assertEqual(resolve_execution_owner(job), AUTO_RECONCILE_OWNER)
        self.assertEqual(job, before)

    def test_explicit_ocpv2_owner_resolves(self):
        self.assertEqual(resolve_execution_owner({"execution_owner": "OCPV2"}), OCPV2_OWNER)

    def test_unknown_owner_fails_closed(self):
        with self.assertRaisesRegex(RunAuthorityError, "EXECUTION_OWNER_INVALID"):
            resolve_execution_owner({"execution_owner": "UNKNOWN"})

    def test_same_run_cannot_rebind_execution_owner(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            registered = register_job(self._job(root, owner="AUTO_RECONCILE"))
            self.assertTrue(registered.is_file())
            with self.assertRaisesRegex(FullPlanJobError, "RUN_ID_REBIND_FORBIDDEN"):
                register_job(self._job(root, owner="OCPV2"))

    def test_boot_skips_ocpv2_ready_job_before_launch(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            registered = register_job(self._job(root, owner="OCPV2"))
            with patch("runtime.orchestrator.production_full_plan_boot.subprocess.run") as run:
                result = reconcile_job(registered, launch=True)
            self.assertEqual(result["action"], "SKIP_EXTERNAL_OWNER")
            self.assertEqual(result["execution_owner"], "OCPV2")
            self.assertFalse(result["launched"])
            run.assert_not_called()

    def test_boot_skips_ocpv2_wait_without_wait_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            registered = register_job(self._job(root, owner="OCPV2"))
            loaded = load_job(registered)
            sup = DurableFullPlanSupervisor(
                root,
                project_id="P",
                run_id="run",
                gates=["G1"],
                authority_core_sha256=loaded["authority_core_sha256"],
                **loaded["policy"],
            )
            state, _ = sup.load()
            state["state"] = "WAITING_RESOURCE"
            state["wait_reason"] = "LOW_RESOURCE_BACKPRESSURE"
            before = sup._persist(state, {"event": "TEST_WAIT"})["state_sha256"]
            with patch("runtime.orchestrator.production_full_plan_boot._attempt_typed_wait_recovery") as recovery:
                result = reconcile_job(registered, launch=True)
            self.assertEqual(result["action"], "SKIP_EXTERNAL_OWNER")
            recovery.assert_not_called()
            after, _ = sup.load()
            self.assertEqual(after["state_sha256"], before)

    def test_ownerless_boot_behavior_remains_auto_reconcile(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            registered = register_job(self._job(root))
            with patch("runtime.orchestrator.production_full_plan_boot._unit_active", return_value=False):
                result = reconcile_job(registered, launch=False)
            self.assertEqual(result["action"], "WOULD_RESUME")

    def test_generic_runner_rejects_ocpv2_owner_before_gate_executor(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            registered = register_job(self._job(root, owner="OCPV2"))
            with patch("runtime.orchestrator.production_full_plan_entry.build_gate_executor") as executor:
                with self.assertRaisesRegex(FullPlanJobError, "EXECUTION_OWNER_MISMATCH"):
                    run_job(registered)
            executor.assert_not_called()

    def test_ocp_rejects_ownerless_auto_job_before_supervisor_or_owner_claim(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            project = root / "project"
            project.mkdir()
            job_path = root / "_workspace" / "production-full-plan-jobs" / "P" / "run.job.json"
            job_path.parent.mkdir(parents=True)
            job_path.write_text("{}\n", encoding="utf-8")
            job = {
                "project_id": "P",
                "run_id": "run",
                "project_root": str(project),
                "harness_root": str(root),
                "harness_state_root": str(root),
                "gates": [{"gate_id": "G1"}],
                "policy": {},
                "authority_core_sha256": "e" * 64,
            }
            with (
                patch("runtime.orchestrator.ocpv2_canonical_resume.load_registered_job", return_value=job),
                patch("runtime.orchestrator.ocpv2_canonical_resume.canonical_job_path", return_value=job_path),
                patch("runtime.orchestrator.ocpv2_canonical_resume.DurableFullPlanSupervisor") as supervisor,
            ):
                with self.assertRaisesRegex(CanonicalRemoteResumeError, "EXECUTION_OWNER_MISMATCH"):
                    execute_registered_full_plan_continuation(
                        harness_state_root=root,
                        project_id="P",
                        run_id="run",
                        gate_id="G1",
                        task_id="G1",
                        task_execution_id="run--g1",
                        expected_state_sha256="a" * 64,
                        expected_owner_epoch=1,
                        expected_source_head="c" * 40,
                        expected_runtime_release_digest="b" * 64,
                        current_project_head=lambda _job: "c" * 40,
                        current_runtime_release_digest=lambda _job: "b" * 64,
                    )
            supervisor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
