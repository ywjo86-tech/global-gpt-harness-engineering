from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.harness_state_root import job_state_root
from runtime.orchestrator.live_auto_canary import LiveAutoCanary
from runtime.orchestrator.production_full_plan_entry import load_registered_job
from runtime.orchestrator.production_full_plan_runner import (
    DurableFullPlanSupervisor,
    FullPlanResult,
    ProductionFullPlanError,
)
from runtime.orchestrator.ocpv2_canonical_resume import (
    CanonicalRemoteResumeError,
    execute_registered_full_plan_continuation,
)


STATE_SHA = "a" * 64
RUNTIME_SHA = "b" * 64
SOURCE_HEAD = "c" * 40
MESSAGE_ID = "MSG-R1-G1"
DIRECTIVE_DIGEST = "f" * 64


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
                remote_message_id=MESSAGE_ID,
                remote_directive_digest=DIRECTIVE_DIGEST,
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
        owner = supervisor.state["continuation_owner"]
        self.assertEqual(owner["epoch"], 4)
        self.assertEqual(owner["source"], "OCPV2")
        self.assertEqual(owner["message_id"], MESSAGE_ID)
        self.assertEqual(owner["directive_digest"], DIRECTIVE_DIGEST)
        self.assertEqual(owner["task_execution_id"], "R1--g1")

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

    def test_fresh_materialized_state_is_accepted_by_real_supervisor(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime_root = Path(__file__).resolve().parents[1]
            run_id = "OCP-REAL-FRESH-CAS"
            canary = LiveAutoCanary(root, runtime_code_root=runtime_root, run_id=run_id)
            job_path = canary.prepare()
            job = load_registered_job(job_path)
            gate_ids = [str(item["gate_id"]) for item in job["gates"]]
            supervisor = DurableFullPlanSupervisor(
                job_state_root(job),
                project_id=job["project_id"],
                run_id=job["run_id"],
                gates=gate_ids,
                authority_core_sha256=str(job["authority_core_sha256"]),
                **dict(job.get("policy") or {}),
            )
            initial, recovered = supervisor.load()
            self.assertFalse(recovered)
            self.assertTrue(supervisor.state_path.is_file())

            result = execute_registered_full_plan_continuation(
                harness_state_root=root,
                project_id=job["project_id"],
                run_id=job["run_id"],
                gate_id="CANARY-A",
                task_id="CANARY-A",
                task_execution_id=f"{run_id}--canary-a",
                expected_state_sha256=initial["state_sha256"],
                expected_owner_epoch=1,
                expected_source_head=SOURCE_HEAD,
                expected_runtime_release_digest=RUNTIME_SHA,
                remote_message_id="MSG-REAL-FRESH-CAS",
                remote_directive_digest=DIRECTIVE_DIGEST,
                current_project_head=lambda _job: SOURCE_HEAD,
                current_runtime_release_digest=lambda _job: RUNTIME_SHA,
            )

            self.assertEqual(result["result_class"], "CANONICAL_FULL_PLAN_RESULT")
            self.assertEqual(result["status"], "COMPLETED")
            self.assertEqual(result["executed_gates"], ["CANARY-A", "CANARY-B", "CANARY-C"])
            self.assertEqual(
                [receipt["gate_id"] for receipt in canary.load_receipts()],
                ["CANARY-A", "CANARY-B", "CANARY-C"],
            )
            owner = canary.load_state()["continuation_owner"]
            self.assertEqual(owner["message_id"], "MSG-REAL-FRESH-CAS")
            self.assertEqual(owner["directive_digest"], DIRECTIVE_DIGEST)
            self.assertEqual(owner["source"], "OCPV2")

    def test_module_has_no_job_registration_path(self):
        import runtime.orchestrator.ocpv2_canonical_resume as module
        source = inspect.getsource(module)
        self.assertNotIn("register_job(", source)
        self.assertNotIn("subprocess.Popen", source)
        self.assertNotIn("os.system", source)


if __name__ == "__main__":
    unittest.main()
