import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from runtime.orchestrator.gate_orchestrator import (
    FULL_PLAN,
    GateLV,
    GatePlan,
    _publish_recovery_canonical_completion,
    _sealed_completed_lv_lineage,
    create_gate_authorization,
)
from runtime.orchestrator.lv_execution_package import canonical_json_bytes


def seal(payload, field):
    payload[field] = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return payload


class RecoveryCanonicalBridgeTests(unittest.TestCase):
    def test_completed_recovery_projects_canonical_lineage_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = base / "project"; project.mkdir()
            harness = base / "harness"; harness.mkdir()
            subprocess.run(["git", "-C", str(project), "init", "-b", "main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(project), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(project), "config", "user.email", "test@example.com"], check=True)
            (project / "app").mkdir()
            owned = project / "app/model.py"
            owned.write_text("baseline\n", encoding="utf-8")
            (project / "PLAN.md").write_text("plan\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(project), "add", "."], check=True)
            subprocess.run(["git", "-C", str(project), "commit", "-m", "base"], check=True, capture_output=True)
            baseline = subprocess.run(
                ["git", "-C", str(project), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
            ).stdout.strip()

            owned.write_text("partial\n", encoding="utf-8")
            partial_sha = hashlib.sha256(owned.read_bytes()).hexdigest()
            lv = GateLV(
                "GATE-1", "TASK-006", 1, "runner", [], ["app/model.py"], ["pass"],
                "STATE_CHANGING", ["pass"], required_capabilities=["implementation"],
            )
            plan = GatePlan("project", str(project), "GATE-1", str(project / "PLAN.md"), "a" * 64, [lv])
            auth = create_gate_authorization(
                plan, "AUTH-1", mode=FULL_PLAN,
                full_plan_opt_in=True, project_final_validation=True,
            )
            run_id = "run-1"
            source = {
                "schema_version": "orchestration.pre-result-partial-source.v1",
                "project_id": "project", "gate_id": "GATE-1", "lv_id": "TASK-006", "run_id": run_id,
                "canonical_plan_sha256": "a" * 64, "approval_event_id": "APR-1", "attempt": 1,
                "branch": "main", "baseline_head": baseline, "source_head": baseline, "current_head": baseline,
                "owned_files": ["app/model.py"], "owned_diff": {"app/model.py": partial_sha},
                "governed_write_effects": [], "tool_effect_artifacts": {}, "failure": {}, "hard_stop": True,
            }
            seal(source, "source_payload_sha256")
            source_path = harness / "_workspace/orchestration-runs" / run_id / "TASK-006/pre-result-partial-source.json"
            source_path.parent.mkdir(parents=True)
            source_path.write_bytes(canonical_json_bytes(source))
            source_file_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()

            owned.write_text("complete\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(project), "add", "app/model.py"], check=True)
            subprocess.run(["git", "-C", str(project), "commit", "-m", "checkpoint"], check=True, capture_output=True)
            current = subprocess.run(
                ["git", "-C", str(project), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
            ).stdout.strip()

            record = {
                "schema_version": "orchestration.production-recovery.v1",
                "project_id": "project", "gate_id": "GATE-1", "lv_id": "TASK-006", "run_id": run_id,
                "recovery_id": "recovery-04", "recovery_attempt": 4, "rejected_attempt": 3,
                "approval_event_id": "APR-1", "plan_sha256": "a" * 64, "branch": "main",
                "baseline_head": baseline, "current_head": baseline,
                "active_transition_sha256": source_file_sha, "source_binding_kind": "PRE_RESULT_PARTIAL_SOURCE",
                "source_shas": {source_path.relative_to(harness).as_posix(): source_file_sha}, "hard_stop": True,
            }
            seal(record, "record_hash")
            control = {
                "schema_version": "orchestration.production-recovery-checkpoint.v1",
                "project_id": "project", "gate_id": "GATE-1", "lv_id": "TASK-006", "run_id": run_id,
                "recovery_id": "recovery-04", "recovery_record_hash": record["record_hash"],
                "rejected_attempt": 3, "next_attempt": 4, "completion_evidence": [],
                "status": "REJECTED_RECOVERY_ATTEMPT_INCOMPLETE",
                "source_binding_kind": "PRE_RESULT_PARTIAL_SOURCE", "hard_stop": True,
            }
            seal(control, "checkpoint_sha256")
            binding = {
                "project_id": "project", "gate_id": "GATE-1", "lv_id": "TASK-006", "run_id": run_id,
                "recovery_id": "recovery-04", "attempt": 4, "canonical_plan_sha256": "a" * 64,
                "approval_event_id": "APR-1", "active_transition_sha256": source_file_sha,
                "recovery_record_hash": record["record_hash"],
                "recovery_checkpoint_sha256": control["checkpoint_sha256"], "hard_stop": True,
            }
            package = {"schema_version": "orchestration.recovery-package.v1", **binding}
            seal(package, "package_sha256")
            preflight = {"schema_version": "orchestration.recovery-preflight.v1", **binding,
                         "package_sha256": package["package_sha256"], "status": "READY"}
            seal(preflight, "preflight_sha256")
            worker = {"schema_version": "orchestration.recovery-worker-result.v1", **binding,
                      "package_sha256": package["package_sha256"], "preflight_sha256": preflight["preflight_sha256"],
                      "preflight_evidence_sha256": preflight["preflight_sha256"], "status": "completed",
                      "baseline_head": baseline, "current_head": current, "checkpoint_commit": current,
                      "changed_files": ["app/model.py"], "tests": [{"status": "PASS"}]}
            seal(worker, "worker_result_sha256")
            review = {"schema_version": "orchestration.recovery-review.v1", **binding,
                      "worker_result_sha256": worker["worker_result_sha256"], "verdict": "PASS"}
            seal(review, "review_sha256")
            checkpoint = {"schema_version": "orchestration.recovery-lifecycle-checkpoint.v1", **binding,
                          "consumption_sha256": "c" * 64, "status": "CHECKPOINTED"}
            seal(checkpoint, "lifecycle_checkpoint_sha256")
            lv_exit = {"schema_version": "orchestration.recovery-lv-exit.v1", **binding,
                       "lifecycle_checkpoint_sha256": checkpoint["lifecycle_checkpoint_sha256"], "status": "EXITED"}
            seal(lv_exit, "lv_exit_sha256")
            gate_exit = {"schema_version": "orchestration.recovery-gate-exit.v1", **binding,
                         "lv_exit_sha256": lv_exit["lv_exit_sha256"], "status": "EXITED",
                         "next_gate_status": "USER_APPROVAL_REQUIRED"}
            seal(gate_exit, "gate_exit_sha256")
            recovery_handoff = {"schema_version": "orchestration.recovery-handoff.v1", **binding,
                                "lifecycle_checkpoint_sha256": checkpoint["lifecycle_checkpoint_sha256"],
                                "lv_exit_sha256": lv_exit["lv_exit_sha256"], "remaining_lvs": [], "next_lv": None,
                                "gate_complete": True, "gate_exit_sha256": gate_exit["gate_exit_sha256"],
                                "next_gate_status": "USER_APPROVAL_REQUIRED", "status": "SEALED"}
            seal(recovery_handoff, "handoff_sha256")
            recovery = {"recovery": record, "checkpoint": control, "next_attempt": 4,
                        "classification": {"completion_eligible": False}}
            outcome = {"package": package, "preflight": preflight, "worker_result": worker}
            final = {"checkpoint": checkpoint, "lv_exit": lv_exit, "gate_exit": gate_exit,
                     "handoff": recovery_handoff}
            context = {"requirements_sha256": "b" * 64, "completed_plan_items": [], "remaining_plan_items": []}

            handoff = _publish_recovery_canonical_completion(
                project, harness, plan, auth, lv_id="TASK-006", run_id=run_id, context=context,
                recovery=recovery, outcome=outcome, review=review, final=final,
            )
            lineage = _sealed_completed_lv_lineage(
                project, harness, plan, auth, lv_id="TASK-006", run_id=run_id, current_head=current,
            )
            self.assertEqual(lineage["current_head"], current)
            self.assertEqual(lineage["handoff_sha256"], handoff["handoff_sha256"])
            self.assertEqual(
                _publish_recovery_canonical_completion(
                    project, harness, plan, auth, lv_id="TASK-006", run_id=run_id, context=context,
                    recovery=recovery, outcome=outcome, review=review, final=final,
                )["handoff_sha256"],
                handoff["handoff_sha256"],
            )

            bad_control = dict(control); bad_control["project_id"] = "other"; bad_control.pop("checkpoint_sha256"); seal(bad_control, "checkpoint_sha256")
            bad_recovery = dict(recovery, checkpoint=bad_control)
            with self.assertRaisesRegex(Exception, "control binding mismatch"):
                _publish_recovery_canonical_completion(
                    project, harness, plan, auth, lv_id="TASK-006", run_id=run_id, context=context,
                    recovery=bad_recovery, outcome=outcome, review=review, final=final,
                )

            source_path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(Exception, "source evidence is unsafe"):
                _publish_recovery_canonical_completion(
                    project, harness, plan, auth, lv_id="TASK-006", run_id=run_id, context=context,
                    recovery=recovery, outcome=outcome, review=review, final=final,
                )


if __name__ == "__main__":
    unittest.main()
