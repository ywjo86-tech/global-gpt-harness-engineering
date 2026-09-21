from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.production_full_plan_runner import FullPlanResult, ProductionFullPlanError
from runtime.orchestrator.ocpv2_canonical_resume import (
    CanonicalRemoteResumeError,
    execute_registered_full_plan_continuation,
)


STATE_SHA = "a" * 64
RUNTIME_SHA = "b" * 64
SOURCE_HEAD = "c" * 40


class FakeSupervisor:
    def __init__(self):
        self.state = {
            "project_id": "P1",
            "run_id": "R1",
            "current_gate": "G1",
            "state": "READY",
            "state_sha256": STATE_SHA,
            "epoch": 2,
            "continuation_owner": {"gate_id": "G1", "epoch": 3},
            "queue": [{
                "gate_id": "G1",
                "gate_run_id": "R1--g1",
                "status": "READY",
            }],
        }
        self.persist_calls = 0
        self.run_calls = 0
        self.locked = False

    def _acquire_run_lock(self):
        self.locked = True
        return object()

    def _release_run_lock(self, _handle):
        self.locked = False

    def load(self):
        return dict(self.state), False

    def _persist(self, state, event, *, semantic=True):
        self.assert_locked()
        self.persist_calls += 1
        self.state = dict(state)
        self.state["state_sha256"] = "d" * 64
        return dict(self.state)

    def _run_locked(self, executor, *, preflight=None):
        self.assert_locked()
        self.run_calls += 1
        if preflight is not None:
            verdict = preflight({"state": dict(self.state)})
            if verdict.get("status") != "PASS":
                raise AssertionError("unexpected preflight block")
        return FullPlanResult("WAITING_APPROVAL", dict(self.state), ("G1",), False)

    def assert_locked(self):
        if not self.locked:
            raise AssertionError("canonical resume escaped Full Plan run lock")


class OCPv2RegisteredFullPlanResumeTests(unittest.TestCase):
    def invoke(self, root: Path, supervisor: FakeSupervisor, *, expected_owner_epoch=4,
               task_id="G1", task_execution_id="R1--g1"):
        job_path = root / "_workspace" / "production-full-plan-jobs" / "P1" / "R1.job.json"
        job_path.parent.mkdir(parents=True, exist_ok=True)
        job_path.write_text("{}\n", encoding="utf-8")
        job = {
            "project_id": "P1",
            "run_id": "R1",
            "project_root": str(root / "project"),
            "harness_root": str(root),
            "harness_state_root": str(root),
            "gates": [{"gate_id": "G1"}],
            "policy": {},
            "authority_core_sha256": "e" * 64,
            "executor_runtime_identity": {"runtime_source_sha256": RUNTIME_SHA},
        }
        (root / "project").mkdir(exist_ok=True)
        with (
            patch("runtime.orchestrator.ocpv2_canonical_resume.load_registered_job", return_value=job),
            patch("runtime.orchestrator.ocpv2_canonical_resume.canonical_job_path", return_value=job_path),
            patch("runtime.orchestrator.ocpv2_canonical_resume.DurableFullPlanSupervisor", return_value=supervisor),
            patch("runtime.orchestrator.ocpv2_canonical_resume.build_gate_executor", return_value=lambda *_: {}),
            patch("runtime.orchestrator.ocpv2_canonical_resume.preflight_job", return_value={"status": "PASS"}),
        ):
            return execute_registered_full_plan_continuation(
                harness_state_root=root,
                project_id="P1",
                run_id="R1",
                gate_id="G1",
                task_id=task_id,
                task_execution_id=task_execution_id,
                expected_state_sha256=STATE_SHA,
                expected_owner_epoch=expected_owner_epoch,
                expected_source_head=SOURCE_HEAD,
                expected_runtime_release_digest=RUNTIME_SHA,
                current_project_head=lambda _job: SOURCE_HEAD,
                current_runtime_release_digest=lambda _job: RUNTIME_SHA,
            )

    def test_exact_registered_job_binding_resumes_under_same_lock(self):
        with tempfile.TemporaryDirectory() as td:
            supervisor = FakeSupervisor()
            result = self.invoke(Path(td), supervisor)
        self.assertEqual(result["status"], "WAITING_APPROVAL")
        self.assertEqual(result["result_class"], "CANONICAL_FULL_PLAN_RESULT")
        self.assertEqual(supervisor.persist_calls, 1)
        self.assertEqual(supervisor.run_calls, 1)
        self.assertEqual(supervisor.state["continuation_owner"]["epoch"], 4)

    def test_stale_expected_owner_epoch_changes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            supervisor = FakeSupervisor()
            with self.assertRaisesRegex(ProductionFullPlanError, "STALE_DIRECTIVE: continuation owner epoch mismatch"):
                self.invoke(Path(td), supervisor, expected_owner_epoch=9)
        self.assertEqual(supervisor.persist_calls, 0)
        self.assertEqual(supervisor.run_calls, 0)
        self.assertEqual(supervisor.state["continuation_owner"]["epoch"], 3)

    def test_task_binding_must_match_active_gate_and_gate_run_id(self):
        with tempfile.TemporaryDirectory() as td:
            supervisor = FakeSupervisor()
            with self.assertRaisesRegex(CanonicalRemoteResumeError, "TASK_BINDING_MISMATCH"):
                self.invoke(Path(td), supervisor, task_id="OTHER")
        self.assertEqual(supervisor.persist_calls, 0)
        self.assertEqual(supervisor.run_calls, 0)

    def test_module_has_no_job_registration_path(self):
        import runtime.orchestrator.ocpv2_canonical_resume as module
        source = inspect.getsource(module)
        self.assertNotIn("register_job(", source)
        self.assertNotIn("subprocess.Popen", source)
        self.assertNotIn("os.system", source)


if __name__ == "__main__":
    unittest.main()
