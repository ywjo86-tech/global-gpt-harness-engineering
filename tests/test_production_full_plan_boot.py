from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.orchestrator.production_full_plan_boot import (
    discover_jobs,
    discover_registered_jobs,
    reconcile_all,
    reconcile_job,
    systemd_user_unit,
    install_user_unit,
)
from runtime.orchestrator.production_full_plan_entry import load_job, register_job
from runtime.orchestrator.operator_plan_execution import build_operator_plan_job
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


    def test_discover_registered_jobs_finds_jobs_across_worktrees(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a = root / "a"; b = root / "b"
            a.mkdir(); b.mkdir()
            ja = self.registered(a, "r1")
            jb = self.registered(b, "r2")
            self.assertCountEqual(discover_registered_jobs(root), [ja, jb])

    def test_discover_registered_jobs_ignores_unrelated_and_symlinked_jobs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a = root / "a"; a.mkdir()
            registered = self.registered(a, "r1")
            unrelated = root / "unrelated.job.json"
            unrelated.write_text("{}")
            link_dir = root / "linked/_workspace/production-full-plan-jobs/P"
            link_dir.mkdir(parents=True)
            (link_dir / "S.job.json").symlink_to(registered)
            self.assertEqual(discover_registered_jobs(root), [registered])

    def test_systemd_unit_decouples_runtime_code_root_from_job_search_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            runtime = root / "runtime-current"; runtime.mkdir()
            search = root / "workspace"; search.mkdir()
            python = root / "python"; python.write_text("#!/bin/sh\nexit 0\n"); python.chmod(0o755)
            text = systemd_user_unit(
                runtime_root=runtime, search_root=search, python_executable=str(python))
            self.assertIn(f"WorkingDirectory={runtime.resolve()}", text)
            self.assertIn(
                f"ExecStart={python.resolve()} -m runtime.orchestrator.production_full_plan_boot --search-root {search.resolve()}",
                text,
            )

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

    def _operator_registered(self, root: Path, *, terminal: bool) -> Path:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
        runtime_entry=root/"runtime/orchestrator/production_full_plan_boot.py"; runtime_entry.parent.mkdir(parents=True); runtime_entry.write_text("# runtime\n")
        plan=root/"plan.md"; spec=root/"spec.md"; plan.write_text("plan\n"); spec.write_text("spec\n")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True); subprocess.run(["git", "-C", str(root), "commit", "-qm", "approved"], check=True)
        job=build_operator_plan_job(project_root=root,harness_root=root,runtime_code_root=root,project_id="P",run_id="R",task_ids=["G1"],approved_plan_path=plan,approved_spec_path=spec,approval_ref="USER_APPROVED")
        registered=register_job(job); loaded=load_job(registered)
        sup=DurableFullPlanSupervisor(root,project_id="P",run_id="R",gates=["G1"],authority_core_sha256=loaded["authority_core_sha256"],**loaded["policy"]); sup.load()
        if terminal: sup.cancel("HISTORICAL_TERMINAL")
        spec.write_text("approved metadata corrected later\n"); subprocess.run(["git", "-C", str(root), "add", "spec.md"], check=True); subprocess.run(["git", "-C", str(root), "commit", "-qm", "correct metadata"], check=True)
        return registered

    def test_terminal_operator_job_with_external_binding_drift_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            registered=self._operator_registered(Path(d),terminal=True)
            result=reconcile_job(registered,launch=False)
            self.assertEqual(result["action"],"SKIP_TERMINAL"); self.assertEqual(result["state"],"CANCELLED")
            self.assertTrue(result["external_binding_drift"])

    def test_nonterminal_operator_job_with_external_binding_drift_stays_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            registered=self._operator_registered(Path(d),terminal=False)
            result=reconcile_job(registered,launch=False)
            self.assertEqual(result["action"],"BLOCKED"); self.assertEqual(result["state"],"UNKNOWN")
            self.assertIn("external binding drift",result["reason"].lower())

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


    def test_low_resource_wait_recovers_only_after_fresh_probe(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); registered = self.registered(root); job = load_job(registered)
            sup = DurableFullPlanSupervisor(root, project_id="proj", run_id="run", gates=["G1"],
                                            authority_core_sha256=job["authority_core_sha256"],
                                            retry_budget=0, gate_timeout_seconds=1, heartbeat_seconds=.03,
                                            lease_seconds=.08, min_disk_free_bytes=0, min_inode_free=0,
                                            min_memory_available_bytes=0)
            state, _ = sup.load(); state["state"] = "WAITING_RESOURCE"
            state["wait_reason"] = "LOW_RESOURCE_BACKPRESSURE"; state["last_error"] = "disk pressure"
            sup._persist(state, {"event":"TEST_LOW_RESOURCE_WAIT"})
            with patch("runtime.orchestrator.production_full_plan_boot.DurableFullPlanSupervisor._resource_gate",
                       return_value=(True,{"disk_free_bytes":999999999})),                  patch("runtime.orchestrator.production_full_plan_boot._unit_active", return_value=False):
                result = reconcile_job(registered, launch=False)
            self.assertEqual(result["action"], "WOULD_RESUME")
            self.assertEqual(result["state"], "RECOVERING")

    def test_provider_wait_recovery_uses_fresh_router_snapshot(self):
        from runtime.orchestrator.provider_router import (
            ELIGIBILITY_SCHEMA_V1, ProviderEligibilitySnapshotV1,
            normalize_legacy_hybrid_request, route_request,
        )
        from runtime.orchestrator.wait_recovery import record_provider_wait_recovery_evidence
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); registered = self.registered(root); job = load_job(registered)
            subprocess.run(["git","-C",str(root),"config","user.email","wait@example.invalid"],check=True)
            subprocess.run(["git","-C",str(root),"config","user.name","Wait Recovery"],check=True)
            (root/"source.txt").write_text("stable\n")
            (root/"source.txt").write_text("stable\n")
            subprocess.run(["git","-C",str(root),"add","source.txt"],check=True)
            subprocess.run(["git","-C",str(root),"commit","-qm","source"],check=True)
            head=subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip()
            sup = DurableFullPlanSupervisor(root, project_id="proj", run_id="run", gates=["G1"],
                                            authority_core_sha256=job["authority_core_sha256"],
                                            retry_budget=0, gate_timeout_seconds=1, heartbeat_seconds=.03,
                                            lease_seconds=.08, min_disk_free_bytes=0, min_inode_free=0,
                                            min_memory_available_bytes=0)
            state,_=sup.load(); state["state"]="WAITING_PROVIDER"; state["wait_reason"]="PROVIDER_UNAVAILABLE"
            state["last_error"]="PROVIDER_ROUTE_BLOCKED:read_provider_unavailable"
            state=sup._persist(state,{"event":"TEST_PROVIDER_WAIT"})
            gate_run_id=state["queue"][0]["gate_run_id"]
            unavailable=ProviderEligibilitySnapshotV1(
                ELIGIBILITY_SCHEMA_V1,"old",{"nvidia":False,"codex":False},{"codex":"openai/test"},("old",),
                provider_capabilities={"codex":("read_only","reasoning")})
            request=normalize_legacy_hybrid_request(
                required_capabilities=("read_only","reasoning"),eligibility_snapshot=unavailable,
                request_id="req",project_id="proj",run_id=gate_run_id,task_id="LV1",
                task_execution_id=f"{gate_run_id}-LV1-worker",directive_digest="d"*64)
            record_provider_wait_recovery_evidence(
                root,project_id="proj",gate_run_id=gate_run_id,gate_id="G1",lv_id="LV1",lv_run_id=gate_run_id,
                project_root=root,source_head=head,router_request=request.to_dict(),router_decision=route_request(request).to_dict(),
                output_contract={"purpose":"read"},validation_contract={"tests":["T1"]},
                risk_contract={"state_change_required":False})
            fresh=ProviderEligibilitySnapshotV1(
                ELIGIBILITY_SCHEMA_V1,"fresh",{"nvidia":False,"codex":True},{"codex":"openai/test"},("fresh-health",),
                provider_capabilities={"codex":("read_only","reasoning")})
            with patch("runtime.orchestrator.provider_runtime_binding.collect_production_provider_eligibility", return_value=fresh),                  patch("runtime.orchestrator.production_full_plan_boot._unit_active", return_value=False):
                result=reconcile_job(registered,launch=False)
            self.assertEqual(result["action"],"WOULD_RESUME")
            self.assertEqual(result["state"],"RECOVERING")


if __name__ == "__main__": unittest.main()