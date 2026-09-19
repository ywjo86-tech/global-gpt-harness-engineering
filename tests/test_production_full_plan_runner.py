from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from runtime.orchestrator.production_full_plan_runner import (
    DurableFullPlanSupervisor,
    ProductionFullPlanError,
    _failure_class,
    run_production_full_plan,
)


def completed(gate_id: str, gate_run_id: str, resume: bool):
    return {"status": "GATE_EXIT", "gate_id": gate_id, "run_id": gate_run_id, "resume": resume,
            "next": {"action": "SYSTEM_TRANSITION", "automatic": True}}


def provider_wait(gate_id: str, gate_run_id: str, resume: bool):
    return {"status": "WAITING_PROVIDER", "reason": "quota", "gate_id": gate_id}


def approval_wait(gate_id: str, gate_run_id: str, resume: bool):
    return {"status": "GATE_EXIT", "next": {"action": "WAIT_FOR_NEXT_GATE_USER_APPROVAL"}}


def always_fail(gate_id: str, gate_run_id: str, resume: bool):
    raise RuntimeError("boom")


def always_hang(gate_id: str, gate_run_id: str, resume: bool):
    time.sleep(2)
    return completed(gate_id, gate_run_id, resume)


def timeout_then_resume(gate_id: str, gate_run_id: str, resume: bool):
    if not resume:
        time.sleep(2)
    return completed(gate_id, gate_run_id, resume)


class ProductionFullPlanRunnerTests(unittest.TestCase):
    def supervisor(self, root, **kw):
        return DurableFullPlanSupervisor(
            root, project_id="proj", run_id="run", gates=kw.pop("gates", ["G1", "G2", "G3"]),
            gate_timeout_seconds=kw.pop("gate_timeout_seconds", 0.25),
            heartbeat_seconds=kw.pop("heartbeat_seconds", 0.03), lease_seconds=kw.pop("lease_seconds", 0.08),
            min_disk_free_bytes=kw.pop("min_disk_free_bytes", 0), min_inode_free=kw.pop("min_inode_free", 0),
            **kw,
        )

    def test_01_real_cross_gate_full_plan_completes_three_gates(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.supervisor(d).run(completed)
            self.assertEqual(out.status, "COMPLETED")
            self.assertEqual(out.state["completed_gates"], ["G1", "G2", "G3"])
            self.assertEqual(out.executed_gates, ("G1", "G2", "G3"))

    def test_02_gate_completion_and_successor_intent_are_same_state_generation(self):
        with tempfile.TemporaryDirectory() as d:
            def executor(gate_id, gate_run_id, resume):
                return completed(gate_id, gate_run_id, resume) if gate_id == "G1" else approval_wait(gate_id, gate_run_id, resume)
            out = self.supervisor(d).run(executor)
            self.assertEqual(out.status, "WAITING_APPROVAL")
            self.assertEqual(out.state["completed_gates"], ["G1"])
            self.assertEqual([x["gate_id"] for x in out.state["queue"]], ["G1", "G2"])
            self.assertEqual(out.state["queue"][1]["status"], "READY")

    def test_03_startup_reconciles_interrupted_running_gate(self):
        with tempfile.TemporaryDirectory() as d:
            sup = self.supervisor(d, gates=["G1"])
            state, _ = sup.load(); item = state["queue"][0]
            state["state"] = "RUNNING"; item["status"] = "RUNNING"; state["lease"] = {"epoch": 1}
            sup._persist(state, {"event": "TEST_CRASH_POINT"})
            seen = []
            def executor(gate_id, gate_run_id, resume):
                seen.append(resume); return completed(gate_id, gate_run_id, resume)
            out = self.supervisor(d, gates=["G1"]).run(executor)
            self.assertEqual(out.status, "COMPLETED"); self.assertTrue(out.recovered_on_startup)
            self.assertEqual(seen, [])  # child-process memory is intentionally isolated
            self.assertTrue(out.state["queue"][0]["resume"])

    def test_04_live_but_hung_gate_times_out_and_resumes(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.supervisor(d, gates=["G1"], retry_budget=1).run(timeout_then_resume)
            self.assertEqual(out.status, "COMPLETED")
            self.assertEqual(out.state["queue"][0]["attempt"], 2)
            self.assertTrue(out.state["queue"][0]["resume"])

    def test_completed_queue_item_clears_prior_error(self):
        with tempfile.TemporaryDirectory() as d:
            sup = self.supervisor(d, gates=["G1"])
            first = sup.run(provider_wait)
            self.assertEqual(first.status, "WAITING_PROVIDER")
            self.assertTrue(first.state["queue"][0]["last_error"])
            sup.resume_wait("WAITING_PROVIDER")
            completed_run = self.supervisor(d, gates=["G1"]).run(completed)
            self.assertEqual(completed_run.status, "COMPLETED")
            self.assertIsNone(completed_run.state["queue"][0]["last_error"])
            self.assertIsNone(completed_run.state["last_error"])

    def test_05_retry_exhaustion_is_dead_letter_blocked_not_silent(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.supervisor(d, gates=["G1"], retry_budget=0).run(always_fail)
            self.assertEqual(out.status, "BLOCKED")
            self.assertEqual(out.state["terminal_reason"], "RETRY_BUDGET_EXHAUSTED")
            self.assertEqual(len(out.state["dead_letter"]), 1)

    def test_06_timeout_exhaustion_is_explicit_block(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.supervisor(d, gates=["G1"], retry_budget=0, gate_timeout_seconds=0.08,
                                  heartbeat_seconds=0.01, lease_seconds=0.03).run(always_hang)
            self.assertEqual(out.status, "BLOCKED")
            self.assertIn("TIMEOUT", out.state["dead_letter"][0]["reason"])

    def test_07_provider_wait_is_typed_and_resumable(self):
        with tempfile.TemporaryDirectory() as d:
            sup = self.supervisor(d, gates=["G1"])
            out = sup.run(provider_wait)
            self.assertEqual(out.status, "WAITING_PROVIDER")
            sup.resume_wait("WAITING_PROVIDER")
            resumed = self.supervisor(d, gates=["G1"]).run(completed)
            self.assertEqual(resumed.status, "COMPLETED")

    def test_07a_project_name_does_not_misclassify_review_failure_as_provider(self):
        reason = (
            "REVIEW verdict is FAIL at /tmp/MULTI_PROVIDER_FOUNDATION/TASK-015: "
            "owned Python test/module scope is missing"
        )
        self.assertEqual(_failure_class(reason), "EXECUTION_FAILURE")

    def test_07b_canonical_codex_readiness_is_provider_failure(self):
        reason = "registered worker failed (production): canonical Worker authority blocked: pre-collected Codex readiness evidence is required"
        self.assertEqual(_failure_class(reason), "PROVIDER_FAILURE")

    def test_08_user_approval_wait_is_not_bypassed(self):
        with tempfile.TemporaryDirectory() as d:
            sup = self.supervisor(d, gates=["G1"])
            out = sup.run(approval_wait)
            self.assertEqual(out.status, "WAITING_APPROVAL")
            self.assertEqual(out.state["completed_gates"], [])

            event = sup.attention_outbox.pending()[0]
            self.assertEqual(event.get("delivery_class"), "IMMEDIATE_DECISION")

    def test_08a_provider_and_resource_incidents_are_deferred(self):
        with tempfile.TemporaryDirectory() as d:
            provider_sup = self.supervisor(d, gates=["G1"])
            self.assertEqual(provider_sup.run(provider_wait).status, "WAITING_PROVIDER")
            self.assertEqual(provider_sup.attention_outbox.pending()[0].get("delivery_class"), "DEFERRED_INCIDENT")
        with tempfile.TemporaryDirectory() as d:
            low = lambda _: {"disk_free_bytes": 1, "inode_free": 1}
            resource_sup = self.supervisor(d, gates=["G1"], min_disk_free_bytes=10, min_inode_free=10, resource_probe=low)
            self.assertEqual(resource_sup.run(completed).status, "WAITING_RESOURCE")
            self.assertEqual(resource_sup.attention_outbox.pending()[0].get("delivery_class"), "DEFERRED_INCIDENT")

    def test_08b_dead_letter_is_deferred_but_stall_is_confirmed(self):
        with tempfile.TemporaryDirectory() as d:
            sup = self.supervisor(d, gates=["G1"], retry_budget=0)
            self.assertEqual(sup.run(always_fail).status, "BLOCKED")
            self.assertEqual(sup.attention_outbox.pending()[0].get("delivery_class"), "DEFERRED_INCIDENT")
        with tempfile.TemporaryDirectory() as d:
            sup = self.supervisor(
                d, gates=["G1"], retry_budget=0, gate_timeout_seconds=0.12,
                heartbeat_seconds=0.01, lease_seconds=0.03, stall_alert_seconds=0.04,
            )
            sup.run(always_hang)
            stalled = [event for event in sup.attention_outbox.pending() if event["kind"] == "STALLED_SUSPECTED"]
            self.assertEqual(stalled[0].get("delivery_class"), "STALL_CONFIRMED")

    def test_09_resource_pressure_applies_backpressure(self):
        with tempfile.TemporaryDirectory() as d:
            probe = lambda _: {"disk_free_bytes": 1, "inode_free": 1}
            sup = self.supervisor(d, gates=["G1"], min_disk_free_bytes=10, min_inode_free=10, resource_probe=probe)
            out = sup.run(completed)
            self.assertEqual(out.status, "WAITING_RESOURCE")
            self.assertEqual(out.executed_gates, ())

    def test_10_resource_wait_can_resume_after_pressure_clears(self):
        with tempfile.TemporaryDirectory() as d:
            low = lambda _: {"disk_free_bytes": 1, "inode_free": 1}
            sup = self.supervisor(d, gates=["G1"], min_disk_free_bytes=10, min_inode_free=10, resource_probe=low)
            self.assertEqual(sup.run(completed).status, "WAITING_RESOURCE")
            sup.resume_wait("WAITING_RESOURCE")
            high = lambda _: {"disk_free_bytes": 100, "inode_free": 100}
            out = self.supervisor(d, gates=["G1"], min_disk_free_bytes=10, min_inode_free=10, resource_probe=high).run(completed)
            self.assertEqual(out.status, "COMPLETED")

    def test_11_duplicate_gate_plan_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ProductionFullPlanError):
                self.supervisor(d, gates=["G1", "G1"])

    def test_12_schema_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            sup = self.supervisor(d, gates=["G1"]); state, _ = sup.load(); sup._persist(state, {"event": "INIT"})
            payload = json.loads(sup.state_path.read_text()); payload["schema_version"] = "future"
            sup.state_path.write_text(json.dumps(payload))
            sup.state_path.with_suffix(".json.prev").unlink(missing_ok=True)
            with self.assertRaises(ProductionFullPlanError): self.supervisor(d, gates=["G1"]).load()

    def test_13_corrupt_primary_recovers_previous_good_generation(self):
        with tempfile.TemporaryDirectory() as d:
            sup = self.supervisor(d, gates=["G1"]); state, _ = sup.load()
            sup._persist(state, {"event": "GEN1"}); state["last_error"] = "GEN2"; sup._persist(state, {"event": "GEN2"})
            sup.state_path.write_bytes(b"{broken")
            loaded, recovered = self.supervisor(d, gates=["G1"]).load()
            self.assertTrue(recovered); self.assertEqual(loaded["schema_version"], "orchestration.production-full-plan.v1")

    def test_14_preflight_block_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.supervisor(d, gates=["G1"]).run(completed, preflight=lambda _: {"status": "BLOCK", "reason": "missing pytest"})
            self.assertEqual(out.status, "BLOCKED"); self.assertEqual(out.state["terminal_reason"], "PREFLIGHT_BLOCKED")

    def test_15_preflight_provider_wait_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.supervisor(d, gates=["G1"]).run(completed, preflight=lambda _: {"status": "BLOCK", "state": "WAITING_PROVIDER", "reason": "quota"})
            self.assertEqual(out.status, "WAITING_PROVIDER")

    def test_16_gate_run_id_is_stable_across_retry_for_effect_reconciliation(self):
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / "effect.txt"
            def effect_then_timeout(gate_id, gate_run_id, resume):
                if not marker.exists(): marker.write_text(gate_run_id)
                if not resume: time.sleep(2)
                self.assertEqual(marker.read_text(), gate_run_id)
                return completed(gate_id, gate_run_id, resume)
            out = self.supervisor(d, gates=["G1"], retry_budget=1).run(effect_then_timeout)
            self.assertEqual(out.status, "COMPLETED")
            self.assertEqual(marker.read_text(), "run--g1")

    def test_17_production_entrypoint_is_not_fixture_only(self):
        with tempfile.TemporaryDirectory() as d:
            out = run_production_full_plan(harness_root=d, project_id="proj", run_id="prod", gates=["G1", "G2", "G3"],
                                           executor=completed, retry_budget=0, gate_timeout_seconds=1,
                                           heartbeat_seconds=.03, lease_seconds=.08,
                                           min_disk_free_bytes=0, min_inode_free=0)
            self.assertEqual(out["status"], "COMPLETED")
            self.assertEqual(out["state"]["completed_gates"], ["G1", "G2", "G3"])

    def test_18_no_silent_idle_state_when_successor_queue_missing(self):
        with tempfile.TemporaryDirectory() as d:
            sup = self.supervisor(d, gates=["G1", "G2"]); state, _ = sup.load()
            state["completed_gates"] = ["G1"]; state["queue"][0]["status"] = "COMPLETED"; state["current_gate"] = "G2"
            state["state"] = "READY"; sup._persist(state, {"event": "TEST_MISSING_SUCCESSOR"})
            out = self.supervisor(d, gates=["G1", "G2"]).run(completed)
            self.assertEqual(out.status, "BLOCKED")
            self.assertEqual(out.state["terminal_reason"], "DURABLE_SUCCESSOR_MISSING")
            self.assertTrue((Path(d)/"_workspace/production-full-plan/proj/run/alerts.jsonl").is_file())

    def test_19_cancel_is_explicit_terminal_state(self):
        with tempfile.TemporaryDirectory() as d:
            sup = self.supervisor(d, gates=["G1"]); state = sup.cancel("operator")
            self.assertEqual(state["state"], "CANCELLED"); self.assertEqual(state["terminal_reason"], "operator")

    def test_20_event_and_alert_evidence_are_durable(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.supervisor(d, gates=["G1"], retry_budget=0).run(always_fail)
            self.assertEqual(out.status, "BLOCKED")
            self.assertTrue((Path(d)/"_workspace/production-full-plan/proj/run/events.jsonl").is_file())
            self.assertTrue((Path(d)/"_workspace/production-full-plan/proj/run/alerts.jsonl").is_file())

    def test_21_memory_pressure_applies_backpressure(self):
        with tempfile.TemporaryDirectory() as d:
            probe = lambda _: {"disk_free_bytes": 100, "inode_free": 100, "memory_available_bytes": 1,
                               "cpu_load_per_cpu_milli": 1, "io_pressure_full_avg10_milli": 1}
            sup = self.supervisor(d, gates=["G1"], min_memory_available_bytes=10, resource_probe=probe)
            self.assertEqual(sup.run(completed).status, "WAITING_RESOURCE")

    def test_22_cpu_pressure_applies_backpressure(self):
        with tempfile.TemporaryDirectory() as d:
            probe = lambda _: {"disk_free_bytes": 100, "inode_free": 100, "memory_available_bytes": 100,
                               "cpu_load_per_cpu_milli": 5000, "io_pressure_full_avg10_milli": 1}
            sup = self.supervisor(d, gates=["G1"], max_cpu_load_per_cpu_milli=1000, resource_probe=probe)
            self.assertEqual(sup.run(completed).status, "WAITING_RESOURCE")

    def test_23_io_pressure_applies_backpressure(self):
        with tempfile.TemporaryDirectory() as d:
            probe = lambda _: {"disk_free_bytes": 100, "inode_free": 100, "memory_available_bytes": 100,
                               "cpu_load_per_cpu_milli": 1, "io_pressure_full_avg10_milli": 90000}
            sup = self.supervisor(d, gates=["G1"], max_io_pressure_full_avg10_milli=1000, resource_probe=probe)
            self.assertEqual(sup.run(completed).status, "WAITING_RESOURCE")

    def test_24_queue_pressure_applies_backpressure(self):
        with tempfile.TemporaryDirectory() as d:
            sup = self.supervisor(d, gates=["G1"], max_queue_depth=1)
            state, _ = sup.load()
            extra = dict(state["queue"][0]); extra["gate_id"] = "G2"; extra["idempotency_key"] = "extra"
            state["queue"].append(extra)
            ok, snapshot = sup._resource_gate(state)
            self.assertFalse(ok); self.assertEqual(snapshot["active_queue_depth"], 2)

    def test_25_step_budget_resume_required_is_reenqueued(self):
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / "attempt"
            def executor(gate_id, gate_run_id, resume):
                if not marker.exists():
                    marker.write_text("1")
                    return {"status": "GATE_EXECUTION_RESUME_REQUIRED"}
                return completed(gate_id, gate_run_id, resume)
            out = self.supervisor(d, gates=["G1"], retry_budget=1).run(executor)
            self.assertEqual(out.status, "COMPLETED")
            self.assertEqual(out.state["queue"][0]["attempt"], 2)
            self.assertTrue(out.state["queue"][0]["resume"])

    def test_26_authority_core_drift_is_rejected_on_reload(self):
        with tempfile.TemporaryDirectory() as d:
            sup = self.supervisor(d, gates=["G1"], authority_core_sha256="a" * 64)
            state, _ = sup.load(); sup._persist(state, {"event": "SEALED"})
            with self.assertRaisesRegex(ProductionFullPlanError, "RUN_AUTHORITY_DRIFT"):
                self.supervisor(d, gates=["G1"], authority_core_sha256="b" * 64).load()

    def test_27_heartbeat_does_not_count_as_semantic_progress_and_stall_is_alerted(self):
        with tempfile.TemporaryDirectory() as d:
            out = self.supervisor(
                d, gates=["G1"], retry_budget=0, gate_timeout_seconds=0.12,
                heartbeat_seconds=0.01, lease_seconds=0.03, stall_alert_seconds=0.04,
            ).run(always_hang)
            self.assertEqual(out.status, "BLOCKED")
            events = (Path(d)/"_workspace/production-full-plan/proj/run/events.jsonl").read_text()
            self.assertIn('"event":"HEARTBEAT"', events)
            self.assertIn('"event":"STALLED_SUSPECTED"', events)
            attention_dir = Path(d)/"_workspace/production-full-plan/proj/run/attention/pending"
            kinds = {json.loads(path.read_text())["kind"] for path in attention_dir.glob("*.json")}
            self.assertIn("STALLED_SUSPECTED", kinds)


if __name__ == "__main__":
    unittest.main()
