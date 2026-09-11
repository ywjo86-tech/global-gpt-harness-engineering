from __future__ import annotations

import unittest
import subprocess
import tempfile
from unittest.mock import patch
from pathlib import Path

from runtime.orchestrator.gate_controller import (
    GateControllerAdapters,
    GateControllerError,
    ApprovalFreshnessError,
    gate_dry_run,
    run_gate_lifecycle,
    run_production_gate_lifecycle,
    _verified_recovery_context,
    authorize_production_descendant,
    verify_same_run_governed_descendant,
    verify_production_recovery_descendant,
    verify_production_transition_descendant,
)
import hashlib, json
from runtime.orchestrator.production_approval import write_production_approval
from tests.test_production_lifecycle import binding
from runtime.orchestrator.production_lifecycle import ProductionLifecycleError, produce
from runtime.orchestrator.resume_store import ResumeStore, RunBinding
from runtime.orchestrator.production_gate_runner import ProductionGateRunner
from runtime.orchestrator.cli import _bind_post_handoff_context
from runtime.orchestrator.gate_orchestrator import resolve_canonical_owned_scope, GateAuthorization, GatePlan, GateLV


SHA = "a" * 64


class GateControllerTests(unittest.TestCase):
    def test_canonical_owned_scope_resolver_does_not_require_caller_field(self):
        lv = GateLV("GATE-1", "G1-LV3-2", 2, "next", [], ["app/b.py", "tests/test_b.py"], ["pass"], "manual", ["tests/test_b.py"], None)
        plan = GatePlan("fixture-project", ".", "GATE-1", "plan.md", SHA, [lv])
        auth = GateAuthorization("v1", "a", "fixture-project", "GATE-1", SHA, [lv.lv_id], [lv.lv_id],
                                 {lv.lv_id: list(lv.owned_files)}, {lv.lv_id: ["pass"]}, [], True, True, [],
                                 "GATE_BY_GATE", "now", False, False)
        resolved, metadata = resolve_canonical_owned_scope(plan, auth, lv.lv_id)
        self.assertEqual(resolved, lv.owned_files)
        self.assertEqual(metadata["canonical_owned_scope_status"], "RESOLVED")
        self.assertEqual(metadata["caller_owned_scope_status"], "ABSENT")
    def _governed_descendant(self, temp: str, mutation: str = "", *, stop_after_worker: bool = False):
        project = Path(temp) / "project"; project.mkdir()
        harness = Path(temp) / "harness"
        subprocess.run(["git", "init", "-q", "-b", "main", str(project)], check=True)
        subprocess.run(["git", "-C", str(project), "config", "user.name", "Fixture"], check=True)
        subprocess.run(["git", "-C", str(project), "config", "user.email", "fixture@example.invalid"], check=True)
        (project / "README.md").write_text("base\n")
        subprocess.run(["git", "-C", str(project), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(project), "commit", "-qm", "base"], check=True)
        baseline = subprocess.check_output(["git", "-C", str(project), "rev-parse", "HEAD"], text=True).strip()
        (project / "app").mkdir(); (project / "app/a.py").write_text("x=1\n")
        subprocess.run(["git", "-C", str(project), "add", "app/a.py"], check=True)
        subprocess.run(["git", "-C", str(project), "commit", "-qm", "machine checkpoint"], check=True)
        checkpoint_head = subprocess.check_output(["git", "-C", str(project), "rev-parse", "HEAD"], text=True).strip()
        approval_hash = "b" * 64
        manifest = {"project_id":"fixture-project", "gate_id":"GATE-1", "lv_id":"G1-LV3-1",
                    "run_id":"run-1", "canonical_plan_sha256":SHA, "approval_id":"approval-1",
                    "approval_record_hash":approval_hash, "source_head":baseline}
        package_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        package_sha = hashlib.sha256(package_bytes).hexdigest()
        package_dir = harness / "_workspace/orchestration-runs/run-1/G1-LV3-1"
        package_dir.mkdir(parents=True); (package_dir / "package.manifest.json").write_bytes(package_bytes)
        binding = RunBinding("fixture-project", "GATE-1", "G1-LV3-1", "run-1", SHA, SHA,
                             "main", baseline, package_sha, {"app/a.py": hashlib.sha256(b"").hexdigest()})
        namespace = harness / "_workspace/global-gate-resume/G1-LV3-1"
        store = ResumeStore(namespace, binding)
        package = store.append("PACKAGE", package_sha, stage_payload={"status":"SEALED"})
        preflight = store.append("PREFLIGHT", "c"*64, stage_payload={"status":"READY"})
        worker_payload = {
            "schema_version":"orchestration.product-completion-evidence.v1", "status":"COMPLETED",
            "worker_status":"completed", "project_id":"fixture-project", "gate_id":"GATE-1",
            "lv_id":"G1-LV3-1", "run_id":"run-1", "plan_sha256":SHA,
            "approval_event_id":"approval-1", "package_sha256":package["evidence_sha256"],
            "preflight_evidence_sha256":preflight["evidence_sha256"], "baseline_head":baseline,
            "checkpoint_commit":checkpoint_head,
            "current_head":checkpoint_head, "staged_changes":False, "unstaged_changes":False,
            "tests":[{"status":"PASS"}], "changed_files":["app/a.py"],
        }
        if mutation == "wrong_checkpoint": worker_payload["checkpoint_commit"] = baseline
        if mutation == "artifacts_changed": worker_payload["changed_files"] = ["README.md"]
        worker = store.append("WORKER", "d"*64, stage_payload=worker_payload)
        if stop_after_worker:
            context = {"project_id":"fixture-project", "gate_id":"GATE-1", "lv_id":"G1-LV3-1",
                       "run_id":"run-1", "plan_sha256":SHA, "requirements_sha256":SHA, "branch":"main",
                       "baseline_head":baseline, "current_head":checkpoint_head, "approval_event_id":"approval-1",
                       "approval_record_hash":approval_hash, "owned_file_scope":{"G1-LV3-1":["app/a.py"]},
                       "canonical_lv_scope":["G1-LV3-1"]}
            return project, harness, context, {
                "store":store, "package":package, "preflight":preflight, "worker":worker,
                "checkpoint_head":checkpoint_head,
            }
        review_status = "FAIL" if mutation == "review_fail" else "PASS"
        review = ({"evidence_sha256":"e"*64} if mutation == "review_missing" else
                  store.append("REVIEW", "e"*64, stage_payload={"status":review_status,
                               "run_id":"run-1", "worker_result_sha256":worker["evidence_sha256"]}))
        prior = {"package":package["evidence_sha256"], "preflight":preflight["evidence_sha256"],
                 "worker":worker["evidence_sha256"], "review":review["evidence_sha256"]}
        store.append("CHECKPOINT", "f"*64, checkpoint=True, stage_payload={"status":"CHECKPOINTED"},
                     checkpoint_payload={"lv_id":"G1-LV3-1", "run_id":"run-1", "prior_evidence":prior})
        if mutation == "duplicate_checkpoint":
            store.append("CHECKPOINT", "1"*64, checkpoint=True, stage_payload={"status":"CHECKPOINTED"},
                         checkpoint_payload={"lv_id":"G1-LV3-1", "run_id":"run-1", "prior_evidence":prior})
        store.append("EXIT", "2"*64, stage_payload={"status":"EXITED"})
        handoff_status = "OPEN" if mutation == "handoff_unsealed" else "SEALED"
        handoff = {"project":"fixture-project", "gate":"GATE-1", "lv":"G1-LV3-1", "run_id":"run-1",
                   "canonical_plan_sha256":SHA, "branch":"main", "head":checkpoint_head,
                   "authorization":{"id":"approval-1"}, "artifact_sha256":worker["evidence_sha256"],
                   "changed_files":["app/a.py"], "hard_stop":True}
        handoff["handoff_sha256"] = hashlib.sha256(json.dumps(handoff, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        store.append("HANDOFF", handoff["handoff_sha256"], stage_payload={"status":handoff_status})
        handoff_path = harness / "_workspace/global-gate/fixture-project/artifact/run-1.handoff.json"
        if mutation != "handoff_missing":
            handoff_path.parent.mkdir(parents=True); handoff_path.write_text(json.dumps(handoff))
        if mutation == "external_descendant":
            (project / "app/a.py").write_text("x=2\n")
            subprocess.run(["git", "-C", str(project), "add", "app/a.py"], check=True)
            subprocess.run(["git", "-C", str(project), "commit", "-qm", "external"], check=True)
        elif mutation == "dirty":
            (project / "app/a.py").write_text("dirty\n")
        context = {"project_id":"fixture-project", "gate_id":"GATE-1", "lv_id":"G1-LV3-1",
                   "run_id":"run-1", "plan_sha256":SHA, "requirements_sha256":SHA, "branch":"main",
                   "baseline_head":baseline, "current_head":checkpoint_head, "approval_event_id":"approval-1",
                   "approval_record_hash":approval_hash, "owned_file_scope":{"G1-LV3-1":["app/a.py"]},
                   "canonical_lv_scope":["G1-LV3-1"]}
        if mutation == "run_mismatch": context["run_id"] = "other-run"
        if mutation == "approval_mismatch": context["approval_record_hash"] = "9"*64
        if mutation == "baseline_mismatch": context["baseline_head"] = "0"*40
        return project, harness, context

    def test_same_run_governed_descendant_requires_complete_sealed_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            project, harness, context = self._governed_descendant(temp)
            self.assertTrue(verify_same_run_governed_descendant(
                context, project_root=project, harness_root=harness))
            result = authorize_production_descendant(context, project_root=project, harness_root=harness)
            self.assertTrue(result["same_run_governed_descendant"])

    def test_same_run_governed_descendant_blocks_each_mutation(self):
        mutations = ("external_descendant", "wrong_checkpoint", "duplicate_checkpoint", "artifacts_changed",
                     "review_missing", "review_fail", "handoff_missing", "handoff_unsealed", "run_mismatch",
                     "approval_mismatch", "baseline_mismatch", "dirty")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                project, harness, context = self._governed_descendant(temp, mutation)
                self.assertFalse(verify_same_run_governed_descendant(
                    context, project_root=project, harness_root=harness))

    def test_truly_stale_descendant_remains_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            project, harness, context = self._governed_descendant(temp, "external_descendant")
            with self.assertRaisesRegex(ValueError, "approval is stale"):
                authorize_production_descendant(context, project_root=project, harness_root=harness)

    def test_helper_boundary_attaches_transition_provenance_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            project, harness, context = self._governed_descendant(temp)
            context["predecessor_lv"] = "G1-LV3-0"
            with patch("runtime.orchestrator.gate_controller.verify_production_transition_descendant",
                       side_effect=ValueError("bounded helper failure")):
                with self.assertRaises(ValueError) as caught:
                    authorize_production_descendant(
                        context, project_root=project, harness_root=harness,
                        predecessor={"status": "SEALED"}, approval_record_hash=SHA,
                    )
            self.assertEqual(caught.exception.authorization_helper_id,
                             "VERIFY_PRODUCTION_TRANSITION_DESCENDANT")
            self.assertEqual(caught.exception.authorization_reason_origin, "VALIDATOR")

    def test_helper_boundary_attaches_same_run_provenance_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            project, harness, context = self._governed_descendant(temp)
            with patch("runtime.orchestrator.gate_controller.verify_same_run_governed_descendant",
                       side_effect=ValueError("bounded helper failure")):
                with self.assertRaises(ValueError) as caught:
                    authorize_production_descendant(context, project_root=project, harness_root=harness)
            self.assertEqual(caught.exception.authorization_helper_id,
                             "VERIFY_SAME_RUN_GOVERNED_DESCENDANT")
            self.assertEqual(caught.exception.authorization_reason_origin, "VALIDATOR")

    def test_helper_boundary_attaches_recovery_provenance_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            project, harness, context = self._governed_descendant(temp)
            with patch("runtime.orchestrator.gate_controller.verify_same_run_governed_descendant",
                       return_value=False), patch(
                           "runtime.orchestrator.gate_controller.verify_production_recovery_descendant",
                           side_effect=ValueError("bounded helper failure")):
                with self.assertRaises(ValueError) as caught:
                    authorize_production_descendant(context, project_root=project, harness_root=harness)
            self.assertEqual(caught.exception.authorization_helper_id,
                             "VERIFY_PRODUCTION_RECOVERY_DESCENDANT")
            self.assertEqual(caught.exception.authorization_reason_origin, "VALIDATOR")

    def test_more_specific_branch_metadata_is_not_overwritten_by_helper_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            project, harness, context = self._governed_descendant(temp)
            specific = ValueError("bounded helper failure")
            specific.authorization_branch_id = "GOVERNANCE_TRANSITION_VALIDATION"
            specific.authorization_reason_origin = "TRANSITION"
            with patch("runtime.orchestrator.gate_controller.verify_same_run_governed_descendant",
                       side_effect=specific):
                with self.assertRaises(ValueError) as caught:
                    authorize_production_descendant(context, project_root=project, harness_root=harness)
            self.assertEqual(caught.exception.authorization_branch_id,
                             "GOVERNANCE_TRANSITION_VALIDATION")
            self.assertFalse(hasattr(caught.exception, "authorization_helper_id"))

    def test_proof38_b_entrypoint_equivalent_reaches_finalization_without_worker_rerun(self):
        with tempfile.TemporaryDirectory() as temp:
            project, harness, first_context, partial = self._governed_descendant(
                temp, stop_after_worker=True,
            )
            store = partial["store"]
            self.assertEqual([row["lifecycle"] for row in store.verify()], ["PACKAGE", "PREFLIGHT", "WORKER"])
            worker_event_count = 1
            worker_reruns = 0; authorizations = []; prior = {}
            runner = ProductionGateRunner(
                harness, project_id="fixture-project", gate_id="GATE-1", run_id="run-1",
                mode="GATE_BY_GATE", canonical_lvs=["G1-LV3-1", "G1-LV3-2"], inherited_completed_lvs=[],
            )

            def execute(lv_id):
                nonlocal prior
                if lv_id == "G1-LV3-1":
                    review = store.append("REVIEW", "e"*64, stage_payload={
                        "status":"PASS", "run_id":"run-1",
                        "worker_result_sha256":partial["worker"]["evidence_sha256"],
                    })
                    prior_evidence = {
                        "package":partial["package"]["evidence_sha256"],
                        "preflight":partial["preflight"]["evidence_sha256"],
                        "worker":partial["worker"]["evidence_sha256"],
                        "review":review["evidence_sha256"],
                    }
                    store.append("CHECKPOINT", "f"*64, checkpoint=True,
                                 stage_payload={"status":"CHECKPOINTED"},
                                 checkpoint_payload={"lv_id":"G1-LV3-1", "run_id":"run-1",
                                                     "prior_evidence":prior_evidence})
                    store.append("EXIT", "2"*64, stage_payload={"status":"EXITED"})
                    handoff = {"project":"fixture-project", "gate":"GATE-1", "lv":"G1-LV3-1",
                               "run_id":"run-1", "canonical_plan_sha256":SHA, "branch":"main",
                               "head":partial["checkpoint_head"], "authorization":{"id":"approval-1"},
                               "artifact_sha256":partial["worker"]["evidence_sha256"],
                               "changed_files":["app/a.py"], "hard_stop":True}
                    handoff["handoff_sha256"] = hashlib.sha256(json.dumps(
                        handoff, sort_keys=True, separators=(",", ":"),
                    ).encode()).hexdigest()
                    store.append("HANDOFF", handoff["handoff_sha256"], stage_payload={"status":"SEALED"})
                    target = harness / "_workspace/global-gate/fixture-project/artifact/run-1.handoff.json"
                    target.parent.mkdir(parents=True); target.write_text(json.dumps(handoff))
                    records = store.verify()
                    evidence = {row["lifecycle"].lower():row["evidence_sha256"] for row in records}
                    prior = {"status":"SYSTEM_TRANSITION", "project_id":"fixture-project", "gate_id":"GATE-1",
                             "lv_id":"G1-LV3-1", "run_id":"run-1", "trace":[
                                 "PACKAGE", "PREFLIGHT", "WORKER", "REVIEW", "CHECKPOINT", "EXIT", "HANDOFF",
                                 "SYSTEM_TRANSITION"], "evidence":evidence}
                    return prior
                next_context = dict(first_context)
                next_context.update({"lv_id":lv_id, "owned_file_scope":{
                    "G1-LV3-1":["app/a.py"], "G1-LV3-2":["app/b.py"]}})
                bound = _bind_post_handoff_context(next_context, prior, ["app/b.py"])
                self.assertEqual(bound["owned_files"], ["app/b.py"])
                self.assertEqual(bound["approval_freshness_stage"], "POST_HANDOFF")
                authorization = authorize_production_descendant(
                    bound, project_root=project, harness_root=harness,
                    predecessor=bound["predecessor_evidence"], freshness_stage="POST_HANDOFF",
                )
                authorizations.append(authorization)
                return {**prior, "lv_id":lv_id}

            outcome = runner.run(execute, lambda completed: {
                "next_gate_status":"USER_APPROVAL_REQUIRED", "gate_status":"EXITED",
                "completed_lvs":list(completed),
            })
            self.assertEqual(outcome["status"], "USER_APPROVAL_REQUIRED")
            self.assertEqual(worker_reruns, 0)
            records = store.verify()
            self.assertEqual(sum(record["lifecycle"] == "WORKER" for record in records), worker_event_count)
            self.assertEqual(sum(record.get("checkpoint") is True for record in records), 1)
            self.assertEqual(authorizations[0]["approval_freshness_stage"], "POST_HANDOFF")
            self.assertEqual(authorizations[0]["approval_descendant_authorization"], "SAME_RUN_GOVERNED")

    def test_post_handoff_outcome_digest_mismatch_is_rejected_with_bounded_stage(self):
        with tempfile.TemporaryDirectory() as temp:
            project, harness, context = self._governed_descendant(temp)
            context.update({"lv_id":"G1-LV3-2", "predecessor_lv":"G1-LV3-1",
                            "owned_file_scope":{"G1-LV3-1":["app/a.py"], "G1-LV3-2":["app/b.py"]}})
            forged = {"status":"SYSTEM_TRANSITION", "project_id":"fixture-project", "gate_id":"GATE-1",
                      "lv_id":"G1-LV3-1", "run_id":"run-1", "trace":[
                          "PACKAGE", "PREFLIGHT", "WORKER", "REVIEW", "CHECKPOINT", "EXIT", "HANDOFF",
                          "SYSTEM_TRANSITION"], "evidence":{"exit":"9"*64}}
            with self.assertRaises(ApprovalFreshnessError) as caught:
                authorize_production_descendant(
                    context, project_root=project, harness_root=harness,
                    predecessor=forged, freshness_stage="POST_HANDOFF",
                )
            self.assertEqual(caught.exception.approval_freshness_stage, "POST_HANDOFF")
            self.assertEqual(caught.exception.approval_descendant_authorization, "REJECTED")

    def test_transition_descendant_requires_verified_predecessor_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            context = {"project_id": "p", "gate_id": "g", "lv_id": "lv2", "predecessor_lv": "lv1",
                       "run_id": "new", "plan_sha256": SHA, "branch": "main", "baseline_head": "a" * 40,
                       "approval_event_id": "approval", "canonical_lv_scope": ["lv1", "lv2"]}
            self.assertFalse(verify_production_transition_descendant(
                context, project_root=root, harness_root=root, predecessor=None, approval_record_hash=SHA,
            ))

    def test_issue034_historical_predecessor_descendant_remains_authorized(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"; project.mkdir()
            harness = Path(temp) / "harness"
            subprocess.run(["git", "init", "-q", "-b", "main", str(project)], check=True)
            subprocess.run(["git", "-C", str(project), "config", "user.name", "Fixture"], check=True)
            subprocess.run(["git", "-C", str(project), "config", "user.email", "fixture@example.invalid"], check=True)
            (project / "app.py").write_text("x=1\n")
            subprocess.run(["git", "-C", str(project), "add", "app.py"], check=True)
            subprocess.run(["git", "-C", str(project), "commit", "-qm", "predecessor checkpoint"], check=True)
            current = subprocess.check_output(["git", "-C", str(project), "rev-parse", "HEAD"], text=True).strip()
            artifact = harness / "_workspace/orchestration-runs/prior-run/attempt-01"
            artifact.mkdir(parents=True)
            worker = {"schema_version":"orchestration.product-completion-evidence.v1", "status":"completed",
                      "project_id":"p", "gate_id":"g", "lv_id":"lv1", "run_id":"prior-run",
                      "plan_sha256":SHA, "checkpoint_commit":current}
            worker_bytes = json.dumps(worker).encode(); (artifact / "worker.result.json").write_bytes(worker_bytes)
            (artifact / "review.json").write_text(json.dumps({"verdict":"PASS"}))
            (artifact / "handoff.json").write_text(json.dumps({"status":"SEALED"}))
            (artifact / "lv.exit.json").write_text(json.dumps({"status":"EXITED"}))
            predecessor = {"status":"COMPLETE", "project_id":"p", "lv_id":"lv1", "run_id":"prior-run",
                           "review_sha256":"c"*64, "worker_sha256":hashlib.sha256(worker_bytes).hexdigest()}
            context = {"project_id":"p", "gate_id":"g", "lv_id":"lv2", "predecessor_lv":"lv1",
                       "run_id":"next-run", "plan_sha256":SHA, "branch":"main", "baseline_head":current,
                       "approval_event_id":"approval", "approval_record_hash":SHA,
                       "canonical_lv_scope":["lv1", "lv2"]}
            self.assertTrue(verify_production_transition_descendant(
                context, project_root=project, harness_root=harness,
                predecessor=predecessor, approval_record_hash=SHA,
            ))

    def test_product_descendant_fallback_requires_sealed_recovery_checkpoint(self):
        base = {"schema_version":"orchestration.production-recovery-checkpoint.v1",
                "project_id":"fixture-project","gate_id":"GATE-1","lv_id":"G1-LV3-1",
                "run_id":"run-1","recovery_id":"run-1-recovery-01","next_attempt":1,
                "status":"REJECTED_COMPLETION_UNPROVEN","hard_stop":True}
        recovery = dict(base)
        recovery["checkpoint_sha256"] = hashlib.sha256(json.dumps(base, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        context = {**self.context, "recovery": recovery}
        self.assertTrue(_verified_recovery_context(context))
        self.assertFalse(_verified_recovery_context(self.context))
        malformed = dict(recovery); malformed["checkpoint_sha256"] = "0" * 64
        self.assertFalse(_verified_recovery_context({**self.context, "recovery": malformed}))
    def test_rejected_legacy_stage_cannot_advance(self):
        def rejected(_):
            return {"status":"REJECTED_UNBOUND_LEGACY","exit_code":0,"evidence_sha256":"b"*64,"hard_stop":True,"completion_eligible":False}
        good = lambda _: {"status":"READY","exit_code":0,"evidence_sha256":"c"*64,"hard_stop":True}
        adapters = GateControllerAdapters(rejected, good, good, good, good, good, good, good)
        with self.assertRaisesRegex(GateControllerError, "completion-ineligible"):
            run_gate_lifecycle(self.context, adapters)

    def test_worker_checkpoint_recovery_proof_is_shared_and_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"; project.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main", str(project)], check=True)
            subprocess.run(["git", "-C", str(project), "config", "user.name", "Fixture"], check=True)
            subprocess.run(["git", "-C", str(project), "config", "user.email", "fixture@example.invalid"], check=True)
            (project / "README.md").write_text("base\n")
            subprocess.run(["git", "-C", str(project), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(project), "commit", "-qm", "base"], check=True)
            baseline = subprocess.check_output(["git", "-C", str(project), "rev-parse", "HEAD"], text=True).strip()
            (project / "app").mkdir(); (project / "app/a.py").write_text("x=1\n")
            subprocess.run(["git", "-C", str(project), "add", "app/a.py"], check=True)
            subprocess.run(["git", "-C", str(project), "commit", "-qm", "machine checkpoint"], check=True)
            current = subprocess.check_output(["git", "-C", str(project), "rev-parse", "HEAD"], text=True).strip()
            harness = Path(temp) / "harness"; namespace = harness / "_workspace/global-gate-resume" / f"G1-adoption-{current[:12]}"
            binding = RunBinding("fixture-project", "GATE-1", "G1-LV3-1", "run-1", SHA, SHA, "main", baseline, "b" * 64, {"app/a.py": hashlib.sha256(b"x=1\n").hexdigest()})
            store = ResumeStore(namespace, binding)
            store.append("WORKER", SHA, checkpoint=True, stage_payload={"status": "completed", "checkpoint_commit": current, "changed_files": ["app/a.py"]})
            context = {**self.context, "plan_sha256": SHA, "requirements_sha256": SHA, "owned_file_scope": {"G1-LV3-1": ["app/a.py"]}}
            self.assertTrue(verify_production_recovery_descendant(context, project_root=project, harness_root=harness))
            self.assertFalse(verify_production_recovery_descendant({**context, "run_id": "other-run"}, project_root=project, harness_root=harness))

    def setUp(self) -> None:
        self.context = {
            "project_id": "fixture-project",
            "gate_id": "GATE-1",
            "lv_id": "G1-LV3-1",
            "run_id": "run-1",
            "plan_sha256": SHA,
        }

    @staticmethod
    def _result(status: str) -> dict[str, object]:
        return {"status": status, "exit_code": 0, "evidence_sha256": SHA, "hard_stop": True}

    def _adapters(self, calls: list[str], reviews: list[str] | None = None) -> GateControllerAdapters:
        review_statuses = iter(reviews or ["PASS"])

        def adapter(name: str, status: str):
            def call(payload):
                self.assertEqual(payload["plan_sha256"], SHA)
                self.assertIsInstance(payload["prior_evidence"], dict)
                calls.append(name)
                return self._result(status)
            return call

        def review(payload):
            calls.append("review")
            return self._result(next(review_statuses))

        return GateControllerAdapters(
            package=adapter("package", "SEALED"),
            preflight=adapter("preflight", "READY"),
            worker=adapter("worker", "COMPLETED"),
            review=review,
            remediation=adapter("remediation", "PASS"),
            checkpoint=adapter("checkpoint", "CHECKPOINTED"),
            exit=adapter("exit", "EXITED"),
            handoff=adapter("handoff", "SEALED"),
        )

    def test_dry_run_is_distinct_and_invokes_nothing(self) -> None:
        outcome = gate_dry_run(self.context)
        self.assertEqual(outcome["status"], "DRY_RUN")
        self.assertFalse(outcome["mutation_performed"])
        self.assertEqual(outcome["stages"][-1], "SYSTEM_TRANSITION")

    def test_actual_controller_calls_full_order_and_transitions(self) -> None:
        calls: list[str] = []
        outcome = run_gate_lifecycle(self.context, self._adapters(calls))
        self.assertEqual(calls, ["package", "preflight", "worker", "review", "checkpoint", "exit", "handoff"])
        self.assertEqual(outcome["status"], "SYSTEM_TRANSITION")
        self.assertFalse(outcome["user_approval_renewal"])
        self.assertFalse(outcome["remediated"])

    def test_actual_controller_seals_all_stages_when_production_binding_is_present(self) -> None:
        calls=[]; context={**self.context,"lifecycle_binding":binding()}
        self.assertEqual(run_gate_lifecycle(context,self._adapters(calls))["status"],"SYSTEM_TRANSITION")
        self.assertEqual(len(calls),7)

    def test_issue065_private_callbacks_do_not_enter_lifecycle_payload(self) -> None:
        post_context=[]; dispatch=[]; adapter_payloads=[]
        def mark_post(edge, **values): post_context.append((edge, values))
        def mark_dispatch(step, **values): dispatch.append((step, values))
        lifecycle_binding=binding()
        context={**self.context,"lifecycle_binding":lifecycle_binding,
                 "issue065_package_preentry":lambda *args, **kwargs: None,
                 "issue065_auth_validation":lambda *args, **kwargs: None,
                 "issue065_lifecycle":lambda *args, **kwargs: None,
                 "issue065_dispatch_preinvoke":mark_dispatch,
                 "issue065_post_context":mark_post}

        # This is the proof87-compatible pre-fix payload defect, reproduced
        # without executing or modifying any actual proof.
        with self.assertRaises(ProductionLifecycleError):
            produce("package", {**self.context, "issue065_post_context":mark_post}, binding())

        adapters=self._adapters([])
        def package(payload):
            adapter_payloads.append(dict(payload))
            return self._result("SEALED")
        adapters=GateControllerAdapters(package, adapters.preflight, adapters.worker, adapters.review,
                                        adapters.remediation, adapters.checkpoint, adapters.exit, adapters.handoff)
        with tempfile.TemporaryDirectory() as artifact_root, patch(
            "runtime.orchestrator.gate_controller.produce_lifecycle", wraps=produce,
        ) as producer:
            context.update({"lifecycle_artifact_root":artifact_root,
                            "lifecycle_source_sha256":lifecycle_binding["source_artifact_sha256"],
                            "lifecycle_predecessor":lifecycle_binding["predecessor_digest"]})
            outcome=run_gate_lifecycle(context, adapters)
        self.assertEqual(outcome["status"], "SYSTEM_TRANSITION")
        self.assertTrue(set(adapter_payloads[0]) & {key for key in context if key.startswith("issue065_")})
        self.assertTrue(all(not any(key.startswith("issue065_") for key in call.args[1])
                            for call in producer.call_args_list))
        self.assertIn(("LIFECYCLE_SEAL_PRODUCE_CONSUME",
                       {"completed":True,"branch":"CONTINUE","exit_kind":"TO_ARTIFACT_PUBLISH",
                        "failure":"NONE","failure_mode":"NONE"}), post_context)
        self.assertTrue(any(edge == "ARTIFACT_PUBLISH_CONDITION" for edge, _ in post_context))
        self.assertTrue(any(edge == "PACKAGE_INVOCATION_GATE" for edge, _ in post_context))
        self.assertIn(("INVOCATION", {"completed":True,"failure":"NONE","exception_bucket":"NONE"}), dispatch)

    def test_issue065_lifecycle_seal_failures_remain_bounded_and_fail_closed(self) -> None:
        cases = (
            ("INVALID_REQUIRED_STATE", None, "VALUE"),
            ("PRODUCE_CONSUME_CONTRACT_MISMATCH", ProductionLifecycleError("bounded"), "VALUE"),
            ("UNEXPECTED", RuntimeError("bounded"), "OTHER"),
        )
        for case_id, consumer_failure, expected_bucket in cases:
            with self.subTest(case_id=case_id):
                post_context=[]; dispatch=[]; calls=[]
                def mark_post(edge, **values): post_context.append((edge, values))
                def mark_dispatch(step, **values): dispatch.append((step, values))
                lifecycle_binding=binding()
                if case_id == "INVALID_REQUIRED_STATE":
                    lifecycle_binding.pop("project_id")
                context={**self.context,"lifecycle_binding":lifecycle_binding,
                         "issue065_dispatch_preinvoke":mark_dispatch,
                         "issue065_post_context":mark_post}
                patcher = (patch("runtime.orchestrator.gate_controller.consume_lifecycle",
                                 side_effect=consumer_failure) if consumer_failure else None)
                with self.assertRaises(Exception):
                    if patcher:
                        with patcher:
                            run_gate_lifecycle(context,self._adapters(calls))
                    else:
                        run_gate_lifecycle(context,self._adapters(calls))
                self.assertEqual(calls, [])
                self.assertEqual(post_context[-1][0], "LIFECYCLE_SEAL_PRODUCE_CONSUME")
                self.assertEqual(post_context[-1][1]["failure_mode"], "RAISED")
                self.assertEqual(post_context[-1][1]["exit_kind"], "BLOCK_RETURN")
                self.assertEqual(dispatch[-1][1]["exception_bucket"], expected_bucket)

    def test_failed_review_runs_remediation_and_independent_rereview(self) -> None:
        calls: list[str] = []
        outcome = run_gate_lifecycle(self.context, self._adapters(calls, ["FAIL", "PASS"]))
        self.assertEqual(calls, ["package", "preflight", "worker", "review", "remediation", "review", "checkpoint", "exit", "handoff"])
        self.assertTrue(outcome["remediated"])

    def test_nonzero_exit_invalid_evidence_and_missing_hard_stop_fail_closed(self) -> None:
        for mutation, message in (
            ({"exit_code": 9}, "exit code 9"),
            ({"evidence_sha256": "bad"}, "invalid evidence"),
            ({"hard_stop": False}, "hard-stop"),
        ):
            with self.subTest(mutation=mutation):
                calls: list[str] = []
                adapters = self._adapters(calls)

                def bad_package(payload):
                    value = self._result("SEALED")
                    value.update(mutation)
                    return value

                adapters = GateControllerAdapters(bad_package, adapters.preflight, adapters.worker, adapters.review, adapters.remediation, adapters.checkpoint, adapters.exit, adapters.handoff)
                with self.assertRaisesRegex(GateControllerError, message):
                    run_gate_lifecycle(self.context, adapters)
                self.assertEqual(calls, [])

    def test_failed_post_remediation_review_stops_before_checkpoint(self) -> None:
        calls: list[str] = []
        with self.assertRaisesRegex(GateControllerError, "did not pass"):
            run_gate_lifecycle(self.context, self._adapters(calls, ["FAIL", "FAIL"]))
        self.assertEqual(calls[-2:], ["remediation", "review"])
        self.assertNotIn("checkpoint", calls)

    def test_production_controller_consumes_only_v2_and_validates_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "fixture-project"; root.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True)
            (root / "PLAN.md").write_text("plan\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "baseline"], cwd=root, check=True, capture_output=True)
            approval = write_production_approval(
                project_root=root, output_path="approval.json", gate_id="GATE-1", plan_sha256=SHA,
                approval_mode="GATE_BY_GATE", canonical_lv_scope=["G1-LV3-1"],
                owned_file_scope={"G1-LV3-1": ["app/a.py"]}, completion_conditions_sha256="c"*64,
                authorization_source="USER_OWNER", dry_run=True,
            )["event"]
            post_context=[]; dispatch=[]
            def mark_post(edge, **values): post_context.append((edge, values))
            def mark_dispatch(step, **values): dispatch.append((step, values))
            context = {
                **self.context, "branch": "main", "baseline_head": approval["baseline_head"],
                "approval_mode": "GATE_BY_GATE", "canonical_lv_scope": ["G1-LV3-1"],
                "owned_file_scope": {"G1-LV3-1": ["app/a.py"]}, "phase": "PHASE-1",
                "issue065_package_preentry":lambda *args, **kwargs: None,
                "issue065_auth_validation":lambda *args, **kwargs: None,
                "issue065_lifecycle":lambda *args, **kwargs: None,
                "issue065_dispatch_preinvoke":mark_dispatch,
                "issue065_post_context":mark_post,
                "issue065_bootstrap":lambda **kwargs: None,
                "issue065_package_transition":lambda **kwargs: None,
            }
            state = {
                "schema_version": "orchestration.canonical-gate-state.v2", "project_id": "fixture-project",
                "gate_id": "GATE-1", "phase": "PHASE-1", "plan_sha256": SHA,
                "gate_status": "READY_FOR_TRANSITION", "closure_status": "CLOSED",
                "approval_record_hash": approval["record_hash"],
            }
            calls: list[str] = []
            outcome = run_production_gate_lifecycle(
                context, self._adapters(calls), approval_events=[approval], project_root=str(root),
                canonical_state=state, completion_conditions_sha256="c"*64,
            )
            self.assertEqual(outcome["production_approval_schema"], "orchestration.production-approval.v2")
            self.assertEqual(outcome["approval_freshness_stage"], "PRE_RUN")
            self.assertEqual(outcome["approval_descendant_authorization"], "BASELINE_EXACT")
            self.assertTrue(any(edge == "LIFECYCLE_SEAL_PRODUCE_CONSUME" and values["completed"]
                                for edge, values in post_context))
            self.assertTrue(any(step == "INVOCATION" and values["completed"]
                                for step, values in dispatch))
            calls.clear()
            with self.assertRaises(GateControllerError):
                run_production_gate_lifecycle(
                    context, self._adapters(calls), approval_events=[{"schema_version": "orchestration.gate-approval.v1"}],
                    project_root=str(root), canonical_state=state, completion_conditions_sha256="c"*64,
                )
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
