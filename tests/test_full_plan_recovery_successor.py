import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.orchestrator.full_plan_recovery_successor import _build_successor_job
from runtime.orchestrator.production_full_plan_entry import (
    FullPlanJobError, load_job, preflight_job, register_job,
)
from runtime.orchestrator.production_full_plan_runner import (
    DurableFullPlanSupervisor,
    ProductionFullPlanError,
    RECOVERY_SUCCESSOR_BINDING_SCHEMA,
    validate_recovery_successor_binding,
)
from runtime.orchestrator.production_run_authority import (
    AUTO_RECONCILE_OWNER,
    seal_authority_core,
    validate_authority_core,
)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def binding(*, predecessor_state_sha="b" * 64):
    value = {
        "schema_version": RECOVERY_SUCCESSOR_BINDING_SCHEMA,
        "project_id": "proj",
        "successor_run_id": "run-successor",
        "predecessor_run_id": "run-predecessor",
        "predecessor_authority_sha256": "a" * 64,
        "predecessor_state_sha256": predecessor_state_sha,
        "gate_id": "G1",
        "predecessor_gate_run_id": "run-predecessor--g1",
        "current_head": "c" * 40,
        "recovery_id": "run-predecessor--g1-task-006-recovery-03",
        "recovery_record_hash": "d" * 64,
        "recovery_checkpoint_sha256": "e" * 64,
        "recovery_source_payload_sha256": "f" * 64,
        "target_runtime_release_digest": "1" * 64,
        "target_runtime_source_head": "2" * 40,
        "approval_ref": "OCP-FULL-PLAN-TEST",
        "approval_proof_path": "_workspace/full-plan-human-approvals/proof.json",
        "approval_proof_sha256": "3" * 64,
    }
    value["binding_sha256"] = digest(value)
    return value


class RecoverySuccessorBindingTests(unittest.TestCase):
    def test_binding_digest_tamper_fails_closed(self):
        value = binding()
        validated = validate_recovery_successor_binding(
            value, project_id="proj", successor_run_id="run-successor"
        )
        self.assertEqual(validated, value)
        tampered = dict(value)
        tampered["current_head"] = "4" * 40
        with self.assertRaisesRegex(
            ProductionFullPlanError, "binding digest mismatch"
        ):
            validate_recovery_successor_binding(
                tampered, project_id="proj", successor_run_id="run-successor"
            )

    def test_successor_state_reuses_only_predecessor_gate_lineage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            predecessor = DurableFullPlanSupervisor(
                root,
                project_id="proj",
                run_id="run-predecessor",
                gates=["G1"],
                authority_core_sha256="a" * 64,
                min_disk_free_bytes=0,
                min_inode_free=0,
            )
            state, _ = predecessor.load()
            old_key = state["queue"][0]["idempotency_key"]
            state["queue"][0]["status"] = "BLOCKED"
            state["queue"][0]["resume"] = True
            state["queue"][0]["attempt"] = 2
            state["state"] = "BLOCKED"
            state["last_error"] = "SOURCE_HEAD_MISMATCH"
            state["terminal_reason"] = "PREFLIGHT_BLOCKED"
            state = predecessor._persist(state, {"event": "TEST_BLOCK"})

            successor = DurableFullPlanSupervisor(
                root,
                project_id="proj",
                run_id="run-successor",
                gates=["G1"],
                authority_core_sha256="9" * 64,
                min_disk_free_bytes=0,
                min_inode_free=0,
            )
            recovery_binding = binding(
                predecessor_state_sha=state["state_sha256"]
            )
            preview = successor.build_recovery_successor_state(
                predecessor_state=state,
                recovery_binding=recovery_binding,
            )
            self.assertEqual(preview["state"], "RECOVERING")
            self.assertEqual(preview["run_id"], "run-successor")
            self.assertEqual(
                preview["queue"][0]["gate_run_id"], "run-predecessor--g1"
            )
            self.assertNotEqual(
                preview["queue"][0]["idempotency_key"], old_key
            )
            self.assertEqual(preview["queue"][0]["attempt"], 3)
            self.assertTrue(preview["queue"][0]["resume"])
            self.assertEqual(
                preview["recovery_successor"], recovery_binding
            )

            seeded = successor.seed_recovery_successor(
                predecessor_state=state,
                recovery_binding=recovery_binding,
            )
            loaded, _ = successor.load()
            self.assertEqual(loaded, seeded)
            self.assertEqual(
                loaded["recovery_successor"]["binding_sha256"],
                recovery_binding["binding_sha256"],
            )

    def test_load_job_rejects_tampered_recovery_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = {
                "schema_version": "orchestration.production-full-plan-job.v1",
                "project_root": str(root),
                "harness_root": str(root),
                "project_id": "proj",
                "run_id": "run-successor",
                "gates": [{
                    "gate_id": "G1",
                    "approval_evidence": str(root / "approval.json"),
                    "requirements_sha256": "a" * 64,
                    "branch": "main",
                    "head": "b" * 40,
                    "full_plan_opt_in": True,
                    "project_final_validation": True,
                }],
                "recovery_successor": binding(),
            }
            job["recovery_successor"]["approval_ref"] = "TAMPERED"
            path = root / "job.json"
            path.write_text(json.dumps(job), encoding="utf-8")
            with self.assertRaisesRegex(
                FullPlanJobError, "binding digest mismatch"
            ):
                load_job(path)

    def test_successor_job_preserves_gate_authority_and_rebinds_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            state = root / "state"
            runtime = root / "runtime"
            for path in (project, state, runtime):
                path.mkdir()
            predecessor = {
                "schema_version": "orchestration.production-full-plan-job.v1",
                "execution_owner": AUTO_RECONCILE_OWNER,
                "project_root": str(project),
                "harness_root": str(state),
                "harness_state_root": str(state),
                "project_id": "proj",
                "run_id": "run-predecessor",
                "expected_branch": "main",
                "expected_head": "b" * 40,
                "approved_plan_path": str(project / "plan.txt"),
                "approved_plan_sha256": "4" * 64,
                "approved_spec_path": str(project / "spec.md"),
                "approved_spec_sha256": "5" * 64,
                "approval_ref": "OLD-APPROVAL",
                "runtime_code_root": str(root / "old-runtime"),
                "runtime_release_digest": "6" * 64,
                "runtime_release_source_head": "7" * 40,
                "activation_binding_digest": "8" * 64,
                "executable_authority_bundle_digest": "9" * 64,
                "ai_office_context_digest": "0" * 64,
                "lifecycle_binding": {
                    "schema_version": "orchestration.lifecycle-binding.v1",
                    "lifecycle_mode": "V2",
                    "bound_at_activation": True,
                    "migration_allowed": False,
                    "runtime_release_digest": "6" * 64,
                },
                "gates": [{
                    "gate_id": "G1",
                    "approval_evidence": str(state / "approval.json"),
                    "approval_evidence_sha256": "a" * 64,
                    "requirements_sha256": "4" * 64,
                    "branch": "main",
                    "head": "b" * 40,
                    "full_plan_opt_in": True,
                    "project_final_validation": True,
                    "requirement_evidence_paths_by_lv": {
                        "TASK-006": str(project / "req.json")
                    },
                    "requirement_evidence_sha256_by_lv": {
                        "TASK-006": "c" * 64
                    },
                }],
            }
            recovery_binding = binding()
            fake_identity = {
                "schema_version": "orchestration.executor-runtime-identity.v1",
                "root": str(runtime),
                "head": "",
                "branch": "",
                "git_common_dir": "",
                "runtime_source_sha256": "d" * 64,
            }
            with patch(
                "runtime.orchestrator.full_plan_recovery_successor.executor_runtime_identity",
                return_value=fake_identity,
            ):
                successor = _build_successor_job(
                    predecessor,
                    binding=recovery_binding,
                    runtime_code_root=runtime,
                )
            self.assertEqual(successor["gates"], predecessor["gates"])
            self.assertEqual(successor["expected_head"], predecessor["expected_head"])
            self.assertEqual(successor["run_id"], "run-successor")
            self.assertEqual(successor["approval_ref"], "OCP-FULL-PLAN-TEST")
            self.assertEqual(
                successor["runtime_release_digest"],
                recovery_binding["target_runtime_release_digest"],
            )
            self.assertEqual(
                successor["activation_binding_digest"],
                recovery_binding["binding_sha256"],
            )
            self.assertEqual(
                successor["execution_authority_bundle"]["activation_source_head"],
                predecessor["expected_head"],
            )
            self.assertEqual(
                successor["execution_authority_bundle"]["runtime_release_digest"],
                recovery_binding["target_runtime_release_digest"],
            )
            self.assertEqual(
                successor["execution_authority_bundle"]["approval_ref"],
                recovery_binding["approval_ref"],
            )
            self.assertEqual(
                validate_authority_core(successor),
                successor["authority_core_sha256"],
            )
            poisoned = json.loads(json.dumps(successor))
            poisoned["recovery_successor"]["current_head"] = "f" * 40
            with self.assertRaises(Exception):
                validate_authority_core(poisoned)


    def test_preflight_rechecks_sealed_predecessor_and_recovery_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            state_root = root / "state"
            runtime = root / "runtime"
            for path in (project, state_root, runtime):
                path.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main", str(project)], check=True)
            subprocess.run(["git", "-C", str(project), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(project), "config", "user.email", "test@example.invalid"], check=True)
            (project / "base.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(project), "add", "base.txt"], check=True)
            subprocess.run(["git", "-C", str(project), "commit", "-qm", "base"], check=True)
            baseline = subprocess.check_output(
                ["git", "-C", str(project), "rev-parse", "HEAD"], text=True
            ).strip()
            (project / "checkpoint.txt").write_text("checkpoint\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(project), "add", "checkpoint.txt"], check=True)
            subprocess.run(["git", "-C", str(project), "commit", "-qm", "checkpoint"], check=True)
            current = subprocess.check_output(
                ["git", "-C", str(project), "rev-parse", "HEAD"], text=True
            ).strip()

            proof_relative = Path("_workspace/full-plan-human-approvals/proof.json")
            proof_path = state_root / proof_relative
            proof_path.parent.mkdir(parents=True)
            proof_value = {
                "approval_ref": "OCP-FULL-PLAN-TEST",
                "status": "APPROVED",
                "proof": {"protected": "x", "payload": "y", "signature": "z"},
            }
            proof_path.write_text(
                json.dumps(proof_value, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            proof_sha = hashlib.sha256(proof_path.read_bytes()).hexdigest()

            fake_identity = {
                "schema_version": "orchestration.executor-runtime-identity.v1",
                "root": str(runtime),
                "head": "",
                "branch": "",
                "git_common_dir": "",
                "runtime_source_sha256": "9" * 64,
            }
            predecessor = seal_authority_core({
                "schema_version": "orchestration.production-full-plan-job.v1",
                "execution_owner": AUTO_RECONCILE_OWNER,
                "project_root": str(project),
                "harness_root": str(state_root),
                "harness_state_root": str(state_root),
                "project_id": "proj",
                "run_id": "run-predecessor",
                "expected_branch": "main",
                "expected_head": baseline,
                "required_executables": ["git"],
                "executor_runtime_identity": fake_identity,
                "gates": [{
                    "gate_id": "G1",
                    "approval_evidence": str(state_root / "approval.json"),
                    "requirements_sha256": "a" * 64,
                    "branch": "main",
                    "head": baseline,
                    "full_plan_opt_in": True,
                    "project_final_validation": True,
                }],
            })
            predecessor_path = register_job(predecessor)
            predecessor = load_job(predecessor_path)
            pred_sup = DurableFullPlanSupervisor(
                state_root,
                project_id="proj",
                run_id="run-predecessor",
                gates=["G1"],
                authority_core_sha256=predecessor["authority_core_sha256"],
            )
            pred_state, _ = pred_sup.load()
            pred_state["queue"][0]["status"] = "BLOCKED"
            pred_state["queue"][0]["resume"] = True
            pred_state["queue"][0]["attempt"] = 2
            pred_state["state"] = "BLOCKED"
            pred_state["last_error"] = "SOURCE_HEAD_MISMATCH"
            pred_state["terminal_reason"] = "PREFLIGHT_BLOCKED"
            pred_state = pred_sup._persist(pred_state, {"event": "TEST_BLOCK"})

            lv_run = "run-predecessor--g1-task-006"
            source_unsigned = {
                "schema_version": "orchestration.pre-result-partial-source.v1",
                "project_id": "proj",
                "gate_id": "G1",
                "lv_id": "TASK-006",
                "run_id": lv_run,
                "source_head": current,
                "current_head": current,
            }
            source = dict(source_unsigned)
            source["source_payload_sha256"] = digest(source_unsigned)
            source_path = (
                state_root / "_workspace" / "orchestration-runs"
                / lv_run / "TASK-006" / "pre-result-partial-source.json"
            )
            source_path.parent.mkdir(parents=True)
            source_path.write_text(
                json.dumps(source, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            source_file_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
            source_relative = source_path.relative_to(state_root).as_posix()
            recovery_id = "recovery-test-1"
            record = {
                "schema_version": "orchestration.production-recovery.v1",
                "recovery_id": recovery_id,
                "project_id": "proj",
                "gate_id": "G1",
                "run_id": lv_run,
                "current_head": current,
                "baseline_head": baseline,
                "branch": "main",
                "source_binding_kind": "PRE_RESULT_PARTIAL_SOURCE",
                "rejected_artifacts": {source_relative: source_file_sha},
                "active_transition_sha256": source_file_sha,
            }
            record["record_hash"] = digest(record)
            checkpoint = {
                "schema_version": "orchestration.production-recovery-checkpoint.v1",
                "recovery_id": recovery_id,
                "project_id": "proj",
                "gate_id": "G1",
                "run_id": lv_run,
                "recovery_record_hash": record["record_hash"],
                "source_binding_kind": "PRE_RESULT_PARTIAL_SOURCE",
            }
            checkpoint["checkpoint_sha256"] = digest(checkpoint)
            recovery_root = (
                state_root / "_workspace" / "global-gate" / "proj" / "recovery"
            )
            recovery_root.mkdir(parents=True)
            (recovery_root / f"{recovery_id}.json").write_text(
                json.dumps(record, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            (recovery_root / f"{recovery_id}.checkpoint.json").write_text(
                json.dumps(checkpoint, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )

            recovery_binding = {
                "schema_version": RECOVERY_SUCCESSOR_BINDING_SCHEMA,
                "project_id": "proj",
                "successor_run_id": "run-successor",
                "predecessor_run_id": "run-predecessor",
                "predecessor_authority_sha256": predecessor["authority_core_sha256"],
                "predecessor_state_sha256": pred_state["state_sha256"],
                "gate_id": "G1",
                "predecessor_gate_run_id": "run-predecessor--g1",
                "current_head": current,
                "recovery_id": recovery_id,
                "recovery_record_hash": record["record_hash"],
                "recovery_checkpoint_sha256": checkpoint["checkpoint_sha256"],
                "recovery_source_payload_sha256": source["source_payload_sha256"],
                "target_runtime_release_digest": "1" * 64,
                "target_runtime_source_head": "2" * 40,
                "approval_ref": "OCP-FULL-PLAN-TEST",
                "approval_proof_path": proof_relative.as_posix(),
                "approval_proof_sha256": proof_sha,
            }
            recovery_binding["binding_sha256"] = digest(recovery_binding)
            successor = seal_authority_core({
                "schema_version": "orchestration.production-full-plan-job.v1",
                "execution_owner": AUTO_RECONCILE_OWNER,
                "project_root": str(project),
                "harness_root": str(state_root),
                "harness_state_root": str(state_root),
                "project_id": "proj",
                "run_id": "run-successor",
                "expected_branch": "main",
                "expected_head": baseline,
                "required_executables": ["git"],
                "runtime_code_root": str(runtime),
                "runtime_release_digest": "1" * 64,
                "runtime_release_source_head": "2" * 40,
                "executor_runtime_identity": fake_identity,
                "approval_ref": "OCP-FULL-PLAN-TEST",
                "activation_binding_digest": recovery_binding["binding_sha256"],
                "executable_authority_bundle_digest": "4" * 64,
                "ai_office_context_digest": "5" * 64,
                "recovery_successor": recovery_binding,
                "gates": [{
                    "gate_id": "G1",
                    "approval_evidence": str(state_root / "approval.json"),
                    "requirements_sha256": "a" * 64,
                    "branch": "main",
                    "head": baseline,
                    "full_plan_opt_in": True,
                    "project_final_validation": True,
                }],
            })
            succ_sup = DurableFullPlanSupervisor(
                state_root,
                project_id="proj",
                run_id="run-successor",
                gates=["G1"],
                authority_core_sha256=successor["authority_core_sha256"],
            )
            preview = succ_sup.build_recovery_successor_state(
                predecessor_state=pred_state,
                recovery_binding=recovery_binding,
            )
            context = {"state": preview, "queue_item": preview["queue"][0]}
            release = SimpleNamespace(manifest_sha256="1" * 64)
            with patch(
                "runtime.orchestrator.production_full_plan_entry.verify_runtime_release",
                return_value=release,
            ), patch(
                "runtime.orchestrator.production_full_plan_entry.validate_executor_runtime",
                return_value=(True, "PASS"),
            ), patch(
                "runtime.orchestrator.production_full_plan_entry._verified_pre_result_partial_resume_head",
                return_value=True,
            ):
                self.assertEqual(
                    preflight_job(successor, resume_context=context)["status"], "PASS"
                )
                source["lv_id"] = "TAMPERED"
                source_path.write_text(
                    json.dumps(source, sort_keys=True, separators=(",", ":")),
                    encoding="utf-8",
                )
                self.assertEqual(
                    preflight_job(successor, resume_context=context)["reason"],
                    "RECOVERY_SUCCESSOR_BINDING_MISMATCH",
                )


if __name__ == "__main__":
    unittest.main()
